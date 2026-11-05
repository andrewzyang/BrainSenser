"""
Grouping Panel Component for Snapshots 5 Hz Band Analysis

Mirrors :class:`SnapshotsGroupingPanel` (PSD) in look and feel — same 4-section
layout, same Qt aesthetic, same Event-Types / Active-Groups widgets — but with
ML-specific stats-table columns and without the test-method, correction, and
timeline-band inputs (none of which apply to per-band held-out LOO AUC analysis).
"""

from typing import List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from src.ui.components.base_grouping_panel import (
    BaseGroupingPanel,
    BOOTSTRAP_LABEL,
    BOOTSTRAP_OPTION_LABELS,
    BOOTSTRAP_VALUES,
    PERMUTATION_LABEL,
    PERMUTATION_OPTION_LABELS,
    PERMUTATION_VALUES,
)
from src.ui.components.selector_combo_style import SELECTOR_COMBO_QSS
from src.ui.electrode_labels import electrode_label_for_hemisphere
from src.ui.theme import Theme
from src.ui.utils.tooltips import wrap_tooltip

# AucProfileResult is created by a sibling agent in
# src/core/services/snapshot_ml_analysis_service.py. The import is wrapped in a
# try/except so this module remains importable while that service is in flight;
# the symbol is only used as a type hint inside populate_ml_table.
try:
    from src.core.services.snapshot_ml_analysis_service import AucProfileResult
except ImportError:  # pragma: no cover - fallback during incremental development
    AucProfileResult = None  # type: ignore[assignment,misc]

# fmt_p lives in the standalone analysis kernel and is the single source of truth
# for pipeline FWER p-value formatting. Wrapped in try/except so a missing/renamed
# helper does not break this module's import path.
try:
    from src.core.analysis.snapshot_loo_kernel import fmt_p
except ImportError:  # pragma: no cover - fallback if script layout changes
    def fmt_p(p: float, n_perm: int) -> str:  # type: ignore[no-redef]
        return f"{p:.4f}"


# Permutation / bootstrap selector options for the Compare controls. The
# selectable VALUES come from the shared single source of truth in
# base_grouping_panel so all three analysis pages offer identical menus; here
# each is paired (display label, integer value) so the combo stores the int as
# item data and selected_n_perm()/selected_n_boot() read it back via
# currentData() — never parsing the formatted display string.
#
# Defaults are the manuscript-locked values (N_PERM=10,000 max-stat FWER null,
# N_BOOT=2,000 CI) so an out-of-the-box Compare reproduces the published
# condition; these intentionally diverge from the Timeline LFP Threshold panel's
# 1,000-permutation default. Defaults are deliberately NOT shared — only the menu.
_PERM_OPTIONS = list(zip(PERMUTATION_OPTION_LABELS, PERMUTATION_VALUES))
_BOOT_OPTIONS = list(zip(BOOTSTRAP_OPTION_LABELS, BOOTSTRAP_VALUES))
_PERM_DEFAULT_VALUE = 10_000
_BOOT_DEFAULT_VALUE = 2_000

_LABEL_STYLE = (
    "font-weight: bold; background-color: transparent; font-size: 11px;"
)
# Perm/boot dropdowns use the shared selector look (single source of truth in
# selector_combo_style) so every dropdown across all pages matches; the shared
# style carries the same :disabled greying these combos relied on.
_COMBO_STYLE = SELECTOR_COMBO_QSS


