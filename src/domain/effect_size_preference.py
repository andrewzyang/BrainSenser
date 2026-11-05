"""
Effect Size Preference Singleton.

Global singleton for managing user's effect size preference across all
statistical analysis pages. Provides persistence via QSettings.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-09
"""

import logging
from PySide6.QtCore import QObject, Signal, QSettings

from src.domain.models import EffectSizeType

logger = logging.getLogger(__name__)

# Settings keys
ORGANIZATION_NAME = "BrainSense"
APPLICATION_NAME = "iEEG-App"
SETTINGS_KEY = "statistics/effect_size_type"
# One-time migration guard. When this key is absent, the stored effect-size
# preference is reset once to DEFAULT_EFFECT_SIZE (rank-biserial) and the guard is
# written, so any value an existing install previously saved (e.g. "cohens_d")
# adopts the new app-wide default. Subsequent user selections are persisted and
# NOT overridden on later launches. Bump the "_v1" suffix to force a future reset.
RESET_GUARD_KEY = "statistics/effect_size_default_reset_v1"
DEFAULT_EFFECT_SIZE = EffectSizeType.RANK_BISERIAL


class EffectSizePreference(QObject):
    """
    Global singleton for effect size preference.

    Ensures all three statistical analysis pages (Snapshots PSD, Timeline Snapshots,
    Streaming Spectrum) use the same effect size selection. Persists user preference
    between sessions using QSettings.

    Signals
    -------
    effect_size_changed : Signal(str)
        Emitted when effect size preference changes (emits effect_type.value)

    Examples
    --------
    >>> # Get singleton instance
    >>> pref = EffectSizePreference()
    >>>
    >>> # Subscribe to changes
    >>> pref.effect_size_changed.connect(on_effect_size_changed)
    >>>
    >>> # Get current preference
    >>> current = pref.get_effect_size()
    >>> print(current.value)  # "rank_biserial"
    >>>
    >>> # Update preference
    >>> pref.set_effect_size(EffectSizeType.RANK_BISERIAL)
    >>> # This saves to QSettings and emits signal

    Notes
    -----
    - Singleton pattern ensures only one instance exists
    - Preference is automatically saved to QSettings on change
    - Preference is automatically loaded from QSettings on first instantiation
    """

    # Signal emitted when effect size changes
    effect_size_changed = Signal(str)  # effect_type.value as string

    # Singleton instance
    _instance = None

    def __new__(cls):
        """
        Implement singleton pattern.

        Ensures only one instance of EffectSizePreference exists.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Initialize EffectSizePreference singleton.

        Only initializes once. Subsequent calls return the existing instance
        without re-initialization.
        """
        # Only initialize once
        if not hasattr(self, '_initialized'):
            super().__init__()
            self._effect_size_type = DEFAULT_EFFECT_SIZE
            self._load_from_settings()
            self._apply_settings_migrations()
            self._initialized = True
            logger.info(
                f"Initialized EffectSizePreference singleton: "
                f"effect_size={self._effect_size_type.value}"
            )

    def set_effect_size(self, effect_type: EffectSizeType):
        """
        Update effect size preference and notify all listeners.

        Saves preference to QSettings and emits effect_size_changed signal
        if the value has changed.

        Parameters
        ----------
        effect_type : EffectSizeType
            New effect size type to use

        Examples
        --------
        >>> pref = EffectSizePreference()
        >>> pref.set_effect_size(EffectSizeType.RANK_BISERIAL)
        >>> # Preference saved and signal emitted
        """
        if self._effect_size_type != effect_type:
            logger.info(
                f"Changing effect size preference: "
                f"{self._effect_size_type.value} -> {effect_type.value}"
            )
            self._effect_size_type = effect_type
            self._save_to_settings()
            self.effect_size_changed.emit(effect_type.value)

    def get_effect_size(self) -> EffectSizeType:
        """
        Get current effect size preference.

        Returns
        -------
        EffectSizeType
            Current effect size type

        Examples
        --------
        >>> pref = EffectSizePreference()
        >>> current = pref.get_effect_size()
        >>> print(current.value)
        rank_biserial
        """
        return self._effect_size_type

    def get_effect_size_value(self) -> str:
        """
        Get current effect size preference as string value.

        Returns
        -------
        str
            Current effect size type value (e.g., "rank_biserial")

        Examples
        --------
        >>> pref = EffectSizePreference()
        >>> print(pref.get_effect_size_value())
        rank_biserial
        """
        return self._effect_size_type.value

    def _load_from_settings(self):
        """
        Load preference from QSettings.

        Called automatically on initialization. If no saved preference exists,
        uses the default (rank-biserial).
        """
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        saved = settings.value(SETTINGS_KEY, DEFAULT_EFFECT_SIZE.value)

        try:
            self._effect_size_type = EffectSizeType(saved)
            logger.info(f"Loaded effect size preference from settings: {saved}")
        except ValueError:
            logger.warning(
                f"Invalid saved effect size '{saved}', using default: "
                f"{DEFAULT_EFFECT_SIZE.value}"
            )
            self._effect_size_type = DEFAULT_EFFECT_SIZE

    def _save_to_settings(self):
        """
        Persist preference to QSettings.

        Called automatically when preference changes.
        """
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue(SETTINGS_KEY, self._effect_size_type.value)
        settings.sync()  # Ensure immediate write to disk
        logger.debug(f"Saved effect size preference to settings: {self._effect_size_type.value}")

    def _apply_settings_migrations(self):
        """Run one-time settings migrations after loading the saved preference.

        Migration v1: reset any previously-saved effect-size preference to the
        current default (rank-biserial). This is a deliberate, one-time
        "reset everyone" so existing installs that saved Cohen's d (or any other
        value) adopt the new app-wide default. The :data:`RESET_GUARD_KEY` makes
        it run exactly once; any selection the user makes afterwards is persisted
        normally and is not overridden on later launches.

        Presence-based guard (not a typed bool) so it works identically against
        real ``QSettings`` and the mock used in tests, whose ``value()`` does not
        accept a ``type=`` keyword.

        Runs at construction, before any listener can connect, so it intentionally
        does NOT emit ``effect_size_changed``.
        """
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        if settings.value(RESET_GUARD_KEY, None) is not None:
            return  # Migration already applied on a previous launch.

        if self._effect_size_type != DEFAULT_EFFECT_SIZE:
            logger.info(
                "Applying one-time effect-size reset migration: "
                f"{self._effect_size_type.value} -> {DEFAULT_EFFECT_SIZE.value}"
            )
            self._effect_size_type = DEFAULT_EFFECT_SIZE
            self._save_to_settings()

        settings.setValue(RESET_GUARD_KEY, "1")
        settings.sync()
        logger.debug("Effect-size reset migration (v1) marked complete.")

    def reset_to_default(self):
        """
        Reset preference to default (rank-biserial).

        Examples
        --------
        >>> pref = EffectSizePreference()
        >>> pref.reset_to_default()
        >>> print(pref.get_effect_size().value)
        rank_biserial
        """
        self.set_effect_size(DEFAULT_EFFECT_SIZE)

    def get_compatible_effect_sizes(self, test_method: str) -> list[EffectSizeType]:
        """
        Get list of effect sizes compatible with a statistical test.

        Parameters
        ----------
        test_method : str
            Name of statistical test (e.g., "Mann-Whitney U", "Independent t-test")

        Returns
        -------
        list[EffectSizeType]
            List of compatible effect size types

        Examples
        --------
        >>> pref = EffectSizePreference()
        >>> compatible = pref.get_compatible_effect_sizes("Mann-Whitney U")
        >>> print([e.value for e in compatible])
        ['rank_biserial', 'rosenthal_r']
        """
        compatibility_map = {
            "Mann-Whitney U": [
                EffectSizeType.RANK_BISERIAL,
                EffectSizeType.ROSENTHAL_R
            ],
            "Independent t-test": [
                EffectSizeType.COHENS_D
            ],
            "Welch's t-test": [
                EffectSizeType.COHENS_D
            ],
            "Wilcoxon Rank-Sum": [
                EffectSizeType.RANK_BISERIAL,
                EffectSizeType.ROSENTHAL_R
            ],
            "Permutation Test": [
                EffectSizeType.COHENS_D,
                EffectSizeType.RANK_BISERIAL,
                EffectSizeType.ROSENTHAL_R
            ]
        }

        return compatibility_map.get(test_method, list(EffectSizeType))

    @classmethod
    def reset_singleton(cls):
        """
        Reset singleton instance (for testing purposes only).

        WARNING: This should only be used in unit tests to reset state
        between test cases.
        """
        if cls._instance is not None:
            if hasattr(cls._instance, '_initialized'):
                delattr(cls._instance, '_initialized')
        cls._instance = None
        logger.debug("Reset EffectSizePreference singleton")
