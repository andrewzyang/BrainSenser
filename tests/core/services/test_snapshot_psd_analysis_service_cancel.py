"""
Tests for the cooperative cancel + progress hooks added to
:class:`SnapshotPsdAnalysisService`.

Two methods accept the new hooks:

* ``analyze_group_comparison`` — checkpoints between group-power computations
  and at the top of the per-band loop.
* ``get_psd_curves_for_groups`` — checkpoints between the two group curve
  computations.

Tests use a real ``SnapshotPsdDataset`` built from synthetic PSD events (mirrors
the pattern in ``test_snapshot_psd_analysis_service.py``) so the service runs
end-to-end without numerical mocking. Hooks are then exercised at each
checkpoint and the call counts / raised exceptions are asserted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

import numpy as np
import pytest

from src.core.services import snapshot_psd_analysis_service as analysis_module
from src.core.services.effect_size_calculator import EffectSizeCalculator
from src.core.services.snapshot_psd_analysis_service import (
    OperationCancelledException,
    SnapshotPsdAnalysisService,
)
from src.domain.models import EffectSizeType
from src.domain.psd_models import SnapshotPsdDataset, SnapshotPsdEvent


# ---------------------------------------------------------------------------
# Fixtures (mirror test_snapshot_psd_analysis_service.py)
# ---------------------------------------------------------------------------


class _StubEffectSizePreference:
    """Sidestep Qt dependency in the EffectSizePreference singleton."""

    def __init__(self, effect_type: EffectSizeType = EffectSizeType.COHENS_D):
        self._effect_size_type = effect_type

    def get_effect_size(self) -> EffectSizeType:
        return self._effect_size_type


@pytest.fixture
def service(monkeypatch) -> SnapshotPsdAnalysisService:
    monkeypatch.setattr(
        analysis_module, "EffectSizePreference",
        lambda: _StubEffectSizePreference(),
    )
    return SnapshotPsdAnalysisService(effect_size_calculator=EffectSizeCalculator())


def _make_event(event_name: str, offset: float, freq_axis: np.ndarray) -> SnapshotPsdEvent:
    base_psd = np.linspace(2.0 + offset, 12.0 + offset, freq_axis.size)
    artifact_mask = np.zeros(freq_axis.shape, dtype=bool)
    return SnapshotPsdEvent(
        timestamp=datetime(2025, 1, 1) + timedelta(minutes=int(offset * 10)),
        event_name=event_name,
        patient_event_id=f"{event_name}_{offset}",
        frequency_axis=freq_axis,
        psd_left=base_psd,
        psd_right=None,
        artifact_mask_left=artifact_mask,
        artifact_mask_right=None,
        hemisphere="LEFT",
    )


@pytest.fixture
def dataset() -> SnapshotPsdDataset:
    freq_axis = np.linspace(1.0, 30.0, 60).round(2)
    events: List[SnapshotPsdEvent] = []
    for offset in [0.0, 0.2, 0.4]:
        events.append(_make_event("Craving", offset, freq_axis))
        events.append(_make_event("Neutral", -0.6 - offset, freq_axis))
    return SnapshotPsdDataset(
        patient_id="patient-cancel-tests",
        events=events,
        frequency_axis=freq_axis,
    )


# ---------------------------------------------------------------------------
# 1. analyze_group_comparison — progress + cancel
# ---------------------------------------------------------------------------


class TestAnalyzeGroupComparisonHooks:
    def test_no_callbacks_preserves_existing_behavior(self, service, dataset):
        results = service.analyze_group_comparison(
            dataset=dataset,
            group1_event_types=["Craving"],
            group2_event_types=["Neutral"],
            group1_name="Craving",
            group2_name="Neutral",
            hemisphere="LEFT",
            filter_stimulation=False,
        )
        assert results, "Default-None hooks should preserve old behavior"

    def test_progress_callback_fires_per_phase(self, service, dataset):
        seen: List[Tuple[int, int, str]] = []
        service.analyze_group_comparison(
            dataset=dataset,
            group1_event_types=["Craving"],
            group2_event_types=["Neutral"],
            group1_name="Craving",
            group2_name="Neutral",
            hemisphere="LEFT",
            filter_stimulation=False,
            progress_callback=lambda d, t, lbl: seen.append((d, t, lbl)),
        )

        # Expected sequence (n_bands = 5: Delta..Gamma_low):
        #   (0, 7, "Computing Craving powers")
        #   (1, 7, "Computing Neutral powers")
        #   (2, 7, <band 0 display name>)
        #   ...
        #   (6, 7, <band 4 display name>)
        #   (7, 7, "Bands complete")
        assert len(seen) >= 3, f"Expected at least 3 emits, got {seen}"
        assert seen[0][0] == 0
        assert "Craving" in seen[0][2]
        # Group2 emit lands second, at idx 1.
        assert seen[1] == (1, seen[1][1], "Computing Neutral powers")
        # Final emit equals total/total.
        last = seen[-1]
        assert last[0] == last[1]
        assert last[2] == "Bands complete"
        # Total work units monotonically equal across all emits.
        total_units = seen[0][1]
        assert all(t == total_units for _, t, _ in seen)

    def test_cancel_check_raises_before_group1_powers(self, service, dataset):
        with pytest.raises(OperationCancelledException):
            service.analyze_group_comparison(
                dataset=dataset,
                group1_event_types=["Craving"],
                group2_event_types=["Neutral"],
                group1_name="Craving",
                group2_name="Neutral",
                hemisphere="LEFT",
                filter_stimulation=False,
                cancel_check=lambda: True,
            )

    def test_cancel_check_raises_after_group1_before_group2(self, service, dataset):
        """Cancel-check that flips after the first 'Computing X' emit must
        halt before group2 powers compute, before any band comparison."""
        progress_seen: List[Tuple[int, int, str]] = []
        cancel_after = {"flipped": False}

        def cb(d: int, t: int, lbl: str) -> None:
            progress_seen.append((d, t, lbl))
            # Flip the cancel flag the moment we observe the first emit (which
            # happens BEFORE group1 powers are computed). The next checkpoint
            # is between group1 and group2, where cancel_check is consulted.
            if d == 0:
                cancel_after["flipped"] = True

        with pytest.raises(OperationCancelledException):
            service.analyze_group_comparison(
                dataset=dataset,
                group1_event_types=["Craving"],
                group2_event_types=["Neutral"],
                group1_name="Craving",
                group2_name="Neutral",
                hemisphere="LEFT",
                filter_stimulation=False,
                progress_callback=cb,
                cancel_check=lambda: cancel_after["flipped"],
            )
        # Only the first emit reached us — the second 'Computing X' emit
        # cannot fire because cancel raises in between.
        assert len(progress_seen) == 1
        assert progress_seen[0][0] == 0


# ---------------------------------------------------------------------------
# 2. get_psd_curves_for_groups — progress + cancel
# ---------------------------------------------------------------------------


class TestGetPsdCurvesForGroupsHooks:
    @pytest.mark.slow
    def test_no_callbacks_preserves_existing_behavior(self, service, dataset):
        out = service.get_psd_curves_for_groups(
            dataset=dataset, hemisphere="LEFT",
            group1_event_types=["Neutral"], group2_event_types=["Craving"],
        )
        assert "non_craving" in out and "craving" in out

    @pytest.mark.slow
    def test_progress_callback_fires_three_times(self, service, dataset):
        seen: List[Tuple[int, int, str]] = []
        service.get_psd_curves_for_groups(
            dataset=dataset, hemisphere="LEFT",
            group1_event_types=["Neutral"], group2_event_types=["Craving"],
            progress_callback=lambda d, t, lbl: seen.append((d, t, lbl)),
        )
        assert seen == [
            (0, 2, "PSD curve: non-craving"),
            (1, 2, "PSD curve: craving"),
            (2, 2, "PSD curves complete"),
        ]

    def test_cancel_check_raises_before_first_group(self, service, dataset):
        with pytest.raises(OperationCancelledException):
            service.get_psd_curves_for_groups(
                dataset=dataset, hemisphere="LEFT",
                group1_event_types=["Neutral"], group2_event_types=["Craving"],
                cancel_check=lambda: True,
            )

    def test_cancel_check_raises_between_groups(self, service, dataset):
        """Flip cancel-check after the first emit; expect raise before group2."""
        cancel_after = {"flipped": False}

        def cb(d: int, t: int, lbl: str) -> None:
            if d == 0:
                cancel_after["flipped"] = True

        with pytest.raises(OperationCancelledException):
            service.get_psd_curves_for_groups(
                dataset=dataset, hemisphere="LEFT",
                group1_event_types=["Neutral"], group2_event_types=["Craving"],
                progress_callback=cb,
                cancel_check=lambda: cancel_after["flipped"],
            )
