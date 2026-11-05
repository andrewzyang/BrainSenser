"""QSettings adapter for the UI preference ports (src/domain/ui_preferences.py).

QSettingsUiPreferences implements ZoomPreferenceStore and ShellPreferenceStore
in the app's one settings scope, EffectSizePreference's organisation and
application name (pinned together by test). It needs QtCore only and no
QCoreApplication, so the bootstrap can read the interface size before
QApplication exists (L0). A value that doesn't parse is ignored with a warning,
so a hand-edited or newer settings file never breaks startup.
"""

import json
import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QByteArray, QSettings

logger = logging.getLogger(__name__)

# The app's settings scope, shared with src.domain.effect_size_preference.
ORGANIZATION_NAME = "BrainSense"
APPLICATION_NAME = "iEEG-App"

# Bump "v1" to discard every saved UI preference at once.
ZOOM_STEPS_KEY = "ui/v1/zoom_steps"                      # JSON object: display name -> ladder step
SUGGESTION_DISMISSED_KEY = "ui/v1/suggestion_dismissed"  # JSON array of display names
SIDEBAR_KEY = "ui/v1/sidebar"                            # sidebar preference value
GEOMETRY_KEY = "ui/v1/geometry"                          # window-geometry memento
SCREEN_KEY = "ui/v1/screen"                              # screen the memento belongs to


def native_settings() -> QSettings:
    """The app's settings in the platform's native store."""
    return QSettings(ORGANIZATION_NAME, APPLICATION_NAME)


class QSettingsUiPreferences:
    """UI preferences in QSettings; ``settings_factory`` defaults to :func:`native_settings`."""

    def __init__(self, settings_factory: Optional[Callable[[], QSettings]] = None) -> None:
        self._settings_factory = settings_factory

    # ---------------------------------------------------------------- zoom

    def load_zoom_steps(self) -> dict[str, int]:
        saved = self._read_json(ZOOM_STEPS_KEY, dict)
        if saved is None:
            return {}
        steps = {name: step for name, step in saved.items()
                 if isinstance(step, int) and not isinstance(step, bool)}
        if len(steps) != len(saved):
            logger.warning("Ignoring non-integer interface-size steps in %s", ZOOM_STEPS_KEY)
        return steps

    def save_zoom_steps(self, steps: dict[str, int]) -> None:
        self._write({ZOOM_STEPS_KEY: json.dumps(steps, sort_keys=True)})

    def load_dismissed_suggestions(self) -> frozenset[str]:
        saved = self._read_json(SUGGESTION_DISMISSED_KEY, list)
        if saved is None:
            return frozenset()
        return frozenset(name for name in saved if isinstance(name, str))

    def save_dismissed_suggestions(self, displays: frozenset[str]) -> None:
        self._write({SUGGESTION_DISMISSED_KEY: json.dumps(sorted(displays))})

    # ---------------------------------------------------------------- shell

    def load_sidebar_preference(self) -> Optional[str]:
        return self._read(SIDEBAR_KEY, str)

    def save_sidebar_preference(self, preference: str) -> None:
        self._write({SIDEBAR_KEY: preference})

    def load_window_geometry(self) -> Optional[bytes]:
        geometry = self._read(GEOMETRY_KEY, QByteArray)
        return bytes(geometry) if geometry else None

    def load_last_screen(self) -> Optional[str]:
        return self._read(SCREEN_KEY, str)

    def save_window_geometry(self, geometry: bytes, screen_name: str) -> None:
        # QByteArray, not bytes: PySide6 would store a Python object (a pickle).
        self._write({GEOMETRY_KEY: QByteArray(geometry), SCREEN_KEY: screen_name})

    # ---------------------------------------------------------------- QSettings

    def _settings(self) -> QSettings:
        # The default is looked up on every call, so the test suite can point
        # native_settings at a throwaway INI file.
        return (self._settings_factory or native_settings)()

    def _read(self, key: str, kind: type) -> Any:
        value = self._settings().value(key)
        if value is not None and not isinstance(value, kind):
            logger.warning("Ignoring unreadable %s: %.80r", key, value)
            return None
        return value

    def _read_json(self, key: str, kind: type) -> Any:
        text = self._read(key, str)
        if text is None:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            value = None
        if not isinstance(value, kind):
            logger.warning("Ignoring unreadable %s: %.80r", key, text)
            return None
        return value

    def _write(self, values: dict[str, Any]) -> None:
        settings = self._settings()
        for key, value in values.items():
            settings.setValue(key, value)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            logger.error("Could not save %s: %s", ", ".join(values), settings.status().name)
