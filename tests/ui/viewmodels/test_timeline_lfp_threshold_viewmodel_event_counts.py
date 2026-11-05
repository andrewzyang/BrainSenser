"""Event-count dedup correctness for :class:`TimelineLfpThresholdViewModel`.

Each event lives in the DB as two ``SnapshotRecord`` rows — one per
hemisphere — sharing the same ``(event_name, timestamp)``. A naive
row-by-row count double-counts and inflates the dropdown labels
relative to what the analysis actually consumes (``run_hemisphere``
keys per timestamp). This test pins the dedup so the bug cannot
silently regress.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List
from unittest.mock import MagicMock

import pytest

from src.core.models.snapshot_record import SnapshotRecord
from src.ui.viewmodels.timeline_lfp_threshold_viewmodel import TimelineLfpThresholdViewModel


def _record(ts: datetime, event_name: str, hemisphere: str) -> SnapshotRecord:
    return SnapshotRecord(
        timestamp=ts,
        event_name=event_name,
        hemisphere=hemisphere,
        patient_event=1,
        source_file="fake.json",
        data_hash=f"{event_name}-{ts.isoformat()}-{hemisphere}",
    )


def _paired_rows(spec: List[tuple[str, int]]) -> List[SnapshotRecord]:
    """Build paired Left+Right rows for ``spec`` = [(event_name, n), ...].

    All events spaced 1 hour apart so timestamps are unique per (name, n).
    """
    out: List[SnapshotRecord] = []
    cursor = datetime(2026, 5, 1, 12, 0, 0)
    for name, n in spec:
        for _ in range(n):
            out.append(_record(cursor, name, "Left"))
            out.append(_record(cursor, name, "Right"))
            cursor = cursor + timedelta(hours=1)
    return out


@pytest.fixture
def viewmodel():
    """Build a VM with mocked deps and a known patient_id."""
    service = MagicMock()
    snapshot_repo = MagicMock()
    timeline_repo = MagicMock()
    snapshot_repo.count_for_patient.return_value = 0
    snapshot_repo.max_timestamp_for_patient.return_value = ""
    timeline_repo.count_for_patient.return_value = 0
    timeline_repo.max_timestamp_for_patient.return_value = ""
    return TimelineLfpThresholdViewModel(service, snapshot_repo, timeline_repo)


class TestEventCountsDedup:
    def test_paired_hemispheres_collapse_to_one_event(self, viewmodel):
        """3 Craving events × 2 hemispheres = 6 rows in the DB, but the
        dropdown must show n=3."""
        snapshots = _paired_rows([("Craving", 3), ("Neutral", 5)])
        viewmodel._snapshot_repo.get_by_time_range.return_value = snapshots

        viewmodel.load_patient_data("PT_001")

        counts = viewmodel.available_event_counts()
        assert counts == {"Craving": 3, "Neutral": 5}, \
            f"row-loop double-count regressed; got {counts}"

    def test_matches_analysis_unique_timestamp_count(self, viewmodel):
        """The dropdown count must equal the number of unique timestamps
        per event_name — i.e. the count `extract_offset_matrix_ext` will
        actually consume after `by_ts[s.timestamp]` aggregation."""
        spec = [
            ("Craving", 3),
            ("Drinking", 36),
            ("Neutral", 41),
            ("Happy", 53),
        ]
        snapshots = _paired_rows(spec)
        viewmodel._snapshot_repo.get_by_time_range.return_value = snapshots

        viewmodel.load_patient_data("PT_001")

        counts = viewmodel.available_event_counts()
        assert counts == dict(spec)

    def test_single_hemisphere_only_still_counts_correctly(self, viewmodel):
        """Defensive: if only one hemisphere is present (no paired row),
        the count must not change. Ensures the dedup is keyed on
        (name, timestamp), not on row presence."""
        cursor = datetime(2026, 5, 1, 12, 0, 0)
        snapshots = [
            _record(cursor + timedelta(hours=0), "Craving", "Left"),
            _record(cursor + timedelta(hours=1), "Craving", "Left"),
            _record(cursor + timedelta(hours=2), "Craving", "Right"),
        ]
        viewmodel._snapshot_repo.get_by_time_range.return_value = snapshots

        viewmodel.load_patient_data("PT_001")

        assert viewmodel.available_event_counts() == {"Craving": 3}

    def test_skips_rows_with_missing_event_name_or_timestamp(self, viewmodel):
        """Defensive: rows with no event_name or no timestamp must be
        skipped (no KeyError, no None key)."""
        cursor = datetime(2026, 5, 1, 12, 0, 0)
        snapshots = [
            _record(cursor, "Craving", "Left"),
            _record(cursor, "Craving", "Right"),
            # Row with empty event_name — should be skipped.
            SnapshotRecord(
                timestamp=cursor + timedelta(hours=1),
                event_name=None,
                hemisphere="Left",
                patient_event=1,
                source_file="fake.json",
                data_hash="empty",
            ),
        ]
        viewmodel._snapshot_repo.get_by_time_range.return_value = snapshots

        viewmodel.load_patient_data("PT_001")

        assert viewmodel.available_event_counts() == {"Craving": 1}
