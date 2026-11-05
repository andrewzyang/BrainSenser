"""ViewModel tests for TimelinePeriEventViewModel.

Covers cache-key correctness (n_perm / n_boot / seed / window all participate),
end-to-end cache hit/miss via ``analyze_event_groups`` (QThreadPool patched so
no worker starts), cancel, and the worker-finished cache write-back. Mirrors
``test_timeline_lfp_threshold_viewmodel_cache.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.services.timeline_peri_event_service import (
    DEFAULT_N_BOOT,
    DEFAULT_N_PERM,
    DEFAULT_WINDOW_MINUTES,
)
from src.ui.viewmodels.timeline_peri_event_viewmodel import (
    TimelinePeriEventViewModel,
)

_VM_MOD = "src.ui.viewmodels.timeline_peri_event_viewmodel"


@pytest.fixture
def viewmodel():
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


class TestMakeCacheKey:
    def test_same_params_produce_same_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42)
        k2 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42)
        assert k1 == k2

    def test_different_n_perm_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42)
        k2 = viewmodel._make_cache_key(["a"], ["b"], 1_000, 5_000, 42)
        assert k1 != k2

    def test_different_seed_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42)
        k2 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 43)
        assert k1 != k2

    def test_different_window_yields_different_key(self, viewmodel):
        k1 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42, 50)
        k2 = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42, 30)
        assert k1 != k2

    def test_default_window_matches_explicit_50(self, viewmodel):
        k_default = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42)
        k_explicit = viewmodel._make_cache_key(["a"], ["b"], 10_000, 5_000, 42, 50)
        assert k_default == k_explicit

    def test_group_order_invariant(self, viewmodel):
        k1 = viewmodel._make_cache_key(["a", "b"], ["c"], 10_000, 5_000, 42)
        k2 = viewmodel._make_cache_key(["b", "a"], ["c"], 10_000, 5_000, 42)
        assert k1 == k2

    def test_different_event_selections_differ(self, viewmodel):
        k1 = viewmodel._make_cache_key(["Craving"], ["Neutral"], 10_000, 5_000, 42)
        k2 = viewmodel._make_cache_key(["Drinking"], ["Neutral"], 10_000, 5_000, 42)
        assert k1 != k2


class TestAnalyzeCacheBehavior:
    def test_cache_hit_does_not_start_worker(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], DEFAULT_N_PERM, DEFAULT_N_BOOT, 42, DEFAULT_WINDOW_MINUTES,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        ready = []
        viewmodel.hemisphere_ready.connect(ready.append)
        complete = []
        viewmodel.analysis_complete.connect(lambda: complete.append(True))

        with patch(f"{_VM_MOD}.QThreadPool") as MockPool:
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=DEFAULT_N_PERM, n_boot=DEFAULT_N_BOOT,
                seed=42, window_minutes=DEFAULT_WINDOW_MINUTES,
            )
            MockPool.globalInstance.assert_not_called()

        assert viewmodel._results == {"Left": "RESULT", "Right": "RESULT"}
        assert set(ready) == {"Left", "Right"}
        assert complete == [True]

    def test_cache_miss_starts_worker(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], DEFAULT_N_PERM, DEFAULT_N_BOOT, 42, DEFAULT_WINDOW_MINUTES,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        with patch(f"{_VM_MOD}.QThreadPool") as MockPool:
            pool = MockPool.globalInstance.return_value
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=1_000, n_boot=DEFAULT_N_BOOT,
                seed=42, window_minutes=DEFAULT_WINDOW_MINUTES,
            )
            assert pool.start.called

    def test_changed_window_misses_cache(self, viewmodel):
        key = viewmodel._make_cache_key(
            ["a"], ["b"], DEFAULT_N_PERM, DEFAULT_N_BOOT, 42, 50,
        )
        viewmodel._cache[key] = {"Left": "RESULT", "Right": "RESULT"}

        with patch(f"{_VM_MOD}.QThreadPool") as MockPool:
            pool = MockPool.globalInstance.return_value
            viewmodel.analyze_event_groups(
                ["a"], ["b"], n_perm=DEFAULT_N_PERM, n_boot=DEFAULT_N_BOOT,
                seed=42, window_minutes=30,
            )
            assert pool.start.called

    def test_empty_group_emits_error_and_no_worker(self, viewmodel):
        errors = []
        viewmodel.error_occurred.connect(errors.append)
        with patch(f"{_VM_MOD}.QThreadPool") as MockPool:
            viewmodel.analyze_event_groups([], ["b"])
            MockPool.globalInstance.assert_not_called()
        assert errors and "at least one" in errors[0]

    def test_cache_writeback_uses_current_params(self, viewmodel):
        viewmodel._current_g1 = ["a"]
        viewmodel._current_g2 = ["b"]
        viewmodel._current_n_perm = 1_000
        viewmodel._current_n_boot = DEFAULT_N_BOOT
        viewmodel._current_seed = 42
        viewmodel._current_window_minutes = 40

        viewmodel._on_worker_finished({"Left": "R", "Right": "R"})

        expected = viewmodel._make_cache_key(
            ["a"], ["b"], 1_000, DEFAULT_N_BOOT, 42, 40,
        )
        assert expected in viewmodel._cache
        default = viewmodel._make_cache_key(
            ["a"], ["b"], DEFAULT_N_PERM, DEFAULT_N_BOOT, 42, DEFAULT_WINDOW_MINUTES,
        )
        assert default not in viewmodel._cache


class TestCancel:
    def test_cancel_emits_complete_and_clears_worker(self, viewmodel):
        worker = MagicMock()
        viewmodel._active_worker = worker
        complete = []
        viewmodel.analysis_complete.connect(lambda: complete.append(True))
        viewmodel.cancel()
        worker.cancel.assert_called_once()
        assert viewmodel._active_worker is None
        assert complete == [True]

    def test_cancel_noop_when_idle(self, viewmodel):
        complete = []
        viewmodel.analysis_complete.connect(lambda: complete.append(True))
        viewmodel.cancel()
        assert complete == []
