"""
TimelineLfpThresholdWorker — background worker for the Timeline → LFP Threshold pipeline.

Runs ``TimelineThresholdMlService`` for both hemispheres sequentially, emits
per-hemisphere ``partial_result`` between calls, and composes a stage-weighted
**monotone** 0→1000 progress bar across the whole analysis.

Mirrors :mod:`src.ui.workers.snapshots_5hz_band_worker`. Cooperative cancellation
via the service's ``cancel_check`` hook; the inner serial loops poll the
flag every iteration (perm) or every 50 resamples (bootstraps).
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.services.timeline_threshold_ml_service import (
    DEFAULT_WINDOW_MINUTES,
    HemiResult,
    InsufficientResult,
    ThresholdMlResult,
    TimelineThresholdMlService,
)
from src.ui.electrode_labels import electrode_label


# Stage weights composing the per-hemisphere 0..1.0 progress fraction.
# Sum to 1.0; cost estimates pinned in `docs/plans/timeline_lfp_threshold_page/04_worker.md`.
STAGE_WEIGHTS = {
    "Extracting events":         0.05,
    "Fitting LR + LOO":          0.05,
    "Bootstrapping AUC CI":      0.10,
    "Bootstrapping threshold":   0.15,
    "Permuting":                 0.65,
}
_STAGE_ORDER: List[str] = [
    "Extracting events",
    "Fitting LR + LOO",
    "Bootstrapping AUC CI",
    "Bootstrapping threshold",
    "Permuting",
]


class _TimelineLfpThresholdWorkerSignals(QObject):
    """Signals carrier for :class:`TimelineLfpThresholdWorker`.

    QRunnable cannot emit signals directly, so we use a separate QObject
    constructed in the GUI thread (where the ViewModel builds the worker).
    Cross-thread delivery uses Qt's auto-detected QueuedConnection.
    """

    # (global_done, global_total, label)
    progress = Signal(int, int, str)
    # (hemisphere, HemiResult) — emitted exactly once per hemisphere
    partial_result = Signal(str, object)
    # dict[str, HemiResult] — exactly one of {finished, error, cancelled}
    finished = Signal(dict)
    error = Signal(str)
    cancelled = Signal()


class TimelineLfpThresholdWorker(QRunnable):
    """Background worker for the Timeline → LFP Threshold pipeline.

    Owns hemisphere ordering: calls ``service.analyze_hemisphere`` twice
    (Left then Right) and emits :attr:`signals.partial_result` between
    calls so the View can render each side as it lands instead of a blank
    wait. Composes per-stage progress into a single 0..1000 monotone scale
    (each hemisphere occupies 0..500; the second is offset by 500).
    """

    def __init__(
        self,
        service: TimelineThresholdMlService,
        patient_id: str,
        group1_event_names: List[str],
        group2_event_names: List[str],
        *,
        n_perm: int = 1_000,
        n_boot: int = 2_000,
        seed: int = 42,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
    ) -> None:
        super().__init__()
        self._service = service
        self._patient_id = patient_id
        self._group1 = list(group1_event_names or [])
        self._group2 = list(group2_event_names or [])
        self._n_perm = n_perm
        self._n_boot = n_boot
        self._seed = seed
        self._window_minutes = int(window_minutes)

        self._signals = _TimelineLfpThresholdWorkerSignals()
        self._is_cancelled = False
        # Updated by the bridge below as labels arrive from the service.
        self._current_hemi_index = 0   # 0 = Left, 1 = Right
        self._completed_stage_weight = 0.0
        self._current_stage_label: str = "Extracting events"
        self._current_stage_weight: float = STAGE_WEIGHTS[self._current_stage_label]

        # ETA tracking. Wall-clock baseline is set on the first stage
        # callback (i.e. when work actually begins, not when the worker is
        # constructed).
        self._t0_global: Optional[float] = None

        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------

    @property
    def signals(self) -> _TimelineLfpThresholdWorkerSignals:
        return self._signals

    def cancel(self) -> None:
        """Request cancellation. The service's serial helpers poll the
        flag and raise :class:`CancelledError` from
        :mod:`src.core.analysis.threshold.bulletproof_threshold` on True."""
        self.logger.info("Cancellation requested for timeline ML analysis")
        self._is_cancelled = True

    def _cancel_check(self) -> bool:
        return self._is_cancelled

    # ------------------------------------------------------------------

    def _stage_to_global_done(self, stage_done: int, stage_total: int) -> int:
        """Compose ``(stage_done, stage_total)`` for the current stage and
        hemisphere into the 0..1000 monotone scale."""
        if stage_total <= 0:
            stage_frac = 1.0
        else:
            stage_frac = max(0.0, min(1.0, stage_done / stage_total))
        per_hemi_fraction = (
            self._completed_stage_weight + self._current_stage_weight * stage_frac
        )
        per_hemi_fraction = max(0.0, min(1.0, per_hemi_fraction))
        # Each hemi occupies 0..500 of the 0..1000 scale; the second is offset.
        offset = 500 * self._current_hemi_index
        return int(round(per_hemi_fraction * 500.0)) + offset

    def _on_service_progress(self, stage_done: int, stage_total: int, label: str) -> None:
        """Bridge service-level (stage_done, stage_total, label) → worker
        progress signal on the 0..1000 scale.

        The label switches stage as the service moves through extraction,
        bootstraps, and permutation. Uses the published stage names from
        :data:`STAGE_WEIGHTS`.

        Also computes a rough ETA from elapsed wall-time and the global
        progress fraction, appended to the label as ``" (≈Ns left)"``.
        """
        if label != self._current_stage_label and label in STAGE_WEIGHTS:
            # Advance: previously-current stage is now in the completed set.
            self._completed_stage_weight += self._current_stage_weight
            self._current_stage_label = label
            self._current_stage_weight = STAGE_WEIGHTS[label]

        global_done = self._stage_to_global_done(stage_done, stage_total)
        electrode = electrode_label(self._current_hemi_index)

        if self._t0_global is None:
            self._t0_global = time.monotonic()
        eta_str = self._format_eta(global_done)

        prefixed = f"{electrode} — {label} {stage_done}/{stage_total}{eta_str}"
        self._signals.progress.emit(global_done, 1000, prefixed)

    def _format_eta(self, global_done: int) -> str:
        """Compute a coarse ETA string from elapsed wall-time and the global
        progress fraction. Returns an empty string before useful progress is
        accumulated and once the bar reaches the end."""
        if self._t0_global is None:
            return ""
        if global_done <= 0 or global_done >= 1000:
            return ""
        elapsed = time.monotonic() - self._t0_global
        # Need a minimum of elapsed wall-time AND a non-trivial progress
        # fraction before the rate is reliable.
        if elapsed < 0.5 or global_done < 20:
            return ""
        remaining = elapsed * (1000 - global_done) / global_done
        if remaining < 1.0:
            return ""
        return f" (≈{remaining:.0f} s left)"

    def _reset_for_hemisphere(self, hemi_index: int) -> None:
        self._current_hemi_index = hemi_index
        self._completed_stage_weight = 0.0
        self._current_stage_label = _STAGE_ORDER[0]
        self._current_stage_weight = STAGE_WEIGHTS[self._current_stage_label]

    # ------------------------------------------------------------------

    @Slot()
    def run(self) -> None:
        """Execute the analysis on a worker thread. Emits exactly one of
        :attr:`signals.finished`, :attr:`signals.error`, or
        :attr:`signals.cancelled` per invocation."""
        try:
            self.logger.info(
                "Starting timeline ML analysis: patient_id=%s, n_perm=%s, "
                "n_boot=%s, seed=%s, window_minutes=%s",
                self._patient_id, self._n_perm, self._n_boot, self._seed,
                self._window_minutes,
            )

            # Initial 0% emission so the UI flips to the running state.
            self._signals.progress.emit(
                0, 1000, f"{electrode_label(0)} — Extracting events"
            )

            if self._is_cancelled:
                self._signals.cancelled.emit()
                return

            results: dict = {}

            for hemi_index, hemi in enumerate(("Left", "Right")):
                self._reset_for_hemisphere(hemi_index)

                if self._is_cancelled:
                    self._signals.cancelled.emit()
                    return

                hemi_result: HemiResult = self._service.analyze_hemisphere(
                    self._patient_id,
                    hemi,
                    self._group1,
                    self._group2,
                    n_perm=self._n_perm,
                    n_boot=self._n_boot,
                    seed=self._seed,
                    window_minutes=self._window_minutes,
                    progress_callback=self._on_service_progress,
                    cancel_check=self._cancel_check,
                )

                if self._is_cancelled:
                    self._signals.cancelled.emit()
                    return

                results[hemi] = hemi_result
                self._signals.partial_result.emit(hemi, hemi_result)

                # Bring the bar to the end of this hemisphere's slot
                # regardless of which stage emitted last (extraction-only
                # paths and InsufficientResult fast-paths skip later stages).
                terminal = 500 * (hemi_index + 1)
                self._signals.progress.emit(
                    terminal, 1000, f"{electrode_label(hemi_index)} — done"
                )

            # Final monotone tick at 1000 even if it duplicates the last
            # per-hemisphere tick — guarantees the UI sees a definitive 100%.
            self._signals.progress.emit(1000, 1000, "Done")
            self._signals.finished.emit(results)

        except _cancelled_error_type():
            self.logger.info("Timeline LFP Threshold analysis cancelled by service")
            self._signals.cancelled.emit()
        except Exception as exc:  # pragma: no cover - integration path
            msg = f"Failed to run timeline ML analysis: {exc}"
            self.logger.error(msg, exc_info=True)
            self._signals.error.emit(msg)


def _cancelled_error_type():
    """Lazy resolver for the `bulletproof_threshold.CancelledError` class.

    Imported lazily so the worker module can be imported without dragging
    `bulletproof_threshold` into the GUI-thread import chain. The actual
    exception only fires from a worker thread, after the service is in
    flight.
    """
    from src.core.analysis.threshold.bulletproof_threshold import CancelledError
    return CancelledError
