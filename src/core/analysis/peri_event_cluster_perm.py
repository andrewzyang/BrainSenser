"""Cluster-based permutation peri-event analysis engine (pure).

Dependency-light (numpy + scipy only) implementation of the manuscript's
cluster-mass permutation test on BrainSense Timeline narrowband
(5.31-10.31 Hz) amplitude. Vendored **verbatim** from the manuscript
reference script
``code_release/scripts/3_timeline_stats_cluster_permutation.py`` (the
algorithmic oracle); the in-app Peri-Event tab pins to it bit-for-bit via
``tests/integration/test_peri_event_cluster_perm_parity.py``.

The only additions over the reference:

  * an explicit group-name labeling branch in :func:`get_data` so the
    app's group picker can drive the craving / non-craving assignment by
    event-name membership (**Group 1 -> label 0 / non-craving**,
    **Group 2 -> label 1 / craving**); passing no group names falls back
    to the publication keyword matcher :func:`classify`, which is the
    path the parity test exercises;
  * an optional ``window_minutes`` / ``offset_bins`` parameterization so
    the GUI can offer an adjustable peri-event window. The defaults
    (``WINDOW_MINUTES = 50``, the 11 ``OFFSET_BINS``) reproduce the
    manuscript analysis exactly, so the four-positional-argument call
    used by the parity test is byte-identical to the reference.

**No Qt, no database, no filesystem, no hardcoded paths.**

Statistics (identical to the reference):
  - Per-bin tie-corrected two-sided Mann-Whitney U -> |z| = |Phi^-1(p/2)|
    (scipy ``method="asymptotic"`` inherits the Lehmann tie correction).
  - Cluster-forming threshold |z| > norm.ppf(0.975) ~ 1.96.
  - Cluster mass = sum of |z| across consecutive suprathreshold bins.
  - Null: maximum cluster mass per permutation across N event-level label
    shuffles (per-event bin vectors kept intact; only labels shuffled).
  - Cluster p-value via Phipson-Smyth 2010:
    ``(sum[null >= obs] + 1) / (n_perm + 1)``.
  - Per-bin mean 95% percentile bootstrap CI (display only; not in the
    cluster test).

Event exclusion (identical to the reference):
  - Same-timestamp mixed-label events discarded.
  - Cross-class events within 60 min mutually excluded.
  - Same-class events within 60 min pruned to the highest-coverage event
    per connected component of the within-60-min same-class graph
    (union-find; ties broken by earliest timestamp).
  - A label-invariant ``usable_mask`` is applied identically to observed
    and permuted |z|: a bin passes iff its non-NaN count
    ``V >= min(n_craving, n_neutral) + MIN_PER_CLASS``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import mannwhitneyu, norm


# ─── Constants (manuscript) ──────────────────────────────────────────────
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


def offset_bins_for_window(window_minutes: int) -> List[int]:
    """Return the 10-min-spaced bin centers for a ``±window_minutes`` window.

    ``offset_bins_for_window(50)`` reproduces the manuscript
    :data:`OFFSET_BINS` exactly, so the default GUI path and the parity
    path share identical bins.
    """
    w = int(window_minutes)
    return list(range(-w, w + 10, 10))


def classify(name: Optional[str]) -> Optional[str]:
    """Publication keyword matcher: craving / neutral / None."""
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


def _label_for(
    name: Optional[str],
    g1_set: Optional[frozenset],
    g2_set: Optional[frozenset],
) -> Optional[str]:
    """Label an event name as ``"craving"`` / ``"neutral"`` / ``None``.

    When either group set is provided (the in-app group-picker path),
    membership decides the class — **Group 2 -> "craving"** (label 1),
    **Group 1 -> "neutral"** (label 0); names in neither group are
    ignored. Group 2 takes precedence if a name somehow appears in both
    (the service validates the groups are disjoint, so this never fires in
    practice). With no group sets, fall back to :func:`classify` — the
    byte-exact parity path.
    """
    if g1_set is not None or g2_set is not None:
        if g2_set is not None and name in g2_set:
            return "craving"
        if g1_set is not None and name in g1_set:
            return "neutral"
        return None
    return classify(name)


def get_data(
    snapshots: Sequence[Tuple[datetime, str]],
    timeline_ts: np.ndarray,
    timeline_val: np.ndarray,
    hemi: str,
    group1_event_names: Optional[Iterable[str]] = None,
    group2_event_names: Optional[Iterable[str]] = None,
    *,
    window_minutes: int = WINDOW_MINUTES,
    offset_bins: Optional[Sequence[int]] = None,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, int], int, float]:
    """Build the ``(n_bins, n_events)`` LFP matrix and ``(n_events,)`` label
    vector, applying the manuscript's three event-exclusion rules.

    Parameters
    ----------
    snapshots
        ``[(timestamp, event_name)]`` already deduplicated by
        ``(timestamp, event_name)`` so multi-hemisphere snapshot rows
        collapse to one event per pair.
    timeline_ts, timeline_val
        Parallel arrays of unix-second timestamps (sorted ascending) and
        the requested hemisphere's narrowband amplitude (NaN where
        missing). ``hemi`` is retained for signature parity with the
        reference; the value array is already hemisphere-specific.
    group1_event_names, group2_event_names
        Optional explicit class membership (Group 1 -> non-craving / 0,
        Group 2 -> craving / 1). ``None`` for both -> :func:`classify`
        keyword fallback (the parity path).
    window_minutes, offset_bins
        Peri-event window and bin centers. Defaults reproduce the
        manuscript ±50-min / 11-bin analysis.

    Returns
    -------
    ``(lfps, y, drop_counts, n_ts_raw, max_same_class_span_min)``.
    """
    del hemi  # value array is already hemisphere-specific; kept for parity.
    if offset_bins is None:
        offset_bins = offset_bins_for_window(window_minutes)
    offset_set = set(offset_bins)

    g1_set = frozenset(group1_event_names) if group1_event_names is not None else None
    g2_set = frozenset(group2_event_names) if group2_event_names is not None else None

    by_ts: Dict[datetime, List[str]] = defaultdict(list)
    for ts, name in snapshots:
        lab = _label_for(name, g1_set, g2_set)
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
    window_s = window_minutes * 60.0

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

    n_bins = len(offset_bins)
    m = len(events)
    lfps = np.full((n_bins, m), np.nan)
    y = np.zeros(m, dtype=int)
    for j, (_, lab, bin_vals, _) in enumerate(events):
        y[j] = lab
        for i, b in enumerate(offset_bins):
            if b in bin_vals:
                lfps[i, j] = bin_vals[b]

    return lfps, y, drop, n_ts_raw, max_component_span_min


def compute_usable_mask(lfps: np.ndarray, y: np.ndarray,
                        n_min: int = MIN_PER_CLASS) -> np.ndarray:
    """Label-invariant mask of bins usable for the cluster test.

    A bin passes iff its non-NaN count ``V >= min(n_craving, n_neutral) +
    n_min``. The condition depends only on the raw LFP matrix and the
    total class counts (invariant under label permutation), so the mask is
    identical for the observed labels and every permuted label vector.
    """
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
    """Two-sided MWU -> |z| for each bin, NaN-safe.

    ``|z| = |Phi^-1(p/2)|`` from scipy's tie-corrected asymptotic
    two-sided p. Bins flagged ``False`` in ``usable_mask`` return 0, as do
    bins with fewer than ``MIN_PER_CLASS`` non-NaN values in either class.
    """
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
    """Return ``[(start_idx, end_idx_inclusive, mass)]`` for runs of
    consecutive ``z_i > threshold``; mass is the sum of ``z_i`` in the run."""
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
                      cluster_thresh: float = CLUSTER_FORMING_Z,
                      offset_bins: Optional[Sequence[int]] = None,
                      progress_callback=None,
                      cancel_check=None) -> Dict:
    """Event-level label-shuffle cluster-mass permutation test.

    Identical to the reference. ``offset_bins`` (default :data:`OFFSET_BINS`)
    maps cluster start/end indices back to bin-center minutes. The optional
    ``progress_callback(done, total)`` and ``cancel_check() -> bool`` hooks
    let the GUI worker report progress and cancel cooperatively; both are
    no-ops by default so the parity path is unaffected.
    """
    if offset_bins is None:
        offset_bins = OFFSET_BINS

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
        if cancel_check is not None and cancel_check():
            raise PeriEventCancelled()
        if progress_callback is not None and (p % 100 == 0 or p == n_perm - 1):
            progress_callback(p + 1, n_perm)

    cluster_results = []
    for (s, e, mass) in obs_clusters:
        p_val = (np.sum(null_max >= mass) + 1) / (n_perm + 1)
        cluster_results.append({
            "start_bin": offset_bins[s],
            "end_bin": offset_bins[e],
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
    """Per-bin, per-class mean + 95% percentile bootstrap CI (display only)."""
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


class PeriEventCancelled(Exception):
    """Raised from :func:`cluster_perm_test` when ``cancel_check`` trips."""