class Snapshots5HzBandGroupingPanel(BaseGroupingPanel):
    """
    Grouping panel for the Snapshots 5 Hz Band page.

    Same 4-section layout as :class:`SnapshotsGroupingPanel` (Event Types /
    Active Groups / Stats Controls / Stats Table), same Qt aesthetic, but:

    * No Timeline-band input (per-band AUC analysis is centered automatically).
    * Test-method + Correction selectors are hidden (don't apply to AUC band
      stepping; the only "test" is the whole-pipeline FWER permutation).
    * Stats table has ML-specific columns (Electrode, Band #, Freq Range,
      LOO AUC, AUC 95% CI, Modal, Pipeline FWER p).

    Comparison-signal contract: emits a 2-arg signal
    ``comparison_requested(group1_event_types, group2_event_types)``. The base
    class does NOT define a ``comparison_requested`` signal of its own — each
    subclass declares whatever payload it needs (the PSD panel emits 5 args:
    groups + test + correction + timeline-center). Defining a 2-arg signal here
    is the simpler, more honest choice — it accurately reflects that ML
    analysis ignores test method and correction, and avoids passing dummy
    empty strings that downstream consumers would have to learn to ignore.
    """

    # 2-arg signal: (group1_event_types, group2_event_types).
    # See class docstring for the rationale on choosing 2-arg over the PSD
    # panel's 5-arg signature.
    comparison_requested = Signal(list, list)

    def __init__(self) -> None:
        super().__init__()
        # Base class created the test-method + correction widgets; we hide them
        # rather than restructure the section so the visual rhythm of the
        # control column (custom-control gap → Test gap → Correction gap →
        # Effect-size selector → Compare button) stays familiar to anyone who
        # has used the PSD panel. The expanding spacers between rows soak up
        # the freed vertical space gracefully.
        self._hide_inapplicable_test_controls()
        # With Test/Correction hidden, re-home the Effect Size selector into the
        # Bootstrap/Permutations stack so all three selectors share one uniform
        # 6 px gap (see _attach_effect_size_to_selector_stack).
        self._attach_effect_size_to_selector_stack()
        # The 5 Hz Band analysis (per-band held-out LOO AUC + FWER permutation)
        # consumes no effect size, so the selector would be a dead control. Hide
        # it like the Timeline Threshold / Peri-Event panels. It is re-homed above
        # for layout, so hide the widget directly rather than via the
        # test/correction wrapper path used by _hide_inapplicable_test_controls.
        if self.effect_size_selector is not None:
            self.effect_size_selector.setVisible(False)

    # ------------------------------------------------------------------
    # Base-class abstract method overrides
    # ------------------------------------------------------------------

    def _create_custom_control_widget(self) -> Optional[QWidget]:
        """
        Return a vertical stack of Bootstrap (CI) + Permutations (p) selectors
        (Bootstrap on top) that sits above the (hidden) test section, in the
        same column slot the Timeline LFP Threshold panel uses for its
        boot/perm/window controls.

        The base class adds whatever this returns to the controls layout
        (``if custom_control:``), so the combos are built here during
        ``super().__init__()`` and are available to ``selected_n_perm`` /
        ``selected_n_boot`` by the time the view reads them at Compare-time.

        Unlike the Timeline panel there is no Window spinbox — Snapshots 5 Hz Band is
        a per-band analysis with no peri-event window.
        """
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addLayout(self._build_boot_row())
        outer.addLayout(self._build_perm_row())
        # Stash the stack's layout so __init__ can append the Effect Size
        # selector here (6 px below Permutations) once the base has built it.
        self._selector_stack_layout = outer
        return container

    def _build_perm_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        label = QLabel(PERMUTATION_LABEL)
        label.setStyleSheet(_LABEL_STYLE)
        row.addWidget(label)

        self.n_perm_combo = QComboBox()
        for text, value in _PERM_OPTIONS:
            self.n_perm_combo.addItem(text, value)
        self._select_combo_value(self.n_perm_combo, _PERM_DEFAULT_VALUE)
        self.n_perm_combo.setToolTip(wrap_tooltip(
            "Label permutations for the per-band held-out AUC max-stat FWER "
            "null. Higher is more precise but slower; 10,000 matches the "
            "published analysis (Phipson & Smyth 2010 floor 1/(N+1))."
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
        for text, value in _BOOT_OPTIONS:
            self.n_boot_combo.addItem(text, value)
        self._select_combo_value(self.n_boot_combo, _BOOT_DEFAULT_VALUE)
        self.n_boot_combo.setToolTip(wrap_tooltip(
            "Bootstrap resamples for the per-band AUC 95% CIs. Higher is more "
            "precise but slower; 2,000 matches the published analysis."
        ))
        self.n_boot_combo.setStyleSheet(_COMBO_STYLE)
        self._add_capped(row, self.n_boot_combo)
        self._boot_label = label
        return row

    @staticmethod
    def _select_combo_value(combo: QComboBox, value: int) -> None:
        """Select the item whose stored data == ``value`` (no-op if absent)."""
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _get_stats_table_headers(self) -> List[str]:
        """Return ML-specific column headers (7 columns)."""
        return [
            "Electrode",         # 0
            "Band #",            # 1
            "Freq Range (Hz)",   # 2
            "LOO AUC",           # 3
            "AUC 95% CI",        # 4
            "Modal",             # 5
            "Pipeline FWER p",   # 6
        ]

    def _emit_comparison_signal(
        self,
        group1: List[str],
        group2: List[str],
        test_method: str,
        correction: str,
    ) -> None:
        """
        Emit the 2-arg ML comparison signal.

        The base class always passes ``test_method`` + ``correction`` (it has
        no way to know we hid those controls); we drop them on the floor here
        because the ML pipeline has only one test (the whole-pipeline FWER
        permutation) and no multiple-comparison correction concept at this
        layer.
        """
        del test_method, correction  # unused for ML
        self.comparison_requested.emit(group1, group2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate_ml_table(
        self,
        left: "Optional[AucProfileResult]",
        right: "Optional[AucProfileResult]",
    ) -> None:
        """
        Clear and populate the stats table with one row per (hemisphere, band).

        Parameters
        ----------
        left : AucProfileResult or None
            Left-hemisphere result. ``None`` means the patient is not
            implanted on the left side; no left rows are emitted.
        right : AucProfileResult or None
            Right-hemisphere result. Same semantics.

        For each non-None result, ``N = len(result.band_centers_hz)`` rows are
        appended (N is read from the data, never hard-coded). The "Modal"
        column shows ``"▼"`` on the row where ``i == result.modal_band_idx``,
        else blank. The "Pipeline FWER p" column is populated ONLY on the
        modal-band row, formatted via :func:`fmt_p`. The modal-band row is
        highlighted with a light-yellow background (matching the PSD panel's
        ``Qt.yellow`` significance highlight).
        """
        rows: List[tuple] = []  # (hemisphere_label, result, band_idx)
        if left is not None:
            for i in range(len(left.band_centers_hz)):
                rows.append(("Left", left, i))
        if right is not None:
            for i in range(len(right.band_centers_hz)):
                rows.append(("Right", right, i))

        self.stats_table.setRowCount(len(rows))

        for row_idx, (hem_label, result, band_idx) in enumerate(rows):
            is_modal = (band_idx == result.modal_band_idx)
            lo_hz, hi_hz = result.band_edges_hz[band_idx]
            auc = float(result.per_band_auc[band_idx])
            ci_lo = float(result.per_band_ci_lo[band_idx])
            ci_hi = float(result.per_band_ci_hi[band_idx])

            # Col 0 — Electrode display name ("Electrode 1" / "Electrode 2",
            # mapped from the Left/Right hemisphere token; never "NAc"). Matches
            # the plot panel titles and the peri-event table convention.
            hem_item = QTableWidgetItem(electrode_label_for_hemisphere(hem_label))
            self.stats_table.setItem(row_idx, 0, hem_item)

            # Col 1 — Band # (1-indexed within the hemisphere).
            band_item = QTableWidgetItem(str(band_idx + 1))
            band_item.setTextAlignment(Qt.AlignCenter)
            self.stats_table.setItem(row_idx, 1, band_item)

            # Col 2 — Freq Range (Hz).
            freq_item = QTableWidgetItem(f"{lo_hz:.2f}–{hi_hz:.2f}")
            freq_item.setTextAlignment(Qt.AlignCenter)
            self.stats_table.setItem(row_idx, 2, freq_item)

            # Col 3 — Per-band held-out LOO AUC (descriptive).
            auc_item = QTableWidgetItem(f"{auc:.3f}")
            auc_item.setTextAlignment(Qt.AlignCenter)
            self.stats_table.setItem(row_idx, 3, auc_item)

            # Col 4 — AUC 95% CI.
            ci_item = QTableWidgetItem(f"[{ci_lo:.3f}, {ci_hi:.3f}]")
            ci_item.setTextAlignment(Qt.AlignCenter)
            self.stats_table.setItem(row_idx, 4, ci_item)

            # Col 5 — Modal marker (▼ on the modal-band row, blank otherwise).
            modal_item = QTableWidgetItem("▼" if is_modal else "")
            modal_item.setTextAlignment(Qt.AlignCenter)
            if is_modal:
                # Bold black, matching the manuscript modal-band marker style.
                modal_font = QFont(modal_item.font())
                modal_font.setBold(True)
                modal_item.setFont(modal_font)
                modal_item.setForeground(Qt.black)
            self.stats_table.setItem(row_idx, 5, modal_item)

            # Col 6 — Pipeline FWER p (modal-band row only).
            if is_modal:
                p_text = fmt_p(float(result.fwer_p), int(result.n_perm))
            else:
                p_text = ""
            p_item = QTableWidgetItem(p_text)
            p_item.setTextAlignment(Qt.AlignCenter)
            self.stats_table.setItem(row_idx, 6, p_item)

            # Highlight the modal-band row with the themed modal-row token
            # so a future dark theme can re-tune in one place.
            if is_modal:
                modal_brush = QBrush(QColor(Theme.HIGHLIGHT_MODAL))
                for col in range(self.stats_table.columnCount()):
                    item = self.stats_table.item(row_idx, col)
                    if item is not None:
                        item.setBackground(modal_brush)

    # The base ``update_statistics_table`` is a no-op default; we don't
    # override it. The ML panel surfaces results through populate_ml_table().

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_selected_hemisphere(self) -> str:
        """
        Always returns ``"BOTH"`` — the 5 Hz Band view renders both hemispheres in
        parallel (mirroring the PSD page's dual-hemisphere widget). Provided
        for API parity with :class:`SnapshotsGroupingPanel`.
        """
        return "BOTH"

    def selected_n_perm(self) -> int:
        """Current Permutations selection as an int (read from combo data)."""
        return int(self.n_perm_combo.currentData())

    def selected_n_boot(self) -> int:
        """Current Bootstraps selection as an int (read from combo data)."""
        return int(self.n_boot_combo.currentData())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _attach_effect_size_to_selector_stack(self) -> None:
        """Re-home the base-created Effect Size selector directly beneath the
        Bootstrap/Permutations rows so the three share one uniform 6 px gap.

        The base lays the controls column out as custom-control → Test →
        Correction → Effect Size, inserting an *expanding* spacer after each row
        — a rhythm tuned for the PSD panel where every row is visible. This
        panel hides Test and Correction, which leaves their two trailing
        expanding spacers (plus the one after the custom control) stacked
        between Permutations and Effect Size: a large, uneven gap versus the
        fixed 6 px Bootstrap → Permutations gap inside the custom-control
        container.

        Moving Effect Size into that container (its QVBoxLayout has spacing 6)
        makes Bootstrap → Permutations → Effect Size one evenly-spaced group;
        the now-orphaned expanding spacers simply pool below it and float the
        Compare button to the bottom, exactly as before.
        """
        if self.effect_size_selector is None or self._selector_stack_layout is None:
            return
        controls_layout = (
            self._test_controls_group.layout()
            if self._test_controls_group is not None
            else None
        )
        if controls_layout is not None:
            controls_layout.removeWidget(self.effect_size_selector)
        self._selector_stack_layout.addWidget(self.effect_size_selector)

    def _hide_inapplicable_test_controls(self) -> None:
        """
        Hide the Test-method + Correction rows.

        The base class wraps each row in a QWidget (``_test_row_widget`` /
        ``_correction_row_widget``) precisely so subclasses can call
        ``setVisible(False)`` on the *wrapper* and have its layout slot
        fully reclaimed. Hiding the individual combo/label/info widgets
        only collapses the internal HBox without freeing the QVBoxLayout
        row, leaving a residual gap that disturbs the visual rhythm
        relative to the PSD page.
        """
        for wrapper in (
            getattr(self, "_test_row_widget", None),
            getattr(self, "_correction_row_widget", None),
        ):
            if wrapper is not None:
                wrapper.setVisible(False)
