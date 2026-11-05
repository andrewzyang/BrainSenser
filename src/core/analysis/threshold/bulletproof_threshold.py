#!/usr/bin/env python3
"""
Bulletproof LFP Threshold Analysis — LOO Sanity Test

Tests whether the publication K-fold threshold findings survive a clean
LOO-CV + cluster-bootstrap + permutation pipeline on the SAME data.

Pre-specifications (locked, not tunable):
  - Data: reuse extract_offset_matrix from lfp_threshold_publication
  - Aggregation: np.nanmedian across 7 bins (match publication)
  - Classifier: L2-LogReg with class_weight="balanced"
  - Threshold: -intercept / coefficient (LR decision boundary)
  - Secondary threshold: Youden's J on empirical ROC of raw X
  - CV: LeaveOneOut
  - Threshold CI: cluster bootstrap resampling events (2000 resamples)
  - Null: label-shuffle permutation, full LOO rerun (default 1000)

What this does NOT test (out of scope for this run):
  - Temporal leakage by day (no LOGO)
  - Stimulation program confound
  - 7.81 Hz vs classifier-optimal band mismatch
  - Alternative aggregations

Usage:
    python results/lfp_threshold/bulletproof_threshold.py
    python results/lfp_threshold/bulletproof_threshold.py --n-perm 10000 --n-jobs 8
"""

import argparse
import time
from pathlib import Path
from datetime import datetime

import numpy as np
from joblib import Parallel, delayed
from scipy.stats import mannwhitneyu, norm
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import roc_auc_score, roc_curve
import warnings
warnings.filterwarnings("ignore")

project_root = Path(__file__).parent.parent.parent

from ._threshold_constants import (
    compute_classic_stats,
    MIN_EVENTS_PER_CLASS,
)
# `ApplicationContainer`, `extract_offset_matrix`, `PATIENTS`, and
# `HEMISPHERES` are lazy-imported inside the functions that need them so
# the in-app service path stays Qt-free and matplotlib-free.
# - `ApplicationContainer` (src/infrastructure/container.py) transitively
#   imports `src/ui/viewmodels`, which pulls PySide6.
# - `extract_offset_matrix`, `PATIENTS`, and `HEMISPHERES` live in
#   `lfp_threshold_publication`, which has top-level matplotlib imports.

RANDOM_STATE = 42
N_BOOTSTRAP = 2000
DEFAULT_N_PERM = 10000

# Sensitivity / specificity stratified-bootstrap stream. Dedicated seed
# (distinct from RANDOM_STATE) to reproduce the manuscript-published sens/spec
# CIs in code_release/scripts/4_timeline_amplitude_threshold_classifier.py.
SENS_SPEC_N_BOOT = 2000
SENS_SPEC_SEED = 20260423

# Rank-biserial r BCa-bootstrap stream (matches the compute_missing_effect_sizes
# companion and the code_release reference script).
RRB_BOOTSTRAP_N = 5000
RRB_BOOTSTRAP_SEED = 2025
RRB_BOOTSTRAP_ALPHA = 0.05


# ─── Core classifier ────────────────────────────────────────────────────────

def fit_lr_threshold(X, y):
    """L2-LogReg decision boundary on raw uV; returns (threshold, coef_sign)."""
    clf = LogisticRegression(
        class_weight="balanced", random_state=RANDOM_STATE, max_iter=1000,
    )
    clf.fit(X.reshape(-1, 1), y)
    coef = clf.coef_[0, 0]
    intercept = clf.intercept_[0]
    if coef == 0:
        return np.nan, 0.0
    threshold = float(-intercept / coef)
    return threshold, float(coef)


def youden_threshold(X, y):
    """
    Empirical Youden's J threshold: argmax(sens + spec - 1) on raw X.

    Direction inferred from class means: craving 'above' if mean(X|craving)
    > mean(X|neutral), else 'below'. Returns threshold in uV and J value.
    """
    craving_mean = np.mean(X[y == 1])
    neutral_mean = np.mean(X[y == 0])
    craving_above = craving_mean > neutral_mean

    scores = X if craving_above else -X
    fpr, tpr, thresholds = roc_curve(y, scores)
    J = tpr - fpr
    best_idx = int(np.argmax(J))
    thr = thresholds[best_idx]
    if not craving_above:
        thr = -thr
    return float(thr), float(J[best_idx]), craving_above


# ─── LOO-CV ─────────────────────────────────────────────────────────────────

