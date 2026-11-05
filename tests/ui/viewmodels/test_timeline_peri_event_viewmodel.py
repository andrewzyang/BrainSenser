"""
analysis_started contract for TimelinePeriEventViewModel.

Mirrors the Timeline LFP Threshold VM: ``analysis_started`` drives the shared
progress popup, so it must fire on a cache MISS (a real worker run) but NEVER
on a cache HIT (an instant cached result shows no popup). Data loading must
likewise emit no ``progress_updated`` / ``analysis_started``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Signal

from src.ui.viewmodels.timeline_peri_event_viewmodel import (
    TimelinePeriEventViewModel,
)


@pytest.fixture
def viewmodel():
    """Build a VM with mocked deps and a stable patient_id + fingerprint."""
    service = MagicMock()
    snapshot_repo = MagicMock()
    timeline_repo = MagicMock()
    snapshot_repo.count_for_patient.return_value = 100
    snapshot_repo.max_timestamp_for_patient.return_value = "2026-05-08T00:00:00"
    timeline_repo.count_for_patient.return_value = 200
    timeline_repo.max_timestamp_for_patient.return_value = "2026-05-08T00:00:00"
    vm = TimelinePeriEventViewModel(service, snapshot_repo, timeline_repo)
    vm._patient_id = "PT_001"
    return vm


class TestAnalysisStartedSignal:
    def test_defines_analysis_started_signal(self):
        attr = getattr(TimelinePeriEventViewModel, "analysis_started")
        assert isinstance(attr, Signal)

    def test_cache_miss_emits_analysis_started_before_progress(self, viewmodel):
        events: list = []
        viewmodel.analysis_started.connect(lambda: events.append("started"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}")
        )

        with patch(
            "src.ui.viewmodels.timeline_peri_event_viewmodel.QThreadPool"
        ):
            viewmodel.analyze_event_groups(["a"], ["b"])

        assert events and events[0] == "started", events
        assert "progress:0" in events

    def test_cache_hit_does_not_emit_analysis_started(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42, window_minutes=20,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        started: list = []
        viewmodel.analysis_started.connect(lambda: started.append(True))

        with patch(
            "src.ui.viewmodels.timeline_peri_event_viewmodel.QThreadPool"
        ):
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
                window_minutes=20,
            )

        assert started == [], "cache hit must not emit analysis_started"
