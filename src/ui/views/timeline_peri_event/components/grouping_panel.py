"""Grouping panel for the Timeline → Peri-Event page.

Inherits :class:`BaseGroupingPanel`. Same four-section layout as the other
analysis pages. Differences:

* Custom controls = a Bootstrap (CI) dropdown (default 5,000; per-bin
  percentile CI bands only, never the p-value) above a Permutations (p) dropdown
  (default 10,000, the manuscript headline), above a Window spinbox (default
  ±50 min).
* Test / correction / effect-size selectors are hidden — the cluster
  permutation test reports a single p-value per cluster.
* The stats table shows one row per (hemisphere, cluster); population is
  delegated to :mod:`...statistics_table_widget`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.ui.components.base_grouping_panel import (
    BaseGroupingPanel,
    BOOTSTRAP_LABEL,
    BOOTSTRAP_OPTION_LABELS,
    PERMUTATION_LABEL,
    PERMUTATION_OPTION_LABELS,
)
from src.ui.components.selector_combo_style import SELECTOR_COMBO_QSS
from src.ui.utils.tooltips import wrap_tooltip
from src.ui.views.timeline_peri_event.components.statistics_table_widget import (
    CLUSTER_HEADERS,
    populate_cluster_rows,
)


# Selectable values come from the shared single source of truth in
# base_grouping_panel so all three analysis pages offer identical menus.
# The default is NOT shared — 10,000 is this page's manuscript headline.
_PERM_OPTIONS = list(PERMUTATION_OPTION_LABELS)
_PERM_DEFAULT = "10,000"

# Bootstrap selector: resamples for the per-bin percentile CI bands drawn on
# the plot (display only — never enters the cluster p-value). Options come from
# the shared menu; default 5,000 (NOT shared) matches DEFAULT_N_BOOT / the
# published analysis.
_BOOT_OPTIONS = list(BOOTSTRAP_OPTION_LABELS)
_BOOT_DEFAULT = "5,000"

# Window selector: peri-event ± window in minutes; bins derive as
# range(-w, w + 10, 10) so the 10-min spacing scales with the window.
_WINDOW_MIN: int = 20
_WINDOW_MAX: int = 100
_WINDOW_STEP: int = 10
_WINDOW_DEFAULT: int = 50

_LABEL_STYLE = "font-weight: bold; background-color: transparent; font-size: 11px;"
# Perm/boot dropdowns use the shared selector look (single source of truth in
# selector_combo_style) so every dropdown across all pages matches; the shared
# style carries the same :disabled greying these combos relied on.
_COMBO_STYLE = SELECTOR_COMBO_QSS
_SPIN_STYLE = """
    QSpinBox {
        border: none;
        border-radius: 4px;
        padding: 4px;
        font-size: 10px;
    }
    QSpinBox:disabled {
        background-color: #f1f5f9;
        color: #94a3b8;
    }
