#!/usr/bin/env python3
"""Cluster-based permutation peri-event analysis of BrainSense Timeline
narrowband (5.31-10.31 Hz) amplitude.

Statistics:
  - Per-bin tie-corrected two-sided Mann-Whitney U via
    |z| = |Phi^{-1}(p/2)| (scipy asymptotic p inherits the Lehmann tie
    correction).
  - Cluster-forming threshold |z| > 1.96 (= norm.ppf(0.975)).
  - Cluster mass = sum of |z| across consecutive suprathreshold bins.
  - Null: maximum cluster mass per permutation across 10,000 event-level
    label permutations (per-event 11-bin vectors kept intact; only labels
    shuffled).
  - Cluster p-value via Phipson-Smyth 2010: (sum[null >= obs] + 1) /
    (n_perm + 1).
  - Per-bin mean 95% percentile bootstrap CI on 5,000 resamples (display
    only; not used in the cluster test).

Event exclusion:
  - Same-timestamp mixed-label events discarded.
  - Cross-class events within 60 min mutually excluded.
  - Same-class events within 60 min pruned to the highest-coverage event
    per connected component of the within-60-min same-class graph (ties
    broken by earliest timestamp).
  - A label-invariant `usable_mask` is applied identically to observed
    and permuted |z|: a bin passes iff V >= min(n_craving, n_neutral) + 3,
    where V is the bin's non-NaN count.

Usage:
  python 3_timeline_stats_cluster_permutation.py \\
      --pt1-snapshots ../data/pt1_snapshots_native.csv \\
      --pt2-snapshots ../data/pt2_snapshots.csv \\
      --pt1-timeline ../data/pt1_timeline.csv \\
      --pt2-timeline ../data/pt2_timeline.csv \\
      --out-dir ../out
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, norm


WINDOW_MINUTES = 50
OFFSET_BINS = [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40, 50]
BIN_TOLERANCE = 5
MIN_INTER_EVENT_MINUTES = 60
MIN_PER_CLASS = 3

N_PERMUTATIONS = 10_000
CLUSTER_FORMING_Z = float(norm.ppf(0.975))
RANDOM_STATE = 42

CRAVING_KEYWORDS = ("Craving", "Drinking")
NON_CRAVING_KEYWORDS = ("Happy", "Neutral")


def classify(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    u = name.upper()
    for k in ("CRAVING", "DRINKING"):
        if k in u:
            return "craving"
    for k in ("HAPPY", "NEUTRAL"):
        if k in u:
            return "neutral"
    return None


def parse_ts(s) -> datetime:
    """Parse ISO-8601 timestamp; coerce to timezone-aware UTC."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_snapshots_csv(csv_path: Path) -> List[Tuple[datetime, str]]:
    """Return [(timestamp, event_name)] deduplicated by (timestamp,
    event_name) so the multi-hemisphere snapshot rows collapse to one
    event per (ts, name) pair, matching the in-repo SnapshotRepository
    semantics."""
    df = pd.read_csv(csv_path)
    df = df.drop_duplicates(subset=["time", "snapshot_name"])
    return [(parse_ts(t), n) for t, n in zip(df["time"], df["snapshot_name"])]


def load_timeline_csv(csv_path: Path, hemi: str) -> Tuple[np.ndarray, np.ndarray]:
    """Return (unix_ts, value) arrays for non-outlier rows of the requested
    hemisphere, sorted by timestamp. unix_ts is float64 seconds-since-epoch
    (UTC), enabling O(log n) np.searchsorted windowing per event."""
    df = pd.read_csv(csv_path)
    df = df.loc[df["is_outlier"] == 0, ["timestamp", f"{hemi}_uV"]].copy()
    df["unix_ts"] = df["timestamp"].apply(lambda s: parse_ts(s).timestamp())
    df = df.sort_values("unix_ts").reset_index(drop=True)
    return df["unix_ts"].to_numpy(dtype=np.float64), df[f"{hemi}_uV"].to_numpy(dtype=np.float64)


