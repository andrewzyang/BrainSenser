"""ShellActions: interface-size and sidebar commands bound to the real ViewModels
(plan §4.7 R2/R3/R9, M4.3, D2, D4).

The actions show the ViewModels' state before following it, and building them
emits and writes nothing; one trigger is one command; a check made from the
ViewModel never calls back; "Aa" shows the size when it isn't the default; the
restart banner and the D2 offer follow the state; the shortcuts are on the
window; "cocoa" gets a View and a Go menu in the menu bar, every other platform
no menu bar at all (offscreen on macOS would put one inside the window, so the
platform name is injected).
"""

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenuBar

from src.infrastructure.preferences import InMemoryUiPreferences
from src.ui.components.sidebar import Sidebar
from src.ui.policy.scale import ZOOM_LADDER, ScreenMetrics, ZoomNotice
from src.ui.shell.shell_actions import ShellActions
from src.ui.viewmodels.shell_viewmodel import ShellViewModel
from src.ui.viewmodels.ui_scale_viewmodel import UiScaleViewModel

LAPTOP = ScreenMetrics("Built-in Retina Display", 1280, 828, 2.0)
UHD = ScreenMetrics("DELL U2720Q", 3840, 2160, 1.0)  # 4K at 100 %: offered 125 % (D2)


class _Restarter:
    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1


@pytest.fixture
def store():
    return InMemoryUiPreferences()


@pytest.fixture
def restarter():
    return _Restarter()


@pytest.fixture
def make(qtbot, store, restarter):
    """``make(platform_name, display=LAPTOP, **vm_options)`` -> (actions, scale_vm, shell_vm, window)."""
    def build(platform_name="offscreen", display=LAPTOP, **vm_options):
        scale_vm = UiScaleViewModel(store, restarter, active_factor=vm_options.pop("factor", 1.0),
                                    **vm_options)
        scale_vm.set_current_display(display)
        shell_vm = ShellViewModel(store)
        window = QMainWindow()
        window.sidebar = Sidebar()
        qtbot.addWidget(window)
        actions = ShellActions(window, scale_vm, shell_vm, platform_name=platform_name)
        return actions, scale_vm, shell_vm, window
    return build


def _texts(menu):
    return [a.text() for a in menu.actions()]


def _recorder(signal):
    received = []
    signal.connect(received.append)
    return received


# ------------------------------------------------------------- read, then connect

def test_built_from_the_state_without_emitting_or_writing(make, store):
    store.zoom_steps = {LAPTOP.name: len(ZOOM_LADDER) - 1}  # 200 %, chosen before
    store.sidebar_preference = "icons"
    before = (dict(store.zoom_steps), store.sidebar_preference)

    actions, scale_vm, shell_vm, _window = make()

    assert actions.size_header.text() == "Interface Size: 200 %"
    assert not actions.size_header.isEnabled()
    assert not actions.zoom_in_action.isEnabled()  # top of the ladder
    assert actions.zoom_out_action.isEnabled() and actions.reset_zoom_action.isEnabled()
    assert actions.restart_action.isVisible()       # 200 % chosen, 100 % active
    assert actions.interface_action.text() == "Aa 200 %"
    assert actions.sidebar_actions["icons"].isChecked()
    assert (dict(store.zoom_steps), store.sidebar_preference) == before


def test_at_the_default_aa_shows_no_size_and_nothing_is_pending(make):
    actions, *_ = make()
    assert actions.interface_action.text() == "Aa"
    assert actions.interface_action.toolTip() == "Interface Size: 100 %"
    assert not actions.restart_action.isVisible()
    assert not actions.reset_zoom_action.isEnabled()
    assert actions.zoom_out_action.isEnabled()  # 90 % is offered on Retina
    assert not actions.banner.isVisibleTo(actions.banner.parentWidget() or actions.banner)


# ---------------------------------------------------------------------- commands

