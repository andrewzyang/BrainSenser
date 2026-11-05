"""ShellActions: the shell's commands as QActions, bound to the shell ViewModels (plan §4.7, M4.3).

- Interface size: Larger Interface, Smaller Interface and Default Size (Ctrl/Cmd
  +, −, 0), and Restart Now whenever a restart would change the size (also after
  the banner's Later), under a greyed "Interface Size: 125 %" header.
- Sidebar: Automatic / Labels / Icons, the persistent preference (D4).
- ``interface_action``: "Aa" (with the size when it isn't the default) and the
  menu of both. The sidebar footer shows it on every platform.
- On macOS (``platform_name == "cocoa"``) the menu bar has the same commands as
  a View menu, and a Go menu of the pages. Elsewhere there is no menu bar; on
  macOS the offscreen platform would put one inside the window, so the platform
  is passed in (R9).
- ``banner``: the restart notice and the D2 suggestion, as ``ZoomState.notice``
  says; MainLayout places it.

State first, then its change signals (R2): every action shows the ViewModels'
state before following it. Commands connect ``triggered``, never ``toggled``
(a check made by code fires that too), and the banner's buttons, to slots
without parameters (R3). The interface-size shortcuts work anywhere in the
window: their actions are added to it.
"""

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenu

from src.ui.components.restart_banner import RestartBanner
from src.ui.policy.layout import SidebarPreference
from src.ui.policy.scale import ZoomState

if TYPE_CHECKING:
    from src.ui.viewmodels import ShellViewModel, UiScaleViewModel

# View ▸ Sidebar, in menu order
SIDEBAR_CHOICES = (
    (SidebarPreference.AUTO, "Automatic"),
    (SidebarPreference.LABELS, "Labels"),
    (SidebarPreference.ICONS, "Icons"),
)


class ShellActions(QObject):
    """
    Interface-size and sidebar commands, their menus and the restart banner.

    Example:
        >>> actions = ShellActions(window, scale_vm, shell_vm,
        ...                        platform_name=QGuiApplication.platformName())
        >>> sidebar.set_interface_action(actions.interface_action)
        >>> main_layout.add_banner(actions.banner)
    """

    def __init__(self, window: QMainWindow, scale_vm: "UiScaleViewModel",
                 shell_vm: "ShellViewModel", *, platform_name: str,
                 parent: Optional[QObject] = None):
        """
        Args:
            window: The main window: its shortcuts, its menu bar (macOS) and its
                sidebar's Go menu
            scale_vm: The interface-size ViewModel
            shell_vm: The shell ViewModel (sidebar preference)
            platform_name: ``QGuiApplication.platformName()``; "cocoa" adds the menu bar
            parent: Owning QObject; the window if None
        """
        super().__init__(parent if parent is not None else window)
        self._shell_vm = shell_vm

        # Interface size
        self.size_header = QAction(self)
        self.size_header.setEnabled(False)
        self.zoom_in_action = QAction("Larger Interface", self)
        self.zoom_in_action.setShortcuts(
            [*QKeySequence.keyBindings(QKeySequence.StandardKey.ZoomIn), QKeySequence("Ctrl+=")])
        self.zoom_out_action = QAction("Smaller Interface", self)
        self.zoom_out_action.setShortcuts(
            QKeySequence.keyBindings(QKeySequence.StandardKey.ZoomOut))
        self.reset_zoom_action = QAction("Default Size", self)
        self.reset_zoom_action.setShortcut(QKeySequence("Ctrl+0"))
        self.restart_action = QAction("Restart Now", self)
        window.addActions([self.zoom_in_action, self.zoom_out_action, self.reset_zoom_action])

        # Sidebar preference
        self._sidebar_group = QActionGroup(self)
        self.sidebar_actions = {}
        for preference, text in SIDEBAR_CHOICES:
            action = QAction(text, self)
            action.setCheckable(True)
            action.setData(preference.value)
            self._sidebar_group.addAction(action)
            self.sidebar_actions[preference.value] = action

        # "Aa" in the sidebar footer, with every command as its menu
        self.interface_menu = QMenu(window)
        self._add_commands(self.interface_menu)
        self.interface_action = QAction("Aa", self)
        self.interface_action.setMenu(self.interface_menu)

        if platform_name == "cocoa":
            view_menu = QMenu("View", window)
            self._add_commands(view_menu)
            menu_bar = window.menuBar()
            menu_bar.addMenu(view_menu)
            menu_bar.addMenu(window.sidebar.go_menu(window))

        # In the window from the start: shown now (a pending size, an offer), it
        # must not open as a window of its own before MainLayout places it.
        self.banner = RestartBanner(window)

        # State first, then its changes
        self._show_zoom_state(scale_vm.state)
        self._show_sidebar_preference(shell_vm.sidebar_preference)
        scale_vm.state_changed.connect(self._show_zoom_state)
        shell_vm.sidebar_preference_changed.connect(self._show_sidebar_preference)

        # Commands
        self.zoom_in_action.triggered.connect(scale_vm.zoom_in)
        self.zoom_out_action.triggered.connect(scale_vm.zoom_out)
        self.reset_zoom_action.triggered.connect(scale_vm.reset_zoom)
        self.restart_action.triggered.connect(scale_vm.restart_now)
        self.banner.restart_requested.connect(scale_vm.restart_now)
        self.banner.restart_postponed.connect(scale_vm.postpone_restart)
        self.banner.suggestion_accepted.connect(scale_vm.accept_suggestion)
        self.banner.suggestion_dismissed.connect(scale_vm.dismiss_suggestion)
        self._sidebar_group.triggered.connect(self._on_sidebar_choice)

    def _add_commands(self, menu: QMenu) -> None:
        """The interface-size commands under their header, then the Sidebar submenu."""
        menu.addActions([self.size_header, self.zoom_in_action, self.zoom_out_action,
                         self.reset_zoom_action, self.restart_action])
        menu.addSeparator()
        # Built with its parent: PySide6 deletes the menu addMenu(title) returns
        # once that Python wrapper is gone.
        sidebar_menu = QMenu("Sidebar", menu)
        sidebar_menu.addActions(list(self.sidebar_actions.values()))
        menu.addMenu(sidebar_menu)

    def _show_zoom_state(self, state: ZoomState) -> None:
        """Enable what can be done now and name the size, in the menus, on "Aa"
        and in the banner."""
        self.size_header.setText(f"Interface Size: {state.label}")
        self.zoom_in_action.setEnabled(state.can_zoom_in)
        self.zoom_out_action.setEnabled(state.can_zoom_out)
        self.reset_zoom_action.setEnabled(state.can_reset)
        self.restart_action.setVisible(state.restart_required)
        is_default = state.chosen_percent == state.default_percent
        self.interface_action.setText("Aa" if is_default else f"Aa {state.label}")
        pending = " — changes after restart" if state.restart_required else ""
        self.interface_action.setToolTip(f"Interface Size: {state.label}{pending}")
        self.banner.show_state(state)

    def _show_sidebar_preference(self, preference: str) -> None:
        """Check the preference's entry (code-made, so no command follows)."""
        self.sidebar_actions[preference].setChecked(True)

    def _on_sidebar_choice(self, action: QAction) -> None:
        """An entry of the Sidebar submenu was picked."""
        self._shell_vm.set_sidebar_preference(action.data())
