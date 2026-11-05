"""
ShellViewModel - presentation state of the application shell.

Owns the sidebar choice and the window-placement memento (plan §4.7, D4):

- the persistent sidebar preference (View ▸ Sidebar: Automatic / Labels / Icons);
- a session override from the sidebar footer toggle, cleared when the window
  width class changes, when a preference is chosen and on relaunch;
- the effective sidebar mode, resolved from the preference, the window width
  class (a fact the View reports; WIDE until it does) and the override;
- the window-geometry memento and the screen it was saved on, kept as opaque
  data that the View hands back to Qt.

Preferences go through the injected ShellPreferenceStore only. The constructor
restores them and emits nothing; afterwards a signal fires only on a real
change, the preference before the mode. Store failures are logged, never raised.

Author: iEEG BrainSense Development Team
Last Updated: 2026-10-27
"""

import logging
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import QObject, Signal

from src.domain.ui_preferences import ShellPreferenceStore
from src.ui.policy.layout import SidebarMode, SidebarPreference, WidthClass, resolve_sidebar_mode

logger = logging.getLogger(__name__)


class ShellViewModel(QObject):
    """
    Sidebar mode and window placement for the main window.

    Signals:
        sidebar_preference_changed: The persistent preference value
            ("auto" | "labels" | "icons"); emitted before sidebar_mode_changed.
        sidebar_mode_changed: The effective mode ("labels" | "icons").

    Example:
        >>> shell_vm = ShellViewModel(store)
        >>> sidebar.set_mode(shell_vm.sidebar_mode)          # read first,
        >>> shell_vm.sidebar_mode_changed.connect(sidebar.set_mode)  # then connect
        >>> shell_vm.set_width_class("narrow")               # View-reported fact
    """

    sidebar_preference_changed = Signal(str)
    sidebar_mode_changed = Signal(str)

    def __init__(self, store: ShellPreferenceStore, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._store = store
        self._width_class = WidthClass.WIDE
        self._override: Optional[SidebarMode] = None

        self._preference = SidebarPreference.AUTO
        saved = self._load(store.load_sidebar_preference)
        if saved is not None:
            try:
                self._preference = SidebarPreference(saved)
            except ValueError:
                logger.warning("Ignoring unknown saved sidebar preference %r", saved)
        geometry = self._load(store.load_window_geometry)
        self._geometry: Optional[bytes] = (
            geometry if isinstance(geometry, bytes) and geometry else None)
        screen = self._load(store.load_last_screen)
        self._last_screen: Optional[str] = screen if isinstance(screen, str) else None

    @property
    def sidebar_preference(self) -> str:
        """The persistent preference: "auto" | "labels" | "icons"."""
        return self._preference.value

    @property
    def sidebar_mode(self) -> str:
        """What the sidebar shows: "labels" | "icons"."""
        return self._mode().value

    @property
    def last_screen_name(self) -> Optional[str]:
        """Name of the screen the window was on when its geometry was saved."""
        return self._last_screen

    def set_sidebar_preference(self, value: str) -> None:
        """Choose the persistent preference; clears the session override."""
        try:
            preference = SidebarPreference(value)
        except ValueError:
            logger.warning("Ignoring unknown sidebar preference %r", value)
            return
        mode_before = self._mode()
        self._override = None
        if preference is not self._preference:
            self._preference = preference
            self._save(self._store.save_sidebar_preference, preference.value)
            self.sidebar_preference_changed.emit(preference.value)
        self._emit_mode_if_changed(mode_before)

    def toggle_sidebar(self) -> None:
        """Footer toggle: show the other mode for this session (not persisted)."""
        mode_before = self._mode()
        target = SidebarMode.ICONS if mode_before is SidebarMode.LABELS else SidebarMode.LABELS
        # Toggling back to what the preference gives anyway leaves no override.
        without_override = resolve_sidebar_mode(self._preference, self._width_class)
        self._override = None if target is without_override else target
        self._emit_mode_if_changed(mode_before)

    def set_width_class(self, width_class: str) -> None:
        """The window's width class ("narrow" | "wide"), as the View classified it.
        A change clears the session override."""
        try:
            new_class = WidthClass(width_class)
        except ValueError:
            logger.warning("Ignoring unknown width class %r", width_class)
            return
        if new_class is self._width_class:
            return
        mode_before = self._mode()
        self._width_class = new_class
        self._override = None
        self._emit_mode_if_changed(mode_before)

    def saved_window_geometry(self, connected_screens: Sequence[str]) -> Optional[bytes]:
        """The saved memento if the screen it was saved on is still connected, else None."""
        if self._geometry is not None and self._last_screen in connected_screens:
            return self._geometry
        return None

    def remember_window_geometry(self, blob: bytes, screen_name: str) -> None:
        """Keep and save the window's geometry memento and its screen; never raises."""
        if not isinstance(blob, bytes) or not blob or not isinstance(screen_name, str):
            logger.warning("Ignoring an invalid window-geometry memento for %r", screen_name)
            return
        self._geometry = blob
        self._last_screen = screen_name
        self._save(self._store.save_window_geometry, blob, screen_name)

    def _mode(self) -> SidebarMode:
        return resolve_sidebar_mode(self._preference, self._width_class, self._override)

    def _emit_mode_if_changed(self, mode_before: SidebarMode) -> None:
        mode = self._mode()
        if mode is not mode_before:
            self.sidebar_mode_changed.emit(mode.value)

    @staticmethod
    def _load(load: Callable[[], Any]) -> Any:
        try:
            return load()
        except Exception:
            logger.exception("Could not load a shell preference; using the default")
            return None

    @staticmethod
    def _save(save: Callable[..., None], *values: Any) -> None:
        try:
            save(*values)
        except Exception:
            logger.exception("Could not save a shell preference")