def get_data(
    snapshots: List[Tuple[datetime, str]],
    timeline_ts: np.ndarray,
    timeline_val: np.ndarray,
    hemi: str,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, int], int, float]:
    """Build the (n_bins, n_events) LFP matrix and the (n_events,) label
    vector, applying the manuscript's three event-exclusion rules.

    Returns (lfps, y, drop_counts, n_ts_raw, max_same_class_span_min).
    """
    by_ts: Dict[datetime, List[str]] = defaultdict(list)
    for ts, name in snapshots:
        lab = classify(name)
        if lab:
            by_ts[ts].append(lab)

    ts_sorted = sorted(by_ts.keys())
    n_ts_raw = len(ts_sorted)

    drop = {"mixed_label": 0, "cross_class_proximity": 0,
            "same_class_proximity": 0}
    excluded = set()

    # Rule 1: same-timestamp mixed-label events.
    for ts in ts_sorted:
        if len(set(by_ts[ts])) > 1:
            excluded.add(ts)
            drop["mixed_label"] += 1

    # Rule 2: cross-class 60-min mutual exclusion.
    for i, ti in enumerate(ts_sorted):
        if ti in excluded:
            continue
        for j in range(i + 1, len(ts_sorted)):
            tj = ts_sorted[j]
            d = (tj - ti).total_seconds() / 60
            if d > MIN_INTER_EVENT_MINUTES:
                break
            if tj in excluded:
                continue
            if by_ts[ti][0] != by_ts[tj][0]:
                if ti not in excluded:
                    excluded.add(ti)
                    drop["cross_class_proximity"] += 1
                excluded.add(tj)
                drop["cross_class_proximity"] += 1

    # Build per-event bin vectors using only retained events.
    window_s = WINDOW_MINUTES * 60.0
    offset_set = set(OFFSET_BINS)

    events: List[Tuple[datetime, int, Dict[int, float], int]] = []
    for ts in ts_sorted:
        if ts in excluded:
            continue
        label = 1 if by_ts[ts][0] == "craving" else 0
        ts_s = ts.timestamp()
        s_idx = np.searchsorted(timeline_ts, ts_s - window_s, side="left")
        e_idx = np.searchsorted(timeline_ts, ts_s + window_s, side="right")
        bb: Dict[int, Tuple[float, float]] = {}
        for k in range(s_idx, e_idx):
            v = timeline_val[k]
            if np.isnan(v):
                continue
            om = (timeline_ts[k] - ts_s) / 60.0
            nb = int(round(om / 10) * 10)
            if nb not in offset_set:
                continue
            dist = abs(om - nb)
            if dist > BIN_TOLERANCE:
                continue
            if nb not in bb or dist < bb[nb][1]:
                bb[nb] = (float(v), dist)
        bin_vals = {b: bb[b][0] for b in bb}
        events.append((ts, label, bin_vals, len(bin_vals)))

    # Rule 3: same-class 60-min connected-component pruning.
    n = len(events)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    events.sort(key=lambda e: e[0])
    for i in range(n):
        for j in range(i + 1, n):
            d = (events[j][0] - events[i][0]).total_seconds() / 60
            if d > MIN_INTER_EVENT_MINUTES:
                break
            ra, rb = find(i), find(j)
            if ra != rb:
                parent[ra] = rb

    components: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        components[find(i)].append(i)

    keep = set()
    max_component_span_min = 0.0
    for _, members in components.items():
        if len(members) == 1:
            keep.add(members[0])
            continue
        best = max(members,
                   key=lambda idx: (events[idx][3], -events[idx][0].timestamp()))
        keep.add(best)
        drop["same_class_proximity"] += len(members) - 1
        ts_list = [events[i][0] for i in members]
        span_min = (max(ts_list) - min(ts_list)).total_seconds() / 60.0
        if span_min > max_component_span_min:
            max_component_span_min = span_min

    events = [events[i] for i in range(n) if i in keep]

    n_bins = len(OFFSET_BINS)
    m = len(events)
    lfps = np.full((n_bins, m), np.nan)
    y = np.zeros(m, dtype=int)
    for j, (_, lab, bin_vals, _) in enumerate(events):
        y[j] = lab
        for i, b in enumerate(OFFSET_BINS):
            if b in bin_vals:
                lfps[i, j] = bin_vals[b]

    return lfps, y, drop, n_ts_raw, max_component_span_min


def compute_usable_mask(lfps: np.ndarray, y: np.ndarray,
                        n_min: int = MIN_PER_CLASS) -> np.ndarray:
    n_bins = lfps.shape[0]
    n1 = int(np.sum(y == 1))
    n0 = int(np.sum(y == 0))
    threshold = min(n1, n0) + n_min
    mask = np.zeros(n_bins, dtype=bool)
    for i in range(n_bins):
        V = int(np.sum(~np.isnan(lfps[i, :])))
        mask[i] = V >= threshold
    return mask


