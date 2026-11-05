"""Worker tests for TimelinePeriEventWorker.

Drives the worker with a fake service (no real analysis) and asserts:
progress is monotone non-decreasing on a 0..1000 scale and ends at 1000;
``partial_result`` fires once per hemisphere; ``finished`` carries the
{Left, Right} dict; cancel and error map to the right terminal signal.

Signals are connected with direct (same-thread) connections and ``run()`` is
called synchronously, so slots fire inline without an event loop.
"""

from __future__ import annotations

import pytest

from src.core.analysis.peri_event_cluster_perm import PeriEventCancelled
from src.ui.workers.timeline_peri_event_worker import (
    STAGE_WEIGHTS,
    TimelinePeriEventWorker,
)


class _FakeService:
    """analyze_hemisphere that drives the full stage callback sequence then
    returns a per-hemisphere sentinel (or raises)."""

    def __init__(self, results=None, *, raise_cancel=False, raise_error=False):
        self._results = results or {"Left": "L", "Right": "R"}
        self._raise_cancel = raise_cancel
        self._raise_error = raise_error
        self.calls = []

    def analyze_hemisphere(self, patient_id, hemisphere, g1, g2, *,
                           n_perm, n_boot, seed, window_minutes,
                           progress_callback=None, cancel_check=None):
        self.calls.append(hemisphere)
        if progress_callback is not None:
            progress_callback(0, 1, "Extracting events")
            progress_callback(1, 1, "Extracting events")
            progress_callback(0, 1, "Bootstrapping CIs")
            progress_callback(1, 1, "Bootstrapping CIs")
            for d in (1, max(1, n_perm // 2), n_perm):
                progress_callback(d, n_perm, "Permuting")
        if self._raise_error:
            raise RuntimeError("boom")
        if self._raise_cancel:
            raise PeriEventCancelled()
        return self._results[hemisphere]


def _make_worker(service, **kw):
    return TimelinePeriEventWorker(
        service, "PT_001", ["a"], ["b"],
        n_perm=kw.get("n_perm", 300), n_boot=kw.get("n_boot", 5_000),
        seed=42, window_minutes=kw.get("window_minutes", 50),
    )


def _wire(worker):
    out = {"progress": [], "partial": [], "finished": [], "error": [], "cancelled": 0}
    worker.signals.progress.connect(lambda d, t, lbl: out["progress"].append((d, t, lbl)))
    worker.signals.partial_result.connect(lambda h, r: out["partial"].append((h, r)))
    worker.signals.finished.connect(lambda res: out["finished"].append(res))
    worker.signals.error.connect(lambda m: out["error"].append(m))
    worker.signals.cancelled.connect(lambda: out.__setitem__("cancelled", out["cancelled"] + 1))
    return out


def test_stage_weights_sum_to_one():
    assert abs(sum(STAGE_WEIGHTS.values()) - 1.0) < 1e-9


def test_happy_path_progress_and_payload(qtbot=None):
    svc = _FakeService({"Left": "L_RES", "Right": "R_RES"})
    worker = _make_worker(svc)
    out = _wire(worker)

    worker.run()

    # Terminal signal: exactly one finished, no error/cancel.
    assert len(out["finished"]) == 1
    assert out["finished"][0] == {"Left": "L_RES", "Right": "R_RES"}
    assert out["error"] == []
    assert out["cancelled"] == 0

    # partial_result once per hemisphere, in order.
    assert [h for h, _ in out["partial"]] == ["Left", "Right"]
    assert [r for _, r in out["partial"]] == ["L_RES", "R_RES"]

    # Both hemispheres analysed.
    assert svc.calls == ["Left", "Right"]

    # Progress is monotone non-decreasing, total always 1000, ends at 1000.
    dones = [d for d, _, _ in out["progress"]]
    totals = {t for _, t, _ in out["progress"]}
    assert totals == {1000}
    assert dones == sorted(dones), f"progress not monotone: {dones}"
    assert dones[-1] == 1000
    assert dones[0] == 0
    # Left occupies 0..500, Right 500..1000: the mid-point boundary is hit.
    assert 500 in dones


def test_cancel_flag_before_run_emits_cancelled():
    svc = _FakeService()
    worker = _make_worker(svc)
    out = _wire(worker)
    worker.cancel()
    worker.run()
    assert out["cancelled"] == 1
    assert out["finished"] == []
    # The service is never invoked because cancellation is checked first.
    assert svc.calls == []


def test_service_cancel_exception_maps_to_cancelled():
    svc = _FakeService(raise_cancel=True)
    worker = _make_worker(svc)
    out = _wire(worker)
    worker.run()
    assert out["cancelled"] == 1
    assert out["finished"] == []
    assert out["error"] == []


def test_service_error_maps_to_error_signal():
    svc = _FakeService(raise_error=True)
    worker = _make_worker(svc)
    out = _wire(worker)
    worker.run()
    assert len(out["error"]) == 1
    assert "boom" in out["error"][0]
    assert out["finished"] == []
    assert out["cancelled"] == 0
