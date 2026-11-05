"""
Pure analysis core for the Timeline Mean ±20 LFP threshold pipeline.

Hosts `OFFSET_BINS_EXT`, `WINDOW_MINUTES_EXT`, `extract_offset_matrix_ext`,
and `run_hemisphere`. Imports constants/helpers from `_threshold_constants`
and analysis helpers from `bulletproof_threshold`. **No matplotlib import.**

The thin wrapper `timeline_mean20_threshold.py` re-exports the public API
from this module so existing positional callers and figure-script paths
stay byte-compatible.
"""

import sys
import time
from collections import defaultdict
from datetime import timedelta
from typing import Callable, Optional

import numpy as np

from ._threshold_constants import (
    BIN_TOLERANCE,
    MIN_EVENTS_PER_CLASS,
    MIN_INTER_EVENT_MINUTES,
    classify_event,
    compute_classic_stats,
)
from .bulletproof_threshold import (
    N_BOOTSTRAP,
    RANDOM_STATE,
    bca_bootstrap_rrb,
    bootstrap_auc_ci,
    cluster_bootstrap_threshold,
    fit_lr_threshold,
    loo_auc,
    loo_predict,
    permutation_test_loo,
    stratified_bootstrap_sens_spec_ci,
    youden_threshold,
)


__all__ = [
    "OFFSET_BINS_EXT",
    "WINDOW_MINUTES_EXT",
    "extract_offset_matrix_ext",
    "run_hemisphere",
]


def _safe_print(*args, **kwargs) -> None:
    """``print`` that swallows :class:`BrokenPipeError` / :class:`OSError`.

    The Qt worker that drives the in-app pipeline writes diagnostic text
    to stdout. When the GUI app is launched from a context whose stdout
    pipe is later closed (background-spawn, detached terminal, certain
    bundled-app launch paths on macOS), `print` raises ``BrokenPipeError``
    and crashes the analysis. The manuscript-script CLI path keeps its
    stdout output verbatim — `_safe_print` only departs from `print` when
    the underlying write fails."""
    try:
        print(*args, **kwargs)
    except (BrokenPipeError, OSError):
        pass


# ─── Narrow-window configuration ──────────────────────────────────────────
WINDOW_MINUTES_EXT: int = 20
OFFSET_BINS_EXT = [-20, -10, 0, 10, 20]


