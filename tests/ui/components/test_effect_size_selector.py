"""
Unit tests for EffectSizeSelector widget.

Tests widget creation, signal emissions, dropdown filtering, and user interactions.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-09
"""

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.components.effect_size_selector import EffectSizeSelector
from src.domain.models import EffectSizeType


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def selector(qapp):
    """Create EffectSizeSelector instance."""
    widget = EffectSizeSelector()
    yield widget
    widget.deleteLater()


class TestEffectSizeSelector:
    """Test suite for EffectSizeSelector widget."""

    # ========================================================================
    # Initialization Tests
    # ========================================================================

    def test_widget_creation(self, selector):
        """Test that widget is created successfully."""
        assert selector is not None
        assert selector.dropdown is not None

    def test_default_selection(self, selector):
        """Test that default selection is rank-biserial."""
        assert selector.get_current_effect_size() == EffectSizeType.RANK_BISERIAL.value

    def test_all_options_available_initially(self, selector):
        """Test that all effect size options are available initially."""
        # Should have all effect size types
        assert selector.dropdown.count() == 3

        # Verify all types are present
        available_values = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]

        for effect_type in EffectSizeType:
            assert effect_type.value in available_values

    def test_dropdown_labels(self, selector):
        """Test that dropdown has correct display labels (rank-biserial first)."""
        expected_labels = [
            "Rank-biserial r",
            "Cohen's d",
            "Rosenthal's r"
        ]

        actual_labels = [
            selector.dropdown.itemText(i) for i in range(selector.dropdown.count())
        ]

        assert actual_labels == expected_labels

    # ========================================================================
    # Signal Emission Tests
    # ========================================================================

    def test_signal_emitted_on_user_selection(self, selector):
        """Test that signal is emitted when user changes selection."""
        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Simulate user selecting Cohen's d (index 1; index 0 is the default)
        selector.dropdown.setCurrentIndex(1)

        assert len(signal_spy) == 1
        assert signal_spy[0] == "cohens_d"

    def test_signal_emitted_for_each_selection(self, selector):
        """Test that signal is emitted for each selection change."""
        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Make multiple selections (order: rank-biserial, Cohen's d, Rosenthal's r)
        selector.dropdown.setCurrentIndex(1)  # Cohen's d
        selector.dropdown.setCurrentIndex(2)  # Rosenthal's r

        assert len(signal_spy) == 2
        assert signal_spy == ["cohens_d", "rosenthal_r"]

    def test_no_signal_on_programmatic_set(self, selector):
        """Test that signal is not emitted when set programmatically."""
        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Programmatic set should NOT emit signal, even when it changes the index
        # (default is rank-biserial; rosenthal_r is a real index change).
        selector.set_current_effect_size("rosenthal_r")

        assert len(signal_spy) == 0

    # ========================================================================
    # Get/Set Functionality Tests
    # ========================================================================

    def test_set_current_effect_size(self, selector):
        """Test setting effect size programmatically."""
        selector.set_current_effect_size("rosenthal_r")

        assert selector.get_current_effect_size() == "rosenthal_r"
        assert selector.dropdown.currentData() == "rosenthal_r"

    def test_set_all_effect_types(self, selector):
        """Test setting each effect type."""
        for effect_type in EffectSizeType:
            selector.set_current_effect_size(effect_type.value)
            assert selector.get_current_effect_size() == effect_type.value

    def test_get_current_effect_size(self, selector):
        """Test getting current selection."""
        # Set to known value
        selector.dropdown.setCurrentIndex(2)  # Rosenthal's r

        result = selector.get_current_effect_size()
        assert result == "rosenthal_r"

    # ========================================================================
    # Filtering/Available Options Tests
    # ========================================================================

    def test_filter_to_parametric_only(self, selector):
        """Test filtering to show only parametric effect sizes."""
        parametric = ["cohens_d"]

        selector.set_available_options(parametric)

        assert selector.dropdown.count() == 1

        available = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]
        assert set(available) == set(parametric)

    def test_filter_to_nonparametric_only(self, selector):
        """Test filtering to show only non-parametric effect sizes."""
        nonparametric = ["rank_biserial", "rosenthal_r"]

        selector.set_available_options(nonparametric)

        assert selector.dropdown.count() == 2

        available = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]
        assert set(available) == set(nonparametric)

    def test_filter_preserves_current_selection(self, selector):
        """Test that filtering preserves current selection if still available."""
        # Set to Rank-biserial
        selector.set_current_effect_size("rank_biserial")

        # Filter to subset that includes current selection
        selector.set_available_options(["rank_biserial", "rosenthal_r"])

        # Should still be selected
        assert selector.get_current_effect_size() == "rank_biserial"

    def test_filter_changes_selection_if_unavailable(self, selector):
        """Test that filtering changes selection if current not in new options."""
        # Set to Cohen's d (will be filtered out)
        selector.set_current_effect_size("cohens_d")

        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Filter to non-parametric (doesn't include Cohen's d)
        selector.set_available_options(["rank_biserial", "rosenthal_r"])

        # Should change to first available option
        assert selector.get_current_effect_size() in ["rank_biserial", "rosenthal_r"]

        # Should emit signal for automatic change
        assert len(signal_spy) == 1

    def test_reset_to_all_options(self, selector):
        """Test resetting filter to show all options."""
        # Filter to subset
        selector.set_available_options(["cohens_d", "rank_biserial"])
        assert selector.dropdown.count() == 2

        # Reset to all
        selector.reset_to_all_options()

        # Should have all options again
        assert selector.dropdown.count() == 3

    def test_empty_filter_list(self, selector):
        """Test behavior with empty filter list."""
        selector.set_available_options([])

        # Should have no options
        assert selector.dropdown.count() == 0

    def test_filter_with_invalid_value(self, selector):
        """Test filtering with list containing invalid values."""
        # Mix of valid and invalid
        selector.set_available_options(["cohens_d", "invalid_type", "rank_biserial"])

        # Should only add valid options
        assert selector.dropdown.count() == 2

        available = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]
        assert set(available) == {"cohens_d", "rank_biserial"}

    # ========================================================================
    # Integration Tests
    # ========================================================================

    def test_complete_user_workflow(self, selector):
        """Test complete workflow: create, select, filter, select again."""
        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Default selection is rank-biserial (no signal on construction)
        assert selector.get_current_effect_size() == "rank_biserial"

        # User selects Cohen's d (index 1; index 0 is the default rank-biserial)
        selector.dropdown.setCurrentIndex(1)
        assert signal_spy[-1] == "cohens_d"

        # Filter to non-parametric (drops Cohen's d) -> falls back to the first
        # option (rank-biserial) and emits the automatic change.
        selector.set_available_options(["rank_biserial", "rosenthal_r"])
        assert selector.get_current_effect_size() == "rank_biserial"
        assert signal_spy[-1] == "rank_biserial"

        # User selects Rosenthal's r (index 1 within the filtered list)
        selector.dropdown.setCurrentIndex(1)
        assert signal_spy[-1] == "rosenthal_r"

    def test_multiple_selectors_independent(self, qapp):
        """Test that multiple selectors operate independently."""
        selector1 = EffectSizeSelector()
        selector2 = EffectSizeSelector()

        try:
            # Change first selector to a non-default value
            selector1.set_current_effect_size("cohens_d")

            # Second should still be at the default (rank-biserial)
            assert selector2.get_current_effect_size() == "rank_biserial"

            # Change second selector
            selector2.set_current_effect_size("rosenthal_r")

            # First should be unchanged
            assert selector1.get_current_effect_size() == "cohens_d"

        finally:
            selector1.deleteLater()
            selector2.deleteLater()

    def test_signal_disconnection(self, selector):
        """Test that signals can be disconnected properly."""
        signal_spy = []

        # Connect
        selector.effect_size_changed.connect(signal_spy.append)

        # Emit signal
        selector.dropdown.setCurrentIndex(1)
        assert len(signal_spy) == 1

        # Disconnect
        selector.effect_size_changed.disconnect(signal_spy.append)

        # Emit signal again
        selector.dropdown.setCurrentIndex(2)

        # Should not receive new signal
        assert len(signal_spy) == 1

    # ========================================================================
    # Edge Cases
    # ========================================================================

    def test_rapid_selection_changes(self, selector):
        """Test rapid sequential selection changes."""
        signal_spy = []
        selector.effect_size_changed.connect(signal_spy.append)

        # Rapid changes (start from index 1 to avoid no-change on first iteration)
        current_idx = selector.dropdown.currentIndex()
        changes_made = 0

        for i in range(selector.dropdown.count()):
            if i != current_idx:
                selector.dropdown.setCurrentIndex(i)
                changes_made += 1
                current_idx = i

        # Should emit signal for each actual change
        assert len(signal_spy) == changes_made

    def test_set_same_value_twice(self, selector):
        """Test setting same value twice programmatically."""
        selector.set_current_effect_size("rosenthal_r")
        selector.set_current_effect_size("rosenthal_r")

        # Should remain at rosenthal_r
        assert selector.get_current_effect_size() == "rosenthal_r"

    def test_filter_then_reset_preserves_selection(self, selector):
        """Test that filtering and resetting preserves selection if possible."""
        selector.set_current_effect_size("cohens_d")

        # Filter
        selector.set_available_options(["cohens_d", "rank_biserial"])

        # Reset
        selector.reset_to_all_options()

        # Should still be at cohens_d
        assert selector.get_current_effect_size() == "cohens_d"

    def test_widget_cleanup(self, qapp):
        """Test that widget cleans up properly."""
        selector = EffectSizeSelector()

        # Connect signal
        spy = []
        selector.effect_size_changed.connect(spy.append)

        # Delete widget
        selector.deleteLater()
        QApplication.processEvents()

        # Widget should be deleted (no way to directly test, but ensure no crash)
        assert True

    def test_dropdown_styling(self, selector):
        """Test that dropdown has custom styling."""
        style = selector.dropdown.styleSheet()

        # Should have custom styles
        assert len(style) > 0
        assert "QComboBox" in style

    def test_label_styling(self, selector):
        """Test that label has styling."""
        layout = selector.layout()
        label = layout.itemAt(0).widget()

        style = label.styleSheet()
        assert len(style) > 0
        assert "font-weight: bold" in style

    def test_all_effect_types_have_labels(self, selector):
        """Test that every EffectSizeType has a corresponding label."""
        all_data = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]

        # Every enum value should have an entry
        for effect_type in EffectSizeType:
            assert effect_type.value in all_data

    def test_dropdown_presentation_order(self, selector):
        """Dropdown order is a presentation choice (rank-biserial first, so the
        intrinsic default matches the domain default), intentionally decoupled
        from EffectSizeType declaration order."""
        expected_order = [
            "rank_biserial",
            "cohens_d",
            "rosenthal_r"
        ]

        actual_order = [
            selector.dropdown.itemData(i) for i in range(selector.dropdown.count())
        ]

        assert actual_order == expected_order
