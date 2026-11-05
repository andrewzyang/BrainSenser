"""
Tests for Snapshots5HzBandView.

Validates view-VM wiring with a mocked VM, state switching between empty
state and analysis content, public API forwarding, slot behaviour, signal
cleanup on close, and the hemisphere-label audit (no "NAc" anywhere).

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QStackedWidget, QTableWidget, QTableWidgetItem

from src.core.services.snapshot_ml_analysis_service import AucProfileResult
from src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view import Snapshots5HzBandView


# ---------------------------------------------------------------------------
# Fake VM — a real QObject carrying every signal Snapshots5HzBandView reads.
# Using a QObject (not MagicMock) lets the view's signal.connect() succeed.
# ---------------------------------------------------------------------------


class FakeMlViewModel(QObject):
    """Subset of Snapshots5HzBandViewModel API used by Snapshots5HzBandView."""

    patient_changed = Signal(str)
    data_loaded = Signal(int)
    analysis_complete = Signal()
    analysis_started = Signal()
    auc_profiles_ready = Signal()
    band_table_ready = Signal()
    error_occurred = Signal(str)
    progress_updated = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.event_counts = {}
        self._left_result = None
        self._right_result = None
        # Counters / records of method calls so tests can assert.
        self.calls: list[tuple] = []

    # Methods the view calls on the VM.
    def load_patient_data(self, patient_id: str) -> None:
        self.calls.append(("load_patient_data", patient_id))

    def clear_patient_data(self) -> None:
        self.calls.append(("clear_patient_data",))

    def analyze_event_groups(self, g1, g2, *, n_perm=10_000, n_boot=2_000) -> None:
        self.calls.append(
            ("analyze_event_groups", list(g1), list(g2), n_perm, n_boot)
        )

    def cancel_analysis(self) -> None:
        self.calls.append(("cancel_analysis",))

    def get_left_result(self):
        return self._left_result

    def get_right_result(self):
        return self._right_result

    def has_analysis_results(self) -> bool:
        return self._left_result is not None or self._right_result is not None


def _build_result(n: int = 5, hemi: str = "L") -> AucProfileResult:
    centers = np.linspace(7.0, 30.0, n)
    edges = np.column_stack([centers - 1.0, centers + 1.0])
    return AucProfileResult(
        hemisphere=hemi,
        band_centers_hz=centers,
        band_edges_hz=edges,
        per_band_auc=np.linspace(0.5, 0.7, n),
        per_band_ci_lo=np.linspace(0.4, 0.6, n),
        per_band_ci_hi=np.linspace(0.6, 0.8, n),
        modal_band_idx=2,
        pipeline_loo_auc=0.65,
        pipeline_loo_ci_lo=0.55,
        pipeline_loo_ci_hi=0.75,
        fwer_p=0.04,
        n_craving=8,
        n_non_craving=9,
        n_perm=200,
        n_boot=200,
    )


@pytest.fixture
def viewmodel():
    return FakeMlViewModel()


@pytest.fixture
def view(viewmodel, qtbot):
    v = Snapshots5HzBandView(viewmodel)
    qtbot.addWidget(v)
    return v


# ---------------------------------------------------------------------------
# 1. Setup and initial state
# ---------------------------------------------------------------------------


class TestSetup:
    def test_view_instantiates_with_mocked_vm(self, view, viewmodel):
        assert view.viewmodel is viewmodel

    def test_content_stack_has_two_pages(self, view):
        assert isinstance(view.content_stack, QStackedWidget)
        assert view.content_stack.count() == 2

    def test_starts_on_empty_state(self, view):
        assert view.content_stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# 2. load_patient / clear_view
# ---------------------------------------------------------------------------


class TestPatientFlow:
    def test_load_patient_calls_vm_and_switches_to_index_1(self, view, viewmodel):
        view.load_patient("PT_001")
        # VM was called.
        assert any(c[0] == "load_patient_data" and c[1] == "PT_001"
                   for c in viewmodel.calls)
        # And once the VM emits patient_changed (it would normally), the
        # view switches to analysis. Simulate the emission:
        viewmodel.patient_changed.emit("PT_001")
        assert view.content_stack.currentIndex() == 1

    def test_load_patient_with_empty_string_clears(self, view, viewmodel):
        # First "load" a patient, then clear by sending empty string.
        view.load_patient("PT_001")
        viewmodel.patient_changed.emit("PT_001")
        view.load_patient("")
        # Empty path is a clear; VM's clear_patient_data is called.
        assert any(c[0] == "clear_patient_data" for c in viewmodel.calls)
        # Empty patient_changed emit returns to empty state.
        viewmodel.patient_changed.emit("")
        assert view.content_stack.currentIndex() == 0

    def test_clear_view_calls_vm_clear_patient_data(self, view, viewmodel):
        view.clear_view()
        assert any(c[0] == "clear_patient_data" for c in viewmodel.calls)
        assert view.content_stack.currentIndex() == 0


# ---------------------------------------------------------------------------
# 3. Slots that paint plots / tables
# ---------------------------------------------------------------------------


class TestPaintingSlots:
    def test_on_auc_profiles_ready_calls_set_results(self, view, viewmodel):
        viewmodel._left_result = _build_result(5, "L")
        viewmodel._right_result = _build_result(5, "R")

        with patch.object(view.auc_plot, "set_results") as set_results:
            viewmodel.auc_profiles_ready.emit()
            set_results.assert_called_once_with(
                viewmodel._left_result, viewmodel._right_result
            )

    def test_on_band_table_ready_calls_populate_ml_table(self, view, viewmodel):
        viewmodel._left_result = _build_result(5, "L")
        viewmodel._right_result = _build_result(5, "R")

        with patch.object(view.grouping_panel, "populate_ml_table") as populate:
            viewmodel.band_table_ready.emit()
            populate.assert_called_once_with(
                viewmodel._left_result, viewmodel._right_result
            )

    def test_on_comparison_requested_calls_vm_analyze(self, view, viewmodel):
        # Switch to analysis content so the grouping panel exists.
        viewmodel.patient_changed.emit("PT_001")
        view._on_comparison_requested(["Craving"], ["Neutral"])
        assert any(
            c[0] == "analyze_event_groups"
            and c[1] == ["Craving"]
            and c[2] == ["Neutral"]
            for c in viewmodel.calls
        )

    def test_on_comparison_requested_forwards_panel_perm_boot(self, view, viewmodel):
        # The view must forward the grouping panel's perm/boot selections to
        # the VM. With the default selection that is the manuscript-locked
        # 10,000 permutations / 2,000 bootstraps.
        viewmodel.patient_changed.emit("PT_001")
        view._on_comparison_requested(["Craving"], ["Neutral"])
        call = next(c for c in viewmodel.calls if c[0] == "analyze_event_groups")
        assert call[3] == view.grouping_panel.selected_n_perm() == 10_000
        assert call[4] == view.grouping_panel.selected_n_boot() == 2_000

    def test_on_comparison_requested_forwards_changed_selection(self, view, viewmodel):
        # Changing the dropdowns changes what the view forwards downstream.
        viewmodel.patient_changed.emit("PT_001")
        panel = view.grouping_panel
        panel.n_perm_combo.setCurrentIndex(panel.n_perm_combo.findData(200))
        panel.n_boot_combo.setCurrentIndex(panel.n_boot_combo.findData(500))
        view._on_comparison_requested(["Craving"], ["Neutral"])
        call = next(c for c in viewmodel.calls if c[0] == "analyze_event_groups")
        assert call[3] == 200
        assert call[4] == 500


# ---------------------------------------------------------------------------
# 4. Signal cleanup on close
# ---------------------------------------------------------------------------


class TestSignalCleanup:
    def test_close_event_disconnects_signals(self, view, viewmodel, qtbot):
        """Closing the view must disconnect every tracked VM signal connection.

        After close, the view's ``_signal_connections`` list is cleared and
        emitting a VM signal does not flip view widget state. We detect the
        latter by emitting ``patient_changed`` before close (page switches
        to index 1) and after close (the post-close state must remain
        whatever the close left it; the slot should not fire and re-toggle
        the stack to 1 if we explicitly set it back to 0).
        """
        assert len(view._signal_connections) > 0

        # Pre-close sanity: VM emission flips the stack.
        viewmodel.patient_changed.emit("PT_001")
        assert view.content_stack.currentIndex() == 1

        # Close the view.
        view.close()

        # Tracked connections cleared.
        assert len(view._signal_connections) == 0

        # Force the stack back to empty state. If the slot is still
        # connected, the next emit would flip it back to 1.
        view.content_stack.setCurrentIndex(0)
        viewmodel.patient_changed.emit("PT_002")
        assert view.content_stack.currentIndex() == 0, (
            "patient_changed slot still wired after close — "
            "connections were not disconnected"
        )

    def test_close_event_cancels_active_worker(self, view, viewmodel):
        """closeEvent must call viewmodel.cancel_analysis to halt any in-flight worker."""
        # FakeMlViewModel is a real QObject subclass; patch the bound method
        # on the instance with a MagicMock so we can assert it was called.
        setattr(viewmodel, "cancel_analysis", MagicMock())
        view.close()
        viewmodel.cancel_analysis.assert_called_once()


# ---------------------------------------------------------------------------
# 5. Hemisphere-label audit — no "NAc" anywhere in rendered tree
# ---------------------------------------------------------------------------


class TestHemisphereLabelAudit:
    def test_no_nac_in_rendered_widget_tree(self, view, viewmodel):
        """Walk every QLabel/QTableWidgetItem; assert no "NAc" substring."""
        # Switch to analysis content so the panels are real, populated.
        viewmodel.patient_changed.emit("PT_001")

        # Populate plots + table with synthetic results.
        viewmodel._left_result = _build_result(5, "L")
        viewmodel._right_result = _build_result(5, "R")
        view.auc_plot.set_results(
            viewmodel._left_result, viewmodel._right_result
        )
        view.grouping_panel.populate_ml_table(
            viewmodel._left_result, viewmodel._right_result
        )

        # Audit every QLabel descendant.
        for label in view.findChildren(QLabel):
            text = label.text() or ""
            assert "NAc" not in text, (
                f"QLabel reads {text!r}; manuscript-rule forbids the "
                f"'NAc' label anywhere in the rendered tree."
            )

        # Audit every cell of every QTableWidget descendant.
        for table in view.findChildren(QTableWidget):
            for row in range(table.rowCount()):
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is None:
                        continue
                    text = item.text() or ""
                    assert "NAc" not in text, (
                        f"Table cell ({row},{col}) reads {text!r}; the "
                        f"electrode column must never say 'NAc'."
                    )
            # Header items too.
            for col in range(table.columnCount()):
                header = table.horizontalHeaderItem(col)
                if header is None:
                    continue
                text = header.text() or ""
                assert "NAc" not in text


# ---------------------------------------------------------------------------
# 6. Export / clipboard methods (smoke tests — they show dialogs when
#    no analysis is present, exactly like the PSD view)
# ---------------------------------------------------------------------------


class TestExportMethods:
    @patch("src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view.QMessageBox")
    def test_export_plot_warns_when_no_results(self, mock_msgbox, view, viewmodel):
        # No results → warning dialog.
        view.export_plot()
        mock_msgbox.warning.assert_called_once()

    @patch("src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view.QMessageBox")
    def test_copy_table_warns_when_no_results(self, mock_msgbox, view, viewmodel):
        view.copy_table_to_clipboard()
        mock_msgbox.warning.assert_called_once()