# ─── Data extraction — narrower window, same exclusion rules ──────────────
def extract_offset_matrix_ext(
    patient_id, snapshot_repo, timeline_repo, hemisphere,
    *,
    group1_event_names=None,
    group2_event_names=None,
    window_minutes: Optional[int] = None,
):
    """
    Build (n_bins, n_events) LFP matrix at ±window offset bins + label vector.

    Structurally identical to lfp_threshold_publication.extract_offset_matrix
    but with a narrower default window (`WINDOW_MINUTES_EXT = 20` minutes
    yielding the 5-element `OFFSET_BINS_EXT`). Event exclusion rules
    (conflict, 60-min cross-class proximity) unchanged.

    The optional ``window_minutes`` overrides the module default. Bins are
    derived deterministically as ``range(-window, window + 1, 10)`` so the
    10-min spacing is preserved at any window length. Manuscript-script
    callers pass nothing → identical bins as before (byte-equivalent).

    Two operating modes:

    * **User-group mode** (in-app path): when ``group1_event_names`` and/or
      ``group2_event_names`` is provided, label is decided by group
      membership — Group 1 → 0 (non-craving, Jade), Group 2 → 1 (craving,
      Rose). Snapshots whose ``event_name`` is in neither group are dropped.
    * **Legacy mode** (manuscript scripts, both args ``None``): label is
      decided by ``classify_event`` keyword matching; this is the original
      Figure 3 d-f pipeline. Manuscript callers stay byte-equivalent.

    The conflict-exclusion (mixed-class timestamps) and 60-min cross-class
    proximity rules apply identically in both modes — they operate on the
    abstract ``"craving" | "neutral"`` strings inside ``by_ts``.
    """
    if window_minutes is None:
        window = WINDOW_MINUTES_EXT
        bins = OFFSET_BINS_EXT
    else:
        window = int(window_minutes)
        if window < 10 or window % 10 != 0:
            raise ValueError(
                f"window_minutes must be a positive multiple of 10, got {window_minutes!r}"
            )
        bins = list(range(-window, window + 1, 10))
    snapshots = snapshot_repo.get_by_time_range(
        patient_id=patient_id, patient_events_only=True, limit=100000,
    )

    use_group_labels = (
        group1_event_names is not None or group2_event_names is not None
    )
    if use_group_labels:
        g1_set = frozenset(group1_event_names or [])
        g2_set = frozenset(group2_event_names or [])
        # Service guarantees disjointness; assert defensively so a caller
        # bypassing the service cannot silently produce ambiguous labels.
        assert g1_set.isdisjoint(g2_set), \
            "group1 and group2 event_name sets must be disjoint"

        def _label_for(name):
            if name in g2_set:
                return "craving"   # label 1 (Group 2, Rose)
            if name in g1_set:
                return "neutral"   # label 0 (Group 1, Jade)
            return None
    else:
        _label_for = classify_event

    by_ts = defaultdict(list)
    for s in snapshots:
        label_str = _label_for(s.event_name)
        if label_str:
            by_ts[s.timestamp].append(label_str)

    sorted_timestamps = sorted(by_ts.keys())

    excluded_ts = {ts for ts in sorted_timestamps if len(set(by_ts[ts])) > 1}

    for i in range(len(sorted_timestamps)):
        for j in range(i + 1, len(sorted_timestamps)):
            delta = (
                sorted_timestamps[j] - sorted_timestamps[i]
            ).total_seconds() / 60
            if delta > MIN_INTER_EVENT_MINUTES:
                break
            if set(by_ts[sorted_timestamps[i]]) != set(by_ts[sorted_timestamps[j]]):
                excluded_ts.add(sorted_timestamps[i])
                excluded_ts.add(sorted_timestamps[j])

    events = []
    hemi_attr = f"{hemisphere}_hemisphere"

    for ts in sorted_timestamps:
        if ts in excluded_ts:
            continue
        label = 1 if by_ts[ts][0] == "craving" else 0

        records = timeline_repo.get_by_time_range(
            patient_id=patient_id,
            start_time=ts - timedelta(minutes=window),
            end_time=ts + timedelta(minutes=window),
            limit=500,
        )
        clean = [r for r in records if not r.is_outlier]

        by_bin = {}
        for r in clean:
            val = getattr(r, hemi_attr, None)
            if val is None:
                continue
            offset_min = (r.timestamp - ts).total_seconds() / 60
            nearest_bin = int(round(offset_min / 10) * 10)
            if nearest_bin not in bins:
                continue
            distance = abs(offset_min - nearest_bin)
            if distance > BIN_TOLERANCE:
                continue
            if nearest_bin not in by_bin or distance < by_bin[nearest_bin][1]:
                by_bin[nearest_bin] = (val, distance)

        events.append({
            "timestamp": ts,
            "label": label,
            "offsets": {b: by_bin[b][0] for b in by_bin},
        })

    n_events = len(events)
    offset_lfps = np.full((len(bins), n_events), np.nan)
    y = np.array([e["label"] for e in events])

    for j, e in enumerate(events):
        for i, b in enumerate(bins):
            if b in e["offsets"]:
                offset_lfps[i, j] = e["offsets"][b]

    return offset_lfps, y


