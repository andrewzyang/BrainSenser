"""
Standalone strict-nested-LOO + max-statistic permutation-FWER kernel.

Self-contained numeric core for the Snapshots-ML per-hemisphere classifier
(manuscript Figure 2 d-f). Pure numpy/scipy -- no Qt, no file I/O, no CSV
loading -- so it is safe to import from the core service layer and to run inside
a background ``QThreadPool`` worker.

The statistics implemented here are byte-for-byte identical to the published
canonical classifier ``code_release/scripts/2_snapshot_5hz_classifier.py`` (and
to the research script ``scripts/predictive_ability_5bin_3step.py`` from which
these functions were extracted verbatim). That equivalence is locked by
``tests/unit/core/services/test_snapshot_ml_analysis_service.py::
test_numerical_parity_with_canonical_classifier``. The copies are intentionally
independent going forward; the parity test is the guarantee they stay correct.

ANALYSIS ENVELOPE (locked, pre-registered): 5.31-37.5 Hz, 5-bin window, 3-bin
step (2-bin overlap), 10000 label permutations, 2000 bootstrap resamples,
seed 42.
"""

from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

import numpy as np
from scipy.stats import rankdata


class _PermutationCancelled(Exception):
    """Raised by `permutation_fwer` when its cancel_check returns True."""


# -----------------------------------------------------------------------------
# Constants (locked envelope)
# -----------------------------------------------------------------------------

WINDOW_BINS = 5
STEP_BINS = 3
FREQ_MIN_HZ = 5.31
FREQ_MAX_HZ = 37.5
N_PERM = 10_000
N_BOOT = 2_000
SEED = 42


def candidate_band_bins(freqs: np.ndarray) -> np.ndarray:
    """Return (n_bands, 2) array of [start_idx, end_idx_inclusive] indexing
    `freqs`. Bands are 5 consecutive bins, stepped by 3 bins (2-bin overlap)
    starting from the first bin in `freqs` (which is already restricted to
    the [FREQ_MIN_HZ, FREQ_MAX_HZ] envelope by load_csv_matrix)."""
    n = len(freqs)
    starts = np.arange(0, n - WINDOW_BINS + 1, STEP_BINS)
    bands = np.empty((len(starts), 2), dtype=np.int64)
    bands[:, 0] = starts
    bands[:, 1] = starts + WINDOW_BINS - 1
    return bands


def band_edges_hz(freqs: np.ndarray, bands: np.ndarray) -> np.ndarray:
    """Return (n_bands, 2) array of effective [lower_edge, upper_edge] in Hz
    using bin_center ± half_bin_width, with half_bin = median(diff(freqs))/2."""
    half = float(np.median(np.diff(freqs)) / 2.0)
    edges = np.empty((len(bands), 2), dtype=float)
    edges[:, 0] = freqs[bands[:, 0]] - half
    edges[:, 1] = freqs[bands[:, 1]] + half
    return edges


def precompute_band_powers(
    X: np.ndarray, bands: np.ndarray,
) -> np.ndarray:
    """log10 of clipped mean linear power within each bin-indexed band.

    Output shape: (n_bands, n_events).
    """
    n_bands = len(bands)
    out = np.zeros((n_bands, X.shape[0]))
    for b in range(n_bands):
        s, e = bands[b]
        raw = np.mean(X[:, s:e + 1], axis=1)
        raw = np.clip(raw, 1e-10, None)
        out[b] = np.log10(raw)
    return out


