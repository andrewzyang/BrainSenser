"""ApplicationContainer: the shell / interface-size providers (plan §4.7 composition row).

Lazy singletons, one per container; both ViewModels share one store; the
interface-size ViewModel's session factor and lock come from the start-up
environment. The default store is the per-test INI of the root conftest.
"""

import pytest
from dependency_injector import providers

import src.infrastructure.preferences.qsettings_ui_preferences as qsettings_ui_preferences
from src.infrastructure.app_restart import QProcessAppRestarter
from src.infrastructure.container import ApplicationContainer
from src.infrastructure.preferences import InMemoryUiPreferences, QSettingsUiPreferences
from src.ui.policy.scale import (
    QT_SCALE_FACTOR, QT_SCREEN_SCALE_FACTORS, SCALE_INJECTED, UI_SCALE_KILL_SWITCH,
    ScreenMetrics,
)
from src.ui.viewmodels import ShellViewModel, UiScaleViewModel


@pytest.fixture
def container():
    container = ApplicationContainer()
    container.startup_environment.override(providers.Object({}))
    return container


def test_one_instance_per_container(container):
    assert container.ui_scale_viewmodel() is container.ui_scale_viewmodel()
    assert container.shell_viewmodel() is container.shell_viewmodel()
    assert container.ui_preferences() is container.ui_preferences()
    assert container.app_restarter() is container.app_restarter()
    other = ApplicationContainer()
    assert other.shell_viewmodel() is not container.shell_viewmodel()


def test_types(container):
    assert isinstance(container.ui_scale_viewmodel(), UiScaleViewModel)
    assert isinstance(container.shell_viewmodel(), ShellViewModel)
    assert isinstance(container.ui_preferences(), QSettingsUiPreferences)
    assert isinstance(container.app_restarter(), QProcessAppRestarter)


def test_both_viewmodels_share_one_store(container):
    store = InMemoryUiPreferences()
    container.ui_preferences.override(providers.Object(store))
    container.shell_viewmodel().set_sidebar_preference("icons")
    scale_vm = container.ui_scale_viewmodel()
    scale_vm.set_current_display(ScreenMetrics("Built-in Retina Display", 1280, 828, 2.0))
    scale_vm.zoom_in()
    assert (store.sidebar_preference, store.zoom_steps) == ("icons", {"Built-in Retina Display": 2})


def test_nothing_is_built_or_read_until_asked(monkeypatch):
    opened = []
    real = qsettings_ui_preferences.native_settings
    monkeypatch.setattr(qsettings_ui_preferences, "native_settings",
                        lambda: opened.append(1) or real())
    container = ApplicationContainer()
    assert opened == []
    container.shell_viewmodel()
    assert opened  # the ShellViewModel restored its preferences now


def test_override_is_per_container():
    overridden, plain = ApplicationContainer(), ApplicationContainer()
    store = InMemoryUiPreferences()
    store.sidebar_preference = "icons"
    overridden.ui_preferences.override(providers.Object(store))
    assert overridden.shell_viewmodel().sidebar_preference == "icons"
    assert plain.shell_viewmodel().sidebar_preference == "auto"


@pytest.mark.parametrize("environment, active_percent, locked", [
    ({}, 100, False),
    ({QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1"}, 125, False),
    ({QT_SCALE_FACTOR: "1.5"}, 150, True),                       # set by the user / IT
    ({QT_SCREEN_SCALE_FACTORS: "DELL U2720Q=1.5"}, 100, True),
    ({UI_SCALE_KILL_SWITCH: "1"}, 100, True),
])
def test_session_factor_and_lock_come_from_the_startup_environment(environment, active_percent,
                                                                   locked):
    container = ApplicationContainer()
    container.startup_environment.override(providers.Object(environment))
    state = container.ui_scale_viewmodel().state
    assert (state.active_percent, state.locked) == (active_percent, locked)


def test_default_startup_environment_is_the_process_environment(monkeypatch):
    monkeypatch.setenv(QT_SCALE_FACTOR, "1.75")
    monkeypatch.setenv(SCALE_INJECTED, "1")
    monkeypatch.delenv(QT_SCREEN_SCALE_FACTORS, raising=False)
    monkeypatch.delenv(UI_SCALE_KILL_SWITCH, raising=False)
    state = ApplicationContainer().ui_scale_viewmodel().state
    assert (state.active_percent, state.locked) == (175, False)


def test_default_store_writes_to_the_per_test_ini(container):
    container.shell_viewmodel().set_sidebar_preference("labels")
    assert QSettingsUiPreferences().load_sidebar_preference() == "labels"
