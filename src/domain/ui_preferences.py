"""Ports of the shell ViewModels: UI preference stores and the app restart.

Pure Python Protocols over primitive types only (str, int, bytes, None,
dict[str, int], frozenset[str]), so the ViewModels depend on these abstractions
and never on QSettings or a process API (plan §4.7, R6). The QSettings adapter
lives in ``src/infrastructure/preferences/`` (tests use ``InMemoryUiPreferences``);
the restarter in ``src/infrastructure/app_restart.py``. Implementations may
raise; the ViewModels log store failures and carry on.
"""

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class ZoomPreferenceStore(Protocol):
    """Interface size per display (UiScaleViewModel)."""

    def load_zoom_steps(self) -> dict[str, int]:
        """The interface-size step chosen per display name; {} if none."""

    def save_zoom_steps(self, steps: dict[str, int]) -> None:
        """Replace every saved step."""

    def load_dismissed_suggestions(self) -> frozenset[str]:
        """Display names whose interface-size suggestion was dismissed."""

    def save_dismissed_suggestions(self, displays: frozenset[str]) -> None:
        """Replace the set of dismissed display names."""


@runtime_checkable
class ShellPreferenceStore(Protocol):
    """Sidebar choice and window placement (ShellViewModel)."""

    def load_sidebar_preference(self) -> Optional[str]:
        """The saved sidebar preference value, or None."""

    def save_sidebar_preference(self, preference: str) -> None:
        """Save the sidebar preference value."""

    def load_window_geometry(self) -> Optional[bytes]:
        """The saved window-geometry memento (opaque bytes), or None."""

    def load_last_screen(self) -> Optional[str]:
        """Name of the screen the window was on when its geometry was saved, or None."""

    def save_window_geometry(self, geometry: bytes, screen_name: str) -> None:
        """Save the memento together with the name of the screen it belongs to."""


@runtime_checkable
class AppRestarter(Protocol):
    """Restarts the application (to apply a new interface size)."""

    def restart(self) -> None:
        """Start a new instance of the app, then quit this one."""
