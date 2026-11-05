"""UI preference stores: adapters for the ports in src/domain/ui_preferences.py.

Only the composition root (container, bootstrap) imports this package; the
ViewModels get a store injected and Views never touch it (plan R6).
"""

from src.infrastructure.preferences.in_memory_ui_preferences import InMemoryUiPreferences
from src.infrastructure.preferences.qsettings_ui_preferences import QSettingsUiPreferences

__all__ = [
    'InMemoryUiPreferences',
    'QSettingsUiPreferences',
]
