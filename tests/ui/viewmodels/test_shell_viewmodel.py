"""ShellViewModel: sidebar preference / session override / mode, window memento (plan §4.7, D4).

No widgets: an in-memory store and plain recorders on the signals. The QAction
test needs the session QApplication (``qapp``).
"""

import inspect
import logging

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction

from src.infrastructure.preferences import InMemoryUiPreferences
from src.ui.viewmodels.shell_viewmodel import ShellViewModel

GEOMETRY = b"\x01\xd9\xd0\xcb\x00\x03\x00\x00"


class FailingStore(InMemoryUiPreferences):
    def __init__(self, fail_loads=False):
        super().__init__()
        self._fail_loads = fail_loads

    def load_sidebar_preference(self):
        if self._fail_loads:
            raise OSError("settings unreadable")
        return super().load_sidebar_preference()

    def load_window_geometry(self):
        if self._fail_loads:
            raise OSError("settings unreadable")
        return super().load_window_geometry()

    def save_sidebar_preference(self, preference):
        raise OSError("settings read-only")

    def save_window_geometry(self, geometry, screen_name):
        raise OSError("settings read-only")


@pytest.fixture
def store():
    return InMemoryUiPreferences()


def record(vm) -> list:
    """("preference" | "mode", value) for every emission, in order."""
    events = []
    vm.sidebar_preference_changed.connect(lambda value: events.append(("preference", value)))
    vm.sidebar_mode_changed.connect(lambda value: events.append(("mode", value)))
    return events


# ------------------------------------------------------------------ construction

def test_ctor_restores_and_emits_nothing(qapp, store):
    store.sidebar_preference = "icons"
    store.window_geometry, store.last_screen = GEOMETRY, "Built-in Retina Display"
    vm = ShellViewModel(store)
    events = record(vm)
    QCoreApplication.processEvents()  # nothing deferred either

    assert (vm.sidebar_preference, vm.sidebar_mode, vm.last_screen_name) == (
        "icons", "icons", "Built-in Retina Display")
    assert vm.saved_window_geometry(["Built-in Retina Display"]) == GEOMETRY
    assert events == []


@pytest.mark.parametrize("saved_preference, geometry, screen", [
    (None, None, None),
    ("rail", "not bytes", 42),
    ("", b"", None),
])
def test_ctor_falls_back_to_defaults(store, saved_preference, geometry, screen):
    store.sidebar_preference, store.window_geometry, store.last_screen = (
        saved_preference, geometry, screen)
    vm = ShellViewModel(store)
    assert (vm.sidebar_preference, vm.sidebar_mode, vm.last_screen_name) == ("auto", "labels", None)
    assert vm.saved_window_geometry(["Built-in Retina Display", ""]) is None


def test_store_load_failure_falls_back_to_defaults(caplog):
    with caplog.at_level(logging.ERROR):
        vm = ShellViewModel(FailingStore(fail_loads=True))
    assert (vm.sidebar_preference, vm.sidebar_mode) == ("auto", "labels")
    assert "Could not load" in caplog.text


# ------------------------------------------------------------------ mode resolution

@pytest.mark.parametrize("preference, width_class, mode", [
    ("auto", "wide", "labels"),
    ("auto", "narrow", "icons"),
    ("labels", "wide", "labels"),
    ("labels", "narrow", "labels"),
    ("icons", "wide", "icons"),
    ("icons", "narrow", "icons"),
])
def test_mode_table(store, preference, width_class, mode):
    store.sidebar_preference = preference
    vm = ShellViewModel(store)
    vm.set_width_class(width_class)
    assert vm.sidebar_mode == mode


def test_width_class_emits_only_on_mode_change(store):
    vm = ShellViewModel(store)
    events = record(vm)
    vm.set_width_class("wide")      # the starting class
    vm.set_width_class("narrow")
    vm.set_width_class("narrow")
    vm.set_width_class("wide")
    assert events == [("mode", "icons"), ("mode", "labels")]


def test_width_class_with_a_fixed_preference_changes_nothing(store):
    store.sidebar_preference = "labels"
    vm = ShellViewModel(store)
    events = record(vm)
    vm.set_width_class("narrow")
    assert events == [] and vm.sidebar_mode == "labels"


@pytest.mark.parametrize("call, value", [
    ("set_sidebar_preference", "rail"),
    ("set_sidebar_preference", "Labels"),
    ("set_width_class", "medium"),
    ("set_width_class", ""),
])
def test_invalid_inputs_are_ignored_and_logged(store, caplog, call, value):
    vm = ShellViewModel(store)
    events = record(vm)
    with caplog.at_level(logging.WARNING):
        getattr(vm, call)(value)
    assert events == [] and store.sidebar_preference is None
    assert (vm.sidebar_preference, vm.sidebar_mode) == ("auto", "labels")
    assert "Ignoring unknown" in caplog.text


# ------------------------------------------------------------------ footer toggle (session)

