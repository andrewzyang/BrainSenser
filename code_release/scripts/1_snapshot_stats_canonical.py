#!/usr/bin/env python3
"""Canonical-band spectral comparison for BrainSense Snapshots.

Per participant-hemisphere, per canonical band (delta, theta, alpha, beta,
low-gamma), computes:
  - Median craving / non-craving power (trapezoidal integration of device
    PSD bins).
  - Two-sided Mann-Whitney U with midrank handling of ties.
  - Benjamini-Hochberg FDR across the 5 bands within the panel (q = 0.05).
  - Rank-biserial r (r_rb = 2U / (n1 * n2) - 1) with 5,000-iter stratified
    BCa bootstrap 95% CI (Efron 1987).
  - Cohen's d on log10 band power with 5,000-iter stratified BCa bootstrap
    95% CI.

Usage:
  python 1_snapshot_stats_canonical.py \\
      --pt1-snapshots ../data/pt1_snapshots_native.csv \\
      --pt2-snapshots ../data/pt2_snapshots.csv \\
      --out-dir ../out
"""

import argparse
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import integrate, stats


BANDS: Dict[str, Tuple[float, float]] = {
    "delta":     (1.0,  4.0),
    "theta":     (4.0,  8.0),
    "alpha":     (8.0, 13.0),
    "beta":      (13.0, 30.0),
    "low_gamma": (30.0, 40.0),
}

CRAVING_KEYWORDS = ["Craving", "Drinking"]
NON_CRAVING_KEYWORDS = ["Happy", "Neutral"]

BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 2025
BOOTSTRAP_ALPHA = 0.05
FDR_Q = 0.05
MIN_PER_GROUP = 3


def _classify(name: str) -> Optional[str]:
    if any(kw in name for kw in CRAVING_KEYWORDS):
        return "craving"
    if any(kw in name for kw in NON_CRAVING_KEYWORDS):
        return "non_craving"
    return None


def load_psd(csv_path: Path, hemisphere: str
             ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    df = pd.read_csv(csv_path)
    freq_cols = [c for c in df.columns if c.endswith("Hz")]
    freqs = np.array([float(c.replace("Hz", "")) for c in freq_cols])
    hemi = df[df["hemisphere"] == hemisphere].copy()
    hemi["group"] = hemi["snapshot_name"].apply(_classify)
    hemi = hemi.dropna(subset=["group"])
    crav = hemi.loc[hemi["group"] == "craving", freq_cols].values.astype(float)
    nc = hemi.loc[hemi["group"] == "non_craving", freq_cols].values.astype(float)
    return freqs, crav, nc


def integrate_band(psd_row: np.ndarray, freqs: np.ndarray,
                   fmin: float, fmax: float) -> Optional[float]:
    mask = (freqs >= fmin) & (freqs <= fmax)
    band_f, band_p = freqs[mask], psd_row[mask]
    valid = ~np.isnan(band_p)
    if valid.sum() < 2:
        return None
    return float(integrate.trapezoid(band_p[valid], band_f[valid]))


def benjamini_hochberg(p_values: List[float]) -> List[float]:
    n = len(p_values)
    order = np.argsort(p_values)
    sorted_p = np.array(p_values)[order]
    q = np.zeros(n)
    for i in range(n):
        q[i] = sorted_p[i] * n / (i + 1)
    for i in range(n - 2, -1, -1):
        q[i] = min(q[i], q[i + 1])
    q = np.minimum(q, 1.0)
    out = np.zeros(n)
    for rank, idx in enumerate(order):
        out[idx] = q[rank]
    return out.tolist()


def _effect_sizes(crav: np.ndarray, nc: np.ndarray
                  ) -> Tuple[float, float, float]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u, p = stats.mannwhitneyu(crav, nc, alternative="two-sided")
    n1, n2 = len(crav), len(nc)
    r_rb = (2 * u) / (n1 * n2) - 1
    return float(u), float(p), float(r_rb)


def _cohens_d(crav: np.ndarray, nc: np.ndarray) -> float:
    n1, n2 = len(crav), len(nc)
    if n1 < 2 or n2 < 2:
        return float("nan")
    s1, s2 = np.var(crav, ddof=1), np.var(nc, ddof=1)
    pooled = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    if pooled == 0:
        return float("nan")
    return float((np.mean(crav) - np.mean(nc)) / pooled)


def _bca_interval(theta_hat: float,
                  theta_boot: np.ndarray,
                  theta_jack: np.ndarray,
                  alpha: float = BOOTSTRAP_ALPHA) -> Tuple[float, float]:
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
                      n_boot: int = BOOTSTRAP_N,
                      seed: int = BOOTSTRAP_SEED,
                      alpha: float = BOOTSTRAP_ALPHA
                      ) -> Tuple[float, float, float]:
    crav = np.asarray(crav, dtype=float)
    nc = np.asarray(nc, dtype=float)
    n1, n2 = crav.size, nc.size
    rng = np.random.default_rng(seed)

    _, _, r_hat = _effect_sizes(crav, nc)

    r_boot = np.empty(n_boot)
    for b in range(n_boot):
        i1 = rng.integers(0, n1, size=n1)
        i2 = rng.integers(0, n2, size=n2)
        _, _, r_boot[b] = _effect_sizes(crav[i1], nc[i2])

    r_jack = np.empty(n1 + n2)
    for i in range(n1):
        _, _, r_jack[i] = _effect_sizes(np.delete(crav, i), nc)
    for j in range(n2):
        _, _, r_jack[n1 + j] = _effect_sizes(crav, np.delete(nc, j))

    lo, hi = _bca_interval(r_hat, r_boot, r_jack, alpha)
    return r_hat, lo, hi


