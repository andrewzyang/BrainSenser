"""UiScaleViewModel: interface size per display (plan §4.7; mvvm §3A).

No widgets: an in-memory store, a recording restarter and plain recorders on
the signal. The QAction tests need the session QApplication (``qapp``).
"""

import inspect
import logging

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QAction

from src.infrastructure.preferences import InMemoryUiPreferences
from src.ui.policy.scale import (
    DEFAULT_STEP, SUGGESTED_PERCENT, ZOOM_LADDER, ScreenMetrics, ZoomNotice,
)
from src.ui.viewmodels.ui_scale_viewmodel import UiScaleViewModel

RETINA = ScreenMetrics("Built-in Retina Display", 1280, 828, 2.0)
ONE_X = ScreenMetrics("DELL P2419H", 1920, 1080, 1.0)
UHD_AT_100 = ScreenMetrics("LG UltraFine", 3840, 2160, 1.0)

COMMANDS = ("zoom_in", "zoom_out", "reset_zoom", "accept_suggestion", "dismiss_suggestion",
            "postpone_restart", "restart_now")


def step(percent: int) -> int:
    return ZOOM_LADDER.index(percent)


class CountingStore(InMemoryUiPreferences):
    """In-memory store that records every call."""

    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    def load_zoom_steps(self):
        self.calls.append("load_zoom_steps")
        return super().load_zoom_steps()

    def save_zoom_steps(self, steps):
        self.calls.append("save_zoom_steps")
        super().save_zoom_steps(steps)

    def load_dismissed_suggestions(self):
        self.calls.append("load_dismissed_suggestions")
        return super().load_dismissed_suggestions()

    def save_dismissed_suggestions(self, displays):
        self.calls.append("save_dismissed_suggestions")
        super().save_dismissed_suggestions(displays)

    def saves(self) -> list[str]:
        return [c for c in self.calls if c.startswith("save_")]


class FailingStore(InMemoryUiPreferences):
    def __init__(self, fail_loads=False):
        super().__init__()
        self._fail_loads = fail_loads

    def load_zoom_steps(self):
        if self._fail_loads:
            raise OSError("settings unreadable")
        return super().load_zoom_steps()

    def load_dismissed_suggestions(self):
        if self._fail_loads:
            raise OSError("settings unreadable")
        return super().load_dismissed_suggestions()

    def save_zoom_steps(self, steps):
        raise OSError("settings read-only")

    def save_dismissed_suggestions(self, displays):
        raise OSError("settings read-only")


class RecordingRestarter:
    def __init__(self, error=None):
        self.restarts = 0
        self._error = error

    def restart(self):
        self.restarts += 1
        if self._error is not None:
            raise self._error


@pytest.fixture
def store():
    return CountingStore()


@pytest.fixture
def restarter():
    return RecordingRestarter()


def make_vm(store, restarter=None, *, active_factor=1.0, locked=False, display=None):
    vm = UiScaleViewModel(store, restarter or RecordingRestarter(), active_factor=active_factor,
                          locked=locked)
    if display is not None:
        vm.set_current_display(display)
    return vm


def record(vm) -> list:
    states = []
    vm.state_changed.connect(states.append)
    return states


# ------------------------------------------------------------------ construction

def test_ctor_reads_once_writes_nothing_emits_nothing(qapp, store, restarter):
    store.zoom_steps = {RETINA.name: step(125)}
    vm = UiScaleViewModel(store, restarter, active_factor=1.25)
    states = record(vm)
    QCoreApplication.processEvents()  # nothing deferred ("emit once") either

    assert sorted(store.calls) == ["load_dismissed_suggestions", "load_zoom_steps"]
    assert states == [] and restarter.restarts == 0
    assert vm.state.display is None and vm.state.active_percent == 125


def test_state_is_readable_before_any_display():
    vm = make_vm(CountingStore(), active_factor=1.1)
    s = vm.state
    assert (s.display, s.active_percent, s.chosen_percent, s.restart_required) == (
        None, 110, 110, False)
    assert not (s.can_zoom_in or s.can_zoom_out or s.can_reset)


