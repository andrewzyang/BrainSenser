"""
Snapshots5HzBandViewModel for coordinating Snapshots 5 Hz Band analysis page.

This ViewModel implements the MVVM pattern, managing state and coordinating
between the UI and the per-band held-out LOO + max-stat FWER pipeline used to
populate manuscript Figure 2 d-f. Long-running analysis is dispatched to a
background ``QRunnable`` worker via ``QThreadPool``; cancellation and signal
disconnection of any prior worker are performed on every patient change,
clear, or new analyze call.

Mirrors the public-API surface of :class:`SnapshotsPsdViewModel` so the view
code is structurally identical between the Classical Stats and Machine
Learning pages. The only payload-level differences are the new
``auc_profiles_ready`` and ``band_table_ready`` signals, which replace
``psd_curves_ready`` / ``band_statistics_ready`` from the PSD VM.

Author: iEEG BrainSense Development Team
Last Updated: 2026-05-08
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, Qt, QThreadPool, Signal

from src.core.services.snapshot_ml_analysis_service import (
    AucProfileResult,
    SnapshotMlAnalysisService,
    SEED,
)
from src.domain.psd_models import SnapshotPsdDataset
from src.infrastructure.psd_data_loader import load_snapshot_psd_dataset
from src.infrastructure.repositories import SnapshotRepository
from src.ui.workers.snapshots_5hz_band_worker import Snapshots5HzBandWorker

logger = logging.getLogger(__name__)


class Snapshots5HzBandViewModel(QObject):
    """
    ViewModel for Snapshots 5 Hz Band analysis page.

    Responsibilities:
    - Load patient snapshot PSD data (mirrors :class:`SnapshotsPsdViewModel`)
    - Hold per-hemisphere :class:`AucProfileResult` from the ML pipeline
    - Dispatch the per-band LOO + FWER analysis to a worker off the GUI
      thread so the ~10-20 s permutation null does not freeze the UI
    - Cancel and disconnect any in-flight worker on patient change, clear,
      or new analyze call (preventing stale ``finished``/``error`` slots
      from firing after a context switch)
    - Emit signals for UI updates following the same contract as the PSD
      VM, swapping the PSD-specific ``psd_curves_ready`` /
      ``band_statistics_ready`` for the ML-specific ``auc_profiles_ready``
      / ``band_table_ready``

    Signals:
        patient_changed: Emitted when patient selection changes (patient_id)
        data_loaded: Emitted when patient data is loaded (n_events)
        analysis_complete: Emitted when both-hemisphere analysis completes
        auc_profiles_ready: Emitted after AUC-profile results are stored
        band_table_ready: Emitted after band-table data is stored
        error_occurred: Emitted when an error occurs (error_message)
        progress_updated: Emitted during long operations (percentage, message)
    """

    # Signals for UI updates
    patient_changed = Signal(str)           # patient_id (or "" on clear)
    data_loaded = Signal(int)               # n_events
    analysis_complete = Signal()            # No args
    analysis_started = Signal()             # analysis run begins (drives popup show)
    auc_profiles_ready = Signal()           # No args (replaces psd_curves_ready)
    band_table_ready = Signal()             # No args (replaces band_statistics_ready)
    error_occurred = Signal(str)            # error_message
    progress_updated = Signal(int, str)     # (percentage, message)

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        ml_service: SnapshotMlAnalysisService,
    ) -> None:
        """
        Initialize Snapshots5HzBandViewModel.

        Parameters
        ----------
        snapshot_repo : SnapshotRepository
            Repository for loading raw snapshot records. Mirrors the
            PSD VM's data-access dependency.
        ml_service : SnapshotMlAnalysisService
            Pure (Qt-free) per-band LOO + FWER analysis service. The VM
            constructs a fresh worker for each ``analyze_event_groups``
            call and hands it this service.
        """
        super().__init__()

        # Dependencies (DI)
        self._snapshot_repo = snapshot_repo
        self._ml_service = ml_service

        # State
        self._current_patient_id: Optional[str] = None
        self._dataset: Optional[SnapshotPsdDataset] = None
        self._left_result: Optional[AucProfileResult] = None
        self._right_result: Optional[AucProfileResult] = None

        # Worker lifecycle tracking. ``_active_worker`` is the single
        # in-flight worker, if any. ``_worker_signal_connections`` records
        # ``(signal, slot)`` pairs so we can disconnect by pair (avoiding
        # accidentally disconnecting unrelated signals on the same carrier).
        self._active_worker: Optional[Snapshots5HzBandWorker] = None
        self._worker_signal_connections: List[Tuple[Signal, object]] = []

    # ========================================================================
    # Public Properties - State Access
    # ========================================================================

    @property
    def current_patient_id(self) -> Optional[str]:
        """Current patient identifier, or ``None`` if no patient loaded."""
        return self._current_patient_id

    @property
    def has_left_data(self) -> bool:
        """Whether the loaded dataset has any left-hemisphere PSD data."""
        if self._dataset is None:
            return False
        return any(event.has_left_data for event in self._dataset.events)

    @property
    def has_right_data(self) -> bool:
        """Whether the loaded dataset has any right-hemisphere PSD data."""
        if self._dataset is None:
            return False
        return any(event.has_right_data for event in self._dataset.events)

    @property
    def event_counts(self) -> Dict[str, int]:
        """Per-event-type counts for the loaded dataset (empty dict if none)."""
        if self._dataset is None:
            return {}
        return self._dataset.get_event_counts()

    def get_left_result(self) -> Optional[AucProfileResult]:
        """Return the left-hemisphere AUC-profile result, or ``None``."""
        return self._left_result

    def get_right_result(self) -> Optional[AucProfileResult]:
        """Return the right-hemisphere AUC-profile result, or ``None``."""
        return self._right_result

    def has_analysis_results(self) -> bool:
        """
        Whether per-hemisphere analysis results are available for export.

        Returns
        -------
        bool
            True if at least one hemisphere's :class:`AucProfileResult`
            is currently stored on the VM.
        """
        return self._left_result is not None or self._right_result is not None

    # ========================================================================
    # Public Methods - Data Loading
    # ========================================================================

    def load_patient_data(self, patient_id: str) -> None:
        """
        Load snapshot PSD data for a patient.

        Mirrors :meth:`SnapshotsPsdViewModel.load_patient_data` 1:1 for the
        data-loading mechanics so both pages have identical event-count and
        event-type semantics for the same patient.

        Parameters
        ----------
        patient_id : str
            Patient ID to load.

        Emits
        -----
        patient_changed : When patient selection changes
        progress_updated : During loading
        data_loaded : When loading completes with event count
        error_occurred : If loading fails
        """
        try:
            logger.info(f"Loading snapshot ML data for patient: {patient_id}")

            # Cancel + disconnect any in-flight worker BEFORE we mutate
            # state. A late-arriving ``finished`` from a previous patient
            # would otherwise stomp the new patient's results.
            self._disconnect_and_cancel_active_worker()

            self._current_patient_id = patient_id
            self.patient_changed.emit(patient_id)

            # Clear previous data + analysis results
            self._dataset = None
            self._left_result = None
            self._right_result = None

            # Load raw snapshot records
            records = self._snapshot_repo.get_by_patient(
                patient_id=patient_id,
                limit=10000
            )

            # Convert to PSD dataset
            self._dataset = load_snapshot_psd_dataset(patient_id, records)

            n_events = len(self._dataset.events)
            logger.info(
                f"Loaded {n_events} PSD events for {patient_id}: "
                f"{self._dataset.get_event_counts()}"
            )

            self.data_loaded.emit(n_events)

        except Exception as e:
            logger.error(f"Failed to load patient data: {e}")
            self.error_occurred.emit(f"Failed to load data: {str(e)}")

    def clear_patient_data(self) -> None:
        """
        Clear current patient data, analysis results, and worker state.

        Emits
        -----
        patient_changed : with empty string to signal cleared selection
        """
        self._disconnect_and_cancel_active_worker()
        self._current_patient_id = None
        self._dataset = None
        self._left_result = None
        self._right_result = None
        self.patient_changed.emit("")
        logger.info("ML patient data cleared")

    # ========================================================================
    # Public Methods - Analysis
    # ========================================================================

    def analyze_event_groups(
        self,
        group1_event_types: List[str],
        group2_event_types: List[str],
        *,
        n_perm: int = 10_000,
        n_boot: int = 2_000,
        seed: int = SEED,
    ) -> None:
        """
        Dispatch the per-band LOO + FWER pipeline for both hemispheres.

        Builds raw PSD matrices for ``group1_event_types`` (treated as the
        craving group, label 1 in the analysis core) and
        ``group2_event_types`` (non-craving, label 0) for each hemisphere,
        then submits a fresh :class:`Snapshots5HzBandWorker` to the global
        ``QThreadPool``. Any in-flight worker is cancelled and signal-
        disconnected before the new submission so stale ``finished`` /
        ``error`` slots cannot fire on the next worker's results.

        Parameters
        ----------
        group1_event_types : list[str]
            Event types comprising the "craving" group (label 1).
        group2_event_types : list[str]
            Event types comprising the "non-craving" group (label 0).
        n_perm : int
            Label permutations for the FWER null. Default 10,000 (matches
            the manuscript locked value).
        n_boot : int
            Bootstrap resamples for CI computation. Default 2,000 (matches
            the manuscript ML CI value, NOT the 5,000 used by the PSD page).
        seed : int
            RNG seed for reproducibility. Defaults to ``SEED`` (42, the
            manuscript-canonical value) so a user's Compare reproduces the
            published CI / FWER conditions; LOO AUC and modal band are
            seed-free regardless.

        Emits
        -----
        progress_updated : Initial 0% with a "Starting…" label
        error_occurred : If pre-checks fail (no patient loaded, no events
            for the requested groups in either hemisphere)

        Worker-driven signals (later, on the GUI thread):
        progress_updated, auc_profiles_ready, band_table_ready,
        analysis_complete, error_occurred
        """
        # Pre-checks before touching the worker.
        if self._dataset is None:
            self.error_occurred.emit("No patient loaded")
            return

        # Build per-hemisphere PSD matrices. ``get_psd_matrix`` uses the
        # PSD-domain hemisphere strings ("LEFT"/"RIGHT") while the ML
        # service expects "L"/"R" — translation happens in the worker
        # arguments below.
        #
        # Panel convention: Group 1 (Jade) = non-craving = label 0,
        # Group 2 (Rose) = craving = label 1. The helper is
        # group-position-agnostic; the labelling lives in this caller.
        #
        # Build BEFORE cancelling/wiping prior results so that a doomed
        # selection (e.g. user clicked Compare with stale groups) does not
        # erase the currently-displayed analysis on the way to surfacing
        # the error dialog.
        nc_L, crav_L = self._build_hemisphere_matrices(
            "LEFT", group1_event_types, group2_event_types
        )
        nc_R, crav_R = self._build_hemisphere_matrices(
            "RIGHT", group1_event_types, group2_event_types
        )

        if crav_L is None and crav_R is None:
            self.error_occurred.emit(
                "No events found for selected groups in either hemisphere"
            )
            return

        # Pre-checks passed — now it is safe to discard prior worker + results.
        # Cancel + disconnect any in-flight worker so a stale finished/error
        # cannot apply its results on top of the new run.
        self._disconnect_and_cancel_active_worker()

        # Forget any previously stored results — a new analyze call should
        # not display a mix of new + stale hemispheres.
        self._left_result = None
        self._right_result = None

        freqs_hz = np.asarray(self._dataset.frequency_axis, dtype=float)

        # Construct + wire the worker.
        worker = Snapshots5HzBandWorker(
            self._ml_service,
            crav_L,
            nc_L,
            crav_R,
            nc_R,
            freqs_hz,
            n_perm=n_perm,
            n_boot=n_boot,
            seed=seed,
        )
        self._connect_worker_signals(worker)
        self._active_worker = worker

        self.analysis_started.emit()
        self.progress_updated.emit(0, "Starting per-band LOO analysis…")

        QThreadPool.globalInstance().start(worker)

    def cancel_analysis(self) -> None:
        """
        Cancel any in-flight analysis.

        Idempotent: a no-op if no worker is currently running.
        """
        if self._active_worker is None:
            return
        logger.info("User-requested cancellation of 5 Hz Band analysis")
        self._disconnect_and_cancel_active_worker()

    # ========================================================================
    # Private Helpers - Worker Lifecycle
    # ========================================================================

    def _disconnect_and_cancel_active_worker(self) -> None:
        """
        Cancel and signal-disconnect any in-flight worker.

        Critical for correctness: without disconnecting the carrier's
        signals from this VM's slots, a late ``finished`` (cancellation
        sometimes loses the race with the last permutation chunk) could
        write stale results into the VM after a context switch. We
        disconnect by ``(signal, slot)`` pair so we don't touch other
        connections that happen to share the same carrier.
        """
        if self._active_worker is None:
            return

        # Request cooperative cancellation. The worker polls
        # ``_is_cancelled`` between permutation chunks; depending on
        # timing the worker may still emit ``cancelled``, ``finished``,
        # or ``error`` — disconnection ensures none of those reach our
        # slots.
        self._active_worker.cancel()

        for sig, slot in self._worker_signal_connections:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                # Already disconnected, or slot no longer connected — both
                # are safe to ignore. Qt will raise RuntimeError if the
                # underlying C++ object is gone, TypeError if the slot
                # signature is mismatched (shouldn't happen here).
                pass
        self._worker_signal_connections.clear()
        self._active_worker = None

    def _connect_worker_signals(self, worker: Snapshots5HzBandWorker) -> None:
        """
        Connect a fresh worker's signals to this VM's slots.

        Uses :data:`Qt.QueuedConnection` explicitly so the worker-thread
        emissions are queued onto the GUI thread's event loop. Auto-detected
        connection would do the same thing here (the carrier was created on
        the GUI thread, the emitter is the worker thread), but making it
        explicit removes any ambiguity for future readers.
        """
        sig = worker.signals
        pairs: List[Tuple[Signal, object]] = [
            (sig.progress, self._on_worker_progress),
            (sig.finished, self._on_worker_finished),
            (sig.error, self._on_worker_error),
            (sig.cancelled, self._on_worker_cancelled),
        ]
        for s, slot in pairs:
            s.connect(slot, Qt.QueuedConnection)
            self._worker_signal_connections.append((s, slot))

    # ========================================================================
    # Private Helpers - Data Preparation
    # ========================================================================

    def _build_hemisphere_matrices(
        self,
        hemisphere: str,
        group1_event_types: List[str],
        group2_event_types: List[str],
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Build raw PSD matrices for one hemisphere, ordered ``(group1, group2)``.

        The helper is **group-position-agnostic** — it returns the matrices in
        the same order as the input event-type lists, leaving the
        non-craving/craving labelling (and therefore the analysis y-vector) to
        the caller. ``get_psd_matrix`` returns artefact-NaN'd raw
        ``(n_events, n_freqs)`` µV²/Hz which is exactly what the ML service
        expects (it does its own envelope masking + per-row NaN handling).

        Returns ``(None, None)`` when either group has zero rows for this
        hemisphere — signalling the worker (and caller) that this side should
        be skipped.
        """
        if self._dataset is None:
            return None, None

        group1_matrix, _ = self._dataset.get_psd_matrix(
            group1_event_types, hemisphere
        )
        group2_matrix, _ = self._dataset.get_psd_matrix(
            group2_event_types, hemisphere
        )

        if group1_matrix.size == 0 or group2_matrix.size == 0:
            return None, None
        return group1_matrix, group2_matrix

    # ========================================================================
    # Private Slots - Worker Signal Handlers
    # ========================================================================

    def _on_worker_progress(self, done: int, total: int, label: str) -> None:
        """
        Bridge worker ``(done, total, label)`` to VM ``(percent, label)``.
        """
        percent = int(round(100.0 * done / total)) if total else 0
        # Clamp to [0, 100] in case the worker emits done > total at boundaries.
        percent = max(0, min(100, percent))
        self.progress_updated.emit(percent, label)

    def _on_worker_finished(self, results: object) -> None:
        """
        Store per-hemisphere :class:`AucProfileResult` and emit readiness
        signals in deterministic order: ``auc_profiles_ready`` (plot
        consumers), then ``band_table_ready`` (table consumers), then
        ``analysis_complete`` (high-level "done" hook for status bar etc.).

        An empty results dict (every event dropped during preprocessing in
        both hemispheres) is treated as an error rather than a silent
        "done" — otherwise the user sees the progress bar fill, a "complete"
        status, and an empty plot with no explanation.
        """
        if not results:
            self._left_result = None
            self._right_result = None
            self._active_worker = None
            self._worker_signal_connections.clear()
            self.error_occurred.emit(
                "No data survived preprocessing — analysis aborted."
            )
            return

        if not isinstance(results, dict):
            logger.error(
                f"Worker emitted unexpected results type: {type(results)!r}"
            )
            self._left_result = None
            self._right_result = None
        else:
            self._left_result = results.get("L")
            self._right_result = results.get("R")
            logger.info(
                f"5 Hz Band analysis complete: hemispheres="
                f"{sorted(results.keys())}"
            )

        # The QRunnable will be garbage-collected after run() returns, so
        # connections naturally die with it; we still clear our tracking
        # list for tidiness and to prevent ``cancel_analysis`` from
        # double-disconnecting a now-finished worker.
        self._active_worker = None
        self._worker_signal_connections.clear()

        self.auc_profiles_ready.emit()
        self.band_table_ready.emit()
        self.analysis_complete.emit()

    def _on_worker_error(self, msg: str) -> None:
        """
        Forward worker errors to ``error_occurred`` and clear worker state.
        """
        logger.error(f"ML worker reported error: {msg}")
        self._active_worker = None
        self._worker_signal_connections.clear()
        self.error_occurred.emit(msg)

    def _on_worker_cancelled(self) -> None:
        """
        Acknowledge a cancellation. Cancellation is user-driven and not an
        error condition — we log at INFO and do **not** emit
        ``error_occurred``.
        """
        logger.info("ML worker cancellation acknowledged")
        self._active_worker = None
        self._worker_signal_connections.clear()