def loo_predict(X, y):
    """
    Leave-one-out CV. Returns pooled out-of-fold probabilities and
    per-fold thresholds (one per event).
    """
    n = len(y)
    oof_prob = np.full(n, np.nan)
    fold_thresholds = np.full(n, np.nan)
    fold_coef_signs = np.full(n, np.nan)

    loo = LeaveOneOut()
    for train_idx, test_idx in loo.split(X):
        clf = LogisticRegression(
            class_weight="balanced",
            random_state=RANDOM_STATE, max_iter=1000,
        )
        clf.fit(X[train_idx].reshape(-1, 1), y[train_idx])
        oof_prob[test_idx[0]] = clf.predict_proba(
            X[test_idx].reshape(-1, 1))[0, 1]
        coef = clf.coef_[0, 0]
        if coef != 0:
            fold_thresholds[test_idx[0]] = -clf.intercept_[0] / coef
        fold_coef_signs[test_idx[0]] = np.sign(coef)

    return oof_prob, fold_thresholds, fold_coef_signs


def loo_auc(X, y):
    """LOO-CV AUC on pooled out-of-fold probabilities."""
    oof_prob, _, _ = loo_predict(X, y)
    return float(roc_auc_score(y, oof_prob)), oof_prob


# ─── Cancellation primitive ────────────────────────────────────────────────

class CancelledError(Exception):
    """Raised by the serial cancellable helpers when ``cancel_check()``
    returns True. Local to this module so the in-app service can catch it
    without importing :mod:`concurrent.futures`."""


# ─── Bootstrap AUC CI (DeLong-style via bootstrap) ─────────────────────────

def bootstrap_auc_ci(y_true, y_score, n_boot=2000, seed=RANDOM_STATE):
    """Percentile CI on AUC by resampling (event, label, score) triples."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    aucs = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        if len(np.unique(y_true[idx])) < 2:
            continue
        aucs.append(roc_auc_score(y_true[idx], y_score[idx]))
    aucs = np.array(aucs)
    return (float(np.percentile(aucs, 2.5)),
            float(np.percentile(aucs, 97.5)),
            float(np.std(aucs, ddof=1)))


def bootstrap_auc_ci_serial(
    y_true, y_score, n_boot=2000,
    *,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Cancel-aware sibling of :func:`bootstrap_auc_ci`. Bit-equal output
    to the parallel original under matched ``(n_boot, seed)`` because the
    RNG sequence and decision logic are identical. Polls ``cancel_check``
    every 50 resamples; raises :class:`CancelledError` on True. Emits
    ``progress_callback(done, total)`` every 50 resamples."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    aucs = []
    for i in range(n_boot):
        if cancel_check is not None and (i % 50 == 0) and cancel_check():
            raise CancelledError()
        idx = rng.choice(n, size=n, replace=True)
        if len(np.unique(y_true[idx])) < 2:
            continue
        aucs.append(roc_auc_score(y_true[idx], y_score[idx]))
        if progress_callback is not None and ((i + 1) % 50 == 0):
            progress_callback(i + 1, n_boot)
    if progress_callback is not None and n_boot % 50 != 0:
        progress_callback(n_boot, n_boot)
    aucs = np.array(aucs)
    return (float(np.percentile(aucs, 2.5)),
            float(np.percentile(aucs, 97.5)),
            float(np.std(aucs, ddof=1)))


def bootstrap_auc_ci_chunked(
    y_true, y_score, n_boot=2000,
    *,
    chunk_size=200,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Chunked-cancellable sibling of :func:`bootstrap_auc_ci`. Same shared
    RNG order so output is bit-equal to the parallel original under matched
    ``(n_boot, seed)``. Cancel polled at chunk boundaries; progress emitted
    after each completed chunk."""
    rng = np.random.RandomState(seed)
    n = len(y_true)
    aucs = []
    done = 0
    while done < n_boot:
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        chunk = min(chunk_size, n_boot - done)
        for _ in range(chunk):
            idx = rng.choice(n, size=n, replace=True)
            if len(np.unique(y_true[idx])) < 2:
                continue
            aucs.append(roc_auc_score(y_true[idx], y_score[idx]))
        done += chunk
        if progress_callback is not None:
            progress_callback(done, n_boot)
    aucs = np.array(aucs)
    return (float(np.percentile(aucs, 2.5)),
            float(np.percentile(aucs, 97.5)),
            float(np.std(aucs, ddof=1)))


# ─── Cluster bootstrap on threshold ────────────────────────────────────────

def cluster_bootstrap_threshold(X, y, n_boot=N_BOOTSTRAP, seed=RANDOM_STATE):
    """
    Cluster bootstrap: resample events (cluster = event) with replacement.
    Returns 95% percentile CI and sign-flip fraction.
    """
    rng = np.random.RandomState(seed)
    n = len(y)

    thresholds = []
    signs = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        if len(np.unique(y[idx])) < 2:
            continue
        thr, coef = fit_lr_threshold(X[idx], y[idx])
        if np.isnan(thr):
            continue
        thresholds.append(thr)
        signs.append(np.sign(coef))

    arr = np.array(thresholds)
    signs = np.array(signs)
    ci = (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))

    # Sign stability: fraction matching the majority sign
    majority = np.sign(np.median(signs)) if len(signs) else 0
    if majority == 0:
        sign_stability = 0.5
    else:
        sign_stability = float(np.mean(signs == majority))

    return ci, sign_stability, arr


