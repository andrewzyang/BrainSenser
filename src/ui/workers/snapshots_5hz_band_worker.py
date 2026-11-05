"""
Snapshots5HzBandWorker - Background worker for the snapshots 5 Hz Band AUC-profile analysis.

This worker runs ``SnapshotMlAnalysisService.analyze_both_hemispheres`` off the
GUI thread using ``QRunnable`` and ``QThreadPool`` so the per-band held-out LOO
AUC + bootstrap CI + max-stat FWER pipeline (~10-20 s for two hemispheres) does
not block the UI.

Per the project threading guidelines and ``docs/plans/snapshots_ml_page_plan.md``
(Performance / threading section):
- Uses QRunnable with QThreadPool for CPU-intensive analysis
- Never updates UI from background thread - uses signals instead
- Cooperative cancellation via ``cancel_check`` callback into the service
- Progress emitted at every Nth permutation chunk via ``progress_callback``
- All result objects crossing the thread boundary are frozen dataclasses

Author: iEEG BrainSense Development Team
Last Updated: 2026-05-08
"""

import logging
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.services.snapshot_ml_analysis_service import (
    AucProfileResult,
    OperationCancelledException,
    SnapshotMlAnalysisService,
    SEED,
)
from src.ui.electrode_labels import electrode_label_for_hemisphere


class Snapshots5HzBandWorkerSignals(QObject):
    """
    Signals for Snapshots5HzBandWorker.

    QRunnable can't have signals directly, so we use a separate QObject.
    All signals are emitted from the worker thread and must be connected
    to UI updates on the main thread; Qt's auto-detected QueuedConnection
    handles cross-thread delivery.
    """

    # Progress signal (done count, total count, status label)
    progress = Signal(int, int, str)  # done, total, label

    # Success signal (per-hemisphere results dict)
    finished = Signal(object)  # dict[str, AucProfileResult]

    # Error signal (error_message)
    error = Signal(str)

    # Cancellation acknowledgement (emitted only if cancel succeeded)
    cancelled = Signal()