@pytest.mark.parametrize("factor", [0, -1.0, float("nan"), float("inf")])
def test_invalid_active_factor_is_rejected(factor):
    with pytest.raises(ValueError):
        UiScaleViewModel(CountingStore(), RecordingRestarter(), active_factor=factor)


@pytest.mark.parametrize("bad", ["abc", 99, -99, None, 1.5, True])
def test_corrupt_saved_step_falls_back_to_the_default(store, bad):
    store.zoom_steps = {RETINA.name: bad}
    vm = make_vm(store, display=RETINA)
    assert vm.state.chosen_percent == 100 and vm.state.restart_required is False


def test_store_load_failure_falls_back_to_defaults(caplog):
    with caplog.at_level(logging.ERROR):
        vm = make_vm(FailingStore(fail_loads=True), display=UHD_AT_100)
    assert vm.state.chosen_percent == 100 and vm.state.suggest_percent == SUGGESTED_PERCENT
    assert "Could not load" in caplog.text


# ------------------------------------------------------------------ display facts

def test_new_display_emits_once_and_equal_metrics_never(store):
    vm = make_vm(store)
    states = record(vm)
    vm.set_current_display(RETINA)
    vm.set_current_display(ScreenMetrics(RETINA.name, 1280, 828, 2.0))
    assert states == [vm.state] and vm.state.display == RETINA.name
    assert store.saves() == []


def test_display_change_with_an_equal_state_emits_nothing(store):
    vm = make_vm(store, display=ONE_X)
    states = record(vm)
    vm.set_current_display(ScreenMetrics(ONE_X.name, 1920, 1200, 1.0))  # new mode, same state
    assert states == []


def test_sizes_are_kept_per_display(store):
    vm = make_vm(store, display=RETINA)
    vm.zoom_in()
    vm.zoom_in()
    vm.set_current_display(ONE_X)
    assert vm.state.chosen_percent == 100
    vm.set_current_display(RETINA)
    assert vm.state.chosen_percent == 125
    assert store.zoom_steps == {RETINA.name: step(125)}


# ------------------------------------------------------------------ commands

def test_zoom_in_walks_the_ladder_persisting_once_per_step(store):
    vm = make_vm(store, display=RETINA)
    states = record(vm)
    seen = []
    for _ in range(len(ZOOM_LADDER) + 2):
        vm.zoom_in()
        seen.append(vm.state.chosen_percent)
    assert seen == [110, 125, 150, 175, 200, 200, 200, 200, 200]
    assert [s.chosen_percent for s in states] == [110, 125, 150, 175, 200]
    assert store.saves() == ["save_zoom_steps"] * 5
    assert store.zoom_steps == {RETINA.name: step(200)}
    assert vm.state.can_zoom_in is False and vm.state.restart_required is True


@pytest.mark.parametrize("display, start, command", [
    (RETINA, 200, "zoom_in"),     # top of the ladder
    (RETINA, 90, "zoom_out"),     # bottom of the ladder on Retina
    (ONE_X, 100, "zoom_out"),     # 100 % is the bottom on a 1x display
    (ONE_X, 100, "reset_zoom"),   # already the default
])
def test_bounds_are_no_ops_without_emission_or_write(store, display, start, command):
    store.zoom_steps = {display.name: step(start)}
    vm = make_vm(store, display=display)
    states = record(vm)
    calls_before = len(store.calls)
    getattr(vm, command)()
    assert states == [] and store.calls[calls_before:] == []
    assert vm.state.chosen_percent == start


def test_reset_once_then_no_op(store):
    store.zoom_steps = {RETINA.name: step(150)}
    vm = make_vm(store, display=RETINA)
    states = record(vm)
    vm.reset_zoom()
    vm.reset_zoom()
    assert [s.chosen_percent for s in states] == [100]
    assert store.zoom_steps == {RETINA.name: DEFAULT_STEP}  # saved explicitly: an answer to D2
    assert store.saves() == ["save_zoom_steps"]