def cluster_bootstrap_threshold_serial(
    X, y, n_boot=N_BOOTSTRAP,
    *,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Cancel-aware sibling of :func:`cluster_bootstrap_threshold`. Bit-equal
    output to the parallel original under matched ``(n_boot, seed)``.
    Polls ``cancel_check`` every 50 resamples; raises :class:`CancelledError`
    on True. Emits ``progress_callback(done, total)`` every 50 resamples."""
    rng = np.random.RandomState(seed)
    n = len(y)

    thresholds = []
    signs = []
    for i in range(n_boot):
        if cancel_check is not None and (i % 50 == 0) and cancel_check():
            raise CancelledError()
        idx = rng.choice(n, size=n, replace=True)
        if len(np.unique(y[idx])) < 2:
            continue
        thr, coef = fit_lr_threshold(X[idx], y[idx])
        if np.isnan(thr):
            continue
        thresholds.append(thr)
        signs.append(np.sign(coef))
        if progress_callback is not None and ((i + 1) % 50 == 0):
            progress_callback(i + 1, n_boot)
    if progress_callback is not None and n_boot % 50 != 0:
        progress_callback(n_boot, n_boot)

    arr = np.array(thresholds)
    signs = np.array(signs)
    ci = (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))

    majority = np.sign(np.median(signs)) if len(signs) else 0
    if majority == 0:
        sign_stability = 0.5
    else:
        sign_stability = float(np.mean(signs == majority))

    return ci, sign_stability, arr


def cluster_bootstrap_threshold_chunked(
    X, y, n_boot=N_BOOTSTRAP,
    *,
    chunk_size=200,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Chunked-cancellable sibling of :func:`cluster_bootstrap_threshold`.
    Same shared RNG order so output is bit-equal to the parallel original
    under matched ``(n_boot, seed)``. Cancel polled at chunk boundaries;
    progress emitted after each completed chunk."""
    rng = np.random.RandomState(seed)
    n = len(y)

    thresholds = []
    signs = []
    done = 0
    while done < n_boot:
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        chunk = min(chunk_size, n_boot - done)
        for _ in range(chunk):
            idx = rng.choice(n, size=n, replace=True)
            if len(np.unique(y[idx])) < 2:
                continue
            thr, coef = fit_lr_threshold(X[idx], y[idx])
            if np.isnan(thr):
                continue
            thresholds.append(thr)
            signs.append(np.sign(coef))
        done += chunk
        if progress_callback is not None:
            progress_callback(done, n_boot)

    arr = np.array(thresholds)
    signs = np.array(signs)
    ci = (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))

    majority = np.sign(np.median(signs)) if len(signs) else 0
    if majority == 0:
        sign_stability = 0.5
    else:
        sign_stability = float(np.mean(signs == majority))

    return ci, sign_stability, arr


# ─── Permutation null on LOO AUC ────────────────────────────────────────────

def _perm_seeds(n_perm, seed=RANDOM_STATE):
    """Per-permutation seeds. Used by both the parallel and serial paths so
    matched ``(n_perm, seed)`` produce bit-equal null-AUC arrays."""
    rng = np.random.RandomState(seed)
    return rng.randint(0, 2**31, size=n_perm)


def _run_one_loo_perm(X, y, seed):
    """Shuffle labels, rerun LOO-CV, return AUC."""
    rng = np.random.RandomState(seed)
    y_perm = rng.permutation(y)
    try:
        auc, _ = loo_auc(X, y_perm)
    except ValueError:
        auc = 0.5
    return float(auc)


def permutation_test_loo(X, y, observed_auc, n_perm, n_jobs=1, *, seed=RANDOM_STATE):
    """
    Label-shuffle permutation test. Null = LOO-AUC under shuffled labels.
    p = (1 + count(null >= observed)) / (1 + n_perm)  [Phipson & Smyth 2010]
    """
    seeds = _perm_seeds(n_perm, seed)
    null_aucs = Parallel(n_jobs=n_jobs, verbose=0)(
        delayed(_run_one_loo_perm)(X, y, int(s)) for s in seeds
    )
    null_aucs = np.array(null_aucs)
    p_value = float((1 + np.sum(null_aucs >= observed_auc)) / (1 + n_perm))
    return p_value, null_aucs


