"""
Unit tests for the perm/boot selectors of Snapshots5HzBandGroupingPanel.

Mirrors tests/ui/components/test_timeline_lfp_threshold_grouping_panel.py, minus the
Window spinbox (Snapshots 5 Hz Band is a per-band analysis with no peri-event
window). Behavioural contract:

  * Default selection is the manuscript-locked 10,000 permutations /
    2,000 bootstraps — deliberately diverging from the Timeline panel's
    1,000-permutation default so an out-of-the-box Compare reproduces the
    published max-stat FWER condition.
  * ``selected_n_perm()`` / ``selected_n_boot()`` return the integer stored
    as combo item data (``currentData()``), never a parse of the display
    string.
  * Every option's display label and stored integer value agree.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.views.snapshots_5hz_band.components.grouping_panel import (
    Snapshots5HzBandGroupingPanel,
    _BOOT_DEFAULT_VALUE,
    _BOOT_OPTIONS,
    _PERM_DEFAULT_VALUE,
    _PERM_OPTIONS,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def panel(qapp):
    widget = Snapshots5HzBandGroupingPanel()
    yield widget
    widget.deleteLater()


class TestDefaults:
    def test_perm_default_is_10000(self, panel):
        assert panel.n_perm_combo.currentText() == "10,000"
        assert panel.selected_n_perm() == 10_000 == _PERM_DEFAULT_VALUE

    def test_boot_default_is_2000(self, panel):
        assert panel.n_boot_combo.currentText() == "2,000"
        assert panel.selected_n_boot() == 2_000 == _BOOT_DEFAULT_VALUE

    def test_perm_option_labels_match_constants(self, panel):
        items = [
            panel.n_perm_combo.itemText(i)
            for i in range(panel.n_perm_combo.count())
        ]
        assert items == [label for label, _ in _PERM_OPTIONS]

    def test_boot_option_labels_match_constants(self, panel):
        items = [
            panel.n_boot_combo.itemText(i)
            for i in range(panel.n_boot_combo.count())
        ]
        assert items == [label for label, _ in _BOOT_OPTIONS]

    def test_perm_option_data_matches_labels(self, panel):
        # The stored integer must equal its comma-stripped label so the
        # display and the value the pipeline receives can never disagree.
        for i, (label, value) in enumerate(_PERM_OPTIONS):
            assert panel.n_perm_combo.itemData(i) == value
            assert int(label.replace(",", "")) == value

    def test_boot_option_data_matches_labels(self, panel):
        for i, (label, value) in enumerate(_BOOT_OPTIONS):
            assert panel.n_boot_combo.itemData(i) == value
            assert int(label.replace(",", "")) == value


class TestSelectionReadback:
    @pytest.mark.parametrize("value", [200, 1_000, 5_000, 10_000])
    def test_selected_n_perm_reads_current_data(self, panel, value):
        idx = panel.n_perm_combo.findData(value)
        assert idx >= 0
        panel.n_perm_combo.setCurrentIndex(idx)
        assert panel.selected_n_perm() == value

    @pytest.mark.parametrize("value", [500, 1_000, 2_000, 5_000])
    def test_selected_n_boot_reads_current_data(self, panel, value):
        idx = panel.n_boot_combo.findData(value)
        assert idx >= 0
        panel.n_boot_combo.setCurrentIndex(idx)
        assert panel.selected_n_boot() == value

    def test_selected_values_are_python_ints(self, panel):
        # currentData() can return a non-int in some Qt builds; the accessor
        # coerces so the worker / service always receive a real int.
        assert isinstance(panel.selected_n_perm(), int)
        assert isinstance(panel.selected_n_boot(), int)