def run_hemisphere(
    patient_id,
    snapshot_repo,
    timeline_repo,
    hemisphere,
    n_perm,
    n_jobs,
    *,
    n_boot: int = N_BOOTSTRAP,
    seed: int = RANDOM_STATE,
    group1_event_names=None,
    group2_event_names=None,
    window_minutes: Optional[int] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
):
    """
    Run the Timeline Mean threshold pipeline for one hemisphere.

    Returns the publication-equivalent results dict, or None when the
    hemisphere has insufficient data. New return-dict keys vs the previous
    container-based signature: `lr_coef_sign`, `perm_p_floor`, and a
    top-level `mann_whitney_p` alias mirroring the value inside `stats`.

    `window_minutes` overrides the published ±20 default; bins are derived
    deterministically as ``range(-window, window + 1, 10)``. Manuscript
    callers pass nothing → behaviour identical to the previous fixed-±20
    pipeline.

    `progress_callback(stage_done, stage_total, label)` is forwarded into
    the cancellable inner loops when `cancel_check is not None`. The
    parallel manuscript-script path (`cancel_check is None`) is unchanged.
    """
    use_chunked = cancel_check is not None
    if use_chunked:
        # Cancel-aware in-app path: chunked-parallel permutation (~3× the
        # speed of the serial loop), chunked-cancellable bootstraps. All
        # three are bit-equal to the parallel originals under matched
        # (n_perm/n_boot, seed); see tests/integration/test_serial_cancellable_helpers.py.
        from .bulletproof_threshold import (
            bootstrap_auc_ci_chunked,
            cluster_bootstrap_threshold_chunked,
            permutation_test_loo_chunked,
        )

    if window_minutes is None:
        resolved_window = WINDOW_MINUTES_EXT
        resolved_bins = OFFSET_BINS_EXT
    else:
        resolved_window = int(window_minutes)
        if resolved_window < 10 or resolved_window % 10 != 0:
            raise ValueError(
                f"window_minutes must be a positive multiple of 10, got {window_minutes!r}"
            )
        resolved_bins = list(range(-resolved_window, resolved_window + 1, 10))

    _safe_print(f"\n  {patient_id} {hemisphere.upper()}  (±{resolved_window} min, "
          f"{len(resolved_bins)} bins)")
    _safe_print(f"  {'─' * 50}")

    if progress_callback is not None:
        progress_callback(0, 1, "Extracting events")

    offset_lfps, y = extract_offset_matrix_ext(
        patient_id, snapshot_repo, timeline_repo, hemisphere,
        group1_event_names=group1_event_names,
        group2_event_names=group2_event_names,
        window_minutes=window_minutes,
    )
    n_total = len(y)
    n_c_total = int(np.sum(y == 1))
    n_n_total = int(np.sum(y == 0))
    _safe_print(f"  Events extracted: {n_c_total} craving, {n_n_total} neutral "
          f"(n={n_total})")

    coverage = np.mean(~np.isnan(offset_lfps), axis=1) if n_total else np.zeros(0)
    if n_total:
        _safe_print(f"  Mean bin fill across {len(resolved_bins)} bins: "
                    f"{coverage.mean():.1%}  (range {coverage.min():.1%}–{coverage.max():.1%})")

    if cancel_check is not None and cancel_check():
        from .bulletproof_threshold import CancelledError
        raise CancelledError()

    X_raw = (np.nanmean(offset_lfps, axis=0) if n_total
             else np.array([], dtype=float))
    valid = ~np.isnan(X_raw)
    X = X_raw[valid]
    y_v = y[valid]

    n_c = int(np.sum(y_v == 1))
    n_n = int(np.sum(y_v == 0))
    dropped = n_total - len(y_v)
    n_bins_per_event = (np.sum(~np.isnan(offset_lfps[:, valid]), axis=0)
                        if n_total else np.zeros(0, dtype=int))
    _safe_print(f"  After all-NaN-row drop: {n_c} craving, {n_n} neutral "
          f"({dropped} events dropped with 0 bins)")
    if n_total:
        _safe_print(f"  Per-event bin count: median {int(np.median(n_bins_per_event))}, "
                    f"min {int(n_bins_per_event.min())}, max {int(n_bins_per_event.max())}")

    if n_c < MIN_EVENTS_PER_CLASS or n_n < MIN_EVENTS_PER_CLASS:
        _safe_print(f"  Insufficient data (min {MIN_EVENTS_PER_CLASS}/class)")
        return None

    stats = compute_classic_stats(X, y_v, seed=seed, n_boot=n_boot)
    _safe_print(f"  Cohen's d: {stats['cohens_d']:.3f}  MW p: {stats['mann_whitney_p']:.4f}")

    lr_threshold, lr_coef = fit_lr_threshold(X, y_v)
    direction = "above" if lr_coef > 0 else "below"
    _safe_print(f"  LR threshold: {lr_threshold:.0f} µV (craving {direction})")

    yj_threshold, yj_J, yj_craving_above = youden_threshold(X, y_v)
    _safe_print(f"  Youden's J threshold: {yj_threshold:.0f} µV (J = {yj_J:.3f})")
    _safe_print(f"  Δ(LR - Youden's J): {lr_threshold - yj_threshold:+.0f} µV")

    _safe_print(f"  Running LOO-CV...")
    t0 = time.time()
    auc_loo, oof_prob = loo_auc(X, y_v)
    _, fold_thresholds, fold_signs = loo_predict(X, y_v)
    _safe_print(f"  LOO AUC: {auc_loo:.3f}  ({time.time() - t0:.1f}s)")

    if use_chunked:
        auc_ci_lo, auc_ci_hi, auc_std = bootstrap_auc_ci_chunked(
            y_v, oof_prob, n_boot=n_boot, seed=seed,
            cancel_check=cancel_check,
            progress_callback=(
                (lambda d, t: progress_callback(d, t, "Bootstrapping AUC CI"))
                if progress_callback is not None else None
            ),
        )
    else:
        auc_ci_lo, auc_ci_hi, auc_std = bootstrap_auc_ci(
            y_v, oof_prob, n_boot=n_boot, seed=seed,
        )
    _safe_print(f"  AUC bootstrap 95% CI: [{auc_ci_lo:.3f}, {auc_ci_hi:.3f}]")

    _safe_print(f"  Cluster bootstrap on threshold ({n_boot} resamples)...")
    if use_chunked:
        thr_ci, sign_stability, _ = cluster_bootstrap_threshold_chunked(
            X, y_v, n_boot=n_boot, seed=seed,
            cancel_check=cancel_check,
            progress_callback=(
                (lambda d, t: progress_callback(d, t, "Bootstrapping threshold"))
                if progress_callback is not None else None
            ),
        )
    else:
        thr_ci, sign_stability, _ = cluster_bootstrap_threshold(
            X, y_v, n_boot=n_boot, seed=seed,
        )
    _safe_print(f"  Threshold 95% CI: [{thr_ci[0]:.0f}, {thr_ci[1]:.0f}] µV")
    _safe_print(f"  Sign stability: {sign_stability:.1%}")

    fold_thr_valid = fold_thresholds[~np.isnan(fold_thresholds)]
    fold_thr_median = float(np.median(fold_thr_valid))
    fold_thr_iqr = (float(np.percentile(fold_thr_valid, 25)),
                    float(np.percentile(fold_thr_valid, 75)))
    fold_sign_stability = float(np.mean(np.sign(fold_signs) == np.sign(lr_coef)))

    y_pred = (oof_prob >= 0.5).astype(int)
    tp = int(np.sum((y_v == 1) & (y_pred == 1)))
    fn = int(np.sum((y_v == 1) & (y_pred == 0)))
    fp = int(np.sum((y_v == 0) & (y_pred == 1)))
    tn = int(np.sum((y_v == 0) & (y_pred == 0)))
    sens = tp / (tp + fn) if (tp + fn) else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    ppv = tp / (tp + fp) if (tp + fp) else 0.0
    npv = tn / (tn + fn) if (tn + fn) else 0.0

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

    # In-app chunked path saturates cores by default; the manuscript-script
    # path keeps whatever the CLI caller chose.
    # Frozen (PyInstaller) builds must not spawn worker processes: joblib's
    # loky backend re-execs the app bundle and relaunches the GUI. Force
    # in-process execution (n_jobs=1) when frozen; dev runs stay multi-core.
    perm_n_jobs = (
        1 if getattr(sys, "frozen", False)
        else (-1 if (use_chunked and n_jobs == 1) else n_jobs)
    )
    _safe_print(f"  Permutation test ({n_perm} perms, {perm_n_jobs} jobs)...")
    t0 = time.time()
    if use_chunked:
        perm_p, null_aucs = permutation_test_loo_chunked(
            X, y_v, auc_loo, n_perm,
            n_jobs=perm_n_jobs, seed=seed,
            cancel_check=cancel_check,
            progress_callback=(
                (lambda d, t: progress_callback(d, t, "Permuting"))
                if progress_callback is not None else None
            ),
        )
    else:
        perm_p, null_aucs = permutation_test_loo(
            X, y_v, auc_loo, n_perm, n_jobs, seed=seed,
        )
    p_floor = 1 / (1 + n_perm)
    p_txt = f"< {p_floor:.4f}" if perm_p <= p_floor + 1e-12 else f"= {perm_p:.4f}"
    _safe_print(f"  Permutation p {p_txt}  ({time.time() - t0:.1f}s)")

    verdict_auc_ok = auc_ci_lo > 0.5
    verdict_perm_ok = perm_p < 0.05
    verdict = verdict_auc_ok and verdict_perm_ok

    # Sens/spec 95% CI at oof_prob >= 0.5 (LR decision boundary) and the
    # rank-biserial BCa CI. Both use dedicated fixed seeds/resample counts
    # (NOT the main pipeline seed/n_boot) to reproduce the manuscript-published
    # values in code_release/scripts/4_…classifier.py bit-for-bit. Both are
    # cheap (no LR refits) so they run unconditionally on the cancellable path.
    (sens_ci_lo, sens_ci_hi), (spec_ci_lo, spec_ci_hi) = (
        stratified_bootstrap_sens_spec_ci(y_v, oof_prob)
    )
    r_rb_point, r_rb_lo, r_rb_hi = bca_bootstrap_rrb(X[y_v == 1], X[y_v == 0])

    return {
        "patient_id": patient_id, "hemisphere": hemisphere,
        # Per-event feature and labels — kept for figure generation so the
        # plotting pass does not repeat the LOO-CV.
        "X": X, "y": y_v,
        "n_craving": n_c, "n_neutral": n_n, "n_valid": len(y_v),
        "n_dropped": dropped,
        "bins_per_event_median": int(np.median(n_bins_per_event)) if n_total else 0,
        "bins_per_event_min": int(n_bins_per_event.min()) if n_total else 0,
        "bins_per_event_max": int(n_bins_per_event.max()) if n_total else 0,
        "bin_coverage_mean": float(coverage.mean()) if n_total else 0.0,
        "stats": stats,
        "lr_threshold": lr_threshold, "lr_coef": lr_coef,
        "lr_coef_sign": int(np.sign(lr_coef)),
        "direction": direction,
        "lr_threshold_ci": thr_ci,
        "sign_stability": sign_stability,
        "yj_threshold": yj_threshold, "yj_J": yj_J,
        "yj_craving_above": yj_craving_above,
        "auc_loo": auc_loo, "oof_prob": oof_prob,
        "auc_ci": (auc_ci_lo, auc_ci_hi), "auc_std": auc_std,
        "fold_thr_median": fold_thr_median,
        "fold_thr_iqr": fold_thr_iqr,
        "fold_sign_stability": fold_sign_stability,
        "sensitivity_lr": sens, "specificity_lr": spec,
        "sens_ci": (sens_ci_lo, sens_ci_hi),
        "spec_ci": (spec_ci_lo, spec_ci_hi),
        "ppv_lr": ppv, "npv_lr": npv,
        "sensitivity_yj": yj_sens, "specificity_yj": yj_spec,
        "perm_p": perm_p, "perm_p_floor": p_floor,
        "mann_whitney_p": float(stats["mann_whitney_p"]),
        "r_rb": float(r_rb_point),
        "r_rb_ci_lo": float(r_rb_lo), "r_rb_ci_hi": float(r_rb_hi),
        "null_aucs": null_aucs,
        "verdict": verdict,
        "verdict_auc_ok": verdict_auc_ok, "verdict_perm_ok": verdict_perm_ok,
    }