def bca_bootstrap_d(crav: np.ndarray, nc: np.ndarray,
                    n_boot: int = BOOTSTRAP_N,
                    seed: int = BOOTSTRAP_SEED,
                    alpha: float = BOOTSTRAP_ALPHA
                    ) -> Tuple[float, float, float]:
    """Stratified BCa bootstrap CI for Cohen's d on the supplied samples.

    Operates on the values passed in (caller log10-transforms before
    invoking, matching the manuscript convention for canonical-band d).
    """
    crav = np.asarray(crav, dtype=float)
    nc = np.asarray(nc, dtype=float)
    n1, n2 = crav.size, nc.size
    rng = np.random.default_rng(seed)

    d_hat = _cohens_d(crav, nc)
    d_boot = np.empty(n_boot)
    for b in range(n_boot):
        i1 = rng.integers(0, n1, size=n1)
        i2 = rng.integers(0, n2, size=n2)
        d_boot[b] = _cohens_d(crav[i1], nc[i2])
    d_boot = d_boot[np.isfinite(d_boot)]

    d_jack = np.empty(n1 + n2)
    for i in range(n1):
        d_jack[i] = _cohens_d(np.delete(crav, i), nc)
    for j in range(n2):
        d_jack[n1 + j] = _cohens_d(crav, np.delete(nc, j))
    d_jack = d_jack[np.isfinite(d_jack)]

    lo, hi = _bca_interval(d_hat, d_boot, d_jack, alpha)
    return d_hat, lo, hi


