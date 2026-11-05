"""
5 Hz Band analysis view for Snapshots.

Renders per-band held-out LOO AUC profiles for both hemispheres alongside
a four-section grouping panel (event types, active groups, controls, stats
table). Mirrors the public API of :class:`SnapshotsPsdView` so the main
window can drive both pages identically.

Strict MVVM: this module imports no services. All analysis is dispatched
through :class:`Snapshots5HzBandViewModel`; signals from the VM are converted
to widget updates here, and user actions on the grouping panel are
forwarded back to VM methods.

Author: iEEG BrainSense Development Team
"""

from typing import List, Optional

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from src.ui.components import MlProgressDialog
from src.ui.components.dialog_fit import show_message
from src.ui.components.table_copy import table_tsv
from src.ui.policy.layout import Density
from src.ui.viewmodels.snapshots_5hz_band_viewmodel import Snapshots5HzBandViewModel
from src.ui.views._shared import AnalysisPageScaffold
from src.ui.views.snapshots_5hz_band.components import (
    DualHemisphereAucWidget,
    Snapshots5HzBandGroupingPanel,
)


class Snapshots5HzBandView(QWidget):
    """
    5 Hz Band analysis view.

    Layout:
        ┌──────────────────────────────────────────────────┐
        │  DualHemisphereAucWidget          (stretch=7)   │
        │  ┌──────────────┬──────────────┐                │
        │  │ Left AUC     │ Right AUC    │                │
        │  └──────────────┴──────────────┘                │
        ├──────────────────────────────────────────────────┤
        │  Snapshots5HzBandGroupingPanel         (stretch=3)   │
        │  [Event Types] [Active Groups] [Controls] [Tbl] │
        └──────────────────────────────────────────────────┘

    Signals:
        export_state_changed: True/False whenever export availability
            (PNG plot + clipboard table) changes for this page.
    """

    export_state_changed = Signal(bool)

    def __init__(
        self,
        viewmodel: Snapshots5HzBandViewModel,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Initialize Snapshots5HzBandView.

        Parameters
        ----------
        viewmodel : Snapshots5HzBandViewModel
            ViewModel coordinating 5 Hz Band analysis.
        parent : Optional[QWidget]
            Parent widget.
        """
        super().__init__(parent)
        self.viewmodel = viewmodel
        # Track every connection we make to the VM so closeEvent can
        # disconnect them cleanly. Lambda-free style throughout to avoid
        # the closure-capture leaks documented in the project agent guide.
        self._signal_connections: List[tuple] = []
        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the empty-state vs analysis-content stacked layout."""
        self._create_analysis_content()

        # The same white shell as the PSD page. Index 0: empty state (no
        # patient). Index 1: real analysis content (patient loaded).
        self._scaffold = AnalysisPageScaffold(self, self.auc_plot, self.grouping_panel)
        self.content_stack = self._scaffold.content_stack
        self.content_stack.setCurrentIndex(0)

        # Shared modal progress popup. Cancel routes back to the VM so a
        # user-pressed Cancel terminates the in-flight worker.
        self.progress_dialog = MlProgressDialog(self)
        self.progress_dialog.cancel_requested.connect(
            self._on_cancel_clicked, Qt.UniqueConnection,
        )

    def _create_analysis_content(self) -> None:
        """
        Two-section analysis content: dual-hemisphere AUC plot on top,
        grouping panel below. The scaffold lays them out in the same
        proportions as :class:`SnapshotsPsdView` so both pages share visual
        rhythm.
        """
        self.auc_plot = DualHemisphereAucWidget()
        self.grouping_panel = Snapshots5HzBandGroupingPanel()

        # Wire grouping-panel signals. UniqueConnection guards against any
        # accidental double-wiring during hot-reload / repeated _setup_ui.
        self.grouping_panel.comparison_requested.connect(
            self._on_comparison_requested, Qt.UniqueConnection
        )
        # BaseGroupingPanel exposes group_cleared (singular). The PSD view
        # uses the same signal name; we mirror that here.
        self.grouping_panel.group_cleared.connect(
            self._on_groups_cleared, Qt.UniqueConnection
        )
        self.grouping_panel.copy_table_requested.connect(
            self.copy_table_to_clipboard, Qt.UniqueConnection
        )

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Connect VM signals to view slots; track every connection."""
        connections = [
            (self.viewmodel.patient_changed,    self._on_patient_changed),
            (self.viewmodel.data_loaded,        self._on_data_loaded),
            (self.viewmodel.analysis_started,   self._on_analysis_started),
            (self.viewmodel.analysis_complete,  self._on_analysis_complete),
            (self.viewmodel.auc_profiles_ready, self._on_auc_profiles_ready),
            (self.viewmodel.band_table_ready,   self._on_band_table_ready),
            (self.viewmodel.error_occurred,     self._on_error),
            (self.viewmodel.progress_updated,   self._on_progress),
        ]
        for signal, slot in connections:
            signal.connect(slot, Qt.UniqueConnection)
            self._signal_connections.append((signal, slot))

    def _disconnect_signals(self) -> None:
        """Disconnect every tracked connection (idempotent on close)."""
        for signal, slot in self._signal_connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                # Signal already disconnected or underlying C++ object gone.
                pass
        self._signal_connections.clear()

    # ------------------------------------------------------------------
    # Slots — ViewModel events
    # ------------------------------------------------------------------

    def _on_patient_changed(self, patient_id: str) -> None:
        """Switch the stack to analysis (or empty if cleared) on patient change."""
        if patient_id:
            self.content_stack.setCurrentIndex(1)
            # Reset the AUC widget back to its empty-axes state so the
            # previous patient's curves don't bleed into the new view, and
            # drop any stale Group 1 / Group 2 selections from the previous
            # patient — those event types may not exist for the new patient.
            self.auc_plot.clear()
            self.grouping_panel.clear_statistics_table()
            self.grouping_panel.clear_active_groups()
            # Also drop the previous patient's event types eagerly so they
            # don't linger before the data_loaded refresh arrives.
            self.grouping_panel.set_available_event_types({})
        else:
            self.content_stack.setCurrentIndex(0)
            self.export_state_changed.emit(False)

    def _on_data_loaded(self, n_events: int) -> None:
        """
        Refresh available event types after a successful data load.

        Mirrors :meth:`SnapshotsPsdView._on_data_loaded`: when at least one
        event came back, the grouping panel's Event-Types list is populated
        from the VM's per-event-type counts. The AUC plot and table are
        cleared so users start every new patient from a blank slate.
        """
        self.progress_dialog.reset()

        # Refresh the available event types unconditionally. On an empty patient
        # event_counts is {}, which clears the list — otherwise the previous
        # patient's event types (and their n= counts) would linger here.
        self.grouping_panel.set_available_event_types(self.viewmodel.event_counts)

        # Always clear previous results — the new patient may have a
        # totally different band envelope, so any stale curve / row is
        # actively misleading.
        self.auc_plot.clear()
        self.grouping_panel.clear_statistics_table()

    def _on_comparison_requested(
        self,
        group1: List[str],
        group2: List[str],
    ) -> None:
        """User clicked Compare → dispatch the 5 Hz Band analysis."""
        if group1 and group2:
            # Permutation / bootstrap counts come from the panel selectors;
            # seed stays pinned to the manuscript value (42) via the VM default
            # (SEED), so Compare reproduces the published CI / FWER conditions.
            self.viewmodel.analyze_event_groups(
                group1,
                group2,
                n_perm=self.grouping_panel.selected_n_perm(),
                n_boot=self.grouping_panel.selected_n_boot(),
            )

    def _on_groups_cleared(self) -> None:
        """Reset plot + table when the user clears active groups."""
        self.auc_plot.clear()
        self.grouping_panel.populate_ml_table(None, None)
        self.grouping_panel.clear_statistics_table()
        self.export_state_changed.emit(False)

    def _on_auc_profiles_ready(self) -> None:
        """Paint per-hemisphere AUC profiles when the VM signals ready."""
        self.auc_plot.set_results(
            self.viewmodel.get_left_result(),
            self.viewmodel.get_right_result(),
        )

    def _on_band_table_ready(self) -> None:
        """Populate the ML stats table when the VM signals ready."""
        self.grouping_panel.populate_ml_table(
            self.viewmodel.get_left_result(),
            self.viewmodel.get_right_result(),
        )

    def _on_analysis_complete(self) -> None:
        """Hide progress and update export availability on analysis end."""
        self.progress_dialog.reset()
        self.export_state_changed.emit(self.viewmodel.has_analysis_results())

    def _on_error(self, message: str) -> None:
        """Surface VM errors as a critical dialog and reset progress UI."""
        self.progress_dialog.reset()
        show_message(self, QMessageBox.Icon.Critical, "Analysis Error", message)

    def _on_analysis_started(self) -> None:
        """Show the shared progress popup for a new analysis run."""
        self.progress_dialog.start()

    def _on_progress(self, percent: int, message: str) -> None:
        """Forward VM progress updates (content only) to the shared dialog."""
        self.progress_dialog.update_progress(percent, message)

    def _on_cancel_clicked(self) -> None:
        """User pressed Cancel → cancel worker and hide the popup (the VM
        no longer drives dialog visibility)."""
        self.viewmodel.cancel_analysis()
        self.progress_dialog.reset()

    # ------------------------------------------------------------------
    # Public API — mirrors SnapshotsPsdView so the main window can call
    # both pages with identical wiring.
    # ------------------------------------------------------------------

    def apply_density(self, density: Density) -> None:
        """Adapt the page to the window's density (DensityAware)."""
        self._scaffold.apply_density(density)

    def row_minimum_width(self) -> int:
        """The narrowest content width the page fits in a ROW (ArrangementAware)."""
        return self._scaffold.row_minimum_width()

    def load_patient(self, patient_id: str) -> None:
        """Load data for the given patient (clears if id is empty)."""
        if not patient_id:
            self.clear_view()
            return
        self.viewmodel.load_patient_data(patient_id)

    def clear_view(self) -> None:
        """Reset to empty state and emit export-disabled."""
        self.viewmodel.clear_patient_data()
        # Clear UI eagerly — the VM's clear is fast but we don't want a
        # frame of stale plot/table during the round-trip.
        if hasattr(self, "auc_plot"):
            self.auc_plot.clear()
        if hasattr(self, "grouping_panel"):
            self.grouping_panel.clear_statistics_table()
        self.content_stack.setCurrentIndex(0)
        self.export_state_changed.emit(False)

    def export_plot(self) -> None:
        """
        Export the dual-hemisphere AUC plot to a PNG file.

        Modelled on :meth:`SnapshotsPsdView.export_plot`. The widget's
        ``export_png`` is the canonical export path — it grabs the entire
        composite (both panels + headers + overlays) so the file matches
        what the user sees on screen.
        """
        if not self.viewmodel.has_analysis_results():
            QMessageBox.warning(
                self,
                "No Results",
                "Please run an analysis before exporting plots.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export AUC Plot",
            "",
            "PNG Image (*.png)",
        )
        if not file_path:
            return  # User cancelled.

        try:
            ok = self.auc_plot.export_png(file_path)
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export plot: {exc}",
            )
            return

        if ok:
            QMessageBox.information(
                self,
                "Export Successful",
                f"Plot saved to:\n{file_path}",
            )
        else:
            QMessageBox.critical(
                self,
                "Export Failed",
                "Failed to write PNG file. The plot may be empty or the "
                "destination is not writable.",
            )

    def copy_table_to_clipboard(self) -> None:
        """
        Copy the stats table to the clipboard in tab-separated format.

        Mirrors :meth:`SnapshotsPsdView.copy_table_to_clipboard`. Reads
        every visible row from the grouping panel's :attr:`stats_table`
        (a ``QTableWidget`` provided by :class:`BaseGroupingPanel`).
        """
        if not self.viewmodel.has_analysis_results():
            QMessageBox.warning(
                self,
                "No Results",
                "Please run an analysis before copying statistics.",
            )
            return

        QApplication.clipboard().setText(table_tsv(self.grouping_panel.stats_table))

        QMessageBox.information(
            self,
            "Table Copied",
            "Statistics table has been copied to clipboard.",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Disconnect tracked signal connections before closing."""
        self.viewmodel.cancel_analysis()
        self._disconnect_signals()
        super().closeEvent(event)
