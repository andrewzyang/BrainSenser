#!/usr/bin/env python3
"""Timeline amplitude-threshold classifier for craving vs non-craving.

Feature
-------
Per-event scalar: ``np.nanmean`` of BrainSense Timeline narrowband amplitude
(uV) across the 5 offset bins at [-20, -10, 0, +10, +20] min, with +/-5 min
tolerance per bin. Outlier rows (``is_outlier == 1``) are dropped before
binning.

Event exclusion
---------------
- Same-timestamp mixed-label events discarded.
- Cross-class events within 60 min mutually excluded.
- NO same-class connected-component pruning (that is a script #3 rule;
  script #4 retains close-in-time same-class events).

Classifier
----------
L2 logistic regression (``LogisticRegression(C=1, class_weight='balanced',
random_state=42, max_iter=1000)``). The decision threshold in uV is
``-intercept / coefficient`` from the full-data fit. Leave-one-out CV
yields pooled out-of-fold probabilities ``p_i = predict_proba_i(c=1)``.

Pipeline outputs
----------------
- LOO AUC: ``roc_auc_score(y, oof_prob)``.
- AUC 95% CI: 2,000-iter bootstrap of (event, label, score) triples,
  ``seed=42``.
- Threshold 95% CI: 2,000-iter cluster bootstrap (events resampled with
  replacement; refit the LR per resample; report 2.5/97.5 percentiles),
  ``seed=42``.
- LOO-fold threshold median + IQR: median and Q1/Q3 of per-fold
  ``-intercept_i / coef_i``.
- Sensitivity / Specificity at ``oof_prob >= 0.5`` (the LR decision
  boundary on the LOO probabilities). 95% CIs: stratified bootstrap on
  craving and neutral event indices independently (2,000 resamples),
  ``RNG_SEED=20260423`` (a separate seed from the main pipeline).
- Cohen's d on per-event mean amplitude with 2,000-iter stratified
  bootstrap CI, ``seed=42``.
- Rank-biserial r (Mann-Whitney) on per-event mean amplitude with
  5,000-iter stratified BCa bootstrap CI, ``seed=2025``.
- Permutation p: 10,000 label-shuffle permutations, each rerunning the
  full LOO-CV; p = ``(1 + #(null_auc >= obs_auc)) / (1 + n_perm)``
  (Phipson-Smyth 2010), ``seed=42``. Parallelized via joblib; pass
  ``--n-jobs 8`` for the validation-equivalent run.

Usage
-----
::

  python 4_timeline_amplitude_threshold_classifier.py \\
      --pt1-snapshots ../data/pt1_snapshots_native.csv \\
      --pt2-snapshots ../data/pt2_snapshots.csv \\
      --pt1-timeline ../data/pt1_timeline.csv \\
      --pt2-timeline ../data/pt2_timeline.csv \\
      --out-dir ../out --n-jobs 8 --panels pt1_left pt2_left pt2_right

Pt1 right NAc is intentionally excluded from the manuscript headline
(Supplementary Note 2 — electrode-position artifact). The script computes
all four hemispheres; the ``--panels`` flag selects which to retain.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats
from scipy.stats import beta as beta_dist
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import LeaveOneOut

warnings.filterwarnings("ignore")


# ============================================================================
# Constants (locked spec)
# ============================================================================

WINDOW_MINUTES = 20
OFFSET_BINS = [-20, -10, 0, 10, 20]
BIN_TOLERANCE = 5

CRAVING_KEYWORDS = ["Craving", "Drinking"]
NEUTRAL_KEYWORDS = ["Happy", "Neutral"]

MIN_EVENTS_PER_CLASS = 10
MIN_INTER_EVENT_MINUTES = 60

# Main pipeline seed (LOO, threshold CI, AUC CI, permutation).
RANDOM_STATE = 42
N_BOOTSTRAP = 2000
DEFAULT_N_PERM = 10000

# r_rb BCa bootstrap stream (matches the compute_missing_effect_sizes companion).
RRB_BOOTSTRAP_N = 5000
RRB_BOOTSTRAP_SEED = 2025
RRB_BOOTSTRAP_ALPHA = 0.05

# Sensitivity / specificity stratified bootstrap stream.
SENS_SPEC_N_BOOT = 2000
SENS_SPEC_SEED = 20260423

# Panels: (patient_id, hemisphere). Pt1 right is excluded from the headline
# but the script computes it for completeness.
PANELS = [
    ("pt1", "left"),
    ("pt1", "right"),
    ("pt2", "left"),
    ("pt2", "right"),
]


# ============================================================================
# CSV ingestion
# ============================================================================


def parse_ts(s) -> datetime:
    """Parse ISO-8601; coerce to UTC tz-aware."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def classify_event(event_name: Optional[str]) -> Optional[str]:
    if event_name is None:
        return None
    upper = event_name.upper()
    for kw in CRAVING_KEYWORDS:
        if kw.upper() in upper:
            return "craving"
    for kw in NEUTRAL_KEYWORDS:
        if kw.upper() in upper:
            return "neutral"
    return None


