"""
SnapshotsPsdView - Main view for Snapshots PSD analysis page.

This page provides PSD analysis for patient-triggered snapshots,
comparing craving vs non-craving states across frequency bands.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import logging
from dataclasses import asdict
from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QLabel, QSizePolicy,
    QMessageBox, QFileDialog,
    QApplication
)
from PySide6.QtCore import Qt, QThreadPool, Signal

from src.ui.export import (
    ExportOutcome,
    build_snapshots_export_request,
    run_export
)
from src.ui.components import MlProgressDialog
from src.ui.components.dialog_fit import show_message
from src.ui.components.table_copy import table_tsv
from src.ui.policy.layout import Density
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.views._shared import AnalysisPageScaffold


logger = logging.getLogger(__name__)
from src.ui.views.snapshots_psd.components import (
    SnapshotsGroupingPanel,
    DualHemispherePsdWidget
)


class _ElidedLabel(QLabel):
    """One line of text elided to the label's width; the full text is its tooltip.

    Its width never depends on its text, so a long message can't widen the
    page, and it never wraps: a wrapped label would switch the page's scroll
    area to height-for-width and pin the plot at its old height.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width())
        self.setText(shown)
        self.setToolTip(self._full_text if shown != self._full_text else "")


class SnapshotsPsdView(QWidget):
    """
    Snapshots PSD analysis page.

    Provides:
    - PSD curve visualization (craving vs non-craving)
    - Frequency band statistics with FDR correction
    - Hemisphere selection
    - Export functionality

    Layout:
    ┌─────────────────────────────────────────────────────┐
    │  CONTROLS                                           │
    │  Hemisphere: [LEFT ▼]  [Analyze]                   │
    ├─────────────────────────────────────────────────────┤
    │  PSD PLOT                                           │
    │  [Interactive PyQtGraph plot with bands]           │
    ├─────────────────────────────────────────────────────┤
    │  BAND STATISTICS TABLE                             │
    │  [Band | N | Medians | Stats | Significance ...]   │
    └─────────────────────────────────────────────────────┘
    """

    # Signals
    export_state_changed = Signal(bool)  # True when export is available

    def __init__(
        self,
        viewmodel: SnapshotsPsdViewModel,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize SnapshotsPsdView.

        Parameters
        ----------
        viewmodel : SnapshotsPsdViewModel
            ViewModel coordinating analysis
        parent : Optional[QWidget]
            Parent widget
        """
        super().__init__(parent)
        self.viewmodel = viewmodel
        self._stale_status_active = False
        # Track every VM→View connection so closeEvent can disconnect them
        # cleanly — the VM can outlive this View.
        self._signal_connections: List[tuple] = []
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Setup the UI layout and widgets."""
        # Persistent stale-results banner (shown after effect-size changes
        # while a previous analysis is still on screen). Progress for
        # in-flight analyses goes through the shared MlProgressDialog popup
        # below, NOT this label — the label is dual-purpose only in name.
        self.status_label = _ElidedLabel()
        self.status_label.setVisible(False)

        # Dual hemisphere PSD plot widget (top) - shows both left and right
        self.psd_plot = DualHemispherePsdWidget()

        # Grouping panel at bottom (includes event types, groups, tests, and stats table)
        self.grouping_panel = SnapshotsGroupingPanel()

        # Empty state (index 0) or the analysis content (index 1), below the banner
        self._scaffold = AnalysisPageScaffold(self, self.psd_plot, self.grouping_panel,
                                              banner=self.status_label, plot_gap=True)
        self.content_stack = self._scaffold.content_stack

        # Start with empty state
        self.content_stack.setCurrentIndex(0)

        # Shared modal progress popup. Cancel routes back to the VM so a
        # user-pressed Cancel terminates the in-flight worker; the VM then
        # emits ``progress_updated(100, "Cancelled")`` which auto-hides the
        # popup via ``update_progress``.
        self.progress_dialog = MlProgressDialog(self)
        self.progress_dialog.cancel_requested.connect(
            self._on_cancel_clicked, Qt.UniqueConnection,
        )

    def _connect_signals(self):
        """Connect ViewModel signals to slots, tracking each connection so
        ``closeEvent`` can disconnect them cleanly."""
        connections = [
            (self.viewmodel.patient_changed, self._on_patient_changed),
            (self.viewmodel.data_loaded, self._on_data_loaded),
            (self.viewmodel.analysis_started, self._on_analysis_started),
            (self.viewmodel.analysis_complete, self._on_analysis_complete),
            (self.viewmodel.psd_curves_ready, self._on_psd_curves_ready),
            (self.viewmodel.band_statistics_ready, self._on_statistics_ready),
            (self.viewmodel.error_occurred, self._on_error),
            (self.viewmodel.progress_updated, self._on_progress_updated),
            (self.viewmodel.analysis_refresh_required, self._on_analysis_refresh_required),
            (self.viewmodel.analysis_refresh_cleared, self._on_analysis_refresh_cleared),
        ]
        for signal, slot in connections:
            signal.connect(slot, Qt.UniqueConnection)
            self._signal_connections.append((signal, slot))

        # New grouping panel signals (child widgets owned by this View)
        self.grouping_panel.comparison_requested.connect(self._on_comparison_requested)
        self.grouping_panel.group_cleared.connect(self._on_groups_cleared)
        self.grouping_panel.copy_table_requested.connect(self.copy_table_to_clipboard)

        # Effect size selector signals
        self.grouping_panel.effect_size_selector.effect_size_changed.connect(
            self._on_effect_size_changed
        )

        # Initialize effect size selector with current preference
        current_effect_size_value = self.viewmodel.get_effect_size_value()
        self.grouping_panel.effect_size_selector.set_current_effect_size(
            current_effect_size_value
        )

    def _disconnect_signals(self):
        """Disconnect every tracked VM connection (idempotent on close)."""
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._signal_connections.clear()

    # ========================================================================
    # Slot Methods - ViewModel Events
    # ========================================================================

    def _on_patient_changed(self, patient_id: str):
        """Handle patient selection change."""
        if patient_id:
            self.content_stack.setCurrentIndex(1)  # Show analysis content
            # Drop any stale Group 1 / Group 2 selections and event types from
            # the previous patient — they may not exist for the new patient, and
            # clearing eagerly avoids a frame of stale data before data_loaded.
            self.grouping_panel.clear_active_groups()
            self.grouping_panel.set_available_event_types({})
            self.progress_dialog.reset()
        else:
            self.content_stack.setCurrentIndex(0)  # Show empty state
            self.psd_plot.clear_plots()
            self.grouping_panel.clear_statistics_table()
            self.grouping_panel.clear_active_groups()
            self.export_state_changed.emit(False)  # Disable export buttons
            self.progress_dialog.reset()

    def _on_data_loaded(self, n_events: int):
        """Handle data loading completion."""
        self.progress_dialog.reset()

        # Refresh the available event types unconditionally. On an empty patient
        # event_counts is {}, which clears the list — otherwise the previous
        # patient's event types (and their n= counts) would linger here.
        self.grouping_panel.set_available_event_types(self.viewmodel.event_counts)

        # Clear previous results
        self.psd_plot.clear_plots()
        self.grouping_panel.clear_statistics_table()
        self.grouping_panel.set_timeline_band_center(
            self.viewmodel.get_timeline_band_center()
        )

    def _on_analysis_complete(self):
        """Handle analysis completion."""
        self.progress_dialog.reset()

        # Enable export buttons (data is available regardless of significance)
        self.export_state_changed.emit(True)

    def _on_psd_curves_ready(self):
        """Handle PSD curves being ready."""
        # Get data for both hemispheres
        left_curves = self.viewmodel.psd_curves_left
        right_curves = self.viewmodel.psd_curves_right
        freq_axis = self.viewmodel.frequency_axis

        if left_curves and right_curves and freq_axis is not None:
            left_craving = left_curves.get('craving', (None, None, 0))
            left_non_craving = left_curves.get('non_craving', (None, None, 0))
            right_craving = right_curves.get('craving', (None, None, 0))
            right_non_craving = right_curves.get('non_craving', (None, None, 0))

            # Update dual hemisphere plot
            self.psd_plot.update_psd_data(
                freq_axis,
                left_craving,
                left_non_craving,
                right_craving,
                right_non_craving
            )

    def _on_statistics_ready(self):
        """Handle band statistics being ready."""
        # Retrieve pre-formatted rows from the ViewModel
        stats_rows = [asdict(row) for row in self.viewmodel.band_statistics_table_rows]
        effect_header = self.viewmodel.effect_size_header_text
        central_header = self.viewmodel.central_tendency_header_text

        self.grouping_panel.set_central_tendency_header(central_header)
        self.grouping_panel.set_effect_size_header(effect_header)
        self.grouping_panel.update_statistics_table(stats_rows)

        # Update plot with significance markers — each plot from its OWN
        # hemisphere (left from band_results_left, right from band_results_right).
        self.psd_plot.update_band_statistics(
            self.viewmodel.band_results_left,
            self.viewmodel.band_results_right,
        )

    def _on_error(self, error_message: str):
        """Handle errors from viewmodel."""
        self.progress_dialog.reset()
        show_message(self, QMessageBox.Icon.Critical, "Analysis Error", error_message)

    def _on_analysis_started(self):
        """Show the shared progress popup for a new analysis run."""
        self.progress_dialog.start()

    def _on_progress_updated(self, percentage: int, message: str):
        """Handle progress updates (content only) on the shared popup."""
        self.progress_dialog.update_progress(percentage, message)

    def _on_cancel_clicked(self) -> None:
        """User pressed Cancel on the progress dialog → cancel the worker
        and hide the popup (the VM no longer drives visibility)."""
        self.viewmodel.cancel_analysis()
        self.progress_dialog.reset()

    def _on_analysis_refresh_required(self, effect_type_value: str):
        """Notify user that PSD results are stale after effect size change."""
        self._stale_status_active = True
        effect_display = self._format_effect_size_name(effect_type_value)
        self._set_status_message(
            f"Effect size changed to {effect_display}. Press Compare Groups to refresh results."
        )
        self.export_state_changed.emit(False)

    def _on_analysis_refresh_cleared(self):
        """Clear stale-results warning when analysis is rerun or results are cleared."""
        if self._stale_status_active:
            self._stale_status_active = False
            self._set_status_message("")

    def _set_status_message(self, message: str):
        """Update status label visibility alongside message text."""
        self.status_label.set_full_text(message)
        self.status_label.setVisible(bool(message))

    @staticmethod
    def _format_effect_size_name(effect_type_value: str) -> str:
        """Convert effect size enum value to human-readable text."""
        mapping = {
            "cohens_d": "Cohen's d",
            "rank_biserial": "Rank-biserial r",
            "rosenthal_r": "Rosenthal's r",
        }
        return mapping.get(effect_type_value, effect_type_value)

    # ========================================================================
    # Slot Methods - UI Events
    # ========================================================================

    def _on_effect_size_changed(self, effect_type_value: str):
        """Handle effect size selection change from UI."""
        try:
            self.viewmodel.set_effect_size_type(effect_type_value)
        except ValueError:
            pass

    # ========================================================================
    # Slot Methods - Grouping Panel Events
    # ========================================================================

    def _on_comparison_requested(self, group1_events, group2_events, test_method, correction_method, timeline_center):
        """Handle comparison request from grouping panel."""
        if group1_events and group2_events:
            # Set hemisphere from grouping panel
            hemisphere = self.grouping_panel.get_selected_hemisphere()
            self.viewmodel.set_hemisphere(hemisphere)
            self.viewmodel.set_timeline_band_center(timeline_center)

            # Run analysis with custom groups
            self.viewmodel.analyze_event_groups(
                group1_event_types=group1_events,
                group2_event_types=group2_events,
                group1_name="Group 1",
                group2_name="Group 2",
                test_method=test_method,
                correction_method=correction_method,
                timeline_band_center=timeline_center
            )

    def _on_groups_cleared(self):
        """Handle groups cleared signal from grouping panel."""
        self.viewmodel.clear_analysis_results(
            clear_groups=True,
            clear_timeline_band=True
        )
        self.psd_plot.clear_plots()
        self.grouping_panel.clear_statistics_table()
        self.grouping_panel.set_timeline_band_center(None)
        self.grouping_panel.set_effect_size_header("Effect Size")
        self.grouping_panel.set_central_tendency_header("Median Δ 95% CI")
        self.export_state_changed.emit(False)  # Disable export buttons

    # ========================================================================
    # Public Methods
    # ========================================================================

    def apply_density(self, density: Density) -> None:
        """Adapt the page to the window's density (DensityAware)."""
        self._scaffold.apply_density(density)

    def row_minimum_width(self) -> int:
        """The narrowest content width the page fits in a ROW (ArrangementAware)."""
        return self._scaffold.row_minimum_width()

    def load_patient(self, patient_id: str):
        """
        Load data for a patient.

        Called when patient selection changes in the app.

        Parameters
        ----------
        patient_id : str
            Patient identifier
        """
        if patient_id:
            self.viewmodel.load_patient_data(patient_id)
        else:
            self.viewmodel.clear_patient_data()

    def clear_view(self):
        """Clear all data and reset to empty state."""
        self.viewmodel.clear_patient_data()
        self.psd_plot.clear_plots()
        self.grouping_panel.clear_statistics_table()
        self.content_stack.setCurrentIndex(0)
        self.export_state_changed.emit(False)

    def export_plot(self):
        """Export current plots to file (PNG, PDF, SVG)."""
        has_results = self.viewmodel.has_analysis_results()
        if not has_results:
            QMessageBox.warning(
                self,
                "No Results",
                "Please run an analysis before exporting plots."
            )
            return

        # File dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Plot",
            "",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)"
        )

        outcome = self._run_plot_export(file_path)

        if outcome.cancelled:
            return

        if outcome.succeeded and outcome.path:
            QMessageBox.information(
                self,
                "Export Successful",
                f"Plot saved to:\n{outcome.path}"
            )
            return

        error_text = str(outcome.error) if outcome.error else "Unknown error."
        QMessageBox.critical(
            self,
            "Export Failed",
            f"Failed to export plot: {error_text}"
        )

    def _run_plot_export(self, path: Optional[str]) -> ExportOutcome:
        """Invoke the shared export helper for the PSD plot."""
        request = build_snapshots_export_request(
            path,
            lambda target, dpi: self.psd_plot.export_figure(target, dpi=dpi),
        )
        return run_export(request)

    def copy_table_to_clipboard(self):
        """Copy statistics table to clipboard in tab-separated format."""
        has_results = self.viewmodel.has_analysis_results()
        if not has_results:
            QMessageBox.warning(
                self,
                "No Results",
                "Please run an analysis before copying statistics."
            )
            return

        QApplication.clipboard().setText(table_tsv(self.grouping_panel.stats_table))

        QMessageBox.information(
            self,
            "Table Copied",
            "Statistics table has been copied to clipboard."
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Cancel any in-flight worker and drain the global thread pool
        before tearing down the view. Mirrors :class:`TimelineLfpThresholdView`."""
        try:
            self.viewmodel.cancel_analysis()
        except Exception:  # pragma: no cover - defensive
            pass
        self._disconnect_signals()
        pool = QThreadPool.globalInstance()
        if not pool.waitForDone(2000):
            logger.warning(
                "SnapshotsPsdView: pool drain timed out at 2s; "
                "zombie threads may remain"
            )
        super().closeEvent(event)
