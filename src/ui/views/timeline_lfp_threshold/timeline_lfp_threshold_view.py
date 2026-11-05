"""
Timeline → LFP Threshold analysis view.

Renders the per-event amplitude-threshold classifier behind manuscript
Figure 3 d-f. Layout follows the standard analysis-page pattern: a
``QStackedWidget`` shell with an empty state when no patient is loaded
and a two-section analysis tab (dual-hemisphere violin widget on top,
grouping panel below) when a patient is active.

Strict MVVM: this module imports zero ``core`` / ``ml`` symbols. All
analysis flows through :class:`TimelineLfpThresholdViewModel`. The View owns the
widgets and the signal-bridging only.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from src.ui.components import MlProgressDialog
from src.ui.components.dialog_fit import show_message
from src.ui.components.table_copy import table_tsv
from src.ui.policy.layout import Density
from src.ui.viewmodels.timeline_lfp_threshold_viewmodel import TimelineLfpThresholdViewModel
from src.ui.views._shared import AnalysisPageScaffold
from src.ui.views.timeline_lfp_threshold.components import (
    DualHemisphereViolinWidget,
    TimelineLfpThresholdGroupingPanel,
)


logger = logging.getLogger(__name__)


def _format_group_label(names: List[str], default: str) -> str:
    """Render a violin x-tick label from the user's group event-name list.

    1 name  → that name (e.g. ``"Happy"``)
    2 names → ``"a + b"`` (e.g. ``"Drinking + Drinking/Craving"``)
    3+      → ``"first (+N more)"`` so the long manuscript-faithful
              selection ``["Craving", "Drinking", "Drinking/Craving"]``
              renders as ``"Craving (+2 more)"`` rather than wrapping
              into the y-axis.
    empty   → ``default`` (``"Group 1"`` / ``"Group 2"`` placeholders).
    """
    if not names:
        return default
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return " + ".join(names)
    return f"{names[0]} (+{len(names) - 1} more)"


class TimelineLfpThresholdView(QWidget):
    """Timeline → LFP Threshold page widget."""

    export_state_changed = Signal(bool)

    _EMPTY_INDEX = 0
    _ANALYSIS_INDEX = 1

    def __init__(
        self,
        viewmodel: TimelineLfpThresholdViewModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._viewmodel = viewmodel
        self._signal_connections: List[tuple] = []
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self._create_analysis_content()
        self._scaffold = AnalysisPageScaffold(self, self.violin_widget, self.grouping_panel)
        self.content_stack = self._scaffold.content_stack
        self.content_stack.setCurrentIndex(self._EMPTY_INDEX)

        # Shared modal progress popup. Cancel routes back to the VM so a
        # user-pressed Cancel terminates the in-flight worker.
        self.progress_dialog = MlProgressDialog(self)
        self.progress_dialog.cancel_requested.connect(
            self._on_cancel_clicked, Qt.UniqueConnection,
        )

    def _create_analysis_content(self) -> None:
        self.violin_widget = DualHemisphereViolinWidget()
        self.grouping_panel = TimelineLfpThresholdGroupingPanel()

        # Wire grouping-panel signals. Cancel lives on the shared
        # MlProgressDialog now, so the panel only emits comparison +
        # group-clear events.
        self.grouping_panel.comparison_requested.connect(
            self._on_comparison_requested, Qt.UniqueConnection,
        )
        self.grouping_panel.group_cleared.connect(
            self._on_groups_cleared, Qt.UniqueConnection,
        )
        self.grouping_panel.copy_table_requested.connect(
            self.copy_table_to_clipboard, Qt.UniqueConnection,
        )

    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        connections = [
            (self._viewmodel.patient_changed,    self._on_patient_changed),
            (self._viewmodel.data_loaded,        self._on_data_loaded),
            (self._viewmodel.analysis_started,   self._on_analysis_started),
            (self._viewmodel.progress_updated,   self._on_progress),
            (self._viewmodel.hemisphere_ready,   self._on_hemisphere_ready),
            (self._viewmodel.analysis_complete,  self._on_analysis_complete),
            (self._viewmodel.error_occurred,     self._on_error),
        ]
        for signal, slot in connections:
            signal.connect(slot, Qt.UniqueConnection)
            self._signal_connections.append((signal, slot))

    def _disconnect_signals(self) -> None:
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._signal_connections.clear()

    # ------------------------------------------------------------------
    # VM signal handlers
    # ------------------------------------------------------------------

    def _on_patient_changed(self, patient_id: str) -> None:
        if patient_id:
            self.content_stack.setCurrentIndex(self._ANALYSIS_INDEX)
            self.violin_widget.render_skeleton()
            self.grouping_panel.set_running(False)
            self.progress_dialog.reset()
        else:
            self.content_stack.setCurrentIndex(self._EMPTY_INDEX)
            self.export_state_changed.emit(False)

    def _on_data_loaded(self) -> None:
        # Populate event types from the VM and pre-classify defaults.
        counts = self._viewmodel.available_event_counts()
        self.grouping_panel.populate_event_types_with_classification(counts)
        # Reset display to skeleton; the user must press Compare.
        self.violin_widget.render_skeleton()
        self.grouping_panel.clear_statistics_table()
        self.grouping_panel.set_running(False)
        self.progress_dialog.reset()

    def _on_analysis_started(self) -> None:
        self.progress_dialog.start()
        self.grouping_panel.set_running(True)

    def _on_progress(self, percent: int, label: str) -> None:
        self.progress_dialog.update_progress(percent, label)
        # If progress is mid-flight, mark as running so Compare stays disabled.
        if 0 < percent < 100:
            self.grouping_panel.set_running(True)

    def _on_hemisphere_ready(self, hemisphere: str) -> None:
        results = self._viewmodel.current_results()
        result = results.get(hemisphere)
        if result is not None:
            self.violin_widget.update_panel(hemisphere, result)

    def _on_analysis_complete(self) -> None:
        results = self._viewmodel.current_results()
        self.violin_widget.update_results(results)
        self.grouping_panel.populate_threshold_table(results)
        self.grouping_panel.set_running(False)
        self.progress_dialog.reset()
        self.export_state_changed.emit(self.violin_widget.export_state())

    def _on_error(self, message: str) -> None:
        self.grouping_panel.set_running(False)
        self.progress_dialog.reset()
        show_message(self, QMessageBox.Icon.Critical, "Analysis Error", message)

    # ------------------------------------------------------------------
    # Grouping-panel handlers
    # ------------------------------------------------------------------

    def _on_comparison_requested(self, group1: List[str], group2: List[str]) -> None:
        if not group1 or not group2:
            return
        # Update the violin x-tick labels with the user's selection BEFORE
        # the worker starts so the skeleton shown during analysis already
        # carries the right labels — and so a cache-hit's synchronous
        # render lands on the new labels too.
        self.violin_widget.set_group_labels(
            _format_group_label(group1, "Group 1"),
            _format_group_label(group2, "Group 2"),
        )
        self.grouping_panel.set_running(True)
        self._viewmodel.analyze_event_groups(
            group1, group2,
            n_perm=self.grouping_panel.selected_n_perm(),
            n_boot=self.grouping_panel.selected_n_boot(),
            window_minutes=self.grouping_panel.selected_window_minutes(),
        )

    def _on_cancel_clicked(self) -> None:
        self._viewmodel.cancel()
        self.progress_dialog.reset()

    def _on_groups_cleared(self) -> None:
        self.violin_widget.render_skeleton()
        self.grouping_panel.clear_statistics_table()
        self.export_state_changed.emit(False)

    # ------------------------------------------------------------------
    # Public API — analysis-page contract (load_patient / clear_view / ...)
    # ------------------------------------------------------------------

    def apply_density(self, density: Density) -> None:
        """Adapt the page to the window's density (DensityAware)."""
        self._scaffold.apply_density(density)

    def row_minimum_width(self) -> int:
        """The narrowest content width the page fits in a ROW (ArrangementAware)."""
        return self._scaffold.row_minimum_width()

    def load_patient(self, patient_id: str) -> None:
        if not patient_id:
            self.clear_view()
            return
        self._viewmodel.load_patient_data(patient_id)

    def clear_view(self) -> None:
        self._viewmodel.clear_view()
        if hasattr(self, "violin_widget"):
            self.violin_widget.clear()
        if hasattr(self, "grouping_panel"):
            self.grouping_panel.clear_statistics_table()
        self.content_stack.setCurrentIndex(self._EMPTY_INDEX)
        self.export_state_changed.emit(False)

    def export_plot(self) -> None:
        if not self.violin_widget.export_state():
            QMessageBox.warning(
                self,
                "No Results",
                "Please run an analysis before exporting plots.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Threshold Plot", "", "PNG Image (*.png)",
        )
        if not path:
            return

        if self.violin_widget.save_figure(path):
            QMessageBox.information(self, "Export Successful", f"Plot saved to:\n{path}")
        else:
            QMessageBox.critical(
                self, "Export Failed",
                "Failed to write PNG file.",
            )

    def copy_table_to_clipboard(self) -> None:
        table = self.grouping_panel.stats_table
        if table.rowCount() == 0:
            QMessageBox.warning(
                self, "No Results",
                "Please run an analysis before copying statistics.",
            )
            return

        QApplication.clipboard().setText(table_tsv(table))
        QMessageBox.information(
            self, "Table Copied",
            "Statistics table has been copied to clipboard.",
        )

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        try:
            self._viewmodel.cancel()
        except Exception:  # pragma: no cover
            pass
        pool = QThreadPool.globalInstance()
        if not pool.waitForDone(2000):
            logger.warning(
                "TimelineLfpThresholdView: pool drain timed out at 2s; zombie threads may remain"
            )
        self._disconnect_signals()
        super().closeEvent(event)
