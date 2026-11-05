"""
TimelineLfpThresholdViewModel — coordinates the Timeline → LFP Threshold page.

QObject ViewModel that owns the active worker, an in-memory result cache,
and the patient-data lifecycle. Mirrors the discipline of
:class:`Snapshots5HzBandViewModel`: no ``CANCELLING`` state. Replacing a worker
disconnects every signal on the previous one, nulls the active reference,
and submits the new worker immediately. The old worker drains in the
background and its emissions are dropped.

Imports zero Qt widgets — only ``QObject`` + signals + the worker.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, FrozenSet, List, Optional, Tuple

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal

from src.core.services.timeline_threshold_ml_service import (
    DEFAULT_WINDOW_MINUTES,
    HemiResult,
    InsufficientResult,
    ThresholdMlResult,
    TimelineThresholdMlService,
)
from src.ui.workers.timeline_lfp_threshold_worker import TimelineLfpThresholdWorker

logger = logging.getLogger(__name__)


CacheKey = Tuple[
    str,
    FrozenSet[str],
    FrozenSet[str],
    Tuple[int, str, int, str],   # data fingerprint
    int,                          # n_perm
    int,                          # n_boot
    int,                          # seed
    int,                          # window_minutes
]


class TimelineLfpThresholdViewModel(QObject):
    """ViewModel for the Timeline → LFP Threshold page.

    Owns:
      * the current patient ID and the available event-type list
      * the per-hemisphere :class:`HemiResult` results
      * an in-memory cache keyed by ``(patient_id, frozenset(g1),
        frozenset(g2), data_fingerprint)``
      * the single in-flight worker

    Cleared on :attr:`data_loaded` (covers fresh imports / `is_outlier`
    re-flags so we never serve stale results).
    """

    # Lifecycle / forwarding
    patient_changed             = Signal(str)
    data_loaded                 = Signal()
    progress_updated            = Signal(int, str)
    hemisphere_ready            = Signal(str)
    analysis_complete           = Signal()
    analysis_started            = Signal()
    analysis_refresh_required   = Signal(str)
    error_occurred              = Signal(str)

    def __init__(
        self,
        service: TimelineThresholdMlService,
        snapshot_repository,
        timeline_repository,
        app_viewmodel=None,
    ) -> None:
        super().__init__()
        self._service = service
        self._snapshot_repo = snapshot_repository
        self._timeline_repo = timeline_repository
        self._app_viewmodel = app_viewmodel

        self._patient_id: Optional[str] = None
        self._available_event_types: List[str] = []
        self._available_event_counts: Dict[str, int] = {}
        self._results: Dict[str, HemiResult] = {}
        self._current_g1: List[str] = []
        self._current_g2: List[str] = []
        self._current_n_perm: int = 1_000
        self._current_n_boot: int = 2_000
        self._current_seed: int = 42
        self._current_window_minutes: int = DEFAULT_WINDOW_MINUTES

        self._cache: Dict[CacheKey, Dict[str, HemiResult]] = {}

        self._active_worker: Optional[TimelineLfpThresholdWorker] = None
        self._worker_signal_connections: List[Tuple[Signal, object]] = []

        # Forward AppViewModel signals (so the View only listens to one VM).
        if app_viewmodel is not None:
            try:
                app_viewmodel.data_loaded.connect(self._on_app_data_loaded)
            except AttributeError:
                # AppViewModel may not have a data_loaded signal in test
                # contexts; degrade gracefully.
                pass

    # ---- Public read API -------------------------------------------------

    def patient_id(self) -> Optional[str]:
        return self._patient_id

    def current_results(self) -> Dict[str, HemiResult]:
        return dict(self._results)

    def available_event_types(self) -> List[str]:
        return list(self._available_event_types)

    def available_event_counts(self) -> Dict[str, int]:
        return dict(self._available_event_counts)

    # ---- Public write API ------------------------------------------------

    def load_patient_data(self, patient_id: str) -> None:
        """Switch to a new patient. Disconnects/cancels any in-flight worker
        BEFORE mutating state so a late ``finished`` from the previous
        patient cannot stomp the new one."""
        try:
            self._disconnect_and_cancel_active_worker()

            self._patient_id = patient_id
            self._results = {}
            self._current_g1 = []
            self._current_g2 = []
            # Clear cache on patient change too: a different patient
            # produces different keys, but the data fingerprint may also
            # have shifted (e.g. fresh import) and we want the next call
            # to be a clean miss.
            self._cache.clear()
            self.patient_changed.emit(patient_id)

            # Populate the event-type selector with counts. Each event has
            # TWO snapshot rows in the DB (one per hemisphere) at the same
            # timestamp, so a naive row-loop double-counts. Dedup by
            # (event_name, timestamp) so the dropdown shows the unique-event
            # count consumed by `extract_offset_matrix_ext` (which keys on
            # `s.timestamp`).
            event_counts: Dict[str, int] = defaultdict(int)
            seen_event_keys: set = set()
            try:
                snapshots = self._snapshot_repo.get_by_time_range(
                    patient_id=patient_id,
                    patient_events_only=True,
                    limit=100_000,
                )
                for s in snapshots:
                    name = getattr(s, "event_name", None)
                    ts = getattr(s, "timestamp", None)
                    if not name or ts is None:
                        continue
                    key = (name, ts)
                    if key in seen_event_keys:
                        continue
                    seen_event_keys.add(key)
                    event_counts[name] += 1
            except Exception as exc:  # pragma: no cover - data-layer specific
                logger.warning(
                    "Failed to enumerate event names for %s: %s", patient_id, exc,
                )
            self._available_event_counts = dict(event_counts)
            self._available_event_types = sorted(event_counts.keys())

            self.data_loaded.emit()
        except Exception as exc:
            logger.error("Failed to load patient data: %s", exc, exc_info=True)
            self.error_occurred.emit(f"Failed to load data: {exc}")

    def clear_view(self) -> None:
        """Cancel any active worker, drop results, and announce the empty
        state to the View."""
        self._disconnect_and_cancel_active_worker()
        self._patient_id = None
        self._available_event_types = []
        self._available_event_counts = {}
        self._results = {}
        self._current_g1 = []
        self._current_g2 = []
        self._cache.clear()
        self.patient_changed.emit("")

    def analyze_event_groups(
        self,
        group1_event_names: List[str],
        group2_event_names: List[str],
        *,
        n_perm: int = 1_000,
        n_boot: int = 2_000,
        seed: int = 42,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
    ) -> None:
        """Submit a worker for the threshold pipeline. Cache hits short-
        circuit synchronously; misses cancel any in-flight worker, install
        a fresh one, and start it on the global ``QThreadPool``."""
        if not self._patient_id:
            self.error_occurred.emit("No patient loaded")
            return

        g1 = list(group1_event_names or [])
        g2 = list(group2_event_names or [])
        if not g1 or not g2:
            self.error_occurred.emit(
                "Both event groups must have at least one event type"
            )
            return

        cache_key = self._make_cache_key(
            g1, g2, n_perm, n_boot, seed, window_minutes,
        )
        if cache_key in self._cache:
            self._results = dict(self._cache[cache_key])
            self._current_g1 = g1
            self._current_g2 = g2
            self._current_n_perm = int(n_perm)
            self._current_n_boot = int(n_boot)
            self._current_seed = int(seed)
            self._current_window_minutes = int(window_minutes)
            for hemi in self._results:
                self.hemisphere_ready.emit(hemi)
            # Cache hit: no analysis_started → the popup never shows for an
            # instant cached result. The View hides defensively on complete.
            self.analysis_complete.emit()
            return

        self._disconnect_and_cancel_active_worker()
        self._results = {}
        self._current_g1 = g1
        self._current_g2 = g2
        self._current_n_perm = int(n_perm)
        self._current_n_boot = int(n_boot)
        self._current_seed = int(seed)
        self._current_window_minutes = int(window_minutes)

        worker = TimelineLfpThresholdWorker(
            self._service,
            self._patient_id,
            g1, g2,
            n_perm=n_perm,
            n_boot=n_boot,
            seed=seed,
            window_minutes=window_minutes,
        )
        self._connect_worker_signals(worker)
        self._active_worker = worker

        self.analysis_started.emit()
        self.progress_updated.emit(0, "Starting threshold analysis…")
        QThreadPool.globalInstance().start(worker)

    def cancel(self) -> None:
        """Cancel the in-flight analysis (if any) and announce completion
        immediately so the UI re-enables Compare and clears the progress
        bar without waiting for the cancelled worker to drain."""
        if self._active_worker is None:
            return
        logger.info("User-requested cancel of timeline ML analysis")
        self._disconnect_and_cancel_active_worker()
        self.analysis_complete.emit()

    # ---- Private worker plumbing ----------------------------------------

    def _disconnect_and_cancel_active_worker(self) -> None:
        if self._active_worker is None:
            return
        # Cancel cooperatively so the serial loops fall through quickly.
        self._active_worker.cancel()
        for sig, slot in self._worker_signal_connections:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._worker_signal_connections.clear()
        self._active_worker = None

    def _connect_worker_signals(self, worker: TimelineLfpThresholdWorker) -> None:
        sig = worker.signals
        pairs: List[Tuple[Signal, object]] = [
            (sig.progress, self._on_worker_progress),
            (sig.partial_result, self._on_worker_partial_result),
            (sig.finished, self._on_worker_finished),
            (sig.error, self._on_worker_error),
            (sig.cancelled, self._on_worker_cancelled),
        ]
        for s, slot in pairs:
            s.connect(slot, Qt.QueuedConnection)
            self._worker_signal_connections.append((s, slot))

    # ---- Worker signal handlers ----------------------------------------

    def _on_worker_progress(self, done: int, total: int, label: str) -> None:
        if total <= 0:
            percent = 0
        else:
            percent = int(round(100.0 * done / total))
        percent = max(0, min(100, percent))
        self.progress_updated.emit(percent, label)

    def _on_worker_partial_result(self, hemi: str, result) -> None:
        self._results[hemi] = result
        self.hemisphere_ready.emit(hemi)

    def _on_worker_finished(self, results) -> None:
        if isinstance(results, dict):
            self._results = dict(results)
            cache_key = self._make_cache_key(
                self._current_g1,
                self._current_g2,
                self._current_n_perm,
                self._current_n_boot,
                self._current_seed,
                self._current_window_minutes,
            )
            self._cache[cache_key] = dict(results)
        self._active_worker = None
        self._worker_signal_connections.clear()
        self.analysis_complete.emit()

    def _on_worker_error(self, msg: str) -> None:
        logger.error("Timeline LFP Threshold worker error: %s", msg)
        self._active_worker = None
        self._worker_signal_connections.clear()
        self.error_occurred.emit(msg)
        self.analysis_complete.emit()

    def _on_worker_cancelled(self) -> None:
        logger.info("Timeline LFP Threshold worker cancelled")
        self._active_worker = None
        self._worker_signal_connections.clear()
        self.analysis_complete.emit()

    # ---- Cache key construction -----------------------------------------

    def _make_cache_key(
        self,
        g1: List[str],
        g2: List[str],
        n_perm: int,
        n_boot: int,
        seed: int,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
    ) -> CacheKey:
        fp = self._data_fingerprint()
        return (
            self._patient_id or "",
            frozenset(g1),
            frozenset(g2),
            fp,
            int(n_perm),
            int(n_boot),
            int(seed),
            int(window_minutes),
        )

    def _data_fingerprint(self) -> Tuple[int, str, int, str]:
        """Cheap O(1) data fingerprint: counts + max timestamps from each
        repo. The View clears the cache on `data_loaded` from
        :class:`AppViewModel`, so the fingerprint is a defence in depth."""

        def _count_and_max(repo):
            try:
                # Both repositories expose an inexpensive aggregate path.
                count_fn = getattr(repo, "count_for_patient", None)
                max_fn = getattr(repo, "max_timestamp_for_patient", None)
                pid = self._patient_id
                if count_fn and max_fn and pid:
                    return int(count_fn(pid)), str(max_fn(pid))
            except Exception:  # pragma: no cover - data-layer specific
                pass
            return 0, ""

        sn_count, sn_max = _count_and_max(self._snapshot_repo)
        tl_count, tl_max = _count_and_max(self._timeline_repo)
        return sn_count, sn_max, tl_count, tl_max

    # ---- AppViewModel forwarding ----------------------------------------

    def _on_app_data_loaded(self) -> None:
        """Triggered by :class:`AppViewModel`'s ``data_loaded`` signal —
        fresh imports and ``is_outlier`` re-flags invalidate every cached
        result. Drop them all."""
        self._cache.clear()
