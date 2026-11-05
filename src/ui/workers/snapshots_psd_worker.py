"""
SnapshotsPsdWorker — background worker for the Snapshots Classic (PSD) page.

Runs :class:`SnapshotPsdAnalysisService` for both hemispheres sequentially,
emits per-hemisphere ``partial_psd`` (median + bootstrap-CI curves) and
``partial_band`` (Mann-Whitney U + FDR band stats) as they land, and composes
a stage-weighted **monotone** 0→1000 progress bar across the whole analysis.

Mirrors :mod:`src.ui.workers.snapshots_5hz_band_worker` and
:mod:`src.ui.workers.timeline_lfp_threshold_worker`. Cooperative cancellation via the
service's ``cancel_check`` hook; the inner per-band loops poll the flag at the
top of each iteration.

Author: iEEG BrainSense Development Team
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from src.core.services.snapshot_psd_analysis_service import (
    BandComparisonResult,
    OperationCancelledException,
    SnapshotPsdAnalysisService,
)
from src.domain.psd_models import SnapshotPsdDataset
from src.ui.electrode_labels import electrode_label_for_hemisphere


# Stage weights composing the per-hemisphere 0..1.0 progress fraction.
# Sum to 1.0. Bands take longer than curves (FDR + bootstrap CIs per band).
_CURVE_WEIGHT = 0.25
_BAND_WEIGHT = 0.75


class _SnapshotsPsdWorkerSignals(QObject):
    """Signals carrier for :class:`SnapshotsPsdWorker`.

    QRunnable cannot emit signals directly, so we use a separate QObject
    constructed in the GUI thread (where the ViewModel builds the worker).
    Cross-thread delivery uses Qt's auto-detected QueuedConnection — but the
    ViewModel pins it to ``Qt.QueuedConnection`` explicitly for clarity.
    """

    # (global_done, global_total, label) — total fixed at 1000.
    progress = Signal(int, int, str)
    # (hemisphere, curves dict) — emitted exactly once per hemisphere, after
    # ``get_psd_curves_for_groups`` returns. Hemisphere is "LEFT" or "RIGHT".
    partial_psd = Signal(str, object)
    # (hemisphere, band_results dict) — emitted exactly once per hemisphere,
    # after ``analyze_group_comparison`` returns.
    partial_band = Signal(str, object)
    # dict[str, object] payload — exactly one of {finished, error, cancelled}
    # per invocation. Keys: ``psd_left``, ``psd_right``, ``band_left``,
    # ``band_right``. Hemispheres without data are absent from the payload.
    finished = Signal(dict)
    error = Signal(str)
    cancelled = Signal()


class SnapshotsPsdWorker(QRunnable):
    """Background worker for the Snapshots Classic (PSD) analysis pipeline.

    Owns hemisphere ordering: calls
    :meth:`SnapshotPsdAnalysisService.get_psd_curves_for_groups` then
    :meth:`SnapshotPsdAnalysisService.analyze_group_comparison` for ``LEFT``,
    then again for ``RIGHT``. Emits :attr:`signals.partial_psd` and
    :attr:`signals.partial_band` between calls so the View can render each
    side as it lands instead of a blank wait. Composes per-stage progress
    into a single 0..1000 monotone scale (each hemisphere occupies 0..500;
    the second is offset by 500).
    """

    def __init__(
        self,
        service: SnapshotPsdAnalysisService,
        dataset: SnapshotPsdDataset,
        group1_event_types: List[str],
        group2_event_types: List[str],
        *,
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
        filter_stimulation: bool = True,
        timeline_band_center: Optional[float] = None,
    ) -> None:
        """Construct the worker on the GUI thread.

        Parameters
        ----------
        service : SnapshotPsdAnalysisService
            Pure (Qt-free) analysis service. The worker only calls its public
            methods — no state mutation on the service.
        dataset : SnapshotPsdDataset
            Frozen dataset shared with the GUI thread. Safe to read from the
            worker thread because the dataclass is frozen and the underlying
            arrays are not mutated by either side.
        group1_event_types, group2_event_types : list[str]
            Event-type membership for the two groups (panel convention:
            Group 1 = non-craving, Group 2 = craving).
        group1_name, group2_name : str
            Display names used by the service for the band-statistics rows.
        filter_stimulation : bool
            Whether to filter for matching stimulation states (mirrors the
            VM's existing flag).
        timeline_band_center : float or None
            Optional 5 Hz custom band center frequency.
        """
        super().__init__()
        self._service = service
        self._dataset = dataset
        self._group1 = list(group1_event_types or [])
        self._group2 = list(group2_event_types or [])
        self._group1_name = group1_name
        self._group2_name = group2_name
        self._filter_stimulation = filter_stimulation
        self._timeline_band_center = timeline_band_center

        self._signals = _SnapshotsPsdWorkerSignals()
        self._is_cancelled = False

        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------

    @property
    def signals(self) -> _SnapshotsPsdWorkerSignals:
        """Return the signals carrier QObject (GUI-thread-owned)."""
        return self._signals

    def cancel(self) -> None:
        """Request cooperative cancellation. Idempotent and thread-safe (a
        plain bool assignment is atomic in CPython). The service polls
        ``cancel_check`` at each phase boundary and raises
        :class:`OperationCancelledException` on True."""
        self.logger.info("Cancellation requested for snapshots PSD analysis")
        self._is_cancelled = True

    def _cancel_check(self) -> bool:
        return self._is_cancelled

    # ------------------------------------------------------------------

    def _emit_progress(
        self,
        hemi_index: int,
        stage_offset: float,
        stage_weight: float,
        stage_done: int,
        stage_total: int,
        label: str,
    ) -> None:
        """Compose ``(stage_done, stage_total)`` for the current stage and
        hemisphere into the 0..1000 monotone scale and emit it."""
        if stage_total <= 0:
            stage_frac = 1.0
        else:
            stage_frac = max(0.0, min(1.0, stage_done / stage_total))
        per_hemi_fraction = stage_offset + stage_weight * stage_frac
        per_hemi_fraction = max(0.0, min(1.0, per_hemi_fraction))
        # Each hemi occupies 0..500 of the 0..1000 scale; the second is offset.
        offset = 500 * hemi_index
        global_done = int(round(per_hemi_fraction * 500.0)) + offset
        self._signals.progress.emit(global_done, 1000, label)

    # ------------------------------------------------------------------

    @Slot()
    def run(self) -> None:
        """Execute the analysis on a worker thread. Emits exactly one of
        :attr:`signals.finished`, :attr:`signals.error`, or
        :attr:`signals.cancelled` per invocation."""
        try:
            self.logger.info(
                "Starting snapshots PSD analysis: patient_id=%s, "
                "group1=%s, group2=%s",
                getattr(self._dataset, "patient_id", "<unknown>"),
                self._group1, self._group2,
            )

            # Initial 0% emission so the UI flips to the running state.
            self._signals.progress.emit(
                0, 1000, f"{electrode_label_for_hemisphere('LEFT')} — PSD curves"
            )

            if self._is_cancelled:
                self._signals.cancelled.emit()
                return

            payload: Dict[str, object] = {}

            for hemi_index, hemi in enumerate(("LEFT", "RIGHT")):
                if self._is_cancelled:
                    self._signals.cancelled.emit()
                    return

                electrode = electrode_label_for_hemisphere(hemi)

                # ---- Stage 1: PSD curves ----
                def curve_progress(
                    done: int, total: int, label: str,
                    _h=hemi_index, _hl=electrode,
                ) -> None:
                    self._emit_progress(
                        _h, 0.0, _CURVE_WEIGHT, done, total,
                        f"{_hl} — {label}",
                    )

                curves = self._service.get_psd_curves_for_groups(
                    dataset=self._dataset,
                    hemisphere=hemi,
                    group1_event_types=self._group1,
                    group2_event_types=self._group2,
                    progress_callback=curve_progress,
                    cancel_check=self._cancel_check,
                )
                payload[f"psd_{hemi.lower()}"] = curves
                self._signals.partial_psd.emit(hemi, curves)

                if self._is_cancelled:
                    self._signals.cancelled.emit()
                    return

                # ---- Stage 2: band statistics ----
                def band_progress(
                    done: int, total: int, label: str,
                    _h=hemi_index, _hl=electrode,
                ) -> None:
                    self._emit_progress(
                        _h, _CURVE_WEIGHT, _BAND_WEIGHT, done, total,
                        f"{_hl} — {label}",
                    )

                bands: Dict[str, BandComparisonResult] = (
                    self._service.analyze_group_comparison(
                        dataset=self._dataset,
                        group1_event_types=self._group1,
                        group2_event_types=self._group2,
                        group1_name=self._group1_name,
                        group2_name=self._group2_name,
                        hemisphere=hemi,
                        filter_stimulation=self._filter_stimulation,
                        timeline_band_center=self._timeline_band_center,
                        progress_callback=band_progress,
                        cancel_check=self._cancel_check,
                    )
                )
                payload[f"band_{hemi.lower()}"] = bands
                self._signals.partial_band.emit(hemi, bands)

                # Bring the bar to the end of this hemisphere's slot
                # regardless of which stage emitted last.
                terminal = 500 * (hemi_index + 1)
                self._signals.progress.emit(
                    terminal, 1000, f"{electrode} — done",
                )

            # Final monotone tick at 1000 even if it duplicates the last
            # per-hemisphere tick — guarantees the UI sees a definitive 100%.
            self._signals.progress.emit(1000, 1000, "Done")
            self._signals.finished.emit(payload)

        except OperationCancelledException:
            self.logger.info("Snapshots PSD analysis cancelled by service")
            self._signals.cancelled.emit()
        except Exception as exc:  # pragma: no cover - integration path
            msg = f"Failed to run snapshots PSD analysis: {exc}"
            self.logger.error(msg, exc_info=True)
            self._signals.error.emit(msg)