@pytest.mark.parametrize("k", range(1, len(ZOOM_LADDER) - 1))
def test_zoom_in_then_out_round_trips_exactly(store, k):
    vm = make_vm(store, display=RETINA)
    for _ in range(k):
        vm.zoom_in()
    assert vm.state.chosen_percent == ZOOM_LADDER[DEFAULT_STEP + k]
    for _ in range(k):
        vm.zoom_out()
    assert vm.state.chosen_percent == 100 and vm.state.restart_required is False


def test_flags_and_label_follow_the_chosen_size(store):
    vm = make_vm(store, display=ONE_X)
    vm.zoom_in()
    vm.zoom_in()
    s = vm.state
    assert (s.chosen_percent, s.label, s.default_percent) == (125, "125 %", 100)
    assert (s.can_zoom_in, s.can_zoom_out, s.can_reset, s.restart_required) == (
        True, True, True, True)


def test_restart_required_is_relative_to_the_session_size(store):
    store.zoom_steps = {RETINA.name: step(125)}
    vm = make_vm(store, active_factor=1.25, display=ScreenMetrics(RETINA.name, 1024, 662, 2.5))
    assert vm.state.restart_required is False
    vm.zoom_out()
    assert vm.state.chosen_percent == 110 and vm.state.restart_required is True


def test_one_emission_per_effective_change(store):
    vm = make_vm(store)
    states = record(vm)
    vm.set_current_display(RETINA)        # change
    vm.set_current_display(RETINA)        # none
    vm.zoom_in()                          # change
    vm.reset_zoom()                       # change
    vm.reset_zoom()                       # none
    vm.zoom_out()                         # change (90 % on Retina)
    vm.zoom_out()                         # none
    vm.accept_suggestion()                # none: nothing suggested
    vm.dismiss_suggestion()               # none
    assert [(s.display, s.chosen_percent) for s in states] == [
        (RETINA.name, 100), (RETINA.name, 110), (RETINA.name, 100), (RETINA.name, 90)]


# ------------------------------------------------------------------ D2 suggestion

def test_suggestion_accepted_once(store):
    vm = make_vm(store, display=UHD_AT_100)
    assert vm.state.suggest_percent == SUGGESTED_PERCENT
    states = record(vm)
    vm.accept_suggestion()
    vm.accept_suggestion()
    assert [(s.chosen_percent, s.suggest_percent, s.restart_required) for s in states] == [
        (SUGGESTED_PERCENT, None, True)]
    assert store.saves() == ["save_zoom_steps"]
    assert make_vm(store, display=UHD_AT_100).state.suggest_percent is None


def test_suggestion_dismissed_once_per_display(store):
    vm = make_vm(store, display=UHD_AT_100)
    states = record(vm)
    vm.dismiss_suggestion()
    vm.dismiss_suggestion()
    assert [(s.chosen_percent, s.suggest_percent) for s in states] == [(100, None)]
    assert store.dismissed_suggestions == {UHD_AT_100.name}
    assert make_vm(store, display=UHD_AT_100).state.suggest_percent is None
    other = ScreenMetrics("Second 4K", 3840, 2160, 1.0)
    assert make_vm(store, display=other).state.suggest_percent == SUGGESTED_PERCENT


def test_no_suggestion_once_a_size_was_chosen(store):
    store.zoom_steps = {UHD_AT_100.name: DEFAULT_STEP}
    assert make_vm(store, display=UHD_AT_100).state.suggest_percent is None


def test_no_suggestion_for_an_ultrawide(store):
    ultrawide = ScreenMetrics("U34", 3440, 1440, 1.0)
    assert make_vm(store, display=ultrawide).state.suggest_percent is None


# ------------------------------------------------------------------ restart notice

# The window on an external display the user set to 125 % last session; the
# session runs at 125 %. Qt reports both displays with the factor applied.
SESSION_DISPLAY = ScreenMetrics("DELL U2720Q", 2048, 1152, 1.25)   # 2560 x 1440 @ 1x
OTHER_DISPLAY = ScreenMetrics("Built-in Retina Display", 1024, 662, 2.5)


