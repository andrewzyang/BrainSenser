"""
Grouping panel for the Timeline → LFP Threshold page.

Inherits :class:`BaseGroupingPanel`. Same four-section layout, same fonts /
spacing / colors as the existing Timeline page. Differences from the base:

* Time-window spinbox is user-configurable in 10-min steps (10–60 min).
  Default is ±20 to match the published Fig. 3 analysis; the bins are
  derived from the window as ``range(-window, window + 1, 10)`` so the
  pipeline's 10-min bin spacing scales with the selected window.
* Cancel button alongside Compare (visible always; enabled only while a
  worker is active).
* Test / correction selectors hidden — the threshold pipeline reports a
  single Mann-Whitney + permutation-test pair per hemisphere.
* Stats table has nine threshold-classifier columns.
* Footer text branches on the count of valid hemispheres (2 / 1 / 0).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidgetItem,
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
from src.ui.electrode_labels import electrode_label_for_hemisphere
from src.ui.utils.tooltips import wrap_tooltip

if TYPE_CHECKING:
    from src.core.services.timeline_threshold_ml_service import HemiResult


# Same fmt_p as the violin widget — keep them in lockstep.
def fmt_p(p: float, n_perm: int) -> str:
    floor = 1.0 / (n_perm + 1)
    if p <= floor + 1e-12:
        return f"< {floor:.4f}"
    if p < 0.001:
        return "< 0.001"
    if p < 0.01:
        return f"= {p:.4f}"
    return f"= {p:.3f}"


# Selectable values come from the shared single source of truth in
# base_grouping_panel so all three analysis pages offer identical menus; this
# panel reads them back by parsing the comma-formatted label (currentText).
# Defaults are NOT shared — 1,000 perm / 2,000 boot are this page's own.
_PERM_OPTIONS = list(PERMUTATION_OPTION_LABELS)
_BOOT_OPTIONS = list(BOOTSTRAP_OPTION_LABELS)
_PERM_DEFAULT = "1,000"
_BOOT_DEFAULT = "2,000"

# Window selector: pre/post extraction range around each event press, in
# minutes. Bins are derived from this value as ``range(-w, w + 1, 10)``,
# preserving the 10-min bin spacing of the published Fig. 3 pipeline.
_WINDOW_MIN: int = 10
_WINDOW_MAX: int = 60
_WINDOW_STEP: int = 10
_WINDOW_DEFAULT: int = 20

_LABEL_STYLE = (
    "font-weight: bold; background-color: transparent; font-size: 11px;"
)
# Perm/boot dropdowns use the shared selector look (single source of truth in
# selector_combo_style) so every dropdown across all pages matches; the shared
# style carries the same :disabled greying these combos relied on.
_COMBO_STYLE = SELECTOR_COMBO_QSS


class TimelineLfpThresholdGroupingPanel(BaseGroupingPanel):
    """Bottom widget for the Timeline → LFP Threshold page."""

    comparison_requested = Signal(list, list)

    def __init__(self) -> None:
        super().__init__()
        self._hide_inapplicable_test_controls()

    # ------------------------------------------------------------------
    # Base-class abstract overrides
    # ------------------------------------------------------------------

    def _create_custom_control_widget(self) -> Optional[QWidget]:
        """Return a vertical container with Bootstrap (CI) + Permutations (p)
        combos (Bootstrap on top) above the user-configurable Window-minutes
        spinbox.

        The selectors live in the same column slot above the Window spinbox so
        the rhythm is Bootstrap (CI) → Permutations (p) → Window → Compare →
        Cancel → progress.
        """
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        outer.addLayout(self._build_boot_row())
        outer.addLayout(self._build_perm_row())
        outer.addLayout(self._build_window_row())
        return container

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
            "Permutation count for the AUC null. Higher is more precise but "
            "slower; ≥ 1,000 matches the published analysis "
            "(Phipson & Smyth 2010 floor 1/(N+1))."
        ))
        self.n_perm_combo.setStyleSheet(_COMBO_STYLE)
        self._add_capped(row, self.n_perm_combo)
        self._perm_label = label
        return row

    def _build_boot_row(self) -> QHBoxLayout:
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
            "Bootstrap resamples for the AUC and threshold 95% CIs. Higher "
            "is more precise but slower; 2,000 matches the published "
            "analysis."
        ))
        self.n_boot_combo.setStyleSheet(_COMBO_STYLE)
        self._add_capped(row, self.n_boot_combo)
        self._boot_label = label
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
        self.window_spinbox.setEnabled(True)
        self.window_spinbox.setToolTip(wrap_tooltip(
            "Pre/post window around each event press. Bins are derived as "
            "range(-w, w + 1, 10) so the 10-min bin spacing scales with the "
            "window. Default ±20 matches published Fig. 3."
        ))
        self.window_spinbox.setStyleSheet(
            """
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
        )
        # Snap to the step grid even if user types an off-grid value.
        self.window_spinbox.editingFinished.connect(self._snap_window_to_step)
        self._add_capped(row, self.window_spinbox)
        self._window_label = label
        return row

    def _snap_window_to_step(self) -> None:
        """Round the spinbox value to the nearest multiple of the step.

        QSpinBox enforces the step only when the user clicks the arrows;
        a typed value can land off-grid (e.g. 25). The pipeline derives
        bins as ``range(-w, w + 1, 10)``, which silently drops off-grid
        bins, so we snap here to keep what the user types in lockstep
        with what the analysis sees.
        """
        v = int(self.window_spinbox.value())
        snapped = max(
            _WINDOW_MIN,
            min(_WINDOW_MAX, int(round(v / _WINDOW_STEP) * _WINDOW_STEP)),
        )
        if snapped != v:
            self.window_spinbox.setValue(snapped)

    def _get_stats_table_headers(self) -> List[str]:
        return [
            "Electrode",         # 0
            "n (G1/G2)",         # 1
            "LR threshold (µV)", # 2
            "AUC (LOO)",         # 3
            "Sens (LR)",         # 4
            "Spec (LR)",         # 5
            "Mann-Whitney p",    # 6
            "Permutation p",     # 7
            "Verdict",           # 8
        ]

    def _emit_comparison_signal(
        self,
        group1: List[str],
        group2: List[str],
        test_method: str,
        correction: str,
    ) -> None:
        del test_method, correction  # Unused; threshold pipeline has one test.
        self.comparison_requested.emit(group1, group2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate_threshold_table(self, results: dict) -> None:
        """Populate the table with one row per hemisphere.

        ``results`` is ``{"Left": HemiResult, "Right": HemiResult}``. Either
        side may be a :class:`ThresholdMlResult` or
        :class:`InsufficientResult`. Order is always Left, Right.
        """
        from src.core.services.timeline_threshold_ml_service import (
            InsufficientResult,
            ThresholdMlResult,
        )

        rows = [
            ("Left", results.get("Left") if results else None),
            ("Right", results.get("Right") if results else None),
        ]
        # An earlier Insufficient row's span would otherwise hide the cells of
        # a full result in the same row.
        self.stats_table.clearSpans()
        self.stats_table.setRowCount(len(rows))

        for row_idx, (hem_label, result) in enumerate(rows):
            self._set_cell(row_idx, 0, electrode_label_for_hemisphere(hem_label))
            if isinstance(result, ThresholdMlResult):
                self._populate_threshold_row(row_idx, result)
            elif isinstance(result, InsufficientResult):
                self._populate_insufficient_row(row_idx, result)
            else:
                self._populate_empty_row(row_idx)

    def update_statistics_table(self, results_data) -> None:
        """Backwards-compatible shim — call :meth:`populate_threshold_table`."""
        if isinstance(results_data, dict):
            self.populate_threshold_table(results_data)
            return
        raise NotImplementedError(
            "TimelineLfpThresholdGroupingPanel expects a dict[str, HemiResult]; "
            "use populate_threshold_table(results) instead.",
        )

    def set_running(self, running: bool) -> None:
        """Toggle Compare + selector enabled state.

        Cancel lives on the shared :class:`MlProgressDialog`; this panel
        only needs to disable Compare and the selectors so the user
        cannot dispatch a second run on top of an in-flight one.
        """
        self.compare_btn.setEnabled(not running and self._has_both_groups())
        # Selectors are read at submit-time only, so disabling them mid-run is
        # cosmetic — but it matches Compare's discipline and avoids implying
        # an in-flight value change has any effect.
        if hasattr(self, "n_perm_combo"):
            self.n_perm_combo.setEnabled(not running)
        if hasattr(self, "n_boot_combo"):
            self.n_boot_combo.setEnabled(not running)
        if hasattr(self, "window_spinbox"):
            self.window_spinbox.setEnabled(not running)

    def selected_n_perm(self) -> int:
        """Parse the Permutations dropdown's current text into an integer."""
        return int(self.n_perm_combo.currentText().replace(",", ""))

    def selected_n_boot(self) -> int:
        """Parse the Bootstraps dropdown's current text into an integer."""
        return int(self.n_boot_combo.currentText().replace(",", ""))

    def selected_window_minutes(self) -> int:
        """Return the Window spinbox value snapped to the 10-min step grid."""
        v = int(self.window_spinbox.value())
        return max(
            _WINDOW_MIN,
            min(_WINDOW_MAX, int(round(v / _WINDOW_STEP) * _WINDOW_STEP)),
        )

    def _has_both_groups(self) -> bool:
        return (
            len(self._active_groups.get(1, [])) > 0
            and len(self._active_groups.get(2, [])) > 0
        )

    def populate_event_types_with_classification(
        self, event_counts: Dict[str, int],
    ) -> None:
        """Populate the event-types list. Group 1 / Group 2 stay empty —
        auto-fill was removed because it was misleading on patient load
        (groups looked filled before the user did anything)."""
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

    # ---- Row population ------------------------------------------------

    def _set_cell(self, row: int, col: int, text: str, *, bold: bool = False) -> None:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignCenter)
        if bold:
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
        self.stats_table.setItem(row, col, item)

    def _populate_threshold_row(self, row_idx: int, r) -> None:
        # n_perm = 1 / floor − 1 (round-trip from the dataclass field).
        n_perm = int(round(1.0 / max(float(r.perm_p_floor), 1e-12)) - 1)
        # Internally y=0 is stored in n_neutral and y=1 in n_craving.
        # Timeline LFP Threshold labels those slots by user-selected group position:
        # Group 1 -> y=0, Group 2 -> y=1.
        self._set_cell(row_idx, 1, f"{int(r.n_neutral)}/{int(r.n_craving)}")
        self._set_cell(
            row_idx, 2,
            f"{float(r.lr_threshold):.0f} "
            f"[{float(r.lr_threshold_ci[0]):.0f}, {float(r.lr_threshold_ci[1]):.0f}]",
        )
        self._set_cell(
            row_idx, 3,
            f"{float(r.auc_loo):.3f} "
            f"[{float(r.auc_ci[0]):.3f}, {float(r.auc_ci[1]):.3f}]",
        )
        self._set_cell(
            row_idx, 4,
            f"{float(r.sensitivity_lr):.3f} "
            f"[{float(r.sens_ci[0]):.3f}, {float(r.sens_ci[1]):.3f}]",
        )
        self._set_cell(
            row_idx, 5,
            f"{float(r.specificity_lr):.3f} "
            f"[{float(r.spec_ci[0]):.3f}, {float(r.spec_ci[1]):.3f}]",
        )
        self._set_cell(
            row_idx, 6, fmt_p(float(r.mann_whitney_p), n_perm).strip(),
        )
        self._set_cell(row_idx, 7, fmt_p(float(r.perm_p), n_perm).strip())
        self._set_cell(
            row_idx, 8,
            "✓" if bool(r.verdict) else "✗",
            bold=bool(r.verdict),
        )

    def _populate_insufficient_row(self, row_idx: int, r) -> None:
        # Span the right columns with the reason; leave the Electrode cell intact.
        # The span is as wide as its columns, so a long reason is elided; the
        # tooltip has it in full.
        msg = QTableWidgetItem(f"Insufficient: {r.reason}")
        msg.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        msg.setToolTip(wrap_tooltip(msg.text()))
        self.stats_table.setItem(row_idx, 1, msg)
        self.stats_table.setSpan(row_idx, 1, 1, 7)
        # Verdict cell shows em-dash (greyed).
        em_dash = QTableWidgetItem("—")
        em_dash.setTextAlignment(Qt.AlignCenter)
        em_dash.setForeground(Qt.gray)
        self.stats_table.setItem(row_idx, 8, em_dash)

    def _populate_empty_row(self, row_idx: int) -> None:
        for col in range(1, 9):
            self._set_cell(row_idx, col, "—")
