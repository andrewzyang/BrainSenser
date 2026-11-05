"""Dict-backed UI preferences: the store ports without QSettings, for tests and harnesses."""

from typing import Optional


class InMemoryUiPreferences:
    """Implements ZoomPreferenceStore and ShellPreferenceStore in memory.

    The attributes are the stored values; tests may set or inspect them directly.
    """

    def __init__(self) -> None:
        self.zoom_steps: dict[str, int] = {}
        self.dismissed_suggestions: frozenset[str] = frozenset()
        self.sidebar_preference: Optional[str] = None
        self.window_geometry: Optional[bytes] = None
        self.last_screen: Optional[str] = None

    def load_zoom_steps(self) -> dict[str, int]:
        return dict(self.zoom_steps)

    def save_zoom_steps(self, steps: dict[str, int]) -> None:
        self.zoom_steps = dict(steps)

    def load_dismissed_suggestions(self) -> frozenset[str]:
        return self.dismissed_suggestions

    def save_dismissed_suggestions(self, displays: frozenset[str]) -> None:
        self.dismissed_suggestions = frozenset(displays)

    def load_sidebar_preference(self) -> Optional[str]:
        return self.sidebar_preference

    def save_sidebar_preference(self, preference: str) -> None:
        self.sidebar_preference = preference

    def load_window_geometry(self) -> Optional[bytes]:
        return self.window_geometry

    def load_last_screen(self) -> Optional[str]:
        return self.last_screen

    def save_window_geometry(self, geometry: bytes, screen_name: str) -> None:
        self.window_geometry = bytes(geometry)
        self.last_screen = screen_name