@pytest.fixture
def session_at_125(store):
    store.zoom_steps = {SESSION_DISPLAY.name: step(125)}
    return make_vm(store, active_factor=1.25, display=SESSION_DISPLAY)


def test_moving_to_a_display_with_another_size_announces_nothing(session_at_125):
    vm = session_at_125
    states = record(vm)
    assert vm.state.notice is ZoomNotice.NONE
    vm.set_current_display(OTHER_DISPLAY)    # never given a size: 100 %
    assert (vm.state.chosen_percent, vm.state.restart_required, vm.state.notice) == (
        100, True, ZoomNotice.NONE)          # Restart Now stays in the "Aa" menu
    vm.set_current_display(SESSION_DISPLAY)
    assert [s.notice for s in states] == [ZoomNotice.NONE, ZoomNotice.NONE]


def test_a_size_chosen_this_session_is_announced(session_at_125):
    vm = session_at_125
    vm.set_current_display(OTHER_DISPLAY)
    vm.zoom_in()                             # 110 % for the laptop, the session at 125 %
    assert (vm.state.chosen_percent, vm.state.notice) == (110, ZoomNotice.RESTART)
    vm.set_current_display(SESSION_DISPLAY)  # nothing chosen here this session
    assert vm.state.notice is ZoomNotice.NONE
    vm.set_current_display(OTHER_DISPLAY)    # still pending there
    assert vm.state.notice is ZoomNotice.RESTART


def test_later_hides_the_notice_until_another_size_is_chosen(store):
    vm = make_vm(store, display=RETINA)
    vm.zoom_in()
    states = record(vm)
    saves_before = list(store.calls)

    vm.postpone_restart()
    vm.postpone_restart()                    # nothing announced any more: no-op

    assert [(s.notice, s.restart_required, s.chosen_percent) for s in states] == [
        (ZoomNotice.NONE, True, 110)]
    assert store.calls == saves_before       # session only: nothing saved
    vm.zoom_in()
    assert (vm.state.chosen_percent, vm.state.notice) == (125, ZoomNotice.RESTART)
    vm.reset_zoom()                          # back to the session's size: nothing pending
    assert (vm.state.restart_required, vm.state.notice) == (False, ZoomNotice.NONE)


def test_later_is_forgotten_by_the_next_session_which_announces_nothing(store):
    vm = make_vm(store, display=RETINA)
    vm.zoom_in()
    vm.postpone_restart()
    again = make_vm(store, display=RETINA)   # e.g. after a quit without a restart
    assert (again.state.chosen_percent, again.state.restart_required, again.state.notice) == (
        110, True, ZoomNotice.NONE)


def test_later_without_a_restart_notice_does_nothing(store):
    vm = make_vm(store, display=UHD_AT_100)  # the D2 offer is showing
    states = record(vm)
    vm.postpone_restart()
    assert states == [] and vm.state.notice is ZoomNotice.SUGGESTION


def test_restart_now_stays_available_after_later(store, restarter):
    vm = make_vm(store, restarter, display=RETINA)
    vm.zoom_in()
    vm.postpone_restart()
    vm.restart_now()
    assert restarter.restarts == 1


def test_the_offer_and_its_answer(store):
    vm = make_vm(store, display=UHD_AT_100)
    assert vm.state.notice is ZoomNotice.SUGGESTION
    vm.accept_suggestion()
    assert vm.state.notice is ZoomNotice.RESTART


# ------------------------------------------------------------------ restart

def test_restart_now_only_when_a_restart_is_pending(store, restarter):
    vm = make_vm(store, restarter, display=RETINA)
    vm.restart_now()
    assert restarter.restarts == 0
    vm.zoom_in()
    vm.restart_now()
    assert restarter.restarts == 1


def test_restart_failure_is_logged_not_raised(store, caplog):
    restarter = RecordingRestarter(error=RuntimeError("no process"))
    vm = make_vm(store, restarter, display=RETINA)
    vm.zoom_in()
    with caplog.at_level(logging.ERROR):
        vm.restart_now()
    assert restarter.restarts == 1 and "Could not restart" in caplog.text