def per_bin_abs_z(lfps: np.ndarray, y: np.ndarray,
                  usable_mask: Optional[np.ndarray] = None) -> np.ndarray:
    n_bins = lfps.shape[0]
    z = np.zeros(n_bins)
    for i in range(n_bins):
        if usable_mask is not None and not usable_mask[i]:
            continue
        cvals = lfps[i, y == 1]
        nvals = lfps[i, y == 0]
        cvals = cvals[~np.isnan(cvals)]
        nvals = nvals[~np.isnan(nvals)]
        n1, n2 = len(cvals), len(nvals)
        if n1 < MIN_PER_CLASS or n2 < MIN_PER_CLASS:
            continue
        _, p = mannwhitneyu(cvals, nvals,
                            alternative="two-sided",
                            method="asymptotic")
        if not np.isfinite(p) or p <= 0.0:
            z[i] = np.inf
        elif p >= 1.0:
            z[i] = 0.0
        else:
            z[i] = float(abs(norm.isf(p / 2.0)))
    return z


def find_clusters(z_vec: np.ndarray, threshold: float):
    clusters = []
    in_cl = False
    start = 0
    mass = 0.0
    for i, zi in enumerate(z_vec):
        if zi > threshold:
            if not in_cl:
                in_cl = True
                start = i
                mass = float(zi)
            else:
                mass += float(zi)
        else:
            if in_cl:
                clusters.append((start, i - 1, mass))
                in_cl = False
    if in_cl:
        clusters.append((start, len(z_vec) - 1, mass))
    return clusters


def cluster_perm_test(lfps: np.ndarray, y: np.ndarray,
                      n_perm: int = N_PERMUTATIONS,
                      seed: int = RANDOM_STATE,
                      cluster_thresh: float = CLUSTER_FORMING_Z) -> Dict:
    usable_mask = compute_usable_mask(lfps, y)
    obs_z = per_bin_abs_z(lfps, y, usable_mask=usable_mask)
    obs_clusters = find_clusters(obs_z, cluster_thresh)

    rng = np.random.RandomState(seed)
    null_max = np.zeros(n_perm)
    y_work = y.copy()
    for p in range(n_perm):
        rng.shuffle(y_work)
        z_perm = per_bin_abs_z(lfps, y_work, usable_mask=usable_mask)
        cl = find_clusters(z_perm, cluster_thresh)
        null_max[p] = max((c[2] for c in cl), default=0.0)

    cluster_results = []
    for (s, e, mass) in obs_clusters:
        p_val = (np.sum(null_max >= mass) + 1) / (n_perm + 1)
        cluster_results.append({
            "start_bin": OFFSET_BINS[s],
            "end_bin": OFFSET_BINS[e],
            "start_idx": s,
            "end_idx": e,
            "mass": mass,
            "p": float(p_val),
        })

    return {
        "obs_z": obs_z,
        "clusters": cluster_results,
        "null_max": null_max,
        "usable_mask": usable_mask,
    }


def per_bin_mean_ci(lfps: np.ndarray, y: np.ndarray,
                    n_boot: int = 5000,
                    seed: int = RANDOM_STATE) -> Dict[str, np.ndarray]:
    n_bins = lfps.shape[0]
    out = {k: np.full(n_bins, np.nan)
           for k in ("craving_mean", "craving_lo", "craving_hi",
                     "craving_n",
                     "neutral_mean", "neutral_lo", "neutral_hi",
                     "neutral_n")}
    rng = np.random.RandomState(seed)
    for i in range(n_bins):
        for lab, prefix in ((1, "craving"), (0, "neutral")):
            vals = lfps[i, y == lab]
            vals = vals[~np.isnan(vals)]
            out[f"{prefix}_n"][i] = len(vals)
            if len(vals) < 3:
                m = float(np.mean(vals)) if len(vals) else float("nan")
                out[f"{prefix}_mean"][i] = m
                out[f"{prefix}_lo"][i] = m
                out[f"{prefix}_hi"][i] = m
                continue
            boot = rng.choice(vals, size=(n_boot, len(vals)),
                              replace=True).mean(axis=1)
            out[f"{prefix}_mean"][i] = float(vals.mean())
            out[f"{prefix}_lo"][i] = float(np.percentile(boot, 2.5))
            out[f"{prefix}_hi"][i] = float(np.percentile(boot, 97.5))
    return out