def test_one_trigger_is_one_step(make, store):
    actions, scale_vm, _shell_vm, _window = make()
    states = _recorder(scale_vm.state_changed)

    actions.zoom_in_action.trigger()  # triggered(bool) must not reach a parameter

    assert scale_vm.state.chosen_percent == 110
    assert store.zoom_steps == {LAPTOP.name: ZOOM_LADDER.index(110)}
    assert len(states) == 1
    assert actions.interface_action.text() == "Aa 110 %"
    assert actions.interface_action.toolTip() == "Interface Size: 110 % — changes after restart"
    assert actions.size_header.text() == "Interface Size: 110 %"
    assert actions.restart_action.isVisible() and actions.reset_zoom_action.isEnabled()


def test_smaller_and_default_size(make):
    actions, scale_vm, *_ = make()
    actions.zoom_out_action.trigger()
    assert scale_vm.state.chosen_percent == 90
    actions.reset_zoom_action.trigger()
    assert scale_vm.state.chosen_percent == 100
    assert not actions.restart_action.isVisible()


def test_restart_now_restarts_once(make, restarter):
    actions, *_ = make()
    actions.restart_action.trigger()
    assert restarter.restarts == 0  # nothing pending
    actions.zoom_in_action.trigger()
    actions.restart_action.trigger()
    assert restarter.restarts == 1


def test_sidebar_choice_sets_the_preference_and_follows_it(make, store):
    actions, _scale_vm, shell_vm, _window = make()
    assert actions.sidebar_actions["auto"].isChecked()
    assert [a.text() for a in actions.sidebar_actions.values()] == ["Automatic", "Labels",
                                                                    "Icons"]

    actions.sidebar_actions["labels"].trigger()
    assert shell_vm.sidebar_preference == "labels" == store.sidebar_preference

    # Set elsewhere: the check follows, and checking it calls nothing back
    writes = []
    store.save_sidebar_preference = writes.append
    shell_vm.set_sidebar_preference("icons")
    assert actions.sidebar_actions["icons"].isChecked()
    assert writes == ["icons"]


def test_locked_interface_size_offers_no_commands(make, store):
    actions, scale_vm, *_ = make(factor=1.25, locked=True)
    assert not any(a.isEnabled() for a in (actions.zoom_in_action, actions.zoom_out_action,
                                           actions.reset_zoom_action))
    assert actions.size_header.text() == "Interface Size: 125 %"
    actions.zoom_in_action.trigger()
    assert store.zoom_steps == {}


# ------------------------------------------------------------------ menus, shortcuts

def test_aa_menu_holds_the_commands_and_the_sidebar_choice(make):
    actions, *_ = make()
    assert actions.interface_action.menu() is actions.interface_menu
    assert _texts(actions.interface_menu) == ["Interface Size: 100 %", "Larger Interface",
                                              "Smaller Interface", "Default Size",
                                              "Restart Now", "", "Sidebar"]
    sidebar_menu = actions.interface_menu.actions()[-1].menu()
    assert sidebar_menu.actions() == list(actions.sidebar_actions.values())


def test_shortcuts_work_anywhere_in_the_window(make):
    actions, _scale_vm, _shell_vm, window = make()
    assert {actions.zoom_in_action, actions.zoom_out_action,
            actions.reset_zoom_action} <= set(window.actions())
    zoom_in = actions.zoom_in_action.shortcuts()
    assert QKeySequence(QKeySequence.StandardKey.ZoomIn) in zoom_in
    assert QKeySequence("Ctrl+=") in zoom_in
    assert QKeySequence(QKeySequence.StandardKey.ZoomOut) in actions.zoom_out_action.shortcuts()
    assert actions.reset_zoom_action.shortcut() == QKeySequence("Ctrl+0")