@pytest.mark.parametrize("preference, width_class, before, after", [
    ("auto", "narrow", "icons", "labels"),
    ("auto", "wide", "labels", "icons"),
    ("labels", "wide", "labels", "icons"),
    ("icons", "narrow", "icons", "labels"),
])
def test_toggle_shows_the_opposite_mode_for_the_session(store, preference, width_class, before,
                                                        after):
    store.sidebar_preference = preference
    vm = ShellViewModel(store)
    vm.set_width_class(width_class)
    events = record(vm)

    vm.toggle_sidebar()
    assert vm.sidebar_mode == after and events == [("mode", after)]
    vm.toggle_sidebar()
    assert vm.sidebar_mode == before and events == [("mode", after), ("mode", before)]
    assert vm.sidebar_preference == preference and store.sidebar_preference == preference


def test_toggle_is_not_persisted(store):
    vm = ShellViewModel(store)
    vm.toggle_sidebar()
    assert vm.sidebar_mode == "icons"
    assert ShellViewModel(store).sidebar_mode == "labels"


def test_width_class_change_clears_the_override(store):
    vm = ShellViewModel(store)
    vm.toggle_sidebar()                 # auto + wide: icons for the session
    events = record(vm)
    vm.set_width_class("narrow")        # auto + narrow: icons; override gone
    vm.set_width_class("wide")
    assert events == [("mode", "labels")] and vm.sidebar_mode == "labels"


def test_choosing_a_preference_clears_the_override_even_if_unchanged(store):
    vm = ShellViewModel(store)
    vm.toggle_sidebar()
    events = record(vm)
    vm.set_sidebar_preference("auto")   # already auto: no preference emission
    assert events == [("mode", "labels")] and store.sidebar_preference is None


# ------------------------------------------------------------------ persistent preference

def test_preference_emitted_before_mode_and_persisted(store):
    vm = ShellViewModel(store)
    events = record(vm)
    vm.set_sidebar_preference("icons")
    assert events == [("preference", "icons"), ("mode", "icons")]
    assert store.sidebar_preference == "icons"
    assert ShellViewModel(store).sidebar_preference == "icons"


def test_preference_change_without_mode_change_emits_the_preference_only(store):
    vm = ShellViewModel(store)
    events = record(vm)
    vm.set_sidebar_preference("labels")  # auto + wide shows labels already
    assert events == [("preference", "labels")]


def test_same_preference_again_is_a_no_op(store):
    store.sidebar_preference = "icons"
    vm = ShellViewModel(store)
    store.sidebar_preference = None
    events = record(vm)
    vm.set_sidebar_preference("icons")
    assert events == [] and store.sidebar_preference is None


# ------------------------------------------------------------------ window memento

def test_geometry_memento_round_trip(store):
    vm = ShellViewModel(store)
    events = record(vm)
    vm.remember_window_geometry(GEOMETRY, "DELL U2720Q")
    assert events == []
    assert vm.last_screen_name == "DELL U2720Q"
    assert vm.saved_window_geometry(["Built-in Retina Display", "DELL U2720Q"]) == GEOMETRY
    assert (store.window_geometry, store.last_screen) == (GEOMETRY, "DELL U2720Q")
    restored = ShellViewModel(store)
    assert restored.saved_window_geometry(("DELL U2720Q",)) == GEOMETRY
    assert restored.last_screen_name == "DELL U2720Q"


def test_saved_geometry_needs_its_screen_connected(store):
    store.window_geometry, store.last_screen = GEOMETRY, "DELL U2720Q"
    vm = ShellViewModel(store)
    assert vm.saved_window_geometry(["Built-in Retina Display"]) is None
    assert vm.saved_window_geometry([]) is None
    assert vm.last_screen_name == "DELL U2720Q"  # still the launch-screen hint


def test_saved_geometry_none_without_a_screen_name(store):
    store.window_geometry = GEOMETRY
    assert ShellViewModel(store).saved_window_geometry(["Built-in Retina Display"]) is None


@pytest.mark.parametrize("blob, screen", [
    (bytearray(GEOMETRY), "DELL U2720Q"),
    (b"", "DELL U2720Q"),
    (None, "DELL U2720Q"),
    (GEOMETRY, None),
])
def test_invalid_memento_is_ignored_and_never_raises(store, caplog, blob, screen):
    vm = ShellViewModel(store)
    with caplog.at_level(logging.WARNING):
        vm.remember_window_geometry(blob, screen)
    assert store.window_geometry is None and vm.last_screen_name is None
    assert "invalid window-geometry memento" in caplog.text


def test_store_save_failures_never_raise(caplog):
    vm = ShellViewModel(FailingStore())
    events = record(vm)
    with caplog.at_level(logging.ERROR):
        vm.set_sidebar_preference("icons")
        vm.remember_window_geometry(GEOMETRY, "DELL U2720Q")
    assert events == [("preference", "icons"), ("mode", "icons")]
    assert vm.saved_window_geometry(["DELL U2720Q"]) == GEOMETRY
    assert caplog.text.count("Could not save") == 2


# ------------------------------------------------------------------ QAction wiring

def test_toggle_takes_no_parameters():
    assert list(inspect.signature(ShellViewModel.toggle_sidebar).parameters) == ["self"]


def test_real_qaction_triggered_toggles_once(qapp, store):
    vm = ShellViewModel(store)
    events = record(vm)
    action = QAction("Toggle Sidebar")
    action.triggered.connect(vm.toggle_sidebar)  # triggered(bool) must not reach a parameter
    action.trigger()
    assert events == [("mode", "icons")]