PANELS = [
    ("pt1", "left",  "Pt1 left NAc"),
    ("pt2", "left",  "Pt2 left NAc"),
    ("pt2", "right", "Pt2 right NAc"),
]


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cluster-based permutation peri-event analysis of Timeline narrowband amplitude.",
    )
    parser.add_argument("--pt1-snapshots", required=True, type=Path)
    parser.add_argument("--pt2-snapshots", required=True, type=Path)
    parser.add_argument("--pt1-timeline", required=True, type=Path)
    parser.add_argument("--pt2-timeline", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--n-perm", type=int, default=N_PERMUTATIONS)
    parser.add_argument("--seed", type=int, default=RANDOM_STATE)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    snap_csv = {"pt1": args.pt1_snapshots, "pt2": args.pt2_snapshots}
    tl_csv = {"pt1": args.pt1_timeline, "pt2": args.pt2_timeline}

    snap_by_pt = {pt: load_snapshots_csv(snap_csv[pt]) for pt in ("pt1", "pt2")}

    bin_rows = []
    cluster_rows = []
    summary_rows = []

    for pid, hemi, title in PANELS:
        print(f"\n  === {title} ===", flush=True)
        timeline_ts, timeline_val = load_timeline_csv(tl_csv[pid], hemi)
        lfps, y, drop, n_ts_raw, max_span = get_data(
            snap_by_pt[pid], timeline_ts, timeline_val, hemi,
        )
        n_c = int(np.sum(y == 1))
        n_n = int(np.sum(y == 0))
        print(f"    retained: {n_c} craving, {n_n} non-craving "
              f"(raw {n_ts_raw}; dropped mixed={drop['mixed_label']}, "
              f"cross={drop['cross_class_proximity']}, "
              f"same={drop['same_class_proximity']})", flush=True)

        stats = per_bin_mean_ci(lfps, y, n_boot=5000, seed=args.seed)
        print(f"    running {args.n_perm:,} permutations…", flush=True)
        perm = cluster_perm_test(lfps, y, n_perm=args.n_perm, seed=args.seed)

        for i, b in enumerate(OFFSET_BINS):
            bin_rows.append({
                "patient": pid,
                "hemisphere": hemi,
                "bin_min": b,
                "n_craving": int(stats["craving_n"][i]),
                "mean_craving": stats["craving_mean"][i],
                "ci_lo_craving": stats["craving_lo"][i],
                "ci_hi_craving": stats["craving_hi"][i],
                "n_non_craving": int(stats["neutral_n"][i]),
                "mean_non_craving": stats["neutral_mean"][i],
                "ci_lo_non_craving": stats["neutral_lo"][i],
                "ci_hi_non_craving": stats["neutral_hi"][i],
                "abs_z": float(perm["obs_z"][i]),
                "usable": bool(perm["usable_mask"][i]),
            })

        for k, cl in enumerate(perm["clusters"]):
            cluster_rows.append({
                "patient": pid,
                "hemisphere": hemi,
                "cluster_id": k + 1,
                "start_bin_min": cl["start_bin"],
                "end_bin_min": cl["end_bin"],
                "cluster_mass": cl["mass"],
                "p_value": cl["p"],
            })
            mark = " [sig]" if cl["p"] <= 0.05 else ""
            print(f"    cluster {cl['start_bin']:+d}..{cl['end_bin']:+d}  "
                  f"mass={cl['mass']:.2f}  p={cl['p']:.4f}{mark}", flush=True)
        if not perm["clusters"]:
            print("    no supra-threshold clusters", flush=True)

        min_cluster_p = min((c["p"] for c in perm["clusters"]), default=1.0)
        summary_rows.append({
            "patient": pid,
            "hemisphere": hemi,
            "n_craving": n_c,
            "n_non_craving": n_n,
            "n_clusters": len(perm["clusters"]),
            "min_cluster_p": float(min_cluster_p),
            "max_component_span_min": float(max_span),
            "drop_mixed_label": int(drop["mixed_label"]),
            "drop_cross_class": int(drop["cross_class_proximity"]),
            "drop_same_class": int(drop["same_class_proximity"]),
        })

    pd.DataFrame(bin_rows).to_csv(
        args.out_dir / "timeline_stats_cluster_permutation_bins.csv",
        index=False, float_format="%.6f",
    )
    pd.DataFrame(cluster_rows).to_csv(
        args.out_dir / "timeline_stats_cluster_permutation_clusters.csv",
        index=False, float_format="%.6f",
    )
    pd.DataFrame(summary_rows).to_csv(
        args.out_dir / "timeline_stats_cluster_permutation_summary.csv",
        index=False, float_format="%.6f",
    )
    print("\nWrote 3 CSVs to", args.out_dir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
