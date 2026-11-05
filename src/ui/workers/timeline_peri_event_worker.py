"""TimelinePeriEventWorker — background worker for the Timeline → Peri-Event pipeline.

Runs :class:`TimelinePeriEventService` for both hemispheres sequentially, emits
per-hemisphere ``partial_result`` between calls, and composes a stage-weighted
**monotone** 0→1000 progress bar across the whole analysis.

Mirrors :mod:`src.ui.workers.timeline_lfp_threshold_worker`. Cooperative
cancellation via the service's ``cancel_check`` hook; the inner permutation
loop polls the flag every 100 iterations and raises
:class:`PeriEventCancelled`, which this worker translates into a ``cancelled``
signal.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.analysis.peri_event_cluster_perm import PeriEventCancelled
from src.core.services.timeline_peri_event_service import (
    DEFAULT_N_BOOT,
    DEFAULT_N_PERM,
    DEFAULT_WINDOW_MINUTES,
    RANDOM_STATE,
    HemiResult,
    TimelinePeriEventService,
)
from src.ui.electrode_labels import electrode_label


# Stage weights composing the per-hemisphere 0..1.0 progress fraction.
# Permutation dominates wall-clock (10k MWU sweeps), so it carries the bulk.
STAGE_WEIGHTS = {
    "Extracting events": 0.05,
    "Bootstrapping CIs": 0.10,
    "Permuting":         0.85,
}
_STAGE_ORDER: List[str] = [
    "Extracting events",
    "Bootstrapping CIs",
    "Permuting",
]


class _TimelinePeriEventWorkerSignals(QObject):
    """Signals carrier for :class:`TimelinePeriEventWorker`.

    QRunnable cannot emit signals directly, so a separate QObject is built
    in the GUI thread (where the ViewModel constructs the worker).
    """

    # (global_done, global_total, label)
    progress = Signal(int, int, str)
    # (hemisphere, HemiResult) — emitted exactly once per hemisphere
    partial_result = Signal(str, object)
    # dict[str, HemiResult] — exactly one of {finished, error, cancelled}
    finished = Signal(dict)
    error = Signal(str)
    cancelled = Signal()


class TimelinePeriEventWorker(QRunnable):
    """Background worker for the Timeline → Peri-Event pipeline.

    Calls ``service.analyze_hemisphere`` twice (Left then Right) and emits
    :attr:`signals.partial_result` between calls so the View can render each
    side as it lands. Composes per-stage progress into a single 0..1000
    monotone scale (each hemisphere occupies 0..500; the second is offset by
    500).
    """

    def __init__(
        self,
        service: TimelinePeriEventService,
        patient_id: str,
        group1_event_names: List[str],
        group2_event_names: List[str],
        *,
        n_perm: int = DEFAULT_N_PERM,
        n_boot: int = DEFAULT_N_BOOT,
        seed: int = RANDOM_STATE,
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

        self._signals = _TimelinePeriEventWorkerSignals()
        self._is_cancelled = False
        self._current_hemi_index = 0   # 0 = Left, 1 = Right
        self._completed_stage_weight = 0.0
        self._current_stage_label: str = _STAGE_ORDER[0]
        self._current_stage_weight: float = STAGE_WEIGHTS[self._current_stage_label]

        self._t0_global: Optional[float] = None

        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------

    @property
    def signals(self) -> _TimelinePeriEventWorkerSignals:
        return self._signals

    def cancel(self) -> None:
        self.logger.info("Cancellation requested for timeline peri-event analysis")
        self._is_cancelled = True

    def _cancel_check(self) -> bool:
        return self._is_cancelled

    # ------------------------------------------------------------------

    def _stage_to_global_done(self, stage_done: int, stage_total: int) -> int:
        if stage_total <= 0:
            stage_frac = 1.0
        else:
            stage_frac = max(0.0, min(1.0, stage_done / stage_total))
        per_hemi_fraction = (
            self._completed_stage_weight + self._current_stage_weight * stage_frac
        )
        per_hemi_fraction = max(0.0, min(1.0, per_hemi_fraction))
        offset = 500 * self._current_hemi_index
        return int(round(per_hemi_fraction * 500.0)) + offset

    def _on_service_progress(self, stage_done: int, stage_total: int, label: str) -> None:
        if label != self._current_stage_label and label in STAGE_WEIGHTS:
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
        if self._t0_global is None:
            return ""
        if global_done <= 0 or global_done >= 1000:
            return ""
        elapsed = time.monotonic() - self._t0_global
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
                "Starting timeline peri-event analysis: patient_id=%s, n_perm=%s, "
                "n_boot=%s, seed=%s, window_minutes=%s",
                self._patient_id, self._n_perm, self._n_boot, self._seed,
                self._window_minutes,
            )

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

                terminal = 500 * (hemi_index + 1)
                self._signals.progress.emit(
                    terminal, 1000, f"{electrode_label(hemi_index)} — done"
                )

            self._signals.progress.emit(1000, 1000, "Done")
            self._signals.finished.emit(results)

        except PeriEventCancelled:
            self.logger.info("Timeline peri-event analysis cancelled by service")
            self._signals.cancelled.emit()
        except Exception as exc:  # pragma: no cover - integration path
            msg = f"Failed to run timeline peri-event analysis: {exc}"
            self.logger.error(msg, exc_info=True)
            self._signals.error.emit(msg)
