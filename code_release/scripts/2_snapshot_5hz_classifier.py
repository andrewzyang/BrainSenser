#!/usr/bin/env python3
"""Strict nested leave-one-out classification of craving from a single
Snapshot, with max-statistic permutation FWER null.

Analysis envelope (locked):
    Frequency range : 5.31 - 37.5 Hz
    Window          : 5 PSD bins  (~4.9 Hz nominal)
    Step            : 3 PSD bins  (~2.9 Hz; 40% overlap)
    Candidate bands : 10 per panel

Pipeline:
  1. Build (n_events, n_freq_bins) PSD matrix per panel restricted to the
     5.31-37.5 Hz envelope; linearly interpolate any remaining NaN bins.
  2. For each candidate 5-bin band b, per-event feature
        band_power[b, i] = log10(clip(mean PSD over band b, 1e-10, inf)).
  3. Strict nested LOO-CV: for each held-out event i, select b* and
     direction d on the n-1 training events by maximizing |AUC_train - 0.5|,
     then held_out_score[i] = d * band_power[b*, i].
  4. Pooled LOO AUC = U(held_out_score, y) / (n_pos * n_neg).
  5. Permutation FWER null: re-run the full nested-LOO pipeline (band
     search included) under 10,000 event-level label permutations.
     FWER P = (sum[null_dev >= obs_dev] + 1) / (n_perm + 1).
  6. Stratified percentile bootstrap (2,000 resamples) on pooled out-of-fold
     scores for the LOO AUC 95% CI and the operating-point sens / spec at
     Youden's J. Cohen's d and rank-biserial r_rb on the modal-band log10
     power with stratified percentile / BCa bootstrap CIs.

Usage:
  python 2_snapshot_5hz_classifier.py \\
      --pt1-snapshots ../data/pt1_snapshots_native.csv \\
      --pt2-snapshots ../data/pt2_snapshots.csv \\
      --out-dir ../out
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
import warnings
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import rankdata


WINDOW_BINS = 5
STEP_BINS = 3
FREQ_MIN_HZ = 5.31
FREQ_MAX_HZ = 37.5
N_PERM = 10_000
N_BOOT = 2_000
SEED = 42

# Independent BCa-bootstrap stream for r_rb on modal-band log power.
RRB_BOOTSTRAP_N = 5000
RRB_BOOTSTRAP_SEED = 2025
RRB_BOOTSTRAP_ALPHA = 0.05

CRAVING_KEYWORDS = ("Craving", "Drinking")
NON_CRAVING_KEYWORDS = ("Happy", "Neutral")

PANELS: List[Tuple[str, str, str]] = [
    ("pt1", "LEFT",  "Left"),
    ("pt2", "LEFT",  "Left"),
    ("pt2", "RIGHT", "Right"),
]


def get_event_label(event_name: str) -> Optional[int]:
    for kw in CRAVING_KEYWORDS:
        if kw in event_name:
            return 1
    for kw in NON_CRAVING_KEYWORDS:
        if kw in event_name:
            return 0
    return None


def load_csv_matrix(
    csv_path: Path,
    hemisphere_csv_label: str,
    freq_min: float = FREQ_MIN_HZ,
    freq_max: float = FREQ_MAX_HZ,
    max_nan_fraction: float = 0.30,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    df = pd.read_csv(csv_path)
    freq_cols = [c for c in df.columns if c.endswith("Hz")]
    freq_axis = np.array([float(c.replace("Hz", "")) for c in freq_cols])
    freq_mask = (freq_axis >= freq_min) & (freq_axis <= freq_max)
    freqs = freq_axis[freq_mask]
    cols_in = [c for c, m in zip(freq_cols, freq_mask) if m]

    df = df[df["hemisphere"] == hemisphere_csv_label].copy()
    df["label"] = df["snapshot_name"].apply(get_event_label)
    df = df.dropna(subset=["label"])

    rows: List[np.ndarray] = []
    labels: List[int] = []
    for _, r in df.iterrows():
        psd = r[cols_in].astype(float).values
        nan_frac = np.sum(np.isnan(psd)) / len(psd)
        if nan_frac > max_nan_fraction:
            continue
        if nan_frac > 0:
            valid = ~np.isnan(psd)
            if np.sum(valid) >= 2:
                psd[~valid] = np.interp(freqs[~valid], freqs[valid], psd[valid])
            else:
                continue
        rows.append(psd)
        labels.append(int(r["label"]))
    if not rows:
        return np.array([]), np.array([]), freqs
    return np.array(rows), np.array(labels), freqs


def candidate_band_bins(freqs: np.ndarray) -> np.ndarray:
    n = len(freqs)
    starts = np.arange(0, n - WINDOW_BINS + 1, STEP_BINS)
    bands = np.empty((len(starts), 2), dtype=np.int64)
    bands[:, 0] = starts
    bands[:, 1] = starts + WINDOW_BINS - 1
    return bands


def band_edges_hz(freqs: np.ndarray, bands: np.ndarray) -> np.ndarray:
    half = float(np.median(np.diff(freqs)) / 2.0)
    edges = np.empty((len(bands), 2), dtype=float)
    edges[:, 0] = freqs[bands[:, 0]] - half
    edges[:, 1] = freqs[bands[:, 1]] + half
    return edges


def precompute_band_powers(X: np.ndarray, bands: np.ndarray) -> np.ndarray:
    n_bands = len(bands)
    out = np.zeros((n_bands, X.shape[0]))
    for b in range(n_bands):
        s, e = bands[b]
        raw = np.mean(X[:, s:e + 1], axis=1)
        raw = np.clip(raw, 1e-10, None)
        out[b] = np.log10(raw)
    return out


def auc_from_ranks(ranks: np.ndarray, y: np.ndarray) -> np.ndarray:
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
        per_band_dirs = np.where(train_aucs >= 0.5, 1.0, -1.0)
        per_band_held[:, i] = per_band_dirs * band_powers[:, i]
    return held, sel, dirs, per_band_held


def nested_loo_auc_only(band_powers: np.ndarray, y: np.ndarray) -> float:
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
) -> Tuple[float, np.ndarray]:
    rng = np.random.default_rng(seed)
    obs_dev = abs(obs_loo_auc - 0.5)
    null_auc = np.empty(n_perm)
    chunk = max(1, n_perm // 20)
    t_start = time.time()
    for p in range(n_perm):
        y_shuf = rng.permutation(y)
        null_auc[p] = nested_loo_auc_only(band_powers, y_shuf)
        if (p + 1) % chunk == 0 or p == n_perm - 1:
            elapsed = time.time() - t_start
            done = (p + 1) / n_perm
            est_total = elapsed / max(done, 1e-9)
            print(
                f"      {progress_label} perm {p + 1}/{n_perm}"
                f"  ({done * 100:5.1f}%)  elapsed {elapsed:6.1f}s"
                f"  ~total {est_total:6.1f}s",
                flush=True,
            )
    null_dev = np.abs(null_auc - 0.5)
    fwer_p = float((np.sum(null_dev >= obs_dev) + 1) / (n_perm + 1))
    return fwer_p, null_auc


def bootstrap_loo_ci(
    held: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> Tuple[float, float]:
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


def youden_threshold_sens_spec(
    scores: np.ndarray, y: np.ndarray
) -> Tuple[float, float, float]:
    n_pos = int(y.sum())
    n_neg = y.size - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan"), float("nan"), float("nan")
    uniq = np.unique(scores)
    if uniq.size > 1:
        mids = (uniq[:-1] + uniq[1:]) / 2.0
    else:
        mids = uniq.copy()
    candidates = np.concatenate([
        [uniq[0] - 1.0], mids, [uniq[-1] + 1.0],
    ])
    best_j = -np.inf
    best_thr = candidates[0]
    best_sens = 0.0
    best_spec = 0.0
    for thr in candidates:
        pos_pred = scores >= thr
        tp = int(np.sum(pos_pred & (y == 1)))
        fp = int(np.sum(pos_pred & (y == 0)))
        sens = tp / n_pos if n_pos else 0.0
        spec = (n_neg - fp) / n_neg if n_neg else 0.0
        j = sens + spec - 1.0
        if j > best_j or (j == best_j and sens > best_sens):
            best_j = j
            best_thr = thr
            best_sens = sens
            best_spec = spec
    return float(best_thr), float(best_sens), float(best_spec)


def bootstrap_youden_sens_spec(
    held: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> Tuple[float, float, float, float]:
    rng = np.random.default_rng(seed)
    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    n_pos = idx_pos.size
    n_neg = idx_neg.size
    if n_pos == 0 or n_neg == 0:
        nan = float("nan")
        return nan, nan, nan, nan
    sens_b = np.empty(n_boot)
    spec_b = np.empty(n_boot)
    for b in range(n_boot):
        rs = np.concatenate([
            rng.choice(idx_pos, n_pos, replace=True),
            rng.choice(idx_neg, n_neg, replace=True),
        ])
        _, sens, spec = youden_threshold_sens_spec(held[rs], y[rs])
        sens_b[b] = sens
        spec_b[b] = spec
    return (
        float(np.percentile(sens_b, 2.5)),
        float(np.percentile(sens_b, 97.5)),
        float(np.percentile(spec_b, 2.5)),
        float(np.percentile(spec_b, 97.5)),
    )


def cohens_d(x_pos: np.ndarray, x_neg: np.ndarray) -> float:
    n1, n2 = x_pos.size, x_neg.size
    if n1 < 2 or n2 < 2:
        return float("nan")
    v1 = np.var(x_pos, ddof=1)
    v2 = np.var(x_neg, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled_sd == 0:
        return float("nan")
    return float((np.mean(x_pos) - np.mean(x_neg)) / pooled_sd)


def bootstrap_cohens_d(
    feature: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> Tuple[float, float, float]:
    idx_pos = np.where(y == 1)[0]
    idx_neg = np.where(y == 0)[0]
    d_obs = cohens_d(feature[idx_pos], feature[idx_neg])
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        rp = rng.choice(idx_pos, idx_pos.size, replace=True)
        rn = rng.choice(idx_neg, idx_neg.size, replace=True)
        boots[b] = cohens_d(feature[rp], feature[rn])
    valid = ~np.isnan(boots)
    if not np.any(valid):
        return d_obs, float("nan"), float("nan")
    return (
        d_obs,
        float(np.percentile(boots[valid], 2.5)),
        float(np.percentile(boots[valid], 97.5)),
    )


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


def per_band_loo_aucs(per_band_held: np.ndarray, y: np.ndarray) -> np.ndarray:
    n_bands = per_band_held.shape[0]
    out = np.empty(n_bands)
    for b in range(n_bands):
        out[b] = loo_auc_from_predictions(per_band_held[b], y)
    return out


def bootstrap_per_band_loo_aucs(
    per_band_held: np.ndarray, y: np.ndarray, n_boot: int, seed: int,
) -> np.ndarray:
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


def analyse_hemisphere(
    csv_path: Path, patient: str, hemisphere: str, hemi_csv_label: str,
    n_perm: int, n_boot: int, seed: int,
) -> Optional[Dict]:
    print(f"\n>> {patient} {hemisphere}", flush=True)
    X, y, freqs = load_csv_matrix(csv_path, hemi_csv_label, FREQ_MIN_HZ, FREQ_MAX_HZ)
    if X.size == 0 or len(np.unique(y)) < 2:
        print(f"   skipped: no usable events for {patient} {hemisphere}")
        return None

    n_craving = int((y == 1).sum())
    n_neutral = int((y == 0).sum())
    n = X.shape[0]
    bands = candidate_band_bins(freqs)
    edges = band_edges_hz(freqs, bands)
    band_powers = precompute_band_powers(X, bands)
    bin_step = float(np.median(np.diff(freqs)))

    print(
        f"   n = {n_craving} craving / {n_neutral} non-craving;"
        f" {len(bands)} bands"
        f" ({edges[0, 0]:.2f}-{edges[-1, 1]:.2f} Hz)",
        flush=True,
    )

    held, sel, dirs, per_band_held = nested_loo_predictions(band_powers, y)
    obs_loo_auc = loo_auc_from_predictions(held, y)

    band_counts = Counter(sel.tolist())
    modal_band_idx, modal_count = band_counts.most_common(1)[0]
    modal_direction = int(np.sign(dirs[sel == modal_band_idx].mean()))
    if modal_direction == 0:
        modal_direction = 1
    modal_lo = float(edges[modal_band_idx, 0])
    modal_hi = float(edges[modal_band_idx, 1])
    modal_pct = 100.0 * modal_count / n

    print(f"   LOO AUC = {obs_loo_auc:.4f}", flush=True)

    ci_lo, ci_hi = bootstrap_loo_ci(held, y, n_boot, seed)
    print(f"   95% CI [{ci_lo:.4f}, {ci_hi:.4f}]", flush=True)

    fwer_p, null_auc = permutation_fwer(
        band_powers, y, obs_loo_auc, n_perm, seed,
        progress_label=f"[{patient} {hemisphere}]",
    )
    print(f"   FWER p = {fmt_p(fwer_p, n_perm)}", flush=True)

    youden_thr, sens, spec = youden_threshold_sens_spec(held, y)
    sens_lo, sens_hi, spec_lo, spec_hi = bootstrap_youden_sens_spec(held, y, n_boot, seed)

    modal_log_power = band_powers[modal_band_idx]
    cd_obs, cd_lo, cd_hi = bootstrap_cohens_d(modal_log_power, y, n_boot, seed)

    crav_mlp = modal_log_power[y == 1]
    nc_mlp = modal_log_power[y == 0]
    rrb_obs, rrb_lo, rrb_hi = bca_bootstrap_rrb(crav_mlp, nc_mlp)

    per_band_aucs = per_band_loo_aucs(per_band_held, y)
    per_band_ci = bootstrap_per_band_loo_aucs(per_band_held, y, n_boot, seed)

    return {
        "patient": patient,
        "hemisphere": hemisphere.lower(),
        "n_craving": n_craving,
        "n_neutral": n_neutral,
        "n": n,
        "n_bands_searched": int(len(bands)),
        "window_bins": WINDOW_BINS,
        "step_bins": STEP_BINS,
        "bin_step_hz": bin_step,
        "freq_min_hz": FREQ_MIN_HZ,
        "freq_max_hz": FREQ_MAX_HZ,
        "modal_band_lo_hz": modal_lo,
        "modal_band_hi_hz": modal_hi,
        "modal_band_freq_pct": modal_pct,
        "modal_band_idx": int(modal_band_idx),
        "loo_auc": obs_loo_auc,
        "loo_auc_ci_lo": ci_lo,
        "loo_auc_ci_hi": ci_hi,
        "fwer_p": fwer_p,
        "n_perm": n_perm,
        "n_boot": n_boot,
        "direction": modal_direction,
        "youden_threshold": youden_thr,
        "sens": sens,
        "sens_ci_lo": sens_lo,
        "sens_ci_hi": sens_hi,
        "spec": spec,
        "spec_ci_lo": spec_lo,
        "spec_ci_hi": spec_hi,
        "cohens_d": cd_obs,
        "cohens_d_ci_lo": cd_lo,
        "cohens_d_ci_hi": cd_hi,
        "r_rb": rrb_obs,
        "r_rb_ci_lo": rrb_lo,
        "r_rb_ci_hi": rrb_hi,
        "per_band_aucs": per_band_aucs.tolist(),
        "per_band_auc_ci_lo": per_band_ci[:, 0].tolist(),
        "per_band_auc_ci_hi": per_band_ci[:, 1].tolist(),
        "held_out_scores": held.tolist(),
        "labels": y.tolist(),
        "modal_log_power": modal_log_power.tolist(),
        "all_band_edges": edges.tolist(),
        "null_auc": null_auc.tolist(),
    }


def save_csv(results: List[Dict], path: Path) -> None:
    cols = [
        "patient", "hemisphere", "n_craving", "n_neutral",
        "n_bands_searched", "window_bins", "step_bins", "bin_step_hz",
        "freq_min_hz", "freq_max_hz",
        "modal_band_lo_hz", "modal_band_hi_hz", "modal_band_freq_pct",
        "loo_auc", "loo_auc_ci_lo", "loo_auc_ci_hi",
        "fwer_p", "n_perm", "n_boot", "direction",
        "youden_threshold", "sens", "sens_ci_lo", "sens_ci_hi",
        "spec", "spec_ci_lo", "spec_ci_hi",
        "cohens_d", "cohens_d_ci_lo", "cohens_d_ci_hi",
        "r_rb", "r_rb_ci_lo", "r_rb_ci_hi",
    ]
    with open(path, "w") as f:
        f.write(",".join(cols) + "\n")
        for r in results:
            f.write(",".join([
                r["patient"], r["hemisphere"],
                str(r["n_craving"]), str(r["n_neutral"]),
                str(r["n_bands_searched"]),
                str(r["window_bins"]), str(r["step_bins"]),
                f"{r['bin_step_hz']:.6f}",
                f"{r['freq_min_hz']:.2f}", f"{r['freq_max_hz']:.2f}",
                f"{r['modal_band_lo_hz']:.2f}", f"{r['modal_band_hi_hz']:.2f}",
                f"{r['modal_band_freq_pct']:.2f}",
                f"{r['loo_auc']:.4f}",
                f"{r['loo_auc_ci_lo']:.4f}", f"{r['loo_auc_ci_hi']:.4f}",
                f"{r['fwer_p']:.4f}", str(r["n_perm"]), str(r["n_boot"]),
                str(int(r["direction"])),
                f"{r['youden_threshold']:.6f}",
                f"{r['sens']:.4f}",
                f"{r['sens_ci_lo']:.4f}", f"{r['sens_ci_hi']:.4f}",
                f"{r['spec']:.4f}",
                f"{r['spec_ci_lo']:.4f}", f"{r['spec_ci_hi']:.4f}",
                f"{r['cohens_d']:+.4f}",
                f"{r['cohens_d_ci_lo']:+.4f}", f"{r['cohens_d_ci_hi']:+.4f}",
                f"{r['r_rb']:+.6f}",
                f"{r['r_rb_ci_lo']:+.6f}", f"{r['r_rb_ci_hi']:+.6f}",
            ]) + "\n")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict leave-one-out 5-Hz classifier with max-statistic permutation FWER null.",
    )
    parser.add_argument("--pt1-snapshots", required=True, type=Path)
    parser.add_argument("--pt2-snapshots", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--n-perm", type=int, default=N_PERM)
    parser.add_argument("--n-boot", type=int, default=N_BOOT)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75, flush=True)
    print("Strict nested LOO-CV — 5-bin x 3-bin step, 5.31-37.5 Hz envelope", flush=True)
    print("=" * 75, flush=True)
    print(f"  n_perm: {args.n_perm:,}   n_boot: {args.n_boot:,}   seed: {args.seed}", flush=True)

    csv_for = {"pt1": args.pt1_snapshots, "pt2": args.pt2_snapshots}
    for pid, p in csv_for.items():
        if not p.exists():
            print(f"  ERROR: CSV not found: {p}", flush=True)
            return 1
        print(f"  CSV {pid}: {p}", flush=True)

    t_total = time.time()
    results: List[Dict] = []
    for pid, hemi, hemi_csv_label in PANELS:
        r = analyse_hemisphere(
            csv_for[pid], pid, hemi, hemi_csv_label,
            args.n_perm, args.n_boot, args.seed,
        )
        if r is not None:
            r["seed"] = args.seed
            results.append(r)

    csv_path = args.out_dir / "snapshot_5hz_classifier.csv"
    save_csv(results, csv_path)
    print(f"\nCSV: {csv_path}", flush=True)

    pkl_path = args.out_dir / "snapshot_5hz_classifier.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(results, f)
    print(f"PKL: {pkl_path}", flush=True)

    total_s = time.time() - t_total
    print(f"\nTotal wall-clock: {total_s / 60:.2f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
