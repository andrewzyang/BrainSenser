"""
Tests for :class:`SnapshotsPsdWorker`.

Covers:
- Signal carrier surface (progress, partial_psd, partial_band, finished, error,
  cancelled).
- Successful run emits ``finished`` with all four payload keys
  (``psd_left``, ``psd_right``, ``band_left``, ``band_right``).
- Per-hemisphere emission order: partial_psd(LEFT) → partial_band(LEFT) →
  partial_psd(RIGHT) → partial_band(RIGHT).
- Cancellation paths (cancel() before run; service raises
  OperationCancelledException; service raises a generic Exception).
- Progress signal scaling onto the 0..1000 monotone bar.

Worker.run() is called synchronously on the test thread (no QThreadPool) so
qtbot's signal machinery captures emissions through direct connections.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Signal

from src.core.services.snapshot_psd_analysis_service import (
    OperationCancelledException,
    SnapshotPsdAnalysisService,
)
from src.domain.psd_models import SnapshotPsdDataset
from src.ui.workers.snapshots_psd_worker import (
    SnapshotsPsdWorker,
    _SnapshotsPsdWorkerSignals,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service() -> MagicMock:
    return MagicMock(spec=SnapshotPsdAnalysisService)


@pytest.fixture
def mock_dataset() -> MagicMock:
    ds = MagicMock(spec=SnapshotPsdDataset)
    ds.patient_id = "PT_TEST"
    return ds


@pytest.fixture
def worker(mock_service, mock_dataset, qtbot) -> SnapshotsPsdWorker:
    return SnapshotsPsdWorker(
        mock_service,
        mock_dataset,
        group1_event_types=["Neutral"],
        group2_event_types=["Craving"],
        group1_name="Non-Craving",
        group2_name="Craving",
        filter_stimulation=False,
        timeline_band_center=None,
    )


def _scripted_curves(hemi: str) -> dict:
    """Stand-in for the (median, ci_lo, ci_hi, n) tuples returned by the
    real service. Content irrelevant to these tests — just identifiable."""
    return {"non_craving": ("median", "lo", "hi", 5), "craving": ("median", "lo", "hi", 5)}


def _scripted_bands(hemi: str) -> dict:
    """Stand-in for the band-comparison dict returned by the real service."""
    return {"Delta": f"band-result-{hemi}"}


# ---------------------------------------------------------------------------
# 1. Signal carrier surface
# ---------------------------------------------------------------------------


def test_signals_carrier_exposes_all_six_signals():
    for name in ("progress", "partial_psd", "partial_band",
                "finished", "error", "cancelled"):
        attr = getattr(_SnapshotsPsdWorkerSignals, name)
        assert isinstance(attr, Signal), f"{name} should be a Signal"


# ---------------------------------------------------------------------------
# 2. Successful run — full payload + per-hemi emission order
# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    def test_finished_contains_all_four_payload_keys(
        self, worker, mock_service,
    ):
        mock_service.get_psd_curves_for_groups.side_effect = (
            lambda **kwargs: _scripted_curves(kwargs["hemisphere"])
        )
        mock_service.analyze_group_comparison.side_effect = (
            lambda **kwargs: _scripted_bands(kwargs["hemisphere"])
        )

        payloads: list[dict] = []
        worker.signals.finished.connect(lambda p: payloads.append(p))
        worker.run()

        assert len(payloads) == 1
        payload = payloads[0]
        assert set(payload.keys()) == {
            "psd_left", "psd_right", "band_left", "band_right",
        }
        # Per-hemi service responses end up in the right slots.
        assert payload["band_left"] == _scripted_bands("LEFT")
        assert payload["band_right"] == _scripted_bands("RIGHT")

    def test_partial_psd_then_partial_band_per_hemisphere_in_order(
        self, worker, mock_service,
    ):
        mock_service.get_psd_curves_for_groups.side_effect = (
            lambda **kwargs: _scripted_curves(kwargs["hemisphere"])
        )
        mock_service.analyze_group_comparison.side_effect = (
            lambda **kwargs: _scripted_bands(kwargs["hemisphere"])
        )

        sequence: list[tuple[str, str]] = []
        worker.signals.partial_psd.connect(
            lambda hemi, _curves: sequence.append(("psd", hemi))
        )
        worker.signals.partial_band.connect(
            lambda hemi, _bands: sequence.append(("band", hemi))
        )

        worker.run()

        assert sequence == [
            ("psd", "LEFT"), ("band", "LEFT"),
            ("psd", "RIGHT"), ("band", "RIGHT"),
        ]

    def test_progress_climbs_to_1000_total_at_completion(
        self, worker, mock_service,
    ):
        mock_service.get_psd_curves_for_groups.side_effect = (
            lambda **kwargs: _scripted_curves(kwargs["hemisphere"])
        )
        mock_service.analyze_group_comparison.side_effect = (
            lambda **kwargs: _scripted_bands(kwargs["hemisphere"])
        )

        progress: list[tuple[int, int, str]] = []
        worker.signals.progress.connect(
            lambda d, t, lbl: progress.append((d, t, lbl))
        )
        worker.run()

        assert progress, "Expected at least one progress emission"
        # All emits use total=1000 (worker's monotone bar).
        assert all(t == 1000 for _, t, _ in progress)
        # The first emission is at 0; the last reaches 1000.
        assert progress[0][0] == 0
        assert progress[-1][0] == 1000


# ---------------------------------------------------------------------------
# 3. Cancellation paths
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_cancel_before_run_short_circuits_to_cancelled(
        self, worker, mock_service,
    ):
        # Service stubbed to a successful path — should still NOT be called.
        mock_service.get_psd_curves_for_groups.return_value = _scripted_curves("LEFT")
        mock_service.analyze_group_comparison.return_value = _scripted_bands("LEFT")

        events: list[str] = []
        worker.signals.cancelled.connect(lambda: events.append("cancelled"))
        worker.signals.finished.connect(lambda _p: events.append("finished"))
        worker.signals.error.connect(lambda _m: events.append("error"))

        worker.cancel()
        worker.run()

        assert events == ["cancelled"]
        # Service was never invoked because the run short-circuited.
        mock_service.get_psd_curves_for_groups.assert_not_called()
        mock_service.analyze_group_comparison.assert_not_called()

    def test_service_cancellation_emits_cancelled_only(
        self, worker, mock_service,
    ):
        mock_service.get_psd_curves_for_groups.side_effect = (
            OperationCancelledException("aborted in curves")
        )

        events: list[str] = []
        worker.signals.cancelled.connect(lambda: events.append("cancelled"))
        worker.signals.finished.connect(lambda _p: events.append("finished"))
        worker.signals.error.connect(lambda _m: events.append("error"))

        worker.run()

        assert events == ["cancelled"]

    def test_cancel_between_hemispheres_skips_right(
        self, worker, mock_service,
    ):
        """Cancel that flips True after LEFT must halt before RIGHT runs."""
        # Make the LEFT calls work; flip cancel as soon as LEFT finishes its
        # band stage (which is what worker.run sees just before checking
        # _is_cancelled before RIGHT).
        def left_curves(**kwargs):
            return _scripted_curves(kwargs["hemisphere"])

        def left_bands(**kwargs):
            # After LEFT's band stage finishes, request cancellation.
            worker.cancel()
            return _scripted_bands(kwargs["hemisphere"])

        mock_service.get_psd_curves_for_groups.side_effect = left_curves
        mock_service.analyze_group_comparison.side_effect = left_bands

        events: list[str] = []
        worker.signals.cancelled.connect(lambda: events.append("cancelled"))
        worker.signals.finished.connect(lambda _p: events.append("finished"))
        worker.signals.error.connect(lambda _m: events.append("error"))

        worker.run()

        assert events == ["cancelled"]
        # LEFT ran exactly once; RIGHT never ran.
        assert mock_service.get_psd_curves_for_groups.call_count == 1
        assert mock_service.analyze_group_comparison.call_count == 1
        called_hemis = [
            call.kwargs["hemisphere"]
            for call in mock_service.get_psd_curves_for_groups.call_args_list
        ]
        assert called_hemis == ["LEFT"]


# ---------------------------------------------------------------------------
# 4. Error path — generic exception
# ---------------------------------------------------------------------------


def test_generic_exception_emits_error(worker, mock_service):
    mock_service.get_psd_curves_for_groups.side_effect = RuntimeError("boom")

    events: list[tuple[str, str]] = []
    worker.signals.cancelled.connect(lambda: events.append(("cancelled", "")))
    worker.signals.finished.connect(lambda _p: events.append(("finished", "")))
    worker.signals.error.connect(lambda m: events.append(("error", m)))

    worker.run()

    assert len(events) == 1
    kind, msg = events[0]
    assert kind == "error"
    assert "boom" in msg


# ---------------------------------------------------------------------------
# 5. Progress callback plumbing — service callback emits 'progress' signal
# ---------------------------------------------------------------------------


def test_service_progress_callback_drives_worker_progress_signal(
    worker, mock_service,
):
    """When the service invokes ``progress_callback(d, t, label)``, the
    worker re-emits a remapped value on the 0..1000 bar with a hemi-prefixed
    label."""

    def driving_curves(**kwargs):
        cb = kwargs["progress_callback"]
        cb(0, 2, "PSD curve: non-craving")
        cb(1, 2, "PSD curve: craving")
        return _scripted_curves(kwargs["hemisphere"])

    def driving_bands(**kwargs):
        cb = kwargs["progress_callback"]
        cb(0, 5, "Computing Non-Craving powers")
        return _scripted_bands(kwargs["hemisphere"])

    mock_service.get_psd_curves_for_groups.side_effect = driving_curves
    mock_service.analyze_group_comparison.side_effect = driving_bands

    captured: list[tuple[int, int, str]] = []
    worker.signals.progress.connect(
        lambda d, t, lbl: captured.append((d, t, lbl))
    )
    worker.run()

    # All emissions use total=1000.
    assert all(t == 1000 for _, t, _ in captured)
    # Every captured progress value must be in 0..1000 monotone-ish.
    values = [d for d, _, _ in captured]
    assert all(0 <= d <= 1000 for d in values)
    # At least one Electrode 1- and one Electrode 2-prefixed label arrived.
    assert any(lbl.startswith("Electrode 1") for _, _, lbl in captured)
    assert any(lbl.startswith("Electrode 2") for _, _, lbl in captured)
