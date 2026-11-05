"""
Cache-key correctness for TimelineLfpThresholdViewModel.

The cache key must include n_perm, n_boot, seed, AND window_minutes so
that toggling any of the dropdowns / spinboxes invalidates a
previously-cached result. Without this, the user could change a
selector and silently get back stale numbers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ui.viewmodels.timeline_lfp_threshold_viewmodel import TimelineLfpThresholdViewModel


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
    vm = TimelineLfpThresholdViewModel(service, snapshot_repo, timeline_repo)
    vm._patient_id = "PT_001"
    return vm


class TestMakeCacheKey:
    def test_same_params_produce_same_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        assert k1 == k2

    def test_different_n_perm_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=5000, n_boot=2000, seed=42,
        )
        assert k1 != k2

    def test_different_n_boot_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=5000, seed=42,
        )
        assert k1 != k2

    def test_different_seed_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=43,
        )
        assert k1 != k2

    def test_different_window_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
            window_minutes=20,
        )
        k2 = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
            window_minutes=30,
        )
        assert k1 != k2

    def test_default_window_matches_explicit_20(self, viewmodel):
        k_default = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
        )
        k_explicit = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1000, n_boot=2000, seed=42,
            window_minutes=20,
        )
        assert k_default == k_explicit

    def test_group_order_invariant(self, viewmodel):
        # frozensets, not lists, drive the cache identity for groups.
        k1 = viewmodel._make_cache_key(
            ["a", "b"], ["c"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["b", "a"], ["c"], n_perm=1000, n_boot=2000, seed=42,
        )
        assert k1 == k2

    def test_different_event_selections_produce_different_cache_keys(self, viewmodel):
        # Position-driven labels: changing the membership of either group
        # must invalidate the cache so the user cannot silently get back
        # results for a different selection.
        k1 = viewmodel._make_cache_key(
            ["Craving"], ["Neutral"], n_perm=1000, n_boot=2000, seed=42,
        )
        k2 = viewmodel._make_cache_key(
            ["Drinking"], ["Neutral"], n_perm=1000, n_boot=2000, seed=42,
        )
        k3 = viewmodel._make_cache_key(
            ["Craving"], ["Happy"], n_perm=1000, n_boot=2000, seed=42,
        )
        assert k1 != k2
        assert k1 != k3
        assert k2 != k3


class TestAnalyzeCacheBehavior:
    """End-to-end check via analyze_event_groups: cache hit must depend on
    n_perm/n_boot. We patch QThreadPool so no worker actually starts."""

    def test_default_run_then_same_run_is_cache_hit(self, viewmodel):
        # Pre-populate the cache with a sentinel result for the default key.
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ) as MockPool:
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
            )
            MockPool.globalInstance.assert_not_called()

        # Cached results were copied onto _results.
        assert viewmodel._results == {"Left": "RESULT", "Right": "RESULT"}

    def test_changed_n_perm_misses_cache_and_starts_worker(self, viewmodel):
        # Cache the default-key result.
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        # Now request with a different n_perm — should be a miss.
        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ) as MockPool:
            mock_pool_inst = MockPool.globalInstance.return_value
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=5_000, n_boot=2_000, seed=42,
            )
            assert mock_pool_inst.start.called, (
                "Different n_perm should bypass the cache and submit a "
                "fresh worker."
            )

    def test_changed_n_boot_misses_cache_and_starts_worker(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ) as MockPool:
            mock_pool_inst = MockPool.globalInstance.return_value
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=5_000, seed=42,
            )
            assert mock_pool_inst.start.called

    def test_changed_window_misses_cache_and_starts_worker(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
            window_minutes=20,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ) as MockPool:
            mock_pool_inst = MockPool.globalInstance.return_value
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
                window_minutes=30,
            )
            assert mock_pool_inst.start.called, (
                "Different window_minutes should bypass the cache and "
                "submit a fresh worker."
            )

    def test_cache_writeback_uses_current_perm_boot_window(self, viewmodel):
        # Drive a finished result through the worker callback path with
        # non-default perm/boot/window and confirm the cache key reflects
        # them.
        viewmodel._current_g1 = ["a"]
        viewmodel._current_g2 = ["b"]
        viewmodel._current_n_perm = 5_000
        viewmodel._current_n_boot = 5_000
        viewmodel._current_seed = 42
        viewmodel._current_window_minutes = 40

        viewmodel._on_worker_finished({"Left": "R", "Right": "R"})

        expected_key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=5_000, n_boot=5_000, seed=42,
            window_minutes=40,
        )
        assert expected_key in viewmodel._cache
        # The default-key bucket must NOT be populated by this run.
        default_key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
            window_minutes=20,
        )
        assert default_key not in viewmodel._cache


class TestAnalysisStartedSignal:
    """``analysis_started`` drives the popup. It must fire on a cache MISS
    (a real worker run) but NEVER on a cache HIT (an instant cached result
    shows no popup)."""

    def test_cache_miss_emits_analysis_started_before_progress(self, viewmodel):
        events: list = []
        viewmodel.analysis_started.connect(lambda: events.append("started"))
        viewmodel.progress_updated.connect(
            lambda p, m: events.append(f"progress:{p}")
        )

        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ):
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
            )

        assert events and events[0] == "started", events
        assert "progress:0" in events

    def test_cache_hit_does_not_emit_analysis_started(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        started: list = []
        viewmodel.analysis_started.connect(lambda: started.append(True))

        with patch(
            "src.ui.viewmodels.timeline_lfp_threshold_viewmodel.QThreadPool"
        ):
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=2_000, seed=42,
            )

        assert started == [], "cache hit must not emit analysis_started"