def load_snapshots_csv(csv_path: Path) -> List[Tuple[datetime, str]]:
    """Return [(timestamp, event_name)] deduplicated by (timestamp, name)
    so the multi-hemisphere rows collapse into one event per (ts, name)."""
    df = pd.read_csv(csv_path)
    df = df.drop_duplicates(subset=["time", "snapshot_name"])
    return [(parse_ts(t), n) for t, n in zip(df["time"], df["snapshot_name"])]


def load_timeline_csv(csv_path: Path, hemi: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return (unix_ts, value) float64 arrays for non-outlier rows of the
    requested hemisphere, sorted by timestamp."""
    df = pd.read_csv(csv_path)
    df = df.loc[df["is_outlier"] == 0, ["timestamp", f"{hemi}_uV"]].copy()
    df["unix_ts"] = df["timestamp"].apply(lambda s: parse_ts(s).timestamp())
    df = df.sort_values("unix_ts").reset_index(drop=True)
    ts = df["unix_ts"].to_numpy(dtype=np.float64)
    val = df[f"{hemi}_uV"].to_numpy(dtype=np.float64)
    return ts, val


# ============================================================================
# Offset-matrix extraction (replaces extract_offset_matrix_ext from the
# repository-chain version)
# ============================================================================


def extract_offset_matrix(
    snapshots: List[Tuple[datetime, str]],
    timeline_ts: np.ndarray,
    timeline_val: np.ndarray,
    window_minutes: int = WINDOW_MINUTES,
) -> Tuple[np.ndarray, np.ndarray, List[datetime]]:
    """Build (n_bins, n_events) LFP matrix at +/-window offset bins and a
    matching (n_events,) binary label vector, applying the manuscript's
    two event-exclusion rules.

    Returns (offset_lfps, y, retained_timestamps).
    """
    bins = list(range(-window_minutes, window_minutes + 1, 10))
    bin_set = set(bins)

    by_ts: Dict[datetime, List[str]] = defaultdict(list)
    for ts, name in snapshots:
        label_str = classify_event(name)
        if label_str:
            by_ts[ts].append(label_str)

    sorted_timestamps = sorted(by_ts.keys())

    # Mixed-label exclusion.
    excluded_ts = {ts for ts in sorted_timestamps if len(set(by_ts[ts])) > 1}

    # Cross-class 60-min mutual exclusion.
    for i in range(len(sorted_timestamps)):
        for j in range(i + 1, len(sorted_timestamps)):
            delta = (sorted_timestamps[j] - sorted_timestamps[i]).total_seconds() / 60
            if delta > MIN_INTER_EVENT_MINUTES:
                break
            if set(by_ts[sorted_timestamps[i]]) != set(by_ts[sorted_timestamps[j]]):
                excluded_ts.add(sorted_timestamps[i])
                excluded_ts.add(sorted_timestamps[j])

    window_s = window_minutes * 60.0
    retained_ts: List[datetime] = []
    events: List[Tuple[datetime, int, Dict[int, float]]] = []

    for ts in sorted_timestamps:
        if ts in excluded_ts:
            continue
        label = 1 if by_ts[ts][0] == "craving" else 0
        ts_s = ts.timestamp()
        s_idx = np.searchsorted(timeline_ts, ts_s - window_s, side="left")
        e_idx = np.searchsorted(timeline_ts, ts_s + window_s, side="right")
        by_bin: Dict[int, Tuple[float, float]] = {}
        for k in range(s_idx, e_idx):
            v = timeline_val[k]
            if np.isnan(v):
                continue
            offset_min = (timeline_ts[k] - ts_s) / 60.0
            nearest_bin = int(round(offset_min / 10) * 10)
            if nearest_bin not in bin_set:
                continue
            dist = abs(offset_min - nearest_bin)
            if dist > BIN_TOLERANCE:
                continue
            if nearest_bin not in by_bin or dist < by_bin[nearest_bin][1]:
                by_bin[nearest_bin] = (float(v), dist)
        retained_ts.append(ts)
        events.append((ts, label, {b: by_bin[b][0] for b in by_bin}))

    n_events = len(events)
    offset_lfps = np.full((len(bins), n_events), np.nan)
    y = np.array([e[1] for e in events])
    for j, (_, _, offsets) in enumerate(events):
        for i, b in enumerate(bins):
            if b in offsets:
                offset_lfps[i, j] = offsets[b]

    return offset_lfps, y, retained_ts


# ============================================================================
# Classic statistics — descriptive + Cohen's d (stratified bootstrap CI),
# Mann-Whitney U, rank-biserial point
# ============================================================================


def clopper_pearson_ci(k: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else float(beta_dist.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta_dist.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


def compute_classic_stats(X: np.ndarray, y: np.ndarray,
                          seed: int = RANDOM_STATE,
                          n_boot: int = N_BOOTSTRAP) -> Dict:
    """Cohen's d + stratified bootstrap CI, Mann-Whitney U + r_rb, descriptives."""
    craving, neutral = X[y == 1], X[y == 0]
    n1, n2 = len(craving), len(neutral)

    pooled_sd = np.sqrt(
        ((n1 - 1) * np.var(craving, ddof=1)
         + (n2 - 1) * np.var(neutral, ddof=1))
        / (n1 + n2 - 2)
    )
    d = float((np.mean(craving) - np.mean(neutral)) / pooled_sd) if pooled_sd > 0 else 0.0

    rng = np.random.RandomState(seed)
    boot_d = []
    for _ in range(n_boot):
        c = craving[rng.choice(n1, size=n1, replace=True)]
        n_arr = neutral[rng.choice(n2, size=n2, replace=True)]
        sd = np.sqrt(
            ((n1 - 1) * np.var(c, ddof=1)
             + (n2 - 1) * np.var(n_arr, ddof=1))
            / (n1 + n2 - 2)
        )
        boot_d.append(float((np.mean(c) - np.mean(n_arr)) / sd) if sd > 0 else 0.0)
    d_ci = (float(np.percentile(boot_d, 2.5)),
            float(np.percentile(boot_d, 97.5)))

    U, p_mw = stats.mannwhitneyu(craving, neutral, alternative="two-sided")
    r_rb_point = 2 * float(U) / (n1 * n2) - 1

    return {
        "cohens_d": d, "cohens_d_ci": d_ci,
        "mann_whitney_u": float(U), "mann_whitney_p": float(p_mw),
        "rank_biserial": r_rb_point,
        "craving_mean": float(np.mean(craving)),
        "craving_std": float(np.std(craving, ddof=1)),
        "craving_median": float(np.median(craving)),
        "neutral_mean": float(np.mean(neutral)),
        "neutral_std": float(np.std(neutral, ddof=1)),
        "neutral_median": float(np.median(neutral)),
        "n_craving": n1, "n_neutral": n2,
    }


# ============================================================================
# r_rb BCa bootstrap CI (independent stream, matches the
# compute_missing_effect_sizes companion)
# ============================================================================


def _rrb_point(crav: np.ndarray, nc: np.ndarray) -> float:
    n1, n2 = crav.size, nc.size
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u, _ = stats.mannwhitneyu(crav, nc, alternative="two-sided")
    return float((2 * u) / (n1 * n2) - 1)


def _bca_interval(theta_hat: float,
                  theta_boot: np.ndarray,
                  theta_jack: np.ndarray,
                  alpha: float = RRB_BOOTSTRAP_ALPHA) -> Tuple[float, float]:
    boot = np.asarray(theta_boot, dtype=float)
    jack = np.asarray(theta_jack, dtype=float)
    B = boot.size
    prop = float(np.mean(boot < theta_hat))
    prop = np.clip(prop, 0.5 / B, 1.0 - 0.5 / B)
    z0 = stats.norm.ppf(prop)
    diffs = jack.mean() - jack
    num = np.sum(diffs ** 3)
    den = 6.0 * (np.sum(diffs ** 2)) ** 1.5
    a = float(num / den) if den > 0 else 0.0
    z_lo = stats.norm.ppf(alpha / 2)
    z_hi = stats.norm.ppf(1 - alpha / 2)

    def _adj(z):
        denom = 1.0 - a * (z0 + z)
        return None if denom <= 0 else stats.norm.cdf(z0 + (z0 + z) / denom)

    a1, a2 = _adj(z_lo), _adj(z_hi)
    if a1 is None or a2 is None:
        a1, a2 = alpha / 2, 1 - alpha / 2
    lo = float(np.quantile(boot, np.clip(a1, 0.0, 1.0)))
    hi = float(np.quantile(boot, np.clip(a2, 0.0, 1.0)))
    return lo, hi


def bca_bootstrap_rrb(crav: np.ndarray, nc: np.ndarray,
                      n_boot: int = RRB_BOOTSTRAP_N,
                      seed: int = RRB_BOOTSTRAP_SEED,
                      alpha: float = RRB_BOOTSTRAP_ALPHA
                      ) -> Tuple[float, float, float]:
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


# ============================================================================
# LR classifier + LOO-CV
# ============================================================================


def fit_lr_threshold(X: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """L2-LogReg decision boundary on raw uV; returns (threshold, coef)."""
    clf = LogisticRegression(
        class_weight="balanced", random_state=RANDOM_STATE, max_iter=1000,
    )
    clf.fit(X.reshape(-1, 1), y)
    coef = float(clf.coef_[0, 0])
    intercept = float(clf.intercept_[0])
    if coef == 0:
        return float("nan"), 0.0
    return float(-intercept / coef), coef


def youden_threshold(X: np.ndarray, y: np.ndarray) -> Tuple[float, float, bool]:
    """Empirical Youden's J threshold on raw X. Direction inferred from
    class means."""
    craving_mean = np.mean(X[y == 1])
    neutral_mean = np.mean(X[y == 0])
    craving_above = bool(craving_mean > neutral_mean)
    scores = X if craving_above else -X
    fpr, tpr, thresholds = roc_curve(y, scores)
    J = tpr - fpr
    best_idx = int(np.argmax(J))
    thr = thresholds[best_idx]
    if not craving_above:
        thr = -thr
    return float(thr), float(J[best_idx]), craving_above


def loo_predict(X: np.ndarray, y: np.ndarray
                ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Leave-one-out CV. Returns (oof_prob, fold_thresholds, fold_coef_signs)."""
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
        coef = float(clf.coef_[0, 0])
        if coef != 0:
            fold_thresholds[test_idx[0]] = -float(clf.intercept_[0]) / coef
        fold_coef_signs[test_idx[0]] = np.sign(coef)

    return oof_prob, fold_thresholds, fold_coef_signs


def loo_auc(X: np.ndarray, y: np.ndarray) -> Tuple[float, np.ndarray]:
    """LOO-CV AUC on pooled out-of-fold probabilities."""
    oof_prob, _, _ = loo_predict(X, y)
    return float(roc_auc_score(y, oof_prob)), oof_prob


# ============================================================================
# Bootstrap CIs — AUC, threshold, sens/spec
# ============================================================================


def bootstrap_auc_ci(y_true: np.ndarray, y_score: np.ndarray,
                     n_boot: int = N_BOOTSTRAP,
                     seed: int = RANDOM_STATE) -> Tuple[float, float, float]:
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


def cluster_bootstrap_threshold(X: np.ndarray, y: np.ndarray,
                                n_boot: int = N_BOOTSTRAP,
                                seed: int = RANDOM_STATE
                                ) -> Tuple[Tuple[float, float], float, np.ndarray]:
    """Cluster bootstrap on threshold; cluster = event. Returns
    (ci, sign_stability, all_thresholds)."""
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
    majority = np.sign(np.median(signs)) if len(signs) else 0
    sign_stability = 0.5 if majority == 0 else float(np.mean(signs == majority))
    return ci, sign_stability, arr


def _sens_spec(y: np.ndarray, pred: np.ndarray) -> Tuple[float, float]:
    tp = int(np.sum((y == 1) & (pred == 1)))
    fn = int(np.sum((y == 1) & (pred == 0)))
    tn = int(np.sum((y == 0) & (pred == 0)))
    fp = int(np.sum((y == 0) & (pred == 1)))
    sens = tp / (tp + fn) if (tp + fn) else float("nan")
    spec = tn / (tn + fp) if (tn + fp) else float("nan")
    return sens, spec


def stratified_bootstrap_sens_spec_ci(
    y: np.ndarray, oof_prob: np.ndarray,
    n_boot: int = SENS_SPEC_N_BOOT,
    seed: int = SENS_SPEC_SEED,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Stratified bootstrap CIs on sens/spec at oof_prob >= 0.5.

    Resample craving and neutral event indices independently with replacement;
    re-evaluate predictions on the bootstrap sample; report 2.5/97.5
    percentiles. Uses a DEDICATED seed (``SENS_SPEC_SEED = 20260423``)
    distinct from the main pipeline's ``RANDOM_STATE = 42`` to match the
    manuscript-published values.
    """
    rng = np.random.RandomState(seed)
    pos = np.where(y == 1)[0]
    neg = np.where(y == 0)[0]
    sens_b: List[float] = []
    spec_b: List[float] = []
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


# ============================================================================
# Permutation null (parallelized over seeds)
# ============================================================================


def _perm_seeds(n_perm: int, seed: int = RANDOM_STATE) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return rng.randint(0, 2**31, size=n_perm)


def _run_one_loo_perm(X: np.ndarray, y: np.ndarray, seed: int) -> float:
    rng = np.random.RandomState(seed)
    y_perm = rng.permutation(y)
    try:
        auc, _ = loo_auc(X, y_perm)
    except ValueError:
        auc = 0.5
    return float(auc)


def permutation_test_loo(X: np.ndarray, y: np.ndarray, observed_auc: float,
                         n_perm: int, n_jobs: int = 1,
                         seed: int = RANDOM_STATE
                         ) -> Tuple[float, np.ndarray]:
    seeds = _perm_seeds(n_perm, seed)
    null_aucs = Parallel(n_jobs=n_jobs, verbose=0)(
        delayed(_run_one_loo_perm)(X, y, int(s)) for s in seeds
    )
    null_aucs = np.array(null_aucs)
    p_value = float((1 + np.sum(null_aucs >= observed_auc)) / (1 + n_perm))
    return p_value, null_aucs


# ============================================================================
# Per-hemisphere driver
# ============================================================================


def fmt_p(p: float, n_perm: int) -> str:
    floor = 1.0 / (n_perm + 1)
    if p <= floor + 1e-12:
        return f"< {floor:.5f}"
    if p < 0.001:
        return "< 0.001"
    if p < 0.01:
        return f"= {p:.4f}"
    return f"= {p:.3f}"


def run_hemisphere(
    patient_id: str, hemisphere: str,
    snapshots: List[Tuple[datetime, str]],
    timeline_ts: np.ndarray, timeline_val: np.ndarray,
    n_perm: int, n_jobs: int,
    n_boot: int = N_BOOTSTRAP, seed: int = RANDOM_STATE,
) -> Optional[Dict]:
    print(f"\n  {patient_id} {hemisphere.upper()}  (+/-{WINDOW_MINUTES} min, "
          f"{len(OFFSET_BINS)} bins)", flush=True)
    print(f"  {'-' * 50}", flush=True)

    offset_lfps, y, retained_ts = extract_offset_matrix(
        snapshots, timeline_ts, timeline_val, window_minutes=WINDOW_MINUTES,
    )
    n_total = len(y)
    n_c_total = int(np.sum(y == 1))
    n_n_total = int(np.sum(y == 0))
    print(f"  Events extracted: {n_c_total} craving, {n_n_total} neutral "
          f"(n={n_total})", flush=True)

    coverage = (np.mean(~np.isnan(offset_lfps), axis=1)
                if n_total else np.zeros(0))
    if n_total:
        print(f"  Mean bin fill across {len(OFFSET_BINS)} bins: "
              f"{coverage.mean():.1%}", flush=True)

    X_raw = (np.nanmean(offset_lfps, axis=0) if n_total
             else np.array([], dtype=float))
    valid = ~np.isnan(X_raw)
    X = X_raw[valid]
    y_v = y[valid]
    retained_valid_ts = [retained_ts[i] for i in range(n_total) if valid[i]]

    n_c = int(np.sum(y_v == 1))
    n_n = int(np.sum(y_v == 0))
    dropped = n_total - len(y_v)
    n_bins_per_event = (np.sum(~np.isnan(offset_lfps[:, valid]), axis=0)
                        if n_total else np.zeros(0, dtype=int))
    print(f"  After all-NaN-row drop: {n_c} craving, {n_n} neutral "
          f"({dropped} events dropped with 0 bins)", flush=True)

    if n_c < MIN_EVENTS_PER_CLASS or n_n < MIN_EVENTS_PER_CLASS:
        print(f"  Insufficient data (min {MIN_EVENTS_PER_CLASS}/class)",
              flush=True)
        return None

    classic = compute_classic_stats(X, y_v, seed=seed, n_boot=n_boot)
    print(f"  Cohen's d: {classic['cohens_d']:.3f}  "
          f"MW p: {classic['mann_whitney_p']:.4f}", flush=True)

    lr_threshold, lr_coef = fit_lr_threshold(X, y_v)
    direction = "above" if lr_coef > 0 else "below"
    print(f"  LR threshold: {lr_threshold:.0f} uV (craving {direction})",
          flush=True)

    yj_threshold, yj_J, yj_craving_above = youden_threshold(X, y_v)

    print("  Running LOO-CV...", flush=True)
    t0 = time.time()
    auc_loo_value, oof_prob = loo_auc(X, y_v)
    _, fold_thresholds, fold_signs = loo_predict(X, y_v)
    print(f"  LOO AUC: {auc_loo_value:.3f}  ({time.time() - t0:.1f}s)",
          flush=True)

    auc_ci_lo, auc_ci_hi, auc_std = bootstrap_auc_ci(
        y_v, oof_prob, n_boot=n_boot, seed=seed,
    )
    print(f"  AUC bootstrap 95% CI: "
          f"[{auc_ci_lo:.3f}, {auc_ci_hi:.3f}]", flush=True)

    print(f"  Cluster bootstrap on threshold ({n_boot} resamples)...",
          flush=True)
    thr_ci, sign_stability, _ = cluster_bootstrap_threshold(
        X, y_v, n_boot=n_boot, seed=seed,
    )
    print(f"  Threshold 95% CI: [{thr_ci[0]:.0f}, {thr_ci[1]:.0f}] uV",
          flush=True)

    fold_thr_valid = fold_thresholds[~np.isnan(fold_thresholds)]
    fold_thr_median = float(np.median(fold_thr_valid))
    fold_thr_iqr = (float(np.percentile(fold_thr_valid, 25)),
                    float(np.percentile(fold_thr_valid, 75)))
    fold_sign_stability = float(
        np.mean(np.sign(fold_signs) == np.sign(lr_coef))
    )

    y_pred = (oof_prob >= 0.5).astype(int)
    sens, spec = _sens_spec(y_v, y_pred)
    (sens_ci_lo, sens_ci_hi), (spec_ci_lo, spec_ci_hi) = (
        stratified_bootstrap_sens_spec_ci(
            y_v, oof_prob, n_boot=SENS_SPEC_N_BOOT, seed=SENS_SPEC_SEED,
        )
    )
    print(f"  Sens {sens*100:.1f}% [{sens_ci_lo*100:.1f}, {sens_ci_hi*100:.1f}]   "
          f"Spec {spec*100:.1f}% [{spec_ci_lo*100:.1f}, {spec_ci_hi*100:.1f}]",
          flush=True)

    if yj_craving_above:
        yj_pred = (X >= yj_threshold).astype(int)
    else:
        yj_pred = (X <= yj_threshold).astype(int)
    yj_sens, yj_spec = _sens_spec(y_v, yj_pred)

    print(f"  Permutation test ({n_perm} perms, {n_jobs} jobs)...",
          flush=True)
    t0 = time.time()
    perm_p, null_aucs = permutation_test_loo(
        X, y_v, auc_loo_value, n_perm, n_jobs=n_jobs, seed=seed,
    )
    p_floor = 1.0 / (1.0 + n_perm)
    print(f"  Permutation p {fmt_p(perm_p, n_perm)}  "
          f"({time.time() - t0:.1f}s)", flush=True)

    crav_X = X[y_v == 1]
    neut_X = X[y_v == 0]
    r_rb_point, r_rb_lo, r_rb_hi = bca_bootstrap_rrb(crav_X, neut_X)

    return {
        "patient_id": patient_id, "hemisphere": hemisphere,
        "X": X, "y": y_v,
        "retained_timestamps": [t.isoformat() for t in retained_valid_ts],
        "fold_thresholds": fold_thresholds, "fold_signs": fold_signs,
        "n_craving": n_c, "n_neutral": n_n, "n_valid": len(y_v),
        "n_dropped": dropped,
        "stats": classic,
        "lr_threshold": float(lr_threshold), "lr_coef": float(lr_coef),
        "lr_coef_sign": int(np.sign(lr_coef)),
        "direction": direction,
        "lr_threshold_ci": (float(thr_ci[0]), float(thr_ci[1])),
        "sign_stability": float(sign_stability),
        "yj_threshold": float(yj_threshold), "yj_J": float(yj_J),
        "yj_craving_above": yj_craving_above,
        "auc_loo": float(auc_loo_value),
        "oof_prob": oof_prob,
        "auc_ci": (float(auc_ci_lo), float(auc_ci_hi)),
        "auc_std": float(auc_std),
        "fold_thr_median": fold_thr_median,
        "fold_thr_iqr": fold_thr_iqr,
        "fold_sign_stability": fold_sign_stability,
        "sensitivity_lr": float(sens), "specificity_lr": float(spec),
        "sens_ci": (float(sens_ci_lo), float(sens_ci_hi)),
        "spec_ci": (float(spec_ci_lo), float(spec_ci_hi)),
        "sensitivity_yj": float(yj_sens), "specificity_yj": float(yj_spec),
        "perm_p": float(perm_p), "perm_p_floor": float(p_floor),
        "n_perm": int(n_perm), "n_boot": int(n_boot),
        "mann_whitney_p": float(classic["mann_whitney_p"]),
        "rank_biserial_point": float(classic["rank_biserial"]),
        "r_rb": float(r_rb_point),
        "r_rb_ci_lo": float(r_rb_lo), "r_rb_ci_hi": float(r_rb_hi),
        "null_aucs": null_aucs,
    }


# ============================================================================
# Output writers
# ============================================================================


HEADLINE_COLS = [
    "patient", "hemisphere", "n_craving", "n_non_craving",
    "auc", "auc_ci_lo", "auc_ci_hi",
    "threshold_uv", "threshold_ci_lo", "threshold_ci_hi",
    "threshold_fold_median", "threshold_fold_iqr_lo", "threshold_fold_iqr_hi",
    "sens", "sens_ci_lo", "sens_ci_hi",
    "spec", "spec_ci_lo", "spec_ci_hi",
    "youden_j", "p_perm", "perm_p_floor", "n_perm", "lr_coef_sign",
    "cohens_d", "cohens_d_ci_lo", "cohens_d_ci_hi",
    "r_rb", "r_rb_ci_lo", "r_rb_ci_hi",
]


def write_headline_csv(results: List[Dict], path: Path) -> None:
    rows = []
    for r in results:
        rows.append({
            "patient": r["patient_id"],
            "hemisphere": r["hemisphere"],
            "n_craving": r["n_craving"],
            "n_non_craving": r["n_neutral"],
            "auc": r["auc_loo"],
            "auc_ci_lo": r["auc_ci"][0],
            "auc_ci_hi": r["auc_ci"][1],
            "threshold_uv": r["lr_threshold"],
            "threshold_ci_lo": r["lr_threshold_ci"][0],
            "threshold_ci_hi": r["lr_threshold_ci"][1],
            "threshold_fold_median": r["fold_thr_median"],
            "threshold_fold_iqr_lo": r["fold_thr_iqr"][0],
            "threshold_fold_iqr_hi": r["fold_thr_iqr"][1],
            "sens": r["sensitivity_lr"],
            "sens_ci_lo": r["sens_ci"][0],
            "sens_ci_hi": r["sens_ci"][1],
            "spec": r["specificity_lr"],
            "spec_ci_lo": r["spec_ci"][0],
            "spec_ci_hi": r["spec_ci"][1],
            "youden_j": r["yj_J"],
            "p_perm": r["perm_p"],
            "perm_p_floor": r["perm_p_floor"],
            "n_perm": r["n_perm"],
            "lr_coef_sign": r["lr_coef_sign"],
            "cohens_d": r["stats"]["cohens_d"],
            "cohens_d_ci_lo": r["stats"]["cohens_d_ci"][0],
            "cohens_d_ci_hi": r["stats"]["cohens_d_ci"][1],
            "r_rb": r["r_rb"],
            "r_rb_ci_lo": r["r_rb_ci_lo"],
            "r_rb_ci_hi": r["r_rb_ci_hi"],
        })
    pd.DataFrame(rows, columns=HEADLINE_COLS).to_csv(
        path, index=False, float_format="%.6f",
    )


FOLD_COLS = [
    "patient", "hemisphere",
    "fold_event_idx", "fold_event_timestamp",
    "fold_threshold_uv", "fold_loo_prob", "fold_true_label",
]


def write_folds_csv(results: List[Dict], path: Path) -> None:
    rows = []
    for r in results:
        for i, ts in enumerate(r["retained_timestamps"]):
            rows.append({
                "patient": r["patient_id"],
                "hemisphere": r["hemisphere"],
                "fold_event_idx": i,
                "fold_event_timestamp": ts,
                "fold_threshold_uv": float(r["fold_thresholds"][i]),
                "fold_loo_prob": float(r["oof_prob"][i]),
                "fold_true_label": int(r["y"][i]),
            })
    pd.DataFrame(rows, columns=FOLD_COLS).to_csv(
        path, index=False, float_format="%.6f",
    )


def write_pickle(results: List[Dict], path: Path) -> None:
    """Structured raw state for reviewers re-deriving CIs or re-permuting."""
    payload = []
    for r in results:
        payload.append({
            "patient_id": r["patient_id"],
            "hemisphere": r["hemisphere"],
            "X": r["X"], "y": r["y"],
            "oof_prob": r["oof_prob"],
            "fold_thresholds": r["fold_thresholds"],
            "fold_signs": r["fold_signs"],
            "null_aucs": r["null_aucs"],
            "lr_threshold": r["lr_threshold"],
            "lr_coef": r["lr_coef"],
            "auc_loo": r["auc_loo"],
            "auc_ci": r["auc_ci"],
            "lr_threshold_ci": r["lr_threshold_ci"],
            "perm_p": r["perm_p"],
            "n_perm": r["n_perm"], "n_boot": r["n_boot"],
            "retained_timestamps": r["retained_timestamps"],
        })
    with open(path, "wb") as f:
        pickle.dump(payload, f)


# ============================================================================
# CLI
# ============================================================================


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="L2 logistic regression amplitude-threshold classifier on Timeline uV with LOO-CV.",
    )
    parser.add_argument("--pt1-snapshots", required=True, type=Path)
    parser.add_argument("--pt2-snapshots", required=True, type=Path)
    parser.add_argument("--pt1-timeline", required=True, type=Path)
    parser.add_argument("--pt2-timeline", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--n-perm", type=int, default=DEFAULT_N_PERM)
    parser.add_argument("--n-boot", type=int, default=N_BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=RANDOM_STATE)
    parser.add_argument("--n-jobs", type=int, default=8,
                        help="joblib n_jobs for the permutation null "
                             "(default: 8 to match the manuscript run)")
    parser.add_argument(
        "--panels", nargs="+", default=None,
        choices=["pt1_left", "pt1_right", "pt2_left", "pt2_right"],
        help="Subset of panels to run (default: all four; the manuscript "
             "headline excludes pt1_right per Supp Note 2)."
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    snap_csv = {"pt1": args.pt1_snapshots, "pt2": args.pt2_snapshots}
    tl_csv = {"pt1": args.pt1_timeline, "pt2": args.pt2_timeline}

    print(f"\n{'=' * 60}", flush=True)
    print(f"  TIMELINE AMPLITUDE-THRESHOLD CLASSIFIER", flush=True)
    print(f"  n_perm: {args.n_perm}  n_boot: {args.n_boot}  "
          f"seed: {args.seed}  n_jobs: {args.n_jobs}", flush=True)
    print(f"{'=' * 60}", flush=True)

    snap_by_pt = {pt: load_snapshots_csv(snap_csv[pt]) for pt in ("pt1", "pt2")}

    panels_to_run = []
    for pt, hemi in PANELS:
        if args.panels is None or f"{pt}_{hemi}" in args.panels:
            panels_to_run.append((pt, hemi))

    results: List[Dict] = []
    t_start = time.time()
    for pt, hemi in panels_to_run:
        timeline_ts, timeline_val = load_timeline_csv(tl_csv[pt], hemi)
        r = run_hemisphere(
            pt, hemi,
            snap_by_pt[pt], timeline_ts, timeline_val,
            n_perm=args.n_perm, n_jobs=args.n_jobs,
            n_boot=args.n_boot, seed=args.seed,
        )
        if r is not None:
            results.append(r)

    csv_path = args.out_dir / "timeline_amplitude_threshold_classifier.csv"
    folds_path = args.out_dir / "timeline_amplitude_threshold_classifier_folds.csv"
    pkl_path = args.out_dir / "timeline_amplitude_threshold_classifier.pkl"
    write_headline_csv(results, csv_path)
    write_folds_csv(results, folds_path)
    write_pickle(results, pkl_path)

    print(f"\nWrote {csv_path}", flush=True)
    print(f"Wrote {folds_path}", flush=True)
    print(f"Wrote {pkl_path}", flush=True)
    print(f"Total wall-clock: {(time.time() - t_start) / 60:.2f} min",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
