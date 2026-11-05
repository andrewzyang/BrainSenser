"""
Unit tests for EffectSizePreference singleton.

Tests singleton behavior, QSettings persistence, signal emissions,
and compatibility checking.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-09
"""

import pytest

from src.domain.effect_size_preference import (
    EffectSizePreference,
    ORGANIZATION_NAME,
    APPLICATION_NAME,
    SETTINGS_KEY,
    RESET_GUARD_KEY,
    DEFAULT_EFFECT_SIZE
)
from src.domain.models import EffectSizeType


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before and after each test."""
    EffectSizePreference.reset_singleton()
    yield
    EffectSizePreference.reset_singleton()


@pytest.fixture
def mock_qsettings(monkeypatch):
    """Mock QSettings to avoid persisting test data."""
    settings_data = {}

    class MockQSettings:
        def __init__(self, org, app):
            self.org = org
            self.app = app

        def value(self, key, default=None):
            return settings_data.get(key, default)

        def setValue(self, key, value):
            settings_data[key] = value

        def sync(self):
            pass

    monkeypatch.setattr('src.domain.effect_size_preference.QSettings', MockQSettings)
    return settings_data


class TestEffectSizePreference:
    """Test suite for EffectSizePreference singleton."""

    # ========================================================================
    # Singleton Pattern Tests
    # ========================================================================

    def test_singleton_pattern(self, mock_qsettings):
        """Test that only one instance exists."""
        pref1 = EffectSizePreference()
        pref2 = EffectSizePreference()

        assert pref1 is pref2

    def test_singleton_initialization_once(self, mock_qsettings):
        """Test that __init__ only runs once."""
        pref1 = EffectSizePreference()
        pref1.get_effect_size()

        # Change the preference
        pref1.set_effect_size(EffectSizeType.RANK_BISERIAL)

        # Create "new" instance - should be same object with same state
        pref2 = EffectSizePreference()
        assert pref2.get_effect_size() == EffectSizeType.RANK_BISERIAL

    def test_reset_singleton(self, mock_qsettings):
        """Test that reset_singleton clears the instance."""
        pref1 = EffectSizePreference()
        pref1.set_effect_size(EffectSizeType.RANK_BISERIAL)

        # Clear settings to simulate fresh start
        mock_qsettings.clear()

        EffectSizePreference.reset_singleton()

        pref2 = EffectSizePreference()
        # Should be new instance with default value
        assert pref2.get_effect_size() == DEFAULT_EFFECT_SIZE

    # ========================================================================
    # Basic Functionality Tests
    # ========================================================================

    def test_default_effect_size(self, mock_qsettings):
        """Test that default effect size is rank-biserial."""
        pref = EffectSizePreference()
        assert pref.get_effect_size() == DEFAULT_EFFECT_SIZE
        assert pref.get_effect_size() == EffectSizeType.RANK_BISERIAL

    def test_get_effect_size_value(self, mock_qsettings):
        """Test getting effect size as string value."""
        pref = EffectSizePreference()
        assert pref.get_effect_size_value() == "rank_biserial"

        pref.set_effect_size(EffectSizeType.COHENS_D)
        assert pref.get_effect_size_value() == "cohens_d"

    def test_set_effect_size(self, mock_qsettings):
        """Test setting effect size."""
        pref = EffectSizePreference()
        pref.set_effect_size(EffectSizeType.RANK_BISERIAL)

        assert pref.get_effect_size() == EffectSizeType.RANK_BISERIAL

    def test_reset_to_default(self, mock_qsettings):
        """Test resetting to default effect size."""
        pref = EffectSizePreference()
        pref.set_effect_size(EffectSizeType.ROSENTHAL_R)

        pref.reset_to_default()

        assert pref.get_effect_size() == DEFAULT_EFFECT_SIZE

    # ========================================================================
    # Signal Emission Tests
    # ========================================================================

    def test_signal_emitted_on_change(self, mock_qsettings):
        """Test that signal is emitted when effect size changes."""
        pref = EffectSizePreference()

        # Set up signal spy
        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        # Change effect size (away from the rank-biserial default)
        pref.set_effect_size(EffectSizeType.COHENS_D)

        # Verify signal emitted
        assert len(signal_spy) == 1
        assert signal_spy[0] == "cohens_d"

    def test_signal_not_emitted_on_same_value(self, mock_qsettings):
        """Test that signal is NOT emitted when setting same value."""
        pref = EffectSizePreference()
        pref.set_effect_size(EffectSizeType.COHENS_D)

        # Set up signal spy
        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        # Set same value
        pref.set_effect_size(EffectSizeType.COHENS_D)

        # Signal should NOT be emitted
        assert len(signal_spy) == 0

    def test_signal_emitted_multiple_times(self, mock_qsettings):
        """Test that signal is emitted for each change."""
        pref = EffectSizePreference()

        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        # Make multiple changes. Default is rank-biserial, so the duplicate
        # cohens_d set is a no-op and must not emit a second time.
        pref.set_effect_size(EffectSizeType.COHENS_D)
        pref.set_effect_size(EffectSizeType.COHENS_D)
        pref.set_effect_size(EffectSizeType.RANK_BISERIAL)
        pref.set_effect_size(EffectSizeType.ROSENTHAL_R)

        assert len(signal_spy) == 3
        assert signal_spy == ["cohens_d", "rank_biserial", "rosenthal_r"]

    # ========================================================================
    # QSettings Persistence Tests
    # ========================================================================

    def test_save_to_settings(self, mock_qsettings):
        """Test that preference is saved to QSettings."""
        pref = EffectSizePreference()
        pref.set_effect_size(EffectSizeType.ROSENTHAL_R)

        # Check settings data
        assert mock_qsettings[SETTINGS_KEY] == "rosenthal_r"

    def test_load_from_settings(self, mock_qsettings):
        """Test that preference is loaded from QSettings on initialization."""
        # Pre-populate settings, and mark the one-time reset migration as already
        # applied so it does not override the saved value under test.
        mock_qsettings[SETTINGS_KEY] = "rosenthal_r"
        mock_qsettings[RESET_GUARD_KEY] = "1"

        # Create new instance
        pref = EffectSizePreference()

        assert pref.get_effect_size() == EffectSizeType.ROSENTHAL_R

    def test_load_invalid_setting_uses_default(self, mock_qsettings):
        """Test that invalid saved value falls back to default."""
        # Pre-populate with invalid value
        mock_qsettings[SETTINGS_KEY] = "glass_delta"

        pref = EffectSizePreference()

        # Should fall back to default
        assert pref.get_effect_size() == DEFAULT_EFFECT_SIZE

    def test_persistence_across_instances(self, mock_qsettings):
        """Test that changes persist across singleton instances."""
        pref1 = EffectSizePreference()
        pref1.set_effect_size(EffectSizeType.ROSENTHAL_R)

        # Reset singleton
        EffectSizePreference.reset_singleton()

        # Create new instance - should load from settings
        pref2 = EffectSizePreference()
        assert pref2.get_effect_size() == EffectSizeType.ROSENTHAL_R

    # ========================================================================
    # One-Time Reset Migration Tests
    # ========================================================================

    def test_migration_resets_saved_value_to_rank_biserial(self, mock_qsettings):
        """A saved value with no guard is reset once to rank-biserial."""
        # Simulate an existing install that previously persisted Cohen's d,
        # before this migration shipped (no guard key present).
        mock_qsettings[SETTINGS_KEY] = "cohens_d"
        assert RESET_GUARD_KEY not in mock_qsettings

        pref = EffectSizePreference()

        # Reset to the new default, persisted, and the guard written.
        assert pref.get_effect_size() == EffectSizeType.RANK_BISERIAL
        assert mock_qsettings[SETTINGS_KEY] == "rank_biserial"
        assert mock_qsettings.get(RESET_GUARD_KEY) is not None

    def test_migration_runs_only_once(self, mock_qsettings):
        """After the guard is set, a user's later choice is not overridden."""
        # First launch resets cohens_d -> rank_biserial and writes the guard.
        mock_qsettings[SETTINGS_KEY] = "cohens_d"
        pref1 = EffectSizePreference()
        assert pref1.get_effect_size() == EffectSizeType.RANK_BISERIAL

        # User deliberately picks Cohen's d again, after the migration.
        pref1.set_effect_size(EffectSizeType.COHENS_D)

        # A later launch must respect that choice (migration does not re-fire).
        EffectSizePreference.reset_singleton()
        pref2 = EffectSizePreference()
        assert pref2.get_effect_size() == EffectSizeType.COHENS_D

    # ========================================================================
    # Compatibility Tests
    # ========================================================================

    def test_compatible_effect_sizes_mann_whitney(self, mock_qsettings):
        """Test getting compatible effect sizes for Mann-Whitney U test."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Mann-Whitney U")

        assert EffectSizeType.RANK_BISERIAL in compatible
        assert EffectSizeType.ROSENTHAL_R in compatible
        assert EffectSizeType.COHENS_D not in compatible

    def test_compatible_effect_sizes_t_test(self, mock_qsettings):
        """Test getting compatible effect sizes for t-test."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Independent t-test")

        assert compatible == [EffectSizeType.COHENS_D]

    def test_compatible_effect_sizes_welch_test(self, mock_qsettings):
        """Test getting compatible effect sizes for Welch's t-test."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Welch's t-test")

        assert compatible == [EffectSizeType.COHENS_D]

    def test_compatible_effect_sizes_wilcoxon(self, mock_qsettings):
        """Test getting compatible effect sizes for Wilcoxon test."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Wilcoxon Rank-Sum")

        assert EffectSizeType.RANK_BISERIAL in compatible
        assert EffectSizeType.ROSENTHAL_R in compatible

    def test_compatible_effect_sizes_permutation(self, mock_qsettings):
        """Test getting compatible effect sizes for permutation test."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Permutation Test")

        assert EffectSizeType.COHENS_D in compatible
        assert EffectSizeType.RANK_BISERIAL in compatible
        assert EffectSizeType.ROSENTHAL_R in compatible

    def test_compatible_effect_sizes_unknown_test(self, mock_qsettings):
        """Test that unknown test returns all effect sizes."""
        pref = EffectSizePreference()
        compatible = pref.get_compatible_effect_sizes("Unknown Test Method")

        # Should return all effect size types
        assert len(compatible) == len(list(EffectSizeType))

    # ========================================================================
    # Integration Tests
    # ========================================================================

    def test_full_workflow(self, mock_qsettings):
        """Test complete workflow: create, change, persist, reload."""
        # Create and set preference
        pref1 = EffectSizePreference()
        assert pref1.get_effect_size() == DEFAULT_EFFECT_SIZE

        # Change preference (away from the rank-biserial default)
        signal_spy = []
        pref1.effect_size_changed.connect(signal_spy.append)
        pref1.set_effect_size(EffectSizeType.COHENS_D)

        # Verify signal and state
        assert signal_spy == ["cohens_d"]
        assert pref1.get_effect_size() == EffectSizeType.COHENS_D

        # Verify persistence
        assert mock_qsettings[SETTINGS_KEY] == "cohens_d"

        # Reset singleton and reload
        EffectSizePreference.reset_singleton()
        pref2 = EffectSizePreference()

        # Should load saved preference (the migration guard was written on the
        # first construction, so the one-time reset does not re-fire here).
        assert pref2.get_effect_size() == EffectSizeType.COHENS_D

    def test_multiple_listeners(self, mock_qsettings):
        """Test that multiple listeners receive signals."""
        pref = EffectSizePreference()

        spy1 = []
        spy2 = []
        spy3 = []

        pref.effect_size_changed.connect(spy1.append)
        pref.effect_size_changed.connect(spy2.append)
        pref.effect_size_changed.connect(spy3.append)

        pref.set_effect_size(EffectSizeType.ROSENTHAL_R)

        # All listeners should receive signal
        assert spy1 == ["rosenthal_r"]
        assert spy2 == ["rosenthal_r"]
        assert spy3 == ["rosenthal_r"]

    def test_all_effect_types_supported(self, mock_qsettings):
        """Test that all EffectSizeType enum values work."""
        pref = EffectSizePreference()

        for effect_type in EffectSizeType:
            pref.set_effect_size(effect_type)
            assert pref.get_effect_size() == effect_type
            assert pref.get_effect_size_value() == effect_type.value

    def test_settings_organization_and_app_name(self, mock_qsettings):
        """Test that correct organization and app names are used."""
        EffectSizePreference()

        # These constants should match expected values
        assert ORGANIZATION_NAME == "BrainSense"
        assert APPLICATION_NAME == "iEEG-App"
        assert SETTINGS_KEY == "statistics/effect_size_type"

    # ========================================================================
    # Edge Cases
    # ========================================================================

    def test_rapid_sequential_changes(self, mock_qsettings):
        """Test rapid sequential changes."""
        pref = EffectSizePreference()

        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        # Get all effect types except the default (to ensure all changes emit signals)
        all_types = list(EffectSizeType)
        changes_made = 0

        # Make changes (skip if already at that value)
        for effect_type in all_types:
            if pref.get_effect_size() != effect_type:
                pref.set_effect_size(effect_type)
                changes_made += 1

        # Should emit signal for each actual change
        assert len(signal_spy) == changes_made

        # Final state should be last value
        assert pref.get_effect_size() == all_types[-1]

    def test_no_settings_file_uses_default(self, mock_qsettings):
        """Test that missing settings file uses default."""
        # Don't pre-populate settings (simulates first run)
        pref = EffectSizePreference()

        assert pref.get_effect_size() == DEFAULT_EFFECT_SIZE

    def test_concurrent_singleton_access(self, mock_qsettings):
        """Test that concurrent access returns same instance."""
        instances = [EffectSizePreference() for _ in range(10)]

        # All should be the same object
        for instance in instances:
            assert instance is instances[0]

    def test_reset_to_default_emits_signal(self, mock_qsettings):
        """Test that reset_to_default emits signal if value changes."""
        pref = EffectSizePreference()
        # Move away from the rank-biserial default so reset is a real change.
        pref.set_effect_size(EffectSizeType.ROSENTHAL_R)

        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        pref.reset_to_default()

        # Should emit signal
        assert len(signal_spy) == 1
        assert signal_spy[0] == DEFAULT_EFFECT_SIZE.value

    def test_reset_to_default_no_signal_if_already_default(self, mock_qsettings):
        """Test that reset_to_default doesn't emit signal if already at default."""
        pref = EffectSizePreference()
        # Already at default

        signal_spy = []
        pref.effect_size_changed.connect(signal_spy.append)

        pref.reset_to_default()

        # Should NOT emit signal (value didn't change)
        assert len(signal_spy) == 0