# ------------------------------------------------------------------ lock and failures

def test_locked_pins_and_never_writes(store, restarter):
    store.zoom_steps = {UHD_AT_100.name: step(150)}
    vm = make_vm(store, restarter, active_factor=1.25, locked=True,
                 display=ScreenMetrics(UHD_AT_100.name, 3072, 1728, 1.25))
    states = record(vm)
    calls_before = len(store.calls)
    for command in COMMANDS:
        getattr(vm, command)()
    s = vm.state
    assert s.locked and (s.active_percent, s.chosen_percent, s.label) == (125, 125, "125 %")
    assert not (s.can_zoom_in or s.can_zoom_out or s.can_reset or s.restart_required)
    assert s.suggest_percent is None
    assert states == [] and store.calls[calls_before:] == [] and restarter.restarts == 0


def test_store_save_failure_is_logged_and_the_session_state_kept(caplog):
    vm = make_vm(FailingStore(), display=UHD_AT_100)
    states = record(vm)
    with caplog.at_level(logging.ERROR):
        vm.zoom_in()
        vm.dismiss_suggestion()  # nothing suggested any more: no-op
    assert [s.chosen_percent for s in states] == [110]
    assert "Could not save the interface size" in caplog.text


def test_dismiss_save_failure_is_logged(caplog):
    vm = make_vm(FailingStore(), display=UHD_AT_100)
    with caplog.at_level(logging.ERROR):
        vm.dismiss_suggestion()
    assert vm.state.suggest_percent is None
    assert "Could not save the dismissed" in caplog.text


# ------------------------------------------------------------------ QAction wiring

@pytest.mark.parametrize("command", COMMANDS)
def test_commands_take_no_parameters(command):
    assert list(inspect.signature(getattr(UiScaleViewModel, command)).parameters) == ["self"]


def test_real_qaction_triggered_moves_one_step(qapp, store):
    vm = make_vm(store, display=RETINA)
    larger, smaller = QAction("Larger Interface"), QAction("Smaller Interface")
    larger.triggered.connect(vm.zoom_in)     # triggered(bool) must not reach a parameter
    smaller.triggered.connect(vm.zoom_out)
    larger.trigger()
    assert vm.state.chosen_percent == 110
    smaller.trigger()
    smaller.trigger()
    assert vm.state.chosen_percent == 90


@pytest.mark.parametrize("command, display, saved_percent, expected", [
    ("zoom_in", RETINA, None, ("chosen_percent", 110)),
    ("zoom_out", RETINA, None, ("chosen_percent", 90)),
    ("reset_zoom", RETINA, 150, ("chosen_percent", 100)),
    ("accept_suggestion", UHD_AT_100, None, ("chosen_percent", SUGGESTED_PERCENT)),
    ("dismiss_suggestion", UHD_AT_100, None, ("suggest_percent", None)),
])
def test_every_command_acts_once_from_qaction_triggered(qapp, store, command, display,
                                                        saved_percent, expected):
    if saved_percent is not None:
        store.zoom_steps = {display.name: step(saved_percent)}
    vm = make_vm(store, display=display)
    states = record(vm)
    action = QAction(command)
    action.triggered.connect(getattr(vm, command))
    action.trigger()
    field, value = expected
    assert getattr(vm.state, field) == value and len(states) == 1


def test_restart_now_from_qaction_triggered(qapp, store, restarter):
    store.zoom_steps = {RETINA.name: step(125)}
    vm = make_vm(store, restarter, display=RETINA)
    action = QAction("Restart Now")
    action.triggered.connect(vm.restart_now)
    action.trigger()
    assert restarter.restarts == 1


def test_postpone_restart_from_qaction_triggered(qapp, store):
    vm = make_vm(store, display=RETINA)
    vm.zoom_in()
    states = record(vm)
    action = QAction("Later")
    action.triggered.connect(vm.postpone_restart)
    action.trigger()
    assert vm.state.notice is ZoomNotice.NONE and len(states) == 1