def auc_from_ranks(ranks: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Vectorised signed AUC = P(score_pos > score_neg) per band from a rank
    matrix. Shapes: ranks (n_bands, n), y (n,)."""
    n = y.size
    n_pos = int(y.sum())
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return np.full(ranks.shape[0], 0.5)
    R1 = ranks[:, y.astype(bool)].sum(axis=1)
    U = R1 - n_pos * (n_pos + 1) / 2.0
    return U / (n_pos * n_neg)


def loo_auc_from_predictions(held: np.ndarray, y: np.ndarray) -> float:
    ranks = rankdata(held, method="average")
    n_pos = int(y.sum())
    n_neg = y.size - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    R1 = ranks[y.astype(bool)].sum()
    U = R1 - n_pos * (n_pos + 1) / 2.0
    return float(U / (n_pos * n_neg))


def nested_loo_predictions(
    band_powers: np.ndarray, y: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Honest held-out LOO scores with inner band selection.

    Returns
    -------
    held : (n,) float
        Held-out signed score from the inner-fold-selected band.
    sel : (n,) int
        Inner-fold-selected band index per held-out event.
    dirs : (n,) int
        Inner-fold-selected direction (+1/-1) per held-out event.
    per_band_held : (n_bands, n) float
        Held-out signed score for each candidate band fixed (train-set
        direction per band per fold). Diagonal-ish: per_band_held[sel[i], i]
        equals held[i].
    """
    n_bands, n = band_powers.shape
    held = np.empty(n)
    sel = np.empty(n, dtype=np.int64)
    dirs = np.empty(n, dtype=np.int64)
    per_band_held = np.empty((n_bands, n))
    for i in range(n):
        train_mask = np.ones(n, dtype=bool)
        train_mask[i] = False
        train_powers = band_powers[:, train_mask]
        train_y = y[train_mask]
        train_ranks = rankdata(train_powers, axis=1, method="average")
        train_aucs = auc_from_ranks(train_ranks, train_y)
        deviation = np.abs(train_aucs - 0.5)
        b = int(np.argmax(deviation))
        d = 1 if train_aucs[b] >= 0.5 else -1
        sel[i] = b
        dirs[i] = d
        held[i] = d * band_powers[b, i]
        # Also store a per-band held-out score using each band's own
        # train-set direction (used for the per-band LOO-AUC profile,
        # Figure 2 row g–i).
        per_band_dirs = np.where(train_aucs >= 0.5, 1.0, -1.0)
        per_band_held[:, i] = per_band_dirs * band_powers[:, i]
    return held, sel, dirs, per_band_held


def nested_loo_auc_only(band_powers: np.ndarray, y: np.ndarray) -> float:
    """LOO AUC only (no per-fold bookkeeping). Used inside the perm loop."""
    n_bands, n = band_powers.shape
    held = np.empty(n)
    for i in range(n):
        train_mask = np.ones(n, dtype=bool)
        train_mask[i] = False
        train_ranks = rankdata(band_powers[:, train_mask], axis=1, method="average")
        train_aucs = auc_from_ranks(train_ranks, y[train_mask])
        b = int(np.argmax(np.abs(train_aucs - 0.5)))
        d = 1.0 if train_aucs[b] >= 0.5 else -1.0
        held[i] = d * band_powers[b, i]
    return loo_auc_from_predictions(held, y)


def permutation_fwer(
    band_powers: np.ndarray, y: np.ndarray, obs_loo_auc: float,
    n_perm: int, seed: int, progress_label: str = "",
    *,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[float, np.ndarray]:
    """Re-run the full nested LOO-CV under shuffled labels."""
    rng = np.random.default_rng(seed)
    obs_dev = abs(obs_loo_auc - 0.5)
    null_auc = np.empty(n_perm)
    chunk = max(1, n_perm // 20)
    t_start = time.time()
    for p in range(n_perm):
        y_shuf = rng.permutation(y)
        null_auc[p] = nested_loo_auc_only(band_powers, y_shuf)
        if (p + 1) % chunk == 0 or p == n_perm - 1:
            if cancel_check is not None and cancel_check():
                raise _PermutationCancelled()
            if progress_callback is None:
                elapsed = time.time() - t_start
                done = (p + 1) / n_perm
                est_total = elapsed / max(done, 1e-9)
                print(
                    f"      {progress_label} perm {p + 1}/{n_perm}"
                    f"  ({done * 100:5.1f}%)  elapsed {elapsed:6.1f}s"
                    f"  ~total {est_total:6.1f}s",
                    flush=True,
                )
            else:
                progress_callback(p + 1, n_perm)
    null_dev = np.abs(null_auc - 0.5)
    fwer_p = float((np.sum(null_dev >= obs_dev) + 1) / (n_perm + 1))
    return fwer_p, null_auc


def bootstrap_loo_ci(
    held: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> Tuple[float, float]:
    """Stratified bootstrap CI on the held-out LOO AUC.

    Sampling/marginal CI (positives resampled with replacement among
    positives, negatives among negatives). Selection-correction lives in
    the FWER P, not the CI.
    """
    rng = np.random.default_rng(seed)
    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    aucs = np.empty(n_boot)
    for b in range(n_boot):
        rs = np.concatenate([
            rng.choice(idx_pos, len(idx_pos), replace=True),
            rng.choice(idx_neg, len(idx_neg), replace=True),
        ])
        aucs[b] = loo_auc_from_predictions(held[rs], y[rs])
    return float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5))


def per_band_loo_aucs(per_band_held: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Pooled LOO AUC for each band, using the train-determined direction
    per band per fold (already baked into per_band_held)."""
    n_bands = per_band_held.shape[0]
    out = np.empty(n_bands)
    for b in range(n_bands):
        out[b] = loo_auc_from_predictions(per_band_held[b], y)
    return out


def bootstrap_per_band_loo_aucs(
    per_band_held: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> np.ndarray:
    """(n_bands, 2) array of [2.5, 97.5]-percentile bootstrap CIs on
    each band's pooled-LOO AUC. Stratified by class membership."""
    rng = np.random.default_rng(seed)
    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    n_bands = per_band_held.shape[0]
    aucs = np.empty((n_boot, n_bands))
    for b in range(n_boot):
        rs = np.concatenate([
            rng.choice(idx_pos, len(idx_pos), replace=True),
            rng.choice(idx_neg, len(idx_neg), replace=True),
        ])
        for k in range(n_bands):
            aucs[b, k] = loo_auc_from_predictions(per_band_held[k, rs], y[rs])
    out = np.empty((n_bands, 2))
    out[:, 0] = np.percentile(aucs, 2.5, axis=0)
    out[:, 1] = np.percentile(aucs, 97.5, axis=0)
    return out


def fmt_p(p: float, n_perm: int) -> str:
    floor = 1.0 / (n_perm + 1)
    if p < floor + 1e-12:
        return f"= {floor:.5f}"
    if p < 0.001:
        return "< 0.001"
    if p < 0.01:
        return f"{p:.4f}"
    return f"{p:.3f}"