class Snapshots5HzBandWorker(QRunnable):
    """
    Background worker for the snapshots 5 Hz Band per-band LOO AUC analysis.

    Runs ``SnapshotMlAnalysisService.analyze_both_hemispheres`` off the GUI
    thread for both hemispheres in a single submission. The pure service
    handles all numerical work; this worker is the only Qt-aware compute
    layer and owns no UI references.

    Architecture:
    - Runs in QThreadPool background thread
    - Uses SnapshotMlAnalysisService for actual analysis
    - Emits signals for progress, completion, cancellation, and errors
    - Cooperative cancellation: ``cancel()`` flips ``_is_cancelled``; the
      service polls a ``cancel_check`` callback at safe points (between
      permutation chunks) and may raise ``OperationCancelledException``
    - Never accesses UI components directly

    Example usage:
        >>> # In ViewModel
        >>> worker = Snapshots5HzBandWorker(
        ...     service, crav_L, nc_L, crav_R, nc_R, freqs_hz,
        ...     n_perm=10_000, n_boot=2_000, seed=42,
        ... )
        >>> worker.signals.progress.connect(self._on_ml_progress)
        >>> worker.signals.finished.connect(self._on_ml_finished)
        >>> worker.signals.cancelled.connect(self._on_ml_cancelled)
        >>> worker.signals.error.connect(self._on_ml_error)
        >>> QThreadPool.globalInstance().start(worker)

    Signals:
        progress(int, int, str): (done, total, label) permutation progress
        finished(object): Success with dict[str, AucProfileResult]
        cancelled(): Emitted if cancellation succeeded (no finished follows)
        error(str): Error message if analysis fails
    """

    def __init__(
        self,
        service: SnapshotMlAnalysisService,
        crav_L: Optional[np.ndarray],
        nc_L: Optional[np.ndarray],
        crav_R: Optional[np.ndarray],
        nc_R: Optional[np.ndarray],
        freqs_hz: np.ndarray,
        *,
        n_perm: int = 10_000,
        n_boot: int = 2_000,
        seed: int = SEED,
    ) -> None:
        """
        Initialize Snapshots5HzBandWorker.

        Args:
            service: SnapshotMlAnalysisService instance for analysis
            crav_L: Left-hemisphere craving PSD matrix (n_crav, n_freq) raw
                µV²/Hz, or None if hemisphere unavailable
            nc_L: Left-hemisphere non-craving PSD matrix (n_nc, n_freq) raw
                µV²/Hz, or None if hemisphere unavailable
            crav_R: Right-hemisphere craving PSD matrix (n_crav, n_freq) raw
                µV²/Hz, or None if hemisphere unavailable
            nc_R: Right-hemisphere non-craving PSD matrix (n_nc, n_freq) raw
                µV²/Hz, or None if hemisphere unavailable
            freqs_hz: PSD bin centers, full spectrum (n_freq,)
            n_perm: Number of label permutations for FWER null
            n_boot: Number of bootstrap resamples for CI
            seed: RNG seed for reproducibility
        """
        super().__init__()
        self._service = service
        self._crav_L = crav_L
        self._nc_L = nc_L
        self._crav_R = crav_R
        self._nc_R = nc_R
        self._freqs_hz = freqs_hz
        self._n_perm = n_perm
        self._n_boot = n_boot
        self._seed = seed
        self._signals = Snapshots5HzBandWorkerSignals()
        self.logger = logging.getLogger(__name__)

        # Worker state
        self._is_cancelled = False

        # Build the list of hemispheres that will actually run (matches the
        # service's own None-check policy). The list lets the progress
        # callback offset its per-hemisphere counts onto a single combined
        # bar of length ``n_hemispheres * n_perm`` — and on unilateral
        # implants the bar climbs 0..100 % once, never stranding at 50 %.
        self._hemispheres_to_run: list[str] = []
        if self._crav_L is not None and self._nc_L is not None:
            self._hemispheres_to_run.append("L")
        if self._crav_R is not None and self._nc_R is not None:
            self._hemispheres_to_run.append("R")

        # Set lazily by the hemisphere announcement callback. Default to the
        # first hemisphere that will run so any pre-callback emission is
        # correctly placed on the bar.
        self._current_hemisphere: str = (
            self._hemispheres_to_run[0] if self._hemispheres_to_run else "L"
        )

    @property
    def signals(self) -> Snapshots5HzBandWorkerSignals:
        """
        Return the signals carrier QObject.

        The carrier is created in the thread that called ``__init__``
        (typically the GUI thread, where the ViewModel constructs the worker).
        Signals emitted from ``run()`` (worker thread) reach GUI-thread slots
        via Qt's auto-detected QueuedConnection.
        """
        return self._signals

    def cancel(self) -> None:
        """
        Request cancellation of the analysis.

        Cooperative cancellation: the worker exposes ``_is_cancelled`` to the
        service via the ``cancel_check`` callback installed in ``run()``. The
        service polls this between permutation chunks and may raise
        ``OperationCancelledException``. This method is idempotent and safe to
        call from any thread (a plain bool assignment is atomic in CPython).
        """
        self.logger.info("Cancellation requested for snapshots 5 Hz Band analysis")
        self._is_cancelled = True

    @Slot()
    def run(self) -> None:
        """
        Execute the analysis task in a background thread.

        This method runs in a QThreadPool worker thread. Never call UI methods
        directly - use signals instead. On cancellation, emits ``cancelled``
        and returns without emitting ``finished``.
        """
        try:
            self.logger.info(
                f"Starting async snapshots 5 Hz Band analysis: "
                f"n_perm={self._n_perm}, n_boot={self._n_boot}, seed={self._seed}"
            )

            # Emit initial progress (0/n_perm, total per hemisphere chunk)
            self._signals.progress.emit(0, self._n_perm, "Starting analysis...")

            if self._is_cancelled:
                self.logger.info("Analysis cancelled before service call")
                self._signals.cancelled.emit()
                return

            # Hemisphere announcement callback: the service fires this just
            # before each ``analyze_hemisphere`` call. We use it to switch
            # the progress remap between hemispheres.
            def hemisphere_label_callback(hemi: str) -> None:
                self._current_hemisphere = hemi

            # Progress callback bridges per-hemisphere ``(done, total)`` onto
            # the combined ``n_hemispheres * total`` scale. The offset is the
            # current hemisphere's *position* in the run order, so a unilateral
            # implant climbs 0..total once instead of stranding at 50 %.
            hemi_count = max(1, len(self._hemispheres_to_run))
            hemi_position = {
                hemi: idx for idx, hemi in enumerate(self._hemispheres_to_run)
            }

            def progress_callback(done: int, total: int) -> None:
                idx = hemi_position.get(self._current_hemisphere, 0)
                offset = idx * total
                label_prefix = electrode_label_for_hemisphere(
                    self._current_hemisphere
                )
                self._signals.progress.emit(
                    offset + done,
                    hemi_count * total,
                    f"{label_prefix} — perm {done}/{total}",
                )

            # Cancel check callback exposes worker state to the service
            def cancel_check() -> bool:
                return self._is_cancelled

            # Run the analysis (this is the slow operation)
            result_dict: dict[str, AucProfileResult] = (
                self._service.analyze_both_hemispheres(
                    self._crav_L,
                    self._nc_L,
                    self._crav_R,
                    self._nc_R,
                    self._freqs_hz,
                    n_perm=self._n_perm,
                    n_boot=self._n_boot,
                    seed=self._seed,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                    hemisphere_label_callback=hemisphere_label_callback,
                )
            )

            # Cancellation may have been requested during the call but not
            # raised (e.g. cancel arrived between the last chunk and return).
            if self._is_cancelled:
                self.logger.info("Analysis cancelled after service returned")
                self._signals.cancelled.emit()
                return

            # Emit success signal with per-hemisphere results
            hemispheres = sorted(result_dict.keys())
            self.logger.info(
                f"Successfully completed snapshots 5 Hz Band analysis: "
                f"hemispheres={hemispheres}"
            )
            self._signals.finished.emit(result_dict)

        except OperationCancelledException:
            self.logger.info("Snapshots 5 Hz Band analysis cancelled by service")
            self._signals.cancelled.emit()
            return

        except Exception as e:
            error_msg = f"Failed to run snapshots 5 Hz Band analysis: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._signals.error.emit(error_msg)