def test_cocoa_mirrors_the_menu_in_the_menu_bar(make):
    actions, _scale_vm, _shell_vm, window = make("cocoa")
    view_menu, go_menu = [a.menu() for a in window.menuBar().actions()]
    assert (view_menu.title(), go_menu.title()) == ("View", "Go")
    assert view_menu.actions()[:5] == actions.interface_menu.actions()[:5]  # the same actions
    assert view_menu.actions()[0].text() == "Interface Size: 100 %"
    assert view_menu.actions()[-1].menu().actions() == list(actions.sidebar_actions.values())
    assert set(window.sidebar.actions()) <= set(go_menu.actions())


@pytest.mark.parametrize("platform_name", ["offscreen", "windows", "xcb", "wayland"])
def test_no_menu_bar_elsewhere(make, platform_name):
    _actions, _scale_vm, _shell_vm, window = make(platform_name)
    assert window.findChildren(QMenuBar) == []


# ----------------------------------------------------------------------- banner

def test_banner_offers_a_restart_after_a_change(make, restarter, qtbot):
    actions, *_ = make()
    banner = actions.banner
    assert not banner.isVisibleTo(banner)  # nothing pending

    actions.zoom_in_action.trigger()
    assert not banner.isHidden()
    assert banner.message.text() == "Interface size changes after restart"
    assert (banner.primary_button.text(), banner.secondary_button.text()) == (
        "Restart Now", "Later")

    banner.primary_button.click()
    assert restarter.restarts == 1


def test_later_hides_the_banner_until_another_size_is_chosen(make, store, restarter):
    actions, scale_vm, *_ = make()
    banner = actions.banner
    actions.zoom_in_action.trigger()
    saved = dict(store.zoom_steps)
    banner.secondary_button.click()  # Later: the ViewModel's call (session only)
    assert banner.isHidden() and scale_vm.state.notice is ZoomNotice.NONE
    assert store.zoom_steps == saved
    assert actions.restart_action.isVisible()  # Restart Now stays in the "Aa" menu
    actions.restart_action.trigger()
    assert restarter.restarts == 1
    actions.zoom_in_action.trigger()  # 125 %
    assert not banner.isHidden()
    actions.reset_zoom_action.trigger()  # back to the active size: nothing pending
    assert banner.isHidden() and not actions.restart_action.isVisible()


def test_moving_to_a_display_with_another_size_shows_no_banner(make, store):
    """The session runs at the 125 % saved for the external display; the window
    moves to the laptop, which has another size: a restart would change the size,
    so the menu offers it, but nothing was chosen, so nothing is announced."""
    external = ScreenMetrics("DELL U2720Q", 2048, 1152, 1.25)
    laptop = ScreenMetrics("Built-in Retina Display", 1024, 662, 2.5)
    store.zoom_steps = {external.name: ZOOM_LADDER.index(125)}
    actions, scale_vm, *_ = make(display=external, factor=1.25)
    assert actions.banner.isHidden() and not actions.restart_action.isVisible()

    scale_vm.set_current_display(laptop)

    assert actions.banner.isHidden()
    assert actions.restart_action.isVisible()
    assert actions.interface_action.toolTip() == "Interface Size: 100 % — changes after restart"


def test_dense_display_is_offered_125_percent_once(make, store):
    actions, scale_vm, _shell_vm, window = make(display=UHD)
    banner = actions.banner
    assert scale_vm.state.suggest_percent == 125
    assert not banner.isHidden()
    assert not banner.isWindow() and window.isAncestorOf(banner)  # never a window of its own
    assert (banner.primary_button.text(), banner.secondary_button.text()) == (
        "Use 125 %", "Keep 100 %")

    banner.secondary_button.click()  # declined: never again on this display
    assert banner.isHidden()
    assert store.dismissed_suggestions == frozenset({UHD.name})


def test_accepting_the_offer_asks_for_a_restart(make):
    actions, scale_vm, *_ = make(display=UHD)
    actions.banner.primary_button.click()
    assert scale_vm.state.chosen_percent == 125
    assert actions.banner.message.text() == "Interface size changes after restart"
    assert actions.interface_action.text() == "Aa 125 %"
