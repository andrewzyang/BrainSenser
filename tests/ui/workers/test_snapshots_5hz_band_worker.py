"""
Tests for Snapshots5HzBandWorker.

Covers signal contract, success path, error path, and the two cancellation
paths (service raises OperationCancelledException, and worker._is_cancelled
is True at completion).

Worker.run() is called synchronously on the test thread — same approach
as test_recording_loader_worker.py — so qtbot's signal machinery sees the
emissions through direct connections without needing a thread pool.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import Signal

from src.core.services.snapshot_ml_analysis_service import (
    AucProfileResult,
    OperationCancelledException,
    SnapshotMlAnalysisService,
)
from src.ui.workers.snapshots_5hz_band_worker import (
    Snapshots5HzBandWorker,
    Snapshots5HzBandWorkerSignals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_result(hemi: str = "L") -> AucProfileResult:
    """Build a minimal frozen AucProfileResult for tests."""
    n = 5
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
        n_perm=20,
        n_boot=20,
    )


@pytest.fixture
def mock_service():
    """Mock SnapshotMlAnalysisService."""
    return MagicMock(spec=SnapshotMlAnalysisService)


@pytest.fixture
def small_inputs():
    """Tiny arrays — content does not matter; the service is mocked."""
    crav = np.zeros((4, 10))
    nc = np.zeros((4, 10))
    freqs = np.linspace(1, 30, 10)
    return crav, nc, freqs


@pytest.fixture
def worker(mock_service, small_inputs, qtbot):
    crav, nc, freqs = small_inputs
    w = Snapshots5HzBandWorker(
        mock_service,
        crav, nc,
        crav, nc,
        freqs,
        n_perm=20, n_boot=20, seed=0,
    )
    return w


# ---------------------------------------------------------------------------
# 1. Signal carrier exposes the four required signals
# ---------------------------------------------------------------------------


def test_signals_carrier_exposes_progress_finished_error_cancelled():
    """The carrier must declare progress, finished, error, cancelled."""
    assert isinstance(Snapshots5HzBandWorkerSignals.progress, Signal)
    assert isinstance(Snapshots5HzBandWorkerSignals.finished, Signal)
    assert isinstance(Snapshots5HzBandWorkerSignals.error, Signal)
    assert isinstance(Snapshots5HzBandWorkerSignals.cancelled, Signal)


# ---------------------------------------------------------------------------
# 2. Successful run emits `finished` with the result dict
# ---------------------------------------------------------------------------


def test_successful_run_emits_finished_with_result_dict(worker, mock_service, qtbot):
    """A successful service call must emit `finished` carrying the dict."""
    expected = {"L": _fake_result("L")}
    mock_service.analyze_both_hemispheres.return_value = expected

    finished_payloads = []
    worker.signals.finished.connect(lambda payload: finished_payloads.append(payload))

    worker.run()

    assert len(finished_payloads) == 1
    assert finished_payloads[0] == expected


# ---------------------------------------------------------------------------
# 3. Cancellation path — service raises OperationCancelledException
# ---------------------------------------------------------------------------


def test_service_cancellation_emits_cancelled_only(worker, mock_service):
    """When service raises OperationCancelledException, only `cancelled` fires."""
    mock_service.analyze_both_hemispheres.side_effect = (
        OperationCancelledException("aborted")
    )

    cancelled_calls = []
    finished_calls = []
    error_calls = []
    worker.signals.cancelled.connect(lambda: cancelled_calls.append(True))
    worker.signals.finished.connect(lambda payload: finished_calls.append(payload))
    worker.signals.error.connect(lambda msg: error_calls.append(msg))

    worker.run()

    assert len(cancelled_calls) == 1
    assert len(finished_calls) == 0
    assert len(error_calls) == 0


# ---------------------------------------------------------------------------
# 4. Cancellation path — cancel() called before run; service runs to
#    completion but worker should still emit `cancelled`.
# ---------------------------------------------------------------------------


def test_cancel_before_run_short_circuits_to_cancelled(worker, mock_service):
    """cancel() before run() must take the cancelled path, not finished."""
    mock_service.analyze_both_hemispheres.return_value = {"L": _fake_result("L")}

    cancelled_calls = []
    finished_calls = []
    worker.signals.cancelled.connect(lambda: cancelled_calls.append(True))
    worker.signals.finished.connect(lambda payload: finished_calls.append(payload))

    worker.cancel()
    worker.run()

    assert len(cancelled_calls) == 1
    assert len(finished_calls) == 0


# ---------------------------------------------------------------------------
# 5. Error path — service raises generic Exception
# ---------------------------------------------------------------------------


def test_generic_exception_emits_error_message(worker, mock_service):
    """A generic Exception from the service is reported via `error`."""
    mock_service.analyze_both_hemispheres.side_effect = RuntimeError("boom")

    cancelled_calls = []
    finished_calls = []
    error_calls = []
    worker.signals.cancelled.connect(lambda: cancelled_calls.append(True))
    worker.signals.finished.connect(lambda payload: finished_calls.append(payload))
    worker.signals.error.connect(lambda msg: error_calls.append(msg))

    worker.run()

    assert len(error_calls) == 1
    assert "boom" in error_calls[0]
    assert len(cancelled_calls) == 0
    assert len(finished_calls) == 0


# ---------------------------------------------------------------------------
# 6. progress_callback plumbing — service callback emits `progress` signal
# ---------------------------------------------------------------------------


def test_progress_callback_plumbs_to_signal(worker, mock_service):
    """When the service invokes its progress_callback, the worker emits the signal.

    With the per-hemisphere remap the worker scales (done, total) onto a
    combined 0..2*total bar. Without a hemisphere_label_callback firing
    first, _current_hemisphere stays at its default "L" so a (5, 10)
    invocation maps to (5, 20).
    """
    captured = []
    worker.signals.progress.connect(
        lambda done, total, label: captured.append((done, total, label))
    )

    def fake_analyze(*args, **kwargs):
        cb = kwargs["progress_callback"]
        cb(5, 10)
        return {"L": _fake_result("L")}

    mock_service.analyze_both_hemispheres.side_effect = fake_analyze

    finished_payloads = []
    worker.signals.finished.connect(lambda payload: finished_payloads.append(payload))

    worker.run()

    # First captured progress is the "0/n_perm" emit at run() entry.
    # The last one carries the remapped (5, 20) — combined-bar scale,
    # default hemisphere "L" so no offset.
    assert any((d, t) == (5, 20) for d, t, _ in captured), (
        f"Expected (5, 20) in progress emissions; got {captured}"
    )
    assert len(finished_payloads) == 1


def test_progress_remaps_per_hemisphere_on_combined_bar(worker, mock_service):
    """L and R per-hemisphere progress map onto a single 0..2*total bar.

    Mock the service so ``analyze_both_hemispheres`` walks through:
      hemisphere_label_callback("L") -> progress_callback(50, 100)  → (50,  200, "Electrode 1 — perm 50/100")
      hemisphere_label_callback("R") -> progress_callback(50, 100)  → (150, 200, "Electrode 2 — perm 50/100")
    """
    captured: list[tuple[int, int, str]] = []
    worker.signals.progress.connect(
        lambda done, total, label: captured.append((done, total, label))
    )

    def fake_analyze(*args, **kwargs):
        prog_cb = kwargs["progress_callback"]
        hemi_cb = kwargs["hemisphere_label_callback"]
        hemi_cb("L")
        prog_cb(50, 100)
        hemi_cb("R")
        prog_cb(50, 100)
        return {"L": _fake_result("L"), "R": _fake_result("R")}

    mock_service.analyze_both_hemispheres.side_effect = fake_analyze

    finished_payloads = []
    worker.signals.finished.connect(
        lambda payload: finished_payloads.append(payload)
    )

    worker.run()

    # Emissions during the fake analyze (skipping the "0/n_perm" startup emit)
    expected_left = (50, 200, "Electrode 1 — perm 50/100")
    expected_right = (150, 200, "Electrode 2 — perm 50/100")
    assert expected_left in captured, (
        f"Expected {expected_left} in {captured}"
    )
    assert expected_right in captured, (
        f"Expected {expected_right} in {captured}"
    )
    # Order: left appears before right in the captured list.
    assert captured.index(expected_left) < captured.index(expected_right)
    assert len(finished_payloads) == 1


def test_unilateral_implant_progress_climbs_to_100_percent(
    mock_service, small_inputs, qtbot
):
    """Right-only patient (no left input) — the bar must climb 0..100 % once,
    not strand at 50 %. Regression for the audit's flaw #5: previously the
    worker initialised ``_current_hemisphere = "L"`` and routed R progress
    through a doubled scale.
    """
    crav, nc, freqs = small_inputs
    w = Snapshots5HzBandWorker(
        mock_service,
        None, None,         # no left
        crav, nc,           # right only
        freqs,
        n_perm=20, n_boot=20, seed=0,
    )

    captured: list[tuple[int, int, str]] = []
    w.signals.progress.connect(
        lambda done, total, label: captured.append((done, total, label))
    )

    def fake_analyze(*args, **kwargs):
        # Service's analyze_both_hemispheres skips the L block when crav_L /
        # nc_L are None; only R fires its hemisphere_label_callback.
        prog_cb = kwargs["progress_callback"]
        hemi_cb = kwargs["hemisphere_label_callback"]
        hemi_cb("R")
        prog_cb(50, 100)
        prog_cb(100, 100)
        return {"R": _fake_result("R")}

    mock_service.analyze_both_hemispheres.side_effect = fake_analyze

    w.run()

    # Bar scale must equal n_perm (a single hemisphere), not 2 * n_perm.
    # And the final emit must reach the top of the bar.
    expected_mid = (50, 100, "Electrode 2 — perm 50/100")
    expected_full = (100, 100, "Electrode 2 — perm 100/100")
    assert expected_mid in captured, f"Expected {expected_mid} in {captured}"
    assert expected_full in captured, f"Expected {expected_full} in {captured}"
