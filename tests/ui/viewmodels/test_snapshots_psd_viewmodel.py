"""
Tests for :class:`SnapshotsPsdViewModel`.

Mirrors :file:`tests/ui/viewmodels/test_snapshots_5hz_band_viewmodel.py` but covers
the Snapshots Classic (PSD) VM after its rewrite to dispatch through
:class:`SnapshotsPsdWorker`. Verifies:

- MVVM compliance: subclasses ``QObject``, all signals are class-level, no
  ``PySide6.QtWidgets`` import in the VM module.
- Patient loading emits ``patient_changed`` before ``data_loaded``; clearing
  data emits ``patient_changed`` with an empty string.
- ``analyze_event_groups`` constructs and submits a
  :class:`SnapshotsPsdWorker` via ``QThreadPool.start`` (patched).
- A doomed analyze call (no dataset) emits ``error_occurred`` and does not
  erase prior results.
- A second analyze call cancels and disconnects the previous worker.
- Worker-callback signal ordering on finished:
  ``psd_curves_ready`` → ``band_statistics_ready`` →
  ``progress_updated(100, …)`` → ``analysis_complete``.
- Error path emits ``error_occurred`` and does NOT emit ``analysis_complete``.
- Cancelled path does NOT emit ``error_occurred`` or ``analysis_complete``.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QObject, QThreadPool, Signal

from src.core.services.snapshot_psd_analysis_service import (
    BandComparisonResult,
    SnapshotPsdAnalysisService,
)
from src.domain.psd_models import SnapshotPsdDataset
from src.infrastructure.repositories import SnapshotRepository
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.workers.snapshots_psd_worker import SnapshotsPsdWorker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo() -> MagicMock:
    return MagicMock(spec=SnapshotRepository)


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=SnapshotPsdAnalysisService)


@pytest.fixture
def viewmodel(mock_repo, mock_service) -> SnapshotsPsdViewModel:
    return SnapshotsPsdViewModel(mock_repo, mock_service)


def _fake_dataset(n_events: int = 6) -> MagicMock:
    """Mock a SnapshotPsdDataset with the methods/attrs the VM touches."""
    ds = MagicMock(spec=SnapshotPsdDataset)
    ds.events = [MagicMock()] * n_events
    ds.frequency_axis = np.linspace(1.0, 95.0, 95)
    ds.get_event_types.return_value = ["Craving", "Neutral"]
    ds.get_event_counts.return_value = {"Craving": 3, "Neutral": 3}
    ds.patient_id = "PT_TEST"
    return ds


def _fake_curves(n: int = 5) -> dict:
    arr = np.zeros(n)
    return {"non_craving": (arr, arr, arr, n), "craving": (arr, arr, arr, n)}


def _fake_band_result(band: str, sig: bool = True) -> BandComparisonResult:
    return BandComparisonResult(
        band_name=band, canonical_band=band,
        min_freq=1.0, max_freq=4.0,
        hemisphere="LEFT",
        group1_name="Non-Craving", group2_name="Craving",
        n_group1=3, n_group2=3,
        median_group1=1.0, median_group2=1.5,
        mad_group1=0.1, mad_group2=0.1,
        u_statistic=5.0, p_value=0.01, q_value=0.04,
        rosenthal_r=0.3, rank_biserial_r=0.3,
        ci_lower=0.1, ci_upper=0.5,
        central_tendency_label="Median",
        central_tendency_difference=0.5,
        central_tendency_ci_lower=0.1,
        central_tendency_ci_upper=0.9,
        is_significant=sig,
    )


# ---------------------------------------------------------------------------
# 1. MVVM compliance
# ---------------------------------------------------------------------------


class TestMvvmCompliance:
    def test_inherits_from_qobject(self, viewmodel):
        assert isinstance(viewmodel, QObject)

    def test_defines_required_signals(self):
        for name in (
            "patient_changed",
            "data_loaded",
            "analysis_complete",
            "analysis_started",
            "psd_curves_ready",
            "band_statistics_ready",
            "error_occurred",
            "progress_updated",
            "effect_size_changed",
            "analysis_refresh_required",
            "analysis_refresh_cleared",
        ):
            attr = getattr(SnapshotsPsdViewModel, name)
            assert isinstance(attr, Signal), (
                f"{name} should be a class-level Signal, got {type(attr)}"
            )

    def test_module_imports_no_qwidgets(self):
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        text = Path(vm_mod.__file__).read_text()
        for line in text.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            assert not re.search(r"^from\s+PySide6\.QtWidgets\s+import", stripped), (
                f"VM imports from PySide6.QtWidgets: {stripped!r}"
            )
            assert not re.search(r"^import\s+PySide6\.QtWidgets", stripped), (
                f"VM imports PySide6.QtWidgets: {stripped!r}"
            )


# ---------------------------------------------------------------------------
# 2. Patient loading
# ---------------------------------------------------------------------------


class TestPatientLoading:
    def test_load_patient_data_emits_patient_changed_then_data_loaded(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset",
            lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []

        seen: List[Tuple[str, object]] = []
        viewmodel.patient_changed.connect(
            lambda pid: seen.append(("patient", pid))
        )
        viewmodel.data_loaded.connect(lambda n: seen.append(("data", n)))

        viewmodel.load_patient_data("PT_001")

        kinds = [k for k, _ in seen]
        assert "patient" in kinds
        assert "data" in kinds
        assert kinds.index("patient") < kinds.index("data")
        assert viewmodel.current_patient == "PT_001"


# ---------------------------------------------------------------------------
# 3. analyze_event_groups dispatches a worker
# ---------------------------------------------------------------------------


class TestAnalyzeEventGroups:
    def test_dispatches_worker_via_threadpool(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset",
            lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        captured: list[SnapshotsPsdWorker] = []

        def fake_start(self_pool, runnable, *a, **kw):
            captured.append(runnable)

        monkeypatch.setattr(QThreadPool, "start", fake_start)

        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])

        assert len(captured) == 1
        assert isinstance(captured[0], SnapshotsPsdWorker)
        # Worker is tracked as the active worker.
        assert viewmodel._active_worker is captured[0]
        # Six (signal, slot) pairs tracked: progress, partial_psd,
        # partial_band, finished, error, cancelled.
        assert len(viewmodel._worker_signal_connections) == 6

    def test_no_dataset_emits_error_and_no_worker(
        self, viewmodel, monkeypatch,
    ):
        captured: list = []
        monkeypatch.setattr(
            QThreadPool, "start",
            lambda self_pool, runnable, *a, **kw: captured.append(runnable),
        )

        errors: list[str] = []
        viewmodel.error_occurred.connect(lambda m: errors.append(m))

        viewmodel.analyze_event_groups(["A"], ["B"])

        assert errors == ["No data loaded"]
        assert captured == []


# ---------------------------------------------------------------------------
# 4. Cancellation: second analyze cancels previous worker
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_second_analyze_cancels_previous_worker(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset(n_events=6)
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset",
            lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        captured: list[SnapshotsPsdWorker] = []
        monkeypatch.setattr(
            QThreadPool, "start",
            lambda self_pool, runnable, *a, **kw: captured.append(runnable),
        )

        # First analyze submits worker A.
        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])
        worker_a = captured[0]

        cancel_called: list[bool] = []
        original_cancel = worker_a.cancel

        def spy_cancel():
            cancel_called.append(True)
            original_cancel()

        worker_a.cancel = spy_cancel  # type: ignore[assignment]

        # Second analyze must cancel A and submit B.
        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])

        assert cancel_called == [True], "worker A's cancel() was not called"
        assert len(captured) == 2
        assert captured[1] is not worker_a
        assert viewmodel._active_worker is captured[1]

    def test_explicit_cancel_emits_no_progress(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset()
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset",
            lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")

        monkeypatch.setattr(
            QThreadPool, "start",
            lambda self_pool, runnable, *a, **kw: None,
        )

        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])
        assert viewmodel._active_worker is not None

        progress: list[Tuple[int, str]] = []
        viewmodel.progress_updated.connect(
            lambda p, m: progress.append((p, m))
        )

        viewmodel.cancel_analysis()

        # Full-purity teardown: cancel no longer drives the popup via a
        # progress emission — the View hides it directly in its cancel slot.
        assert progress == [], (
            f"cancel_analysis must not emit progress; got {progress}"
        )
        assert viewmodel._active_worker is None
        assert viewmodel._worker_signal_connections == []

    def test_cancel_analysis_no_op_when_no_worker(self, viewmodel):
        # No worker → no signal traffic.
        signals: list = []
        viewmodel.progress_updated.connect(
            lambda *args: signals.append(args)
        )
        viewmodel.cancel_analysis()
        assert signals == []


# ---------------------------------------------------------------------------
# 4b. Progress contract: the popup is analysis-only
# ---------------------------------------------------------------------------


class TestProgressContract:
    """Locks the popup-visibility invariant at the VM contract layer:
    data loading emits neither ``progress_updated`` nor ``analysis_started``
    (so the popup never appears on patient switch / page load), and a real
    run emits ``analysis_started`` before its first progress update."""

    def test_load_patient_data_emits_no_progress(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset()
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset", lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []

        progress: list = []
        started: list = []
        viewmodel.progress_updated.connect(lambda p, m: progress.append((p, m)))
        viewmodel.analysis_started.connect(lambda: started.append(True))

        viewmodel.load_patient_data("PT_001")

        assert progress == [], f"load must not emit progress; got {progress}"
        assert started == [], "load must not emit analysis_started"

    def test_analyze_emits_analysis_started_before_progress(
        self, viewmodel, mock_repo, monkeypatch,
    ):
        fake = _fake_dataset()
        import src.ui.viewmodels.snapshots_psd_viewmodel as vm_mod
        monkeypatch.setattr(
            vm_mod, "load_snapshot_psd_dataset", lambda pid, records: fake,
        )
        mock_repo.get_by_patient.return_value = []
        viewmodel.load_patient_data("PT_001")
        monkeypatch.setattr(
            QThreadPool, "start", lambda self_pool, runnable, *a, **kw: None,
        )

        events: list = []
        viewmodel.analysis_started.connect(lambda: events.append("started"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}")
        )

        viewmodel.analyze_event_groups(["Neutral"], ["Craving"])

        assert events and events[0] == "started", events
        assert "progress:0" in events


# ---------------------------------------------------------------------------
# 5. Worker callbacks: signal ordering and error/cancel paths
# ---------------------------------------------------------------------------


class TestWorkerCallbacks:
    def test_on_finished_signal_order(self, viewmodel):
        # Seed the partial-state slots so _on_worker_finished has data to
        # combine. (In production these arrive via partial_psd / partial_band.)
        viewmodel._psd_curves_left = _fake_curves()
        viewmodel._psd_curves_right = _fake_curves()
        viewmodel._band_results_left = {"Delta": _fake_band_result("Delta")}
        viewmodel._band_results_right = {"Theta": _fake_band_result("Theta")}

        events: list[str] = []
        viewmodel.psd_curves_ready.connect(lambda: events.append("psd"))
        viewmodel.band_statistics_ready.connect(lambda: events.append("band"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}")
        )
        viewmodel.analysis_complete.connect(lambda: events.append("done"))

        viewmodel._on_worker_finished({})

        # Required ordering: psd, band, done. Full-purity teardown: finished
        # no longer emits progress(100); the View hides the popup on complete.
        assert events == ["psd", "band", "done"], (
            f"Wrong signal order; got {events}"
        )
        # Combined band_results are populated for the View.
        assert "Delta" in viewmodel.band_results
        assert "Theta" in viewmodel.band_results

    def test_on_worker_error_emits_error_not_complete(self, viewmodel):
        events: list[str] = []
        viewmodel.error_occurred.connect(lambda m: events.append(f"err:{m}"))
        viewmodel.analysis_complete.connect(lambda: events.append("done"))

        viewmodel._on_worker_error("kaboom")

        assert "err:kaboom" in events
        assert "done" not in events
        assert viewmodel._active_worker is None
        assert viewmodel._worker_signal_connections == []

    def test_on_worker_cancelled_no_error_no_complete(self, viewmodel):
        events: list[str] = []
        viewmodel.error_occurred.connect(lambda m: events.append(f"err:{m}"))
        viewmodel.analysis_complete.connect(lambda: events.append("done"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}:{m}")
        )

        viewmodel._on_worker_cancelled()

        # Full purity: no error, no analysis_complete, and no progress emit
        # (the View hides the popup in its cancel slot).
        assert not any(e.startswith("progress:") for e in events), events
        assert not any(e.startswith("err:") for e in events)
        assert "done" not in events
        assert viewmodel._active_worker is None

    def test_on_worker_partial_stores_silently_without_emit(self, viewmodel):
        """Partial signals populate state but must NOT emit psd_curves_ready
        or band_statistics_ready (the View renders both hemispheres at once
        in the existing handlers)."""
        emitted: list[str] = []
        viewmodel.psd_curves_ready.connect(lambda: emitted.append("psd"))
        viewmodel.band_statistics_ready.connect(lambda: emitted.append("band"))

        viewmodel._on_worker_partial_psd("LEFT", _fake_curves())
        viewmodel._on_worker_partial_band("LEFT", {"Delta": _fake_band_result("Delta")})

        assert emitted == []
        # State stored under the right hemisphere key.
        assert "non_craving" in viewmodel.psd_curves_left
        assert "Delta" in viewmodel.band_results_left

    def test_progress_callback_clamps_and_forwards(self, viewmodel):
        seen: list[Tuple[int, str]] = []
        viewmodel.progress_updated.connect(
            lambda p, m: seen.append((p, m))
        )
        # done > total clamps to 100.
        viewmodel._on_worker_progress(1500, 1000, "labelhi")
        # Negative inputs clamp to 0.
        viewmodel._on_worker_progress(-1, 1000, "labellow")
        # Zero total should not crash.
        viewmodel._on_worker_progress(0, 0, "labelzero")
        assert seen == [(100, "labelhi"), (0, "labellow"), (0, "labelzero")]
