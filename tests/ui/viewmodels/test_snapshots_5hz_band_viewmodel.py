"""
Tests for Snapshots5HzBandViewModel.

Validates MVVM compliance, signal contract, the constructor signature
(snapshot_repo, ml_service), worker lifecycle, signal ordering on
completion, and that no QWidget types leak into the VM.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from src.core.services.snapshot_ml_analysis_service import (
    AucProfileResult,
    SnapshotMlAnalysisService,
)
from src.infrastructure.repositories import SnapshotRepository
from src.ui.viewmodels.snapshots_5hz_band_viewmodel import Snapshots5HzBandViewModel
from src.ui.workers.snapshots_5hz_band_worker import (
    Snapshots5HzBandWorker,
    Snapshots5HzBandWorkerSignals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo():
    return MagicMock(spec=SnapshotRepository)


@pytest.fixture
def mock_ml_service():
    return MagicMock(spec=SnapshotMlAnalysisService)


@pytest.fixture
def viewmodel(mock_repo, mock_ml_service):
    return Snapshots5HzBandViewModel(mock_repo, mock_ml_service)


def _fake_dataset(n_events: int = 6) -> MagicMock:
    """Mock a SnapshotPsdDataset with the methods/attrs the VM touches."""
    ds = MagicMock()
    ds.events = [MagicMock(has_left_data=True, has_right_data=True)] * n_events
    ds.frequency_axis = np.linspace(1.0, 95.0, 95)
    ds.get_event_counts.return_value = {"Craving": 4, "Neutral": 2}

    # get_psd_matrix returns (matrix, valid_mask). Matrices have at least
    # one row so the analyze pre-check doesn't bail with "no events".
    fake_matrix = np.ones((3, 95)) * 1e-6
    fake_mask = np.ones((3, 95), dtype=bool)
    ds.get_psd_matrix.return_value = (fake_matrix, fake_mask)
    return ds


def _fake_result(hemi: str = "L", n: int = 5) -> AucProfileResult:
    return AucProfileResult(
        hemisphere=hemi,
        band_centers_hz=np.linspace(7.0, 30.0, n),
        band_edges_hz=np.column_stack([
            np.linspace(5.0, 28.0, n),
            np.linspace(9.0, 32.0, n),
        ]),
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


# ---------------------------------------------------------------------------
# 1. MVVM compliance — inherits QObject
# ---------------------------------------------------------------------------


class TestMvvmCompliance:
    def test_inherits_from_qobject(self, viewmodel):
        assert isinstance(viewmodel, QObject)

    def test_defines_required_signals(self):
        """All seven signals must be class-level Signal declarations."""
        for name in (
            "patient_changed",
            "data_loaded",
            "analysis_complete",
            "analysis_started",
            "auc_profiles_ready",
            "band_table_ready",
            "error_occurred",
            "progress_updated",
        ):
            attr = getattr(Snapshots5HzBandViewModel, name)
            assert isinstance(attr, Signal), (
                f"{name} should be a class-level Signal, got {type(attr)}"
            )


# ---------------------------------------------------------------------------
# 2. Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_current_patient_id_initially_none(self, viewmodel):
        assert viewmodel.current_patient_id is None

    def test_event_counts_initially_empty_dict(self, viewmodel):
        assert viewmodel.event_counts == {}

    def test_has_no_analysis_results_initially(self, viewmodel):
        assert viewmodel.has_analysis_results() is False


# ---------------------------------------------------------------------------
# 3. Patient loading
# ---------------------------------------------------------------------------


class TestPatientLoading:
    def test_load_patient_data_emits_patient_changed_then_data_loaded(
        self, viewmodel, mock_repo, monkeypatch, qtbot
    ):
        # Make load_snapshot_psd_dataset (used by the VM) return our fake.
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                             lambda pid, records: fake)

        mock_repo.get_by_patient.return_value = []

        seen = []
        viewmodel.patient_changed.connect(lambda pid: seen.append(("patient", pid)))
        viewmodel.data_loaded.connect(lambda n: seen.append(("data", n)))

        viewmodel.load_patient_data("PT_001")

        # Both signals fired, in this order: patient_changed, then data_loaded.
        kinds = [k for k, _ in seen]
        assert kinds[0] == "patient"
        assert "data" in kinds
        assert kinds.index("patient") < kinds.index("data")
        assert viewmodel.current_patient_id == "PT_001"

    def test_clear_patient_data_resets_state_and_emits(
        self, viewmodel, mock_repo, monkeypatch, qtbot
    ):
        fake = _fake_dataset(n_events=4)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                             lambda pid, records: fake)
        mock_repo.get_by_patient.return_value = []

        viewmodel.load_patient_data("PT_001")
        assert viewmodel.current_patient_id == "PT_001"

        with qtbot.waitSignal(viewmodel.patient_changed, timeout=1000) as blocker:
            viewmodel.clear_patient_data()

        assert blocker.args == [""]
        assert viewmodel.current_patient_id is None
        assert viewmodel.event_counts == {}


# ---------------------------------------------------------------------------
# 3b. Progress contract: the popup is analysis-only
# ---------------------------------------------------------------------------


class TestProgressContract:
    """Loading emits neither ``progress_updated`` nor ``analysis_started``
    (so the popup never appears on patient switch / page load); a real run
    emits ``analysis_started`` before its first progress update."""

    def test_load_patient_data_emits_no_progress(
        self, viewmodel, mock_repo, monkeypatch
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                            lambda pid, records: fake)
        mock_repo.get_by_patient.return_value = []

        progress, started = [], []
        viewmodel.progress_updated.connect(lambda p, m: progress.append((p, m)))
        viewmodel.analysis_started.connect(lambda: started.append(True))

        viewmodel.load_patient_data("PT_001")

        assert progress == [], f"load must not emit progress; got {progress}"
        assert started == [], "load must not emit analysis_started"

    def test_analyze_emits_analysis_started_before_progress(
        self, viewmodel, mock_repo, monkeypatch
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                            lambda pid, records: fake)
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        from PySide6.QtCore import QThreadPool
        monkeypatch.setattr(
            QThreadPool, "start",
            lambda self_pool, runnable, *a, **kw: None,
        )

        events = []
        viewmodel.analysis_started.connect(lambda: events.append("started"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}")
        )

        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])

        assert events and events[0] == "started", events
        assert "progress:0" in events


# ---------------------------------------------------------------------------
# 4. analyze_event_groups dispatches a worker
# ---------------------------------------------------------------------------


class TestAnalyzeEventGroups:
    def test_dispatches_worker_via_threadpool(
        self, viewmodel, mock_repo, monkeypatch, qtbot
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                             lambda pid, records: fake)
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        captured = []

        # Patch QThreadPool.start globally on the VM's reference so the
        # worker is captured but never actually run.
        from PySide6.QtCore import QThreadPool

        original_start = QThreadPool.start

        def fake_start(self_pool, runnable, *args, **kwargs):
            captured.append(runnable)
            # Don't actually start it — we just want to capture it.

        monkeypatch.setattr(QThreadPool, "start", fake_start)

        try:
            viewmodel.analyze_event_groups(["Neutral"], ["Craving"])
        finally:
            monkeypatch.setattr(QThreadPool, "start", original_start)

        assert len(captured) == 1
        assert isinstance(captured[0], Snapshots5HzBandWorker)

    def test_doomed_call_preserves_prior_results(
        self, viewmodel, mock_repo, monkeypatch, qtbot
    ):
        """A second analyze call whose pre-check fails must not erase the
        currently-displayed analysis on the way to surfacing the error."""
        # Set up a dataset whose get_psd_matrix returns empty for the
        # second (doomed) call's event types.
        fake_ds = MagicMock()
        fake_ds.events = [MagicMock(has_left_data=True, has_right_data=True)] * 6
        fake_ds.frequency_axis = np.linspace(1.0, 95.0, 95)
        fake_ds.get_event_counts.return_value = {"A": 3, "B": 3}

        good_matrix = np.ones((3, 95)) * 1e-6
        good_mask = np.ones((3, 95), dtype=bool)
        empty_matrix = np.empty((0, 95))
        empty_mask = np.empty((0, 95), dtype=bool)

        def selective_get_psd_matrix(event_types, hemisphere):
            if event_types and event_types[0] in ("A", "B"):
                return good_matrix, good_mask
            return empty_matrix, empty_mask
        fake_ds.get_psd_matrix.side_effect = selective_get_psd_matrix

        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                             lambda pid, records: fake_ds)
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        # Stub out the worker so analyze_event_groups doesn't actually run.
        from PySide6.QtCore import QThreadPool
        monkeypatch.setattr(
            QThreadPool, "start",
            lambda self_pool, runnable, *a, **kw: None,
        )

        # Plant a "current result" so we can detect whether it gets erased.
        sentinel_left = _fake_result("L")
        sentinel_right = _fake_result("R")
        viewmodel._left_result = sentinel_left
        viewmodel._right_result = sentinel_right

        # Doomed call — both event-type lists yield empty matrices.
        errors: list[str] = []
        viewmodel.error_occurred.connect(lambda m: errors.append(m))
        viewmodel.analyze_event_groups(["UNKNOWN1"], ["UNKNOWN2"])

        assert len(errors) == 1, "Should have surfaced an error"
        assert "no events found" in errors[0].lower()

        # Crucial: prior results survive the doomed call.
        assert viewmodel.get_left_result() is sentinel_left, (
            "Doomed analyze_event_groups must NOT erase a prior left result"
        )
        assert viewmodel.get_right_result() is sentinel_right, (
            "Doomed analyze_event_groups must NOT erase a prior right result"
        )


# ---------------------------------------------------------------------------
# 5. Cancellation: a second analyze call cancels the previous worker
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_second_analyze_cancels_and_disconnects_previous_worker(
        self, viewmodel, mock_repo, monkeypatch, qtbot
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
        monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                             lambda pid, records: fake)
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        captured: list[Snapshots5HzBandWorker] = []
        from PySide6.QtCore import QThreadPool

        def fake_start(self_pool, runnable, *args, **kwargs):
            captured.append(runnable)

        monkeypatch.setattr(QThreadPool, "start", fake_start)

        # First analyze submits worker A; we need to track its cancel().
        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])
        assert len(captured) == 1
        worker_a = captured[0]

        cancel_called = []
        original_cancel = worker_a.cancel

        def spy_cancel():
            cancel_called.append(True)
            original_cancel()

        worker_a.cancel = spy_cancel  # type: ignore[assignment]

        # Track disconnections on the carrier signals before the second
        # analyze fires.
        connections_before = list(viewmodel._worker_signal_connections)
        assert len(connections_before) == 4, (
            f"Expected 4 (signal, slot) pairs tracked from worker A, "
            f"got {len(connections_before)}"
        )

        # Second analyze: should cancel worker A and start worker B.
        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])

        assert cancel_called == [True], "worker A's cancel() was not called"
        assert len(captured) == 2
        worker_b = captured[1]
        assert worker_b is not worker_a
        # The VM has fresh tracking pointing at worker B's signals.
        assert viewmodel._active_worker is worker_b

        # Connections to worker A's carrier should have been removed: we
        # can't easily prove a direct disconnect, but the VM's tracking
        # list should have rotated to worker B's pairs only.
        assert all(
            sig is not getattr(worker_a.signals, name)
            for sig, _slot in viewmodel._worker_signal_connections
            for name in ("progress", "finished", "error", "cancelled")
        ), "VM still tracks worker A's signals after cancellation"


# ---------------------------------------------------------------------------
# 6. Worker callbacks: signal ordering and error/cancel paths
# ---------------------------------------------------------------------------


class TestWorkerCallbacks:
    def test_on_finished_stores_results_and_emits_in_order(self, viewmodel, qtbot):
        """auc_profiles_ready → band_table_ready → analysis_complete order."""
        result_dict = {"L": _fake_result("L"), "R": _fake_result("R")}

        events = []
        viewmodel.auc_profiles_ready.connect(lambda: events.append("auc"))
        viewmodel.band_table_ready.connect(lambda: events.append("band"))
        viewmodel.analysis_complete.connect(lambda: events.append("done"))

        viewmodel._on_worker_finished(result_dict)

        assert viewmodel.get_left_result() is result_dict["L"]
        assert viewmodel.get_right_result() is result_dict["R"]
        assert events == ["auc", "band", "done"], (
            f"Wrong signal order; got {events}"
        )
        assert viewmodel.has_analysis_results()

    def test_on_cancelled_does_not_emit_error(self, viewmodel, qtbot):
        error_calls = []
        viewmodel.error_occurred.connect(lambda msg: error_calls.append(msg))
        viewmodel._on_worker_cancelled()
        assert error_calls == []

    def test_on_error_emits_error_occurred_with_message(self, viewmodel, qtbot):
        with qtbot.waitSignal(viewmodel.error_occurred, timeout=1000) as blocker:
            viewmodel._on_worker_error("kaboom")
        assert blocker.args == ["kaboom"]

    def test_on_finished_with_empty_dict_emits_error_not_complete(
        self, viewmodel, qtbot
    ):
        """An empty results dict means every event was dropped during
        preprocessing on both sides. The VM must surface that as an error
        (so the user gets a dialog) and must NOT emit the
        auc_profiles_ready / band_table_ready / analysis_complete trio,
        which would falsely tell the view to render empty plots.
        """
        error_calls: list[str] = []
        auc_calls: list[bool] = []
        band_calls: list[bool] = []
        complete_calls: list[bool] = []

        viewmodel.error_occurred.connect(lambda msg: error_calls.append(msg))
        viewmodel.auc_profiles_ready.connect(lambda: auc_calls.append(True))
        viewmodel.band_table_ready.connect(lambda: band_calls.append(True))
        viewmodel.analysis_complete.connect(
            lambda: complete_calls.append(True)
        )

        viewmodel._on_worker_finished({})

        assert len(error_calls) == 1
        assert "preprocessing" in error_calls[0].lower()
        assert auc_calls == []
        assert band_calls == []
        assert complete_calls == []
        assert viewmodel.get_left_result() is None
        assert viewmodel.get_right_result() is None


# ---------------------------------------------------------------------------
# 7. VM does not import any QWidget types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. Group-role convention: Group 1 (Jade) → non-craving, Group 2 (Rose) → craving
# ---------------------------------------------------------------------------


def test_group1_is_non_craving_label_0(viewmodel, mock_repo, monkeypatch):
    """Pin the panel-to-backend convention.

    The grouping panel styles Group 1 in Jade (manuscript: non-craving) and
    Group 2 in Rose (manuscript: craving). The VM must therefore route
    ``group1_event_types`` into the *non-craving* slot of the worker
    (positional arg ``nc_L``/``nc_R``) and ``group2_event_types`` into the
    *craving* slot (``crav_L``/``crav_R``). A regression on this rule is
    silent under the per-fold direction-correction in the ML core, so this
    test is the only thing keeping the convention honest.
    """
    # Build a synthetic dataset where each event-name list returns a
    # uniquely sized matrix so we can identify which group ended up where.
    fake_ds = MagicMock()
    fake_ds.events = [MagicMock(has_left_data=True, has_right_data=True)] * 6
    fake_ds.frequency_axis = np.linspace(1.0, 95.0, 95)
    fake_ds.get_event_counts.return_value = {"Neutral": 5, "Drinking": 7}

    # Tag each group's matrix with its row count: 5 rows for Neutral, 7 for
    # Drinking. Both hemispheres return the same shapes for simplicity.
    def tagged_get_psd_matrix(event_types, hemisphere):
        if "Neutral" in event_types:
            return np.full((5, 95), 1e-6), np.ones((5, 95), dtype=bool)
        if "Drinking" in event_types:
            return np.full((7, 95), 2e-6), np.ones((7, 95), dtype=bool)
        return np.empty((0, 95)), np.empty((0, 95), dtype=bool)
    fake_ds.get_psd_matrix.side_effect = tagged_get_psd_matrix

    import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod
    monkeypatch.setattr(vm_mod, "load_snapshot_psd_dataset",
                         lambda pid, records: fake_ds)
    mock_repo.get_by_patient.return_value = []
    viewmodel.load_patient_data("PT_001")

    # Capture worker construction args.
    captured = {}
    real_worker_cls = vm_mod.Snapshots5HzBandWorker

    class CapturingWorker(real_worker_cls):
        def __init__(self, service, crav_L, nc_L, crav_R, nc_R, freqs, **kw):
            captured["crav_L"] = crav_L
            captured["nc_L"]   = nc_L
            captured["crav_R"] = crav_R
            captured["nc_R"]   = nc_R
            super().__init__(service, crav_L, nc_L, crav_R, nc_R, freqs, **kw)

    monkeypatch.setattr(vm_mod, "Snapshots5HzBandWorker", CapturingWorker)

    from PySide6.QtCore import QThreadPool
    monkeypatch.setattr(
        QThreadPool, "start",
        lambda self_pool, runnable, *a, **kw: None,  # don't actually run
    )

    # Panel convention: Group 1 (Jade) = non-craving, Group 2 (Rose) = craving.
    viewmodel.analyze_event_groups(
        group1_event_types=["Neutral"],   # Jade box
        group2_event_types=["Drinking"],  # Rose box
    )

    # Group 1 events (Neutral, 5 rows) must land in the non-craving slot.
    # Group 2 events (Drinking, 7 rows) must land in the craving slot.
    assert captured["nc_L"].shape[0]   == 5, "nc_L must carry Group 1 (Neutral) events"
    assert captured["crav_L"].shape[0] == 7, "crav_L must carry Group 2 (Drinking) events"
    assert captured["nc_R"].shape[0]   == 5
    assert captured["crav_R"].shape[0] == 7


def test_vm_module_imports_no_qwidgets():
    """The VM module must not import from PySide6.QtWidgets at all."""
    import src.ui.viewmodels.snapshots_5hz_band_viewmodel as vm_mod

    src_path = Path(vm_mod.__file__)
    text = src_path.read_text()
    for line in text.splitlines():
        # Strip line comments + leading whitespace.
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if re.search(r"^from\s+PySide6\.QtWidgets\s+import", stripped):
            raise AssertionError(
                f"VM imports from PySide6.QtWidgets: {stripped!r}; "
                f"the ViewModel must not depend on widget types."
            )
        if re.search(r"^import\s+PySide6\.QtWidgets", stripped):
            raise AssertionError(
                f"VM imports PySide6.QtWidgets: {stripped!r}"
            )
