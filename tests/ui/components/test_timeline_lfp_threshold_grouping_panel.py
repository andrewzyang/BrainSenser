"""
Unit tests for the perm/boot/window selectors of TimelineLfpThresholdGroupingPanel.

Covers Phase 11 of `docs/plans/timeline_lfp_threshold_page/11_perm_boot_selectors.md`
and the configurable-window addition:
  * Default selection is 1,000 permutations / 2,000 bootstraps / ±20 min.
  * `selected_n_perm()` / `selected_n_boot()` parse the comma-formatted
    text for every dropdown option.
  * `set_running(True)` disables every selector (combos AND the window
    spinbox); `set_running(False)` re-enables them when at least one
    event-type group is populated.
  * The Window spinbox is user-configurable in 10-min steps from
    ±10 min to ±60 min, and `selected_window_minutes()` snaps off-grid
    values to the nearest 10.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.views.timeline_lfp_threshold.components.grouping_panel import (
    TimelineLfpThresholdGroupingPanel,
    _BOOT_OPTIONS,
    _PERM_OPTIONS,
    _WINDOW_DEFAULT,
    _WINDOW_MAX,
    _WINDOW_MIN,
    _WINDOW_STEP,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def panel(qapp):
    widget = TimelineLfpThresholdGroupingPanel()
    yield widget
    widget.deleteLater()


def _seed_groups(panel: TimelineLfpThresholdGroupingPanel) -> None:
    """Populate both groups so set_running(False) can re-enable Compare.
    Avoids the "no groups → Compare stays disabled" branch from leaking
    into our combo-state assertions.
    """
    panel._active_groups[1] = ["evt_a"]
    panel._active_groups[2] = ["evt_b"]


class TestDefaults:
    def test_perm_default_is_1000(self, panel):
        assert panel.n_perm_combo.currentText() == "1,000"
        assert panel.selected_n_perm() == 1_000

    def test_boot_default_is_2000(self, panel):
        assert panel.n_boot_combo.currentText() == "2,000"
        assert panel.selected_n_boot() == 2_000

    def test_perm_options_match_constants(self, panel):
        items = [
            panel.n_perm_combo.itemText(i)
            for i in range(panel.n_perm_combo.count())
        ]
        assert items == _PERM_OPTIONS

    def test_boot_options_match_constants(self, panel):
        items = [
            panel.n_boot_combo.itemText(i)
            for i in range(panel.n_boot_combo.count())
        ]
        assert items == _BOOT_OPTIONS

    def test_count_header_uses_group_labels(self, panel):
        assert panel.stats_table.horizontalHeaderItem(1).text() == "n (G1/G2)"

    def test_count_row_uses_group1_group2_order(self, panel):
        panel.stats_table.setRowCount(1)
        result = SimpleNamespace(
            n_neutral=5,       # Group 1 slot (y=0)
            n_craving=7,       # Group 2 slot (y=1)
            lr_threshold=123.0,
            lr_threshold_ci=(100.0, 150.0),
            auc_loo=0.75,
            auc_ci=(0.60, 0.90),
            sensitivity_yj=0.70,
            specificity_yj=0.80,
            sensitivity_lr=0.70,
            specificity_lr=0.80,
            sens_ci=(0.55, 0.85),
            spec_ci=(0.65, 0.92),
            mann_whitney_p=0.02,
            perm_p=0.01,
            perm_p_floor=1.0 / 1001,
            verdict=True,
        )

        panel._populate_threshold_row(0, result)

        assert panel.stats_table.item(0, 1).text() == "5/7"
        assert panel.stats_table.item(0, 4).text() == "0.700 [0.550, 0.850]"
        assert panel.stats_table.item(0, 5).text() == "0.800 [0.650, 0.920]"


class TestSelectionParsing:
    @pytest.mark.parametrize("text,expected", [
        ("200", 200),
        ("1,000", 1_000),
        ("5,000", 5_000),
        ("10,000", 10_000),
    ])
    def test_perm_parsing_strips_commas(self, panel, text, expected):
        panel.n_perm_combo.setCurrentText(text)
        assert panel.selected_n_perm() == expected

    @pytest.mark.parametrize("text,expected", [
        ("500", 500),
        ("1,000", 1_000),
        ("2,000", 2_000),
        ("5,000", 5_000),
    ])
    def test_boot_parsing_strips_commas(self, panel, text, expected):
        panel.n_boot_combo.setCurrentText(text)
        assert panel.selected_n_boot() == expected


class TestRunningState:
    def test_set_running_true_disables_all_selectors(self, panel):
        _seed_groups(panel)
        panel.set_running(True)
        assert panel.n_perm_combo.isEnabled() is False
        assert panel.n_boot_combo.isEnabled() is False
        assert panel.window_spinbox.isEnabled() is False

    def test_set_running_false_reenables_all_selectors(self, panel):
        _seed_groups(panel)
        panel.set_running(True)
        panel.set_running(False)
        assert panel.n_perm_combo.isEnabled() is True
        assert panel.n_boot_combo.isEnabled() is True
        assert panel.window_spinbox.isEnabled() is True

    def test_set_running_does_not_crash_before_init_attrs(self, qapp):
        # Defensive: hasattr guard in set_running should make the call
        # safe even if a subclass instantiated before the selectors were
        # built. We simulate by deleting them post-construct.
        panel = TimelineLfpThresholdGroupingPanel()
        del panel.n_perm_combo
        del panel.n_boot_combo
        del panel.window_spinbox
        try:
            panel.set_running(True)  # must not raise
            panel.set_running(False)
        finally:
            panel.deleteLater()


class TestWindowSelector:
    def test_default_window_is_20(self, panel):
        assert panel.window_spinbox.value() == _WINDOW_DEFAULT == 20
        assert panel.selected_window_minutes() == 20

    def test_window_range_is_10_to_60(self, panel):
        assert panel.window_spinbox.minimum() == _WINDOW_MIN == 10
        assert panel.window_spinbox.maximum() == _WINDOW_MAX == 60

    def test_window_step_is_10(self, panel):
        assert panel.window_spinbox.singleStep() == _WINDOW_STEP == 10

    def test_window_spinbox_is_enabled_by_default(self, panel):
        # The previous design locked the spinbox at 20; this pins the
        # configurable behaviour so the lock cannot silently regress.
        assert panel.window_spinbox.isEnabled() is True

    @pytest.mark.parametrize("value,expected", [
        (10, 10),
        (20, 20),
        (30, 30),
        (40, 40),
        (50, 50),
        (60, 60),
    ])
    def test_selected_window_minutes_returns_grid_value(
        self, panel, value, expected,
    ):
        panel.window_spinbox.setValue(value)
        assert panel.selected_window_minutes() == expected

    @pytest.mark.parametrize("typed,expected", [
        # Off-grid values must snap to the nearest 10-minute multiple.
        (12, 10),
        (16, 20),
        (24, 20),
        (25, 20),  # half-step rounds to nearest-even via int(round(...))
        (33, 30),
        (47, 50),
        (55, 60),
    ])
    def test_off_grid_values_snap_to_nearest_step(
        self, panel, typed, expected,
    ):
        panel.window_spinbox.setValue(typed)
        assert panel.selected_window_minutes() == expected