def permutation_test_loo_serial(
    X, y, observed_auc, n_perm,
    *,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Cancel-aware sibling of :func:`permutation_test_loo`. Same per-perm
    seeded loop, run serially. Polls ``cancel_check`` every iteration;
    raises :class:`CancelledError` on True. Emits ``progress_callback(done,
    total)`` every 25 iterations.

    Returns ``(p_value, null_aucs)`` bit-equal to the parallel path under
    matched ``(n_perm, seed)`` because both consume :func:`_perm_seeds` in
    the same order."""
    seeds = _perm_seeds(n_perm, seed)
    null_aucs = []
    for i, s in enumerate(seeds):
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        null_aucs.append(_run_one_loo_perm(X, y, int(s)))
        if progress_callback is not None and ((i + 1) % 25 == 0):
            progress_callback(i + 1, n_perm)
    if progress_callback is not None and n_perm % 25 != 0:
        progress_callback(n_perm, n_perm)
    null_aucs = np.array(null_aucs)
    p_value = float((1 + np.sum(null_aucs >= observed_auc)) / (1 + n_perm))
    return p_value, null_aucs


def permutation_test_loo_chunked(
    X, y, observed_auc, n_perm,
    *,
    chunk_size=100,
    n_jobs=-1,
    seed=RANDOM_STATE,
    cancel_check=None,
    progress_callback=None,
):
    """Chunked-parallel cancellable sibling of :func:`permutation_test_loo`.

    Splits :func:`_perm_seeds(n_perm, seed)` into chunks of ``chunk_size``
    and runs each chunk under ``Parallel(n_jobs=n_jobs)``. Cancel polled
    BEFORE each chunk so the worst-case cancel latency is one chunk
    (~300 ms on a fast machine for chunk_size=100).

    Output is bit-equal to :func:`permutation_test_loo` under matched
    ``(n_perm, seed)``: both consume :func:`_perm_seeds` in the same order
    and joblib preserves input ordering when assembling the result list.
    Each ``_run_one_loo_perm(X, y, seed)`` is deterministic given the seed.

    ``progress_callback(done, total)`` is emitted after each completed
    chunk."""
    seeds = _perm_seeds(n_perm, seed)
    null_aucs: list = []
    done = 0
    while done < n_perm:
        if cancel_check is not None and cancel_check():
            raise CancelledError()
        chunk_end = min(done + chunk_size, n_perm)
        chunk_seeds = seeds[done:chunk_end]
        chunk_results = Parallel(n_jobs=n_jobs, verbose=0)(
            delayed(_run_one_loo_perm)(X, y, int(s)) for s in chunk_seeds
        )
        null_aucs.extend(chunk_results)
        done = chunk_end
        if progress_callback is not None:
            progress_callback(done, n_perm)
    null_aucs = np.array(null_aucs)
    p_value = float((1 + np.sum(null_aucs >= observed_auc)) / (1 + n_perm))
    return p_value, null_aucs


# ─── Sens/spec stratified bootstrap CI ──────────────────────────────────────
# Byte-for-byte port of code_release/scripts/4_timeline_amplitude_threshold_
# classifier.py. Dedicated SENS_SPEC_SEED (distinct from RANDOM_STATE) to
# reproduce the manuscript-published CIs.

def _sens_spec(y, pred):
    tp = int(np.sum((y == 1) & (pred == 1)))
    fn = int(np.sum((y == 1) & (pred == 0)))
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    sens = tp / (tp + fn) if (tp + fn) else float("nan")
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    return sens, spec


def stratified_bootstrap_sens_spec_ci(
    y, oof_prob, n_boot=SENS_SPEC_N_BOOT, seed=SENS_SPEC_SEED,
):
    """Stratified bootstrap CIs on sens/spec at oof_prob >= 0.5.

    Resample craving and neutral event indices independently with replacement;
    re-evaluate predictions on the bootstrap sample; report 2.5/97.5
    percentiles. Uses a DEDICATED seed (``SENS_SPEC_SEED = 20260423``) distinct
    from the main pipeline's ``RANDOM_STATE = 42`` to match the
    manuscript-published values.
    """
    rng = np.random.RandomState(seed)
    pos = np.where(y == 1)[0]
    neg = np.where(y == 0)[0]
    sens_b = []
    spec_b = []
    for _ in range(n_boot):
        ip = rng.choice(pos, size=len(pos), replace=True)
        ine = rng.choice(neg, size=len(neg), replace=True)
        idx = np.concatenate([ip, ine])
        pred_b = (oof_prob[idx] >= 0.5).astype(int)
        s, sp = _sens_spec(y[idx], pred_b)
        sens_b.append(s)
        spec_b.append(sp)
    sens_arr = np.array(sens_b)
    spec_arr = np.array(spec_b)
    return (
        (float(np.percentile(sens_arr, 2.5)),
         float(np.percentile(sens_arr, 97.5))),
        (float(np.percentile(spec_arr, 2.5)),
         float(np.percentile(spec_arr, 97.5))),
    )


# ─── Rank-biserial r BCa bootstrap CI ───────────────────────────────────────
# Byte-for-byte port of the reference script (independent stream, seed 2025).

def _rrb_point(crav, nc):
    n1, n2 = crav.size, nc.size
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u, _ = mannwhitneyu(crav, nc, alternative="two-sided")
    return float((2 * u) / (n1 * n2) - 1)


def _bca_interval(theta_hat, theta_boot, theta_jack, alpha=RRB_BOOTSTRAP_ALPHA):
    boot = np.asarray(theta_boot, dtype=float)
    jack = np.asarray(theta_jack, dtype=float)
    B = boot.size
    prop = float(np.mean(boot < theta_hat))
    prop = np.clip(prop, 0.5 / B, 1.0 - 0.5 / B)
    z0 = norm.ppf(prop)
    diffs = jack.mean() - jack
    num = np.sum(diffs ** 3)
    den = 6.0 * (np.sum(diffs ** 2)) ** 1.5
    a = float(num / den) if den > 0 else 0.0
    z_lo = norm.ppf(alpha / 2)
    z_hi = norm.ppf(1 - alpha / 2)

    def _adj(z):
        denom = 1.0 - a * (z0 + z)
        return None if denom <= 0 else norm.cdf(z0 + (z0 + z) / denom)

    a1, a2 = _adj(z_lo), _adj(z_hi)
    if a1 is None or a2 is None:
        a1, a2 = alpha / 2, 1 - alpha / 2
    lo = float(np.quantile(boot, np.clip(a1, 0.0, 1.0)))
    hi = float(np.quantile(boot, np.clip(a2, 0.0, 1.0)))
    return lo, hi


def bca_bootstrap_rrb(crav, nc, n_boot=RRB_BOOTSTRAP_N,
                      seed=RRB_BOOTSTRAP_SEED, alpha=RRB_BOOTSTRAP_ALPHA):
    crav = np.asarray(crav, dtype=float)
    nc = np.asarray(nc, dtype=float)
    n1, n2 = crav.size, nc.size
    rng = np.random.default_rng(seed)

    r_hat = _rrb_point(crav, nc)

    r_boot = np.empty(n_boot)
    for b in range(n_boot):
        i1 = rng.integers(0, n1, size=n1)
        i2 = rng.integers(0, n2, size=n2)
        r_boot[b] = _rrb_point(crav[i1], nc[i2])

    r_jack = np.empty(n1 + n2)
    for i in range(n1):
        r_jack[i] = _rrb_point(np.delete(crav, i), nc)
    for j in range(n2):
        r_jack[n1 + j] = _rrb_point(crav, np.delete(nc, j))

    lo, hi = _bca_interval(r_hat, r_boot, r_jack, alpha)
    return r_hat, lo, hi


# ─── Per-hemisphere pipeline ────────────────────────────────────────────────

def run_hemisphere(patient_id, container, hemisphere, n_perm, n_jobs):
    from lfp_threshold_publication import extract_offset_matrix
    print(f"\n  {patient_id} {hemisphere.upper()}")
    print(f"  {'─' * 50}")

    offset_lfps, y = extract_offset_matrix(patient_id, container, hemisphere)
    n_c = int(np.sum(y == 1))
    n_n = int(np.sum(y == 0))
    print(f"  Events: {n_c} craving, {n_n} neutral")

    if n_c < MIN_EVENTS_PER_CLASS or n_n < MIN_EVENTS_PER_CLASS:
        print(f"  Insufficient data (min {MIN_EVENTS_PER_CLASS}/class)")
        return None

    # Match publication: median aggregation, drop all-NaN events
    X_raw = np.nanmedian(offset_lfps, axis=0)
    valid = ~np.isnan(X_raw)
    X = X_raw[valid]
    y_v = y[valid]

    # Classic statistics (Cohen's d, Mann-Whitney) — same as publication
    stats = compute_classic_stats(X, y_v)
    print(f"  Cohen's d: {stats['cohens_d']:.3f}  MW p: {stats['mann_whitney_p']:.4f}")

    # Full-data LR threshold (the deployable number)
    lr_threshold, lr_coef = fit_lr_threshold(X, y_v)
    direction = "above" if lr_coef > 0 else "below"
    print(f"  LR threshold: {lr_threshold:.0f} uV (craving {direction})")

    # Youden's J threshold (secondary, on empirical ROC of X)
    yj_threshold, yj_J, yj_craving_above = youden_threshold(X, y_v)
    print(f"  Youden's J threshold: {yj_threshold:.0f} uV  (J = {yj_J:.3f})")
    print(f"  Δ(LR - Youden's J): {lr_threshold - yj_threshold:+.0f} uV")

    # LOO-CV AUC on pooled out-of-fold predictions
    print(f"  Running LOO-CV...")
    t0 = time.time()
    auc_loo, oof_prob = loo_auc(X, y_v)
    _, fold_thresholds, fold_signs = loo_predict(X, y_v)
    print(f"  LOO AUC: {auc_loo:.3f}  ({time.time() - t0:.1f}s)")

    # Bootstrap CI on LOO AUC
    auc_ci_lo, auc_ci_hi, auc_std = bootstrap_auc_ci(y_v, oof_prob, n_boot=2000)
    print(f"  AUC bootstrap 95% CI: [{auc_ci_lo:.3f}, {auc_ci_hi:.3f}]")

    # Cluster bootstrap on threshold
    print(f"  Cluster bootstrap on threshold ({N_BOOTSTRAP} resamples)...")
    thr_ci, sign_stability, boot_thresholds = cluster_bootstrap_threshold(X, y_v)
    print(f"  Threshold 95% CI: [{thr_ci[0]:.0f}, {thr_ci[1]:.0f}] uV")
    print(f"  Sign stability: {sign_stability:.1%}")

    # LOO-fold threshold stability (each fold is trained on n-1)
    fold_thr_valid = fold_thresholds[~np.isnan(fold_thresholds)]
    fold_thr_median = float(np.median(fold_thr_valid))
    fold_thr_iqr = (float(np.percentile(fold_thr_valid, 25)),
                    float(np.percentile(fold_thr_valid, 75)))
    fold_sign_stability = float(np.mean(np.sign(fold_signs) == np.sign(lr_coef)))

    # Performance at fitted threshold (using oof predictions at 0.5)
    y_pred = (oof_prob >= 0.5).astype(int)
    tp = int(np.sum((y_v == 1) & (y_pred == 1)))
    fn = int(np.sum((y_v == 1) & (y_pred == 0)))
    fp = int(np.sum((y_v == 0) & (y_pred == 1)))
    tn = int(np.sum((y_v == 0) & (y_pred == 0)))
    sens = tp / (tp + fn) if (tp + fn) else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    ppv = tp / (tp + fp) if (tp + fp) else 0.0
    npv = tn / (tn + fn) if (tn + fn) else 0.0

    # Performance at Youden's J on X directly (not via probabilities)
    if yj_craving_above:
        yj_pred = (X >= yj_threshold).astype(int)
    else:
        yj_pred = (X <= yj_threshold).astype(int)
    yj_tp = int(np.sum((y_v == 1) & (yj_pred == 1)))
    yj_fn = int(np.sum((y_v == 1) & (yj_pred == 0)))
    yj_fp = int(np.sum((y_v == 0) & (yj_pred == 1)))
    yj_tn = int(np.sum((y_v == 0) & (yj_pred == 0)))
    yj_sens = yj_tp / (yj_tp + yj_fn) if (yj_tp + yj_fn) else 0.0
    yj_spec = yj_tn / (yj_tn + yj_fp) if (yj_tn + yj_fp) else 0.0

    # Permutation test on LOO-AUC
    print(f"  Permutation test ({n_perm} perms, {n_jobs} jobs)...")
    t0 = time.time()
    perm_p, null_aucs = permutation_test_loo(X, y_v, auc_loo, n_perm, n_jobs)
    p_floor = 1 / (1 + n_perm)
    p_txt = f"< {p_floor:.4f}" if perm_p <= p_floor + 1e-12 else f"= {perm_p:.4f}"
    print(f"  Permutation p {p_txt}  ({time.time() - t0:.1f}s)")

    verdict_auc_ok = auc_ci_lo > 0.5
    verdict_perm_ok = perm_p < 0.05
    verdict = verdict_auc_ok and verdict_perm_ok

    return {
        "patient_id": patient_id,
        "hemisphere": hemisphere,
        "n_craving": n_c,
        "n_neutral": n_n,
        "n_valid": len(y_v),
        "stats": stats,
        "lr_threshold": lr_threshold,
        "lr_coef": lr_coef,
        "direction": direction,
        "lr_threshold_ci": thr_ci,
        "sign_stability": sign_stability,
        "yj_threshold": yj_threshold,
        "yj_J": yj_J,
        "yj_craving_above": yj_craving_above,
        "auc_loo": auc_loo,
        "auc_ci": (auc_ci_lo, auc_ci_hi),
        "auc_std": auc_std,
        "fold_thr_median": fold_thr_median,
        "fold_thr_iqr": fold_thr_iqr,
        "fold_sign_stability": fold_sign_stability,
        "sensitivity_lr": sens, "specificity_lr": spec,
        "ppv_lr": ppv, "npv_lr": npv,
        "sensitivity_yj": yj_sens, "specificity_yj": yj_spec,
        "perm_p": perm_p,
        "null_aucs": null_aucs,
        "verdict": verdict,
        "verdict_auc_ok": verdict_auc_ok,
        "verdict_perm_ok": verdict_perm_ok,
    }


# ─── Report ─────────────────────────────────────────────────────────────────

def generate_report(all_results, n_perm):
    L = []
    L.append("# Bulletproof LFP Threshold Analysis — LOO Sanity Test")
    L.append("")
    L.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append(f"**Goal:** verify publication threshold findings under "
             f"LOO-CV + cluster bootstrap + {n_perm}-perm null")
    L.append("")
    L.append("## Pre-specifications (locked)")
    L.append("")
    L.append("- Data: identical to publication (`extract_offset_matrix`)")
    L.append("- Aggregation: median across 7 bins (`np.nanmedian`)")
    L.append("- Classifier: L2-LogReg, `class_weight='balanced'`")
    L.append("- Primary threshold: `-intercept / coef` from full-data fit")
    L.append("- Secondary threshold: Youden's J on empirical ROC of X")
    L.append("- Validation: LeaveOneOut on events")
    L.append(f"- Threshold CI: cluster bootstrap ({N_BOOTSTRAP} resamples, "
             "events resampled with replacement)")
    L.append(f"- Null: label-shuffle + full LOO rerun × {n_perm}")
    L.append("")
    L.append("**Verdict rule:** survives = AUC CI lower bound > 0.5 AND perm p < 0.05")
    L.append("")
    L.append("---")
    L.append("")

    # Comparison table vs publication
    pub_ref = {
        ("pt2", "left"):  {"thr": 1117, "auc": 0.764, "p": "< 0.005"},
        ("pt2", "right"): {"thr": 980,  "auc": 0.758, "p": "< 0.005"},
        ("pt1",     "left"):  {"thr": 636,  "auc": 0.605, "p": "0.020"},
        ("pt1",     "right"): {"thr": None, "auc": 0.534, "p": "0.259"},
    }
    patient_label = {"pt2": "Pt2", "pt1": "Pt1"}

    L.append("## Summary Comparison")
    L.append("")
    L.append("| Hemisphere | Pub threshold (µV) | Bulletproof threshold (µV) | Pub AUC | LOO AUC | LOO AUC 95% CI | Perm p (LOO) | Verdict |")
    L.append("|:--|:--:|:--:|:--:|:--:|:--:|:--:|:--:|")

    for (pid, hemi), r in all_results.items():
        label = f"{patient_label[pid]} {hemi[0].upper()}"
        pub = pub_ref.get((pid, hemi), {})
        pub_thr = f"{pub.get('thr')}" if pub.get("thr") else "—"
        pub_auc = f"{pub.get('auc', 'n/a'):.3f}" if isinstance(pub.get('auc'), float) else "—"
        pub_p = pub.get("p", "—")

        if r is None:
            L.append(f"| {label} | {pub_thr} | — | {pub_auc} | — | — | — | insufficient |")
            continue

        p_floor = 1 / (1 + n_perm)
        p_txt = f"< {p_floor:.4f}" if r["perm_p"] <= p_floor + 1e-12 else f"{r['perm_p']:.4f}"
        verdict_txt = "✓ survives" if r["verdict"] else "✗ fails"
        L.append(
            f"| {label} | {pub_thr} | {r['lr_threshold']:.0f} "
            f"| {pub_auc} | {r['auc_loo']:.3f} "
            f"| [{r['auc_ci'][0]:.3f}, {r['auc_ci'][1]:.3f}] "
            f"| {p_txt} | {verdict_txt} |"
        )
    L.append("")

    L.append("---")
    L.append("")
    L.append("## Per-Hemisphere Detail")

    for (pid, hemi), r in all_results.items():
        label = f"{patient_label[pid]} {hemi.upper()}"
        L.append("")
        L.append(f"### {label}")
        L.append("")
        if r is None:
            L.append("Insufficient data for analysis.")
            continue

        stats = r["stats"]
        L.append(f"- Events: {r['n_craving']} craving, {r['n_neutral']} neutral "
                 f"(n_valid = {r['n_valid']})")
        L.append(f"- Craving: {stats['craving_mean']:.0f} ± {stats['craving_std']:.0f} µV "
                 f"(median {stats['craving_median']:.0f})")
        L.append(f"- Neutral: {stats['neutral_mean']:.0f} ± {stats['neutral_std']:.0f} µV "
                 f"(median {stats['neutral_median']:.0f})")
        L.append(f"- Cohen's d = {stats['cohens_d']:.3f} "
                 f"[{stats['cohens_d_ci'][0]:.3f}, {stats['cohens_d_ci'][1]:.3f}]")
        L.append(f"- Mann-Whitney U p = {stats['mann_whitney_p']:.4f}; "
                 f"rank-biserial r = {stats['rank_biserial']:.3f}")
        L.append("")
        L.append("#### Thresholds")
        L.append("")
        L.append(f"| | LR (balanced-weight) | Youden's J |")
        L.append(f"|:--|:--:|:--:|")
        L.append(f"| Threshold (µV) | {r['lr_threshold']:.0f} | {r['yj_threshold']:.0f} |")
        L.append(f"| Direction | craving {r['direction']} | craving "
                 f"{'above' if r['yj_craving_above'] else 'below'} |")
        L.append(f"| Sensitivity | {r['sensitivity_lr']:.1%} | {r['sensitivity_yj']:.1%} |")
        L.append(f"| Specificity | {r['specificity_lr']:.1%} | {r['specificity_yj']:.1%} |")
        L.append("")
        L.append(f"- LR threshold 95% CI (cluster bootstrap): "
                 f"[{r['lr_threshold_ci'][0]:.0f}, {r['lr_threshold_ci'][1]:.0f}] µV")
        L.append(f"- Coefficient sign stability: {r['sign_stability']:.1%} "
                 f"(fraction of bootstrap replicates matching majority sign)")
        L.append(f"- LOO-fold threshold median: {r['fold_thr_median']:.0f} µV "
                 f"(IQR [{r['fold_thr_iqr'][0]:.0f}, {r['fold_thr_iqr'][1]:.0f}])")
        L.append(f"- LOO-fold sign stability: {r['fold_sign_stability']:.1%}")
        L.append(f"- PPV = {r['ppv_lr']:.1%}, NPV = {r['npv_lr']:.1%}")
        L.append("")
        L.append("#### LOO-CV AUC")
        L.append("")
        L.append(f"- AUC = {r['auc_loo']:.3f} "
                 f"[95% CI {r['auc_ci'][0]:.3f}, {r['auc_ci'][1]:.3f}]")
        L.append(f"- Bootstrap SD: {r['auc_std']:.3f}")
        p_floor = 1 / (1 + n_perm)
        p_txt = (f"< {p_floor:.4f}" if r["perm_p"] <= p_floor + 1e-12
                 else f"= {r['perm_p']:.4f}")
        L.append(f"- Permutation p {p_txt} ({n_perm} permutations)")
        L.append(f"- Null AUC distribution: mean {np.mean(r['null_aucs']):.3f}, "
                 f"95th pctile {np.percentile(r['null_aucs'], 95):.3f}")
        L.append("")
        L.append(f"**Verdict:** {'✓ survives' if r['verdict'] else '✗ fails'} "
                 f"(AUC lower CI > 0.5: {r['verdict_auc_ok']}; "
                 f"perm p < 0.05: {r['verdict_perm_ok']})")

    L.append("")
    L.append("---")
    L.append("")
    L.append("## Methodological notes")
    L.append("")
    L.append(
        "**LOO vs K-fold.** LOO is deterministic (no seed), uses n-1 events "
        "per fit (maximum training data), and produces one out-of-fold "
        "prediction per event. At small n (minority class 22–43), K-fold "
        "introduces fold-assignment noise that dominates true generalization "
        "variance; LOO collapses this."
    )
    L.append("")
    L.append(
        "**Cluster bootstrap on threshold.** Resampling events (cluster = "
        "event) with replacement respects event-level independence; the "
        "publication's stratified-within-class bootstrap does not."
    )
    L.append("")
    L.append(
        "**Youden's J on raw X.** Secondary threshold from empirical ROC. "
        "Does not depend on LR parametric form or class-weight choice. "
        "Agreement with LR threshold (Δ = LR − J) is an interpretability "
        "sanity check; disagreement indicates the LR-balanced decision "
        "surface is shifted by class reweighting."
    )
    L.append("")
    L.append(
        "**Limits of this test.** Does not address (i) same-day temporal "
        "autocorrelation (would need LOGO-by-day), (ii) stimulation program "
        "confound, (iii) the 7.81 Hz vs classifier-optimal band mismatch. "
        "These remain open concerns regardless of LOO outcome."
    )
    L.append("")

    return "\n".join(L)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    from lfp_threshold_publication import PATIENTS, HEMISPHERES
    from src.infrastructure.container import ApplicationContainer
    parser = argparse.ArgumentParser(
        description="Bulletproof LFP Threshold — LOO Sanity Test",
    )
    parser.add_argument("--n-perm", type=int, default=DEFAULT_N_PERM)
    parser.add_argument("--n-jobs", type=int, default=-1)
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  BULLETPROOF LFP THRESHOLD — LOO SANITY TEST")
    print(f"  Patients: {', '.join(PATIENTS)}")
    print(f"  Permutations: {args.n_perm}  |  Jobs: {args.n_jobs}")
    print(f"{'=' * 60}")

    container = ApplicationContainer()
    output_dir = project_root / "results" / "lfp_threshold"

    all_results = {}
    t_start = time.time()
    for pid in PATIENTS:
        for hemi in HEMISPHERES:
            r = run_hemisphere(pid, container, hemi, args.n_perm, args.n_jobs)
            all_results[(pid, hemi)] = r

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY  (total time: {(time.time() - t_start)/60:.1f} min)")
    print(f"{'=' * 60}")
    for (pid, hemi), r in all_results.items():
        if r is None:
            print(f"  {pid} {hemi.upper()}: insufficient")
            continue
        v = "✓ survives" if r["verdict"] else "✗ fails"
        p_floor = 1 / (1 + args.n_perm)
        p_txt = (f"< {p_floor:.4f}" if r["perm_p"] <= p_floor + 1e-12
                 else f"{r['perm_p']:.4f}")
        print(f"  {pid} {hemi.upper()}: {v}  |  thr {r['lr_threshold']:.0f}µV "
              f"| AUC {r['auc_loo']:.3f} "
              f"[{r['auc_ci'][0]:.3f}, {r['auc_ci'][1]:.3f}]"
              f"  | p {p_txt}")

    # Report
    report = generate_report(all_results, args.n_perm)
    report_path = output_dir / "bulletproof_threshold_report.md"
    report_path.write_text(report)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