def analyze_panel(patient: str, hemisphere: str,
                  freqs: np.ndarray,
                  crav_mat: np.ndarray,
                  nc_mat: np.ndarray) -> List[Dict]:
    records = []
    for band, (fmin, fmax) in BANDS.items():
        crav_power = [integrate_band(r, freqs, fmin, fmax) for r in crav_mat]
        nc_power = [integrate_band(r, freqs, fmin, fmax) for r in nc_mat]
        crav_arr = np.array([x for x in crav_power if x is not None])
        nc_arr = np.array([x for x in nc_power if x is not None])

        if crav_arr.size < MIN_PER_GROUP or nc_arr.size < MIN_PER_GROUP:
            records.append({
                "patient": patient, "hemisphere": hemisphere,
                "band_name": band, "fmin_hz": fmin, "fmax_hz": fmax,
                "n_craving": int(crav_arr.size), "n_non_craving": int(nc_arr.size),
                "median_craving": None, "median_non_craving": None,
                "U": None, "p_raw": None, "p_fdr": None,
                "fdr_significant": False,
                "r_rb": None, "r_rb_ci_lo": None, "r_rb_ci_hi": None,
                "cohens_d": None, "cohens_d_ci_lo": None, "cohens_d_ci_hi": None,
            })
            continue

        u, p, _ = _effect_sizes(crav_arr, nc_arr)
        r_rb, r_lo, r_hi = bca_bootstrap_rrb(crav_arr, nc_arr)
        d_hat, d_lo, d_hi = bca_bootstrap_d(np.log10(crav_arr), np.log10(nc_arr))

        records.append({
            "patient": patient, "hemisphere": hemisphere,
            "band_name": band, "fmin_hz": fmin, "fmax_hz": fmax,
            "n_craving": int(crav_arr.size), "n_non_craving": int(nc_arr.size),
            "median_craving": float(np.median(crav_arr)),
            "median_non_craving": float(np.median(nc_arr)),
            "U": u, "p_raw": p, "p_fdr": None,
            "fdr_significant": False,
            "r_rb": r_rb, "r_rb_ci_lo": r_lo, "r_rb_ci_hi": r_hi,
            "cohens_d": d_hat, "cohens_d_ci_lo": d_lo, "cohens_d_ci_hi": d_hi,
        })

    valid_idx = [i for i, r in enumerate(records) if r["p_raw"] is not None]
    qs = benjamini_hochberg([records[i]["p_raw"] for i in valid_idx])
    for i, q in zip(valid_idx, qs):
        records[i]["p_fdr"] = q
        records[i]["fdr_significant"] = bool(q < FDR_Q)
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Canonical-band Mann-Whitney U + FDR + r_rb + Cohen's d on Snapshot PSDs.",
    )
    parser.add_argument("--pt1-snapshots", required=True, type=Path,
                        help="Path to pt1_snapshots_native.csv")
    parser.add_argument("--pt2-snapshots", required=True, type=Path,
                        help="Path to pt2_snapshots.csv")
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="Directory to write snapshot_stats_canonical.csv")
    parser.add_argument("--bootstrap-n", type=int, default=BOOTSTRAP_N,
                        help=f"BCa bootstrap iterations (default: {BOOTSTRAP_N})")
    parser.add_argument("--fdr-q", type=float, default=FDR_Q,
                        help=f"FDR threshold (default: {FDR_Q})")
    parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED,
                        help=f"BCa bootstrap RNG seed (default: {BOOTSTRAP_SEED})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global BOOTSTRAP_N, FDR_Q, BOOTSTRAP_SEED
    BOOTSTRAP_N = args.bootstrap_n
    FDR_Q = args.fdr_q
    BOOTSTRAP_SEED = args.seed

    panels = [
        ("pt1", "Left",  args.pt1_snapshots),
        ("pt2", "Left",  args.pt2_snapshots),
        ("pt2", "Right", args.pt2_snapshots),
    ]

    all_records: List[Dict] = []
    for patient, hemi, csv_path in panels:
        freqs, crav_mat, nc_mat = load_psd(csv_path, hemi)
        records = analyze_panel(patient, hemi.lower(), freqs, crav_mat, nc_mat)
        all_records.extend(records)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = args.out_dir / "snapshot_stats_canonical.csv"
    pd.DataFrame(all_records).to_csv(out_csv, index=False, float_format="%.6f")
    print(f"Wrote {out_csv} ({len(all_records)} rows)")


if __name__ == "__main__":
    main()
