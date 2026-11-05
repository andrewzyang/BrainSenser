"""
Snapshot ML Analysis Service.

Pure (Qt-free) wrapper around the per-band held-out leave-one-out (LOO)
machine-learning analysis used to populate manuscript Figure 2 d-f.

For each hemisphere this service performs:
  - Frequency-envelope masking + per-event NaN handling (parity with the
    script's ``load_csv_matrix``).
  - Bin-indexed candidate-band construction (5-bin window, 3-bin step).
  - Strict nested LOO predictions with inner-fold band selection.
  - Whole-pipeline pooled LOO AUC + bootstrap 95% CI (the FWER test
    statistic).
  - Per-band held-out LOO AUC profile + bootstrap 95% CIs.
  - Modal-band identification by mode of inner-fold band selections (NOT
    argmax of per-band AUC).
  - Whole-pipeline FWER p-value via max-statistic permutation null over
    label permutations.

The analytical functions live in ``src.core.analysis.snapshot_loo_kernel`` -- a
self-contained, Qt-free copy of the strict-nested-LOO + permutation-FWER kernel.
Its statistics are byte-for-byte identical to the published canonical classifier
``code_release/scripts/2_snapshot_5hz_classifier.py`` (locked by a parity test);
the app carries its own copy so it ships standalone.

Author: iEEG BrainSense Development Team
Last Updated: 2026-05-08
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from src.core.analysis.snapshot_loo_kernel import (
    _PermutationCancelled,
    candidate_band_bins,
    band_edges_hz,
    precompute_band_powers,
    nested_loo_predictions,
    loo_auc_from_predictions,
    bootstrap_loo_ci,
    per_band_loo_aucs,
    bootstrap_per_band_loo_aucs,
    permutation_fwer,
    fmt_p,
    WINDOW_BINS,
    STEP_BINS,
    FREQ_MIN_HZ,
    FREQ_MAX_HZ,
    N_PERM,
    N_BOOT,
    SEED,
)

logger = logging.getLogger(__name__)

# Maximum NaN fraction allowed per event row before the row is dropped.
# Matches ``load_csv_matrix`` in the canonical 2_snapshot_5hz_classifier.py.
_MAX_NAN_FRACTION = 0.30

__all__ = [
    "AucProfileResult",
    "OperationCancelledException",
    "SnapshotMlAnalysisService",
    "SEED",
]


class OperationCancelledException(Exception):
    """Raised when an analysis is aborted via ``cancel_check``.

    The worker layer catches this and converts it to a quiet UI state
    (no error dialog) so user-driven cancellation is silent.
    """


@dataclass(frozen=True)
class AucProfileResult:
    """
    Per-hemisphere result of the band-stepping LOO + FWER analysis.

    Attributes
    ----------
    hemisphere : str
        ``"L"`` or ``"R"``.
    band_centers_hz : np.ndarray
        ``(N,)`` array of effective band center frequencies in Hz, where
        ``N`` is the number of candidate bands produced by
        ``candidate_band_bins`` for the masked frequency envelope. Not
        hard-coded; depends on the patient's PSD bin grid.
    band_edges_hz : np.ndarray
        ``(N, 2)`` array of effective ``[lower_edge, upper_edge]`` per band
        (``bin_center ± half_bin_width``).
    per_band_auc : np.ndarray
        ``(N,)`` descriptive held-out LOO AUC for each band held fixed.
        Per-band direction is set by the train-set sign for each fold and
        baked into the held-out scores.
    per_band_ci_lo : np.ndarray
        ``(N,)`` 2.5th-percentile bootstrap CI for ``per_band_auc``.
    per_band_ci_hi : np.ndarray
        ``(N,)`` 97.5th-percentile bootstrap CI for ``per_band_auc``.
    modal_band_idx : int
        Mode of the per-fold band selections from the nested LOO loop.
        On every LOO fold the inner selector picks
        ``b* = argmax_b |AUC_train[b] - 0.5|``; ``modal_band_idx`` is the
        most-common ``b*`` across folds. **Not** ``argmax(per_band_auc)``.
    pipeline_loo_auc : float
        Whole-pipeline pooled held-out LOO AUC. This is the FWER test
        statistic.
    pipeline_loo_ci_lo : float
        Lower bound of the bootstrap 95% CI on ``pipeline_loo_auc``.
    pipeline_loo_ci_hi : float
        Upper bound of the bootstrap 95% CI on ``pipeline_loo_auc``.
    fwer_p : float
        Whole-pipeline FWER p-value from the max-statistic permutation
        null (label permutations re-run the full nested LOO).
    n_craving : int
        Number of craving events surviving preprocessing.
    n_non_craving : int
        Number of non-craving events surviving preprocessing.
    n_perm : int
        Number of label permutations used for the FWER null.
    n_boot : int
        Number of bootstrap resamples used for CIs.
    """

    hemisphere: str
    band_centers_hz: np.ndarray
    band_edges_hz: np.ndarray
    per_band_auc: np.ndarray
    per_band_ci_lo: np.ndarray
    per_band_ci_hi: np.ndarray
    modal_band_idx: int
    pipeline_loo_auc: float
    pipeline_loo_ci_lo: float
    pipeline_loo_ci_hi: float
    fwer_p: float
    n_craving: int
    n_non_craving: int
    n_perm: int
    n_boot: int


class SnapshotMlAnalysisService:
    """
    Service for the per-hemisphere band-stepping LOO + FWER analysis.

    Pure analysis layer (no Qt). Wraps the functions in
    ``src.core.analysis.snapshot_loo_kernel`` (a standalone copy pinned to the
    canonical classifier by a parity test). Long-running calls accept a
    ``progress_callback`` and a ``cancel_check`` for cooperative
    cancellation from a worker thread.
    """

    def __init__(
        self,
        *,
        freq_min_hz: float = FREQ_MIN_HZ,
        freq_max_hz: float = FREQ_MAX_HZ,
    ) -> None:
        """
        Initialize the analysis service.

        Parameters
        ----------
        freq_min_hz : float
            Lower edge of the analysis envelope (Hz). Defaults to the
            locked manuscript value (``5.31``).
        freq_max_hz : float
            Upper edge of the analysis envelope (Hz). Defaults to the
            locked manuscript value (``37.5``).
        """
        if freq_min_hz >= freq_max_hz:
            raise ValueError(
                f"freq_min_hz ({freq_min_hz}) must be < freq_max_hz "
                f"({freq_max_hz})"
            )
        self._freq_min_hz = float(freq_min_hz)
        self._freq_max_hz = float(freq_max_hz)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_hemisphere(
        self,
        crav_psd_matrix: np.ndarray,
        nc_psd_matrix: np.ndarray,
        freqs_hz: np.ndarray,
        hemisphere: str,
        *,
        n_perm: int = N_PERM,
        n_boot: int = N_BOOT,
        seed: int = SEED,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AucProfileResult:
        """
        Run the full per-band LOO + FWER pipeline for a single hemisphere.

        Parameters
        ----------
        crav_psd_matrix : np.ndarray
            ``(n_crav, n_freq)`` raw PSD (µV²/Hz) for craving events. Full
            spectrum; the service masks to the analysis envelope. NaN
            artifact bins are tolerated and handled per the script's
            ``load_csv_matrix`` rules.
        nc_psd_matrix : np.ndarray
            ``(n_nc, n_freq)`` raw PSD (µV²/Hz) for non-craving events.
        freqs_hz : np.ndarray
            ``(n_freq,)`` PSD bin centers in Hz, full spectrum.
        hemisphere : str
            ``"L"`` or ``"R"`` (used only for labelling in the result).
        n_perm : int
            Number of label permutations for the FWER null. Default
            ``N_PERM`` (10,000).
        n_boot : int
            Number of bootstrap resamples for CIs. Default ``N_BOOT``
            (2,000). **Not** 5,000 — that was the value used for the PSD
            top row of Figure 2 (a-c).
        seed : int
            RNG seed for bootstrap and permutation reproducibility.
            Defaults to ``SEED`` (42, the manuscript-canonical value) so the
            page reproduces the published CI / FWER conditions; point estimates
            are seed-free regardless.
        progress_callback : Optional[Callable[[int, int], None]]
            ``(done, total)`` callback forwarded into ``permutation_fwer``
            so the GUI can render permutation-loop progress.
        cancel_check : Optional[Callable[[], bool]]
            Callable returning ``True`` if the operation should abort.
            Checked between major analysis steps. On abort the service
            raises ``OperationCancelledException``.

        Returns
        -------
        AucProfileResult
            Frozen dataclass with the per-band profile, modal band,
            whole-pipeline AUC + CI, and whole-pipeline FWER p.

        Raises
        ------
        ValueError
            If either matrix has zero rows after preprocessing or after
            shape validation (e.g. column count does not match
            ``freqs_hz``).
        OperationCancelledException
            If ``cancel_check`` returns True at any check point.
        """
        if hemisphere not in ("L", "R"):
            raise ValueError(
                f"hemisphere must be 'L' or 'R', got {hemisphere!r}"
            )
        if n_perm < 1:
            raise ValueError(f"n_perm must be >= 1, got {n_perm}")
        if n_boot < 1:
            raise ValueError(f"n_boot must be >= 1, got {n_boot}")

        # 1. Frequency envelope mask + per-row NaN handling (parity with
        #    load_csv_matrix in code_release/scripts/2_snapshot_5hz_classifier.py).
        crav_clean, nc_clean, freqs_envelope = self._preprocess_matrices(
            crav_psd_matrix, nc_psd_matrix, freqs_hz, hemisphere
        )

        n_crav_after = int(crav_clean.shape[0])
        n_nc_after = int(nc_clean.shape[0])
        if n_crav_after == 0 or n_nc_after == 0:
            raise ValueError(
                f"Hemisphere {hemisphere}: insufficient data after "
                f"preprocessing (n_crav={n_crav_after}, n_nc={n_nc_after})"
            )

        # 2. Concatenate into the (X, y) format the analysis core expects.
        #    Order matches the script: non-craving first (label 0), craving
        #    second (label 1).
        X = np.vstack([nc_clean, crav_clean])
        y = np.concatenate([
            np.zeros(n_nc_after, dtype=np.int64),
            np.ones(n_crav_after, dtype=np.int64),
        ])

        logger.info(
            "ML hemisphere %s: %d craving / %d non-craving events; "
            "%d freq bins in envelope [%.2f, %.2f] Hz",
            hemisphere, n_crav_after, n_nc_after, freqs_envelope.size,
            self._freq_min_hz, self._freq_max_hz,
        )

        # 3. Build candidate bands and per-event log10 mean linear power.
        bands = candidate_band_bins(freqs_envelope)
        if len(bands) == 0:
            raise ValueError(
                f"Hemisphere {hemisphere}: no candidate bands could be "
                f"constructed from the {freqs_envelope.size} freq bins in "
                f"the analysis envelope (window={WINDOW_BINS}, "
                f"step={STEP_BINS})"
            )
        edges = band_edges_hz(freqs_envelope, bands)
        # Effective band centers = midpoints of effective edges
        # (equivalent to bin centers for the central bin of an odd-width
        # window, but computed from edges so it is robust to any future
        # change in window/step).
        centers = 0.5 * (edges[:, 0] + edges[:, 1])

        self._raise_if_cancelled(cancel_check)
        band_powers = precompute_band_powers(X, bands)

        # 4. Strict nested LOO with inner-fold band selection.
        self._raise_if_cancelled(cancel_check)
        held, sel, dirs, per_band_held = nested_loo_predictions(
            band_powers, y
        )
        pipeline_loo_auc = float(loo_auc_from_predictions(held, y))

        # 5. Modal band = mode of per-fold band selections. CRITICAL:
        #    NOT argmax(per_band_auc) — those are different numbers and
        #    using argmax would silently misreport the headline band.
        band_counts = Counter(sel.tolist())
        modal_band_idx, _modal_count = band_counts.most_common(1)[0]
        modal_band_idx = int(modal_band_idx)

        # 6. Bootstrap CI on the whole-pipeline LOO AUC.
        self._raise_if_cancelled(cancel_check)
        pipeline_ci_lo, pipeline_ci_hi = bootstrap_loo_ci(
            held, y, n_boot, seed
        )

        # 7. FWER p-value: max-stat null over band search via label
        #    permutations re-running the full nested LOO. The callback
        #    drives GUI progress; permutation_fwer falls back to its
        #    stdout print if callback is None. ``cancel_check`` is polled
        #    inside the perm loop so user cancellation interrupts the
        #    longest stage with sub-chunk latency.
        self._raise_if_cancelled(cancel_check)
        try:
            fwer_p, _null_max = permutation_fwer(
                band_powers,
                y,
                pipeline_loo_auc,
                n_perm,
                seed,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
        except _PermutationCancelled:
            raise OperationCancelledException(
                f"Hemisphere {hemisphere}: cancelled during permutation null"
            ) from None
        fwer_p = float(fwer_p)

        # 8. Per-band descriptive held-out LOO AUC profile + CIs.
        self._raise_if_cancelled(cancel_check)
        per_band_auc = per_band_loo_aucs(per_band_held, y)
        per_band_ci = bootstrap_per_band_loo_aucs(
            per_band_held, y, n_boot, seed
        )
        per_band_ci_lo = per_band_ci[:, 0]
        per_band_ci_hi = per_band_ci[:, 1]

        logger.info(
            "ML hemisphere %s: pipeline LOO AUC = %.4f "
            "[%.4f, %.4f]; FWER p = %s; modal band idx = %d "
            "(%.2f-%.2f Hz)",
            hemisphere, pipeline_loo_auc, pipeline_ci_lo, pipeline_ci_hi,
            fmt_p(fwer_p, n_perm), modal_band_idx,
            float(edges[modal_band_idx, 0]),
            float(edges[modal_band_idx, 1]),
        )

        return AucProfileResult(
            hemisphere=hemisphere,
            band_centers_hz=np.asarray(centers, dtype=float),
            band_edges_hz=np.asarray(edges, dtype=float),
            per_band_auc=np.asarray(per_band_auc, dtype=float),
            per_band_ci_lo=np.asarray(per_band_ci_lo, dtype=float),
            per_band_ci_hi=np.asarray(per_band_ci_hi, dtype=float),
            modal_band_idx=modal_band_idx,
            pipeline_loo_auc=float(pipeline_loo_auc),
            pipeline_loo_ci_lo=float(pipeline_ci_lo),
            pipeline_loo_ci_hi=float(pipeline_ci_hi),
            fwer_p=fwer_p,
            n_craving=n_crav_after,
            n_non_craving=n_nc_after,
            n_perm=int(n_perm),
            n_boot=int(n_boot),
        )

    def analyze_both_hemispheres(
        self,
        crav_L: Optional[np.ndarray],
        nc_L: Optional[np.ndarray],
        crav_R: Optional[np.ndarray],
        nc_R: Optional[np.ndarray],
        freqs_hz: np.ndarray,
        *,
        n_perm: int = N_PERM,
        n_boot: int = N_BOOT,
        seed: int = SEED,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        hemisphere_label_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, AucProfileResult]:
        """
        Run the analysis on both hemispheres.

        Hemispheres for which either matrix is ``None`` (or empty after
        preprocessing) are simply absent from the returned dict — the key
        is **not** included with a ``None`` value. This lets unilateral
        implants get a partial result without the caller having to filter
        ``None`` entries.

        Parameters
        ----------
        crav_L, nc_L : Optional[np.ndarray]
            Left-hemisphere craving / non-craving PSD matrices, or
            ``None`` if the hemisphere is not implanted.
        crav_R, nc_R : Optional[np.ndarray]
            Right-hemisphere matrices, or ``None``.
        freqs_hz : np.ndarray
            Shared PSD bin centers (Hz) for both hemispheres.
        n_perm, n_boot, seed, progress_callback, cancel_check
            See ``analyze_hemisphere``. The callback is forwarded
            unchanged to each hemisphere's permutation loop, so callers
            wanting a single combined progress bar across both
            hemispheres should wrap the callback themselves.
        hemisphere_label_callback : Optional[Callable[[str], None]]
            Optional announcement callback fired with ``"L"`` or ``"R"``
            immediately before that hemisphere's ``analyze_hemisphere``
            call begins. Lets the worker layer remap the per-hemisphere
            ``progress_callback`` (which counts perm 1..n_perm on its own
            scale) onto a single combined 0..2*n_perm bar.

        Returns
        -------
        dict[str, AucProfileResult]
            Mapping ``{"L": result, "R": result}``, omitting any
            hemisphere lacking input data.

        Raises
        ------
        OperationCancelledException
            If ``cancel_check`` returns True at any check point.
        """
        results: Dict[str, AucProfileResult] = {}

        if crav_L is not None and nc_L is not None:
            self._raise_if_cancelled(cancel_check)
            if hemisphere_label_callback is not None:
                hemisphere_label_callback("L")
            try:
                results["L"] = self.analyze_hemisphere(
                    crav_L,
                    nc_L,
                    freqs_hz,
                    "L",
                    n_perm=n_perm,
                    n_boot=n_boot,
                    seed=seed,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            except ValueError as exc:
                # Insufficient data after preprocessing — skip this side
                # rather than aborting the whole call. Right-hemisphere
                # analysis may still be viable.
                logger.warning(
                    "Skipping left hemisphere ML analysis: %s", exc
                )

        if crav_R is not None and nc_R is not None:
            self._raise_if_cancelled(cancel_check)
            if hemisphere_label_callback is not None:
                hemisphere_label_callback("R")
            try:
                results["R"] = self.analyze_hemisphere(
                    crav_R,
                    nc_R,
                    freqs_hz,
                    "R",
                    n_perm=n_perm,
                    n_boot=n_boot,
                    seed=seed,
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            except ValueError as exc:
                logger.warning(
                    "Skipping right hemisphere ML analysis: %s", exc
                )

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _preprocess_matrices(
        self,
        crav_matrix: np.ndarray,
        nc_matrix: np.ndarray,
        freqs_hz: np.ndarray,
        hemisphere: str,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Apply frequency masking and per-row NaN handling.

        Mirrors ``load_csv_matrix`` in the canonical
        ``code_release/scripts/2_snapshot_5hz_classifier.py``:

        1. Restrict columns to ``[freq_min_hz, freq_max_hz]``.
        2. Drop event rows whose NaN fraction exceeds 30%.
        3. Linearly interpolate any remaining NaN bins from valid bins;
           drop the row if fewer than 2 valid bins remain after masking.

        Parameters
        ----------
        crav_matrix : np.ndarray
            ``(n_crav, n_freq)`` raw PSD; full spectrum.
        nc_matrix : np.ndarray
            ``(n_nc, n_freq)`` raw PSD; full spectrum.
        freqs_hz : np.ndarray
            Full-spectrum PSD bin centers in Hz.
        hemisphere : str
            Hemisphere label, used only for diagnostic logging.

        Returns
        -------
        tuple of np.ndarray
            ``(crav_clean, nc_clean, freqs_envelope)``. ``crav_clean`` and
            ``nc_clean`` may have fewer rows than the inputs.
        """
        freqs_hz = np.asarray(freqs_hz, dtype=float)
        if freqs_hz.ndim != 1:
            raise ValueError(
                f"freqs_hz must be 1-D, got shape {freqs_hz.shape}"
            )

        crav_matrix = np.asarray(crav_matrix, dtype=float)
        nc_matrix = np.asarray(nc_matrix, dtype=float)

        for label, mat in (("craving", crav_matrix), ("non-craving", nc_matrix)):
            if mat.ndim != 2:
                raise ValueError(
                    f"{label} PSD matrix must be 2-D, got shape "
                    f"{mat.shape}"
                )
            if mat.size > 0 and mat.shape[1] != freqs_hz.size:
                raise ValueError(
                    f"{label} PSD matrix has {mat.shape[1]} freq columns "
                    f"but freqs_hz has {freqs_hz.size} bins"
                )

        freq_mask = (
            (freqs_hz >= self._freq_min_hz)
            & (freqs_hz <= self._freq_max_hz)
        )
        if not np.any(freq_mask):
            raise ValueError(
                f"No PSD bins fall inside the analysis envelope "
                f"[{self._freq_min_hz}, {self._freq_max_hz}] Hz "
                f"(hemisphere {hemisphere})"
            )

        freqs_envelope = freqs_hz[freq_mask]
        crav_envelope = crav_matrix[:, freq_mask] if crav_matrix.size else \
            np.empty((0, freqs_envelope.size))
        nc_envelope = nc_matrix[:, freq_mask] if nc_matrix.size else \
            np.empty((0, freqs_envelope.size))

        crav_clean = self._clean_event_rows(
            crav_envelope, freqs_envelope, label=f"craving/{hemisphere}"
        )
        nc_clean = self._clean_event_rows(
            nc_envelope, freqs_envelope, label=f"non-craving/{hemisphere}"
        )
        return crav_clean, nc_clean, freqs_envelope

    @staticmethod
    def _clean_event_rows(
        matrix: np.ndarray,
        freqs_envelope: np.ndarray,
        *,
        label: str,
    ) -> np.ndarray:
        """
        Drop high-NaN rows and interpolate residual NaN bins.

        Per-row rule (parity with ``load_csv_matrix``):
          * If ``isnan`` fraction > 0.30, drop the row.
          * Else, replace NaN bins by linear interpolation across the
            valid bins (using ``np.interp`` over the envelope's frequency
            axis). If fewer than 2 valid bins exist, drop the row.

        Returns a contiguous ``(n_kept, n_freq)`` array (possibly empty).
        """
        if matrix.size == 0:
            return matrix
        n_freq = matrix.shape[1]
        if n_freq == 0:
            return np.empty((0, 0))

        kept_rows = []
        n_dropped_high_nan = 0
        n_dropped_no_valid = 0
        for row in matrix:
            nan_mask = np.isnan(row)
            nan_frac = float(np.sum(nan_mask)) / n_freq
            if nan_frac > _MAX_NAN_FRACTION:
                n_dropped_high_nan += 1
                continue
            if nan_frac > 0:
                valid = ~nan_mask
                if int(np.sum(valid)) < 2:
                    n_dropped_no_valid += 1
                    continue
                row = row.copy()
                row[nan_mask] = np.interp(
                    freqs_envelope[nan_mask],
                    freqs_envelope[valid],
                    row[valid],
                )
            kept_rows.append(row)

        if n_dropped_high_nan or n_dropped_no_valid:
            logger.info(
                "Preprocessing %s: dropped %d row(s) with NaN fraction > "
                "%.0f%%, %d row(s) with insufficient valid bins; kept %d",
                label, n_dropped_high_nan, _MAX_NAN_FRACTION * 100,
                n_dropped_no_valid, len(kept_rows),
            )

        if not kept_rows:
            return np.empty((0, n_freq))
        return np.asarray(kept_rows, dtype=float)

    @staticmethod
    def _raise_if_cancelled(
        cancel_check: Optional[Callable[[], bool]],
    ) -> None:
        """Raise ``OperationCancelledException`` if ``cancel_check`` says so."""
        if cancel_check is not None and cancel_check():
            raise OperationCancelledException(
                "Snapshot ML analysis cancelled by caller"
            )