"""


class TimelinePeriEventGroupingPanel(BaseGroupingPanel):
    """Bottom widget for the Timeline → Peri-Event page."""

    comparison_requested = Signal(list, list)

    def __init__(self) -> None:
        super().__init__()
        self._hide_inapplicable_test_controls()

    # ------------------------------------------------------------------
    # Base-class abstract overrides
    # ------------------------------------------------------------------

    def _create_custom_control_widget(self) -> Optional[QWidget]:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addLayout(self._build_bootstrap_row())
        outer.addLayout(self._build_perm_row())
        outer.addLayout(self._build_window_row())
        return container

    def _build_bootstrap_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(BOOTSTRAP_LABEL)
        label.setStyleSheet(_LABEL_STYLE)
        row.addWidget(label)
        self.n_boot_combo = QComboBox()
        self.n_boot_combo.addItems(_BOOT_OPTIONS)
        self.n_boot_combo.setCurrentText(_BOOT_DEFAULT)
        self.n_boot_combo.setToolTip(wrap_tooltip(
            "Resamples for the per-bin percentile CI bands shown on the plot. "
            "Display only — does NOT affect the cluster p-value. Higher is "
            "smoother but slower; 5,000 matches the published analysis."
        ))
        self.n_boot_combo.setStyleSheet(_COMBO_STYLE)
        self._add_capped(row, self.n_boot_combo)
        self._boot_label = label
        return row

    def _build_perm_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(PERMUTATION_LABEL)
        label.setStyleSheet(_LABEL_STYLE)
        row.addWidget(label)
        self.n_perm_combo = QComboBox()
        self.n_perm_combo.addItems(_PERM_OPTIONS)
        self.n_perm_combo.setCurrentText(_PERM_DEFAULT)
        self.n_perm_combo.setToolTip(wrap_tooltip(
            "Event-level label permutations for the cluster-mass null. Higher "
            "is more precise but slower; 10,000 matches the published analysis "
            "(Phipson & Smyth 2010 floor 1/(N+1))."
        ))
        self.n_perm_combo.setStyleSheet(_COMBO_STYLE)
        self._add_capped(row, self.n_perm_combo)
        self._perm_label = label
        return row

    def _build_window_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel("Window (± min):")
        label.setStyleSheet(_LABEL_STYLE)
        row.addWidget(label)
        self.window_spinbox = QSpinBox()
        self.window_spinbox.setRange(_WINDOW_MIN, _WINDOW_MAX)
        self.window_spinbox.setSingleStep(_WINDOW_STEP)
        self.window_spinbox.setValue(_WINDOW_DEFAULT)
        self.window_spinbox.setSuffix(" min")
        self.window_spinbox.setToolTip(wrap_tooltip(
            "Peri-event window. Bins derive as range(-w, w + 10, 10), so the "
            "10-min bin spacing scales with the window. Default ±50 matches "
            "the manuscript (11 bins)."
        ))
        self.window_spinbox.setStyleSheet(_SPIN_STYLE)
        self.window_spinbox.editingFinished.connect(self._snap_window_to_step)
        self._add_capped(row, self.window_spinbox)
        self._window_label = label
        return row

    def _snap_window_to_step(self) -> None:
        v = int(self.window_spinbox.value())
        snapped = max(_WINDOW_MIN,
                      min(_WINDOW_MAX, int(round(v / _WINDOW_STEP) * _WINDOW_STEP)))
        if snapped != v:
            self.window_spinbox.setValue(snapped)

    def _get_stats_table_headers(self) -> List[str]:
        return list(CLUSTER_HEADERS)

    def _emit_comparison_signal(self, group1, group2, test_method, correction) -> None:
        del test_method, correction  # cluster permutation has one test.
        self.comparison_requested.emit(group1, group2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate_cluster_table(self, results: dict) -> None:
        populate_cluster_rows(self.stats_table, results)

    def update_statistics_table(self, results_data) -> None:
        if isinstance(results_data, dict):
            self.populate_cluster_table(results_data)
            return
        raise NotImplementedError(
            "TimelinePeriEventGroupingPanel expects dict[str, HemiResult]; "
            "use populate_cluster_table(results)."
        )

    def set_running(self, running: bool) -> None:
        self.compare_btn.setEnabled(not running and self._has_both_groups())
        if hasattr(self, "n_boot_combo"):
            self.n_boot_combo.setEnabled(not running)
        if hasattr(self, "n_perm_combo"):
            self.n_perm_combo.setEnabled(not running)
        if hasattr(self, "window_spinbox"):
            self.window_spinbox.setEnabled(not running)

    def selected_n_boot(self) -> int:
        return int(self.n_boot_combo.currentText().replace(",", ""))

    def selected_n_perm(self) -> int:
        return int(self.n_perm_combo.currentText().replace(",", ""))

    def selected_window_minutes(self) -> int:
        v = int(self.window_spinbox.value())
        return max(_WINDOW_MIN,
                   min(_WINDOW_MAX, int(round(v / _WINDOW_STEP) * _WINDOW_STEP)))

    def _has_both_groups(self) -> bool:
        return (len(self._active_groups.get(1, [])) > 0
                and len(self._active_groups.get(2, [])) > 0)

    def populate_event_types_with_classification(
        self, event_counts: Dict[str, int],
    ) -> None:
        """Populate the event-types list. Groups stay empty until the user
        assigns them."""
        self.set_available_event_types(dict(event_counts))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _hide_inapplicable_test_controls(self) -> None:
        # Hide the Test / Correction row wrappers, not their widgets: a visible
        # wrapper keeps its slot (and spacing) in the controls column.
        for widget in (
            self._test_row_widget,
            self._correction_row_widget,
            self.effect_size_selector,
        ):
            if widget is not None:
                widget.setVisible(False)
