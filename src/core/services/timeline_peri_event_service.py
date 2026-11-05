"""Timeline → Peri-Event service.

Pure analysis service that adapts the repositories to the vendored
:mod:`src.core.analysis.peri_event_cluster_perm` engine. Validates the
user's group selection (Group 1 → label 0 / non-craving, Group 2 → label 1
/ craving) and returns either a :class:`PeriEventResult` (full
cluster-permutation output) or an :class:`InsufficientPeriEvent` (guard
tripped) per hemisphere. Labels are decided by group membership, matching
the Snapshots 5 Hz Band / LFP Threshold convention.

Data path (single code path shared with the manuscript CSV oracle): fetch
all patient events, dedup by ``(timestamp, event_name)``; fetch the full
timeline, drop ``is_outlier`` rows, and build sorted unix-second timestamp
+ per-hemisphere value arrays (``None`` → NaN). The engine then performs
identical windowing, binning, event exclusion, and cluster-permutation
statistics to the reference, so the same ``(lfps, y)`` flows through both.

Headless and Qt-free **and** matplotlib-free.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from src.core.analysis import peri_event_cluster_perm as engine

__all__ = [
    "PeriEventResult",
    "InsufficientPeriEvent",
    "HemiResult",
    "TimelinePeriEventService",
    "DEFAULT_WINDOW_MINUTES",
    "DEFAULT_N_PERM",
    "DEFAULT_N_BOOT",
    "RANDOM_STATE",
    "MIN_PER_CLASS",
]


DEFAULT_WINDOW_MINUTES: int = engine.WINDOW_MINUTES      # 50
DEFAULT_N_PERM: int = engine.N_PERMUTATIONS              # 10_000
DEFAULT_N_BOOT: int = 5_000
RANDOM_STATE: int = engine.RANDOM_STATE                  # 42
MIN_PER_CLASS: int = engine.MIN_PER_CLASS               # 3

# Fetch the WHOLE timeline (the engine needs global sorted arrays to match
# the CSV oracle bit-for-bit). The repo default limit is 100_000; BrainSense
# Timeline is ~10-min cadence, so multi-year recordings can approach that —
# pass a limit large enough to never truncate.
_TIMELINE_FETCH_LIMIT: int = 100_000_000
_SNAPSHOT_FETCH_LIMIT: int = 100_000


# ─── Result dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class PeriEventResult:
    """Full cluster-permutation peri-event output for one hemisphere.

    ``offset_bins`` are the bin-center minutes (default ``-50…50`` by 10).
    ``obs_z`` / ``usable_mask`` / ``null_max`` are length-``n_bins`` /
    ``n_perm`` arrays from the cluster test; ``clusters`` is the list of
    ``{start_bin, end_bin, start_idx, end_idx, mass, p}`` dicts. The
    ``*_mean`` / ``*_lo`` / ``*_hi`` arrays are the per-bin, per-class mean
    and percentile-bootstrap CI used by the plot (display only).
    """

    hemisphere: str
    n_craving: int
    n_neutral: int
    n_ts_raw: int
    drop: Dict[str, int]
    max_component_span_min: float

    offset_bins: Tuple[int, ...]
    obs_z: np.ndarray
    usable_mask: np.ndarray
    clusters: Tuple[dict, ...]
    null_max: np.ndarray

    craving_mean: np.ndarray
    craving_lo: np.ndarray
    craving_hi: np.ndarray
    neutral_mean: np.ndarray
    neutral_lo: np.ndarray
    neutral_hi: np.ndarray

    n_perm: int
    window_minutes: int

    @property
    def n_clusters(self) -> int:
        return len(self.clusters)

    @property
    def sig_clusters(self) -> List[dict]:
        return [c for c in self.clusters if c["p"] <= 0.05]


@dataclass(frozen=True)
class InsufficientPeriEvent:
    """Returned when a hemisphere cannot be analysed (empty/overlapping
    groups, single class, < MIN_PER_CLASS per class, or no LFP data)."""

    hemisphere: str
    reason: str
    n_craving: int
    n_neutral: int


HemiResult = Union[PeriEventResult, InsufficientPeriEvent]


# ─── Helpers ─────────────────────────────────────────────────────────────


def _normalize_hemisphere(hemisphere: str) -> str:
    """Accept 'Left'/'Right' (UI casing) → lowercase attribute stem."""
    h = hemisphere.strip().lower()
    if h not in {"left", "right"}:
        raise ValueError(
            f"hemisphere must be 'Left' or 'Right', got {hemisphere!r}"
        )
    return h


def _label_hemisphere(hemisphere: str) -> str:
    return "Left" if hemisphere.strip().lower() == "left" else "Right"


# ─── Service ─────────────────────────────────────────────────────────────


class TimelinePeriEventService:
    """Cluster-permutation peri-event analysis for the Timeline → Peri-Event
    page. Group 1 → label 0 (non-craving, Jade); Group 2 → label 1 (craving,
    Rose). Any event_name is allowed in either group as long as the two
    lists are non-empty and disjoint."""

    def __init__(self, snapshot_repository, timeline_repository):
        self._snapshot_repo = snapshot_repository
        self._timeline_repo = timeline_repository

    # ---- Public API ------------------------------------------------------

    def analyze_hemisphere(
        self,
        patient_id: str,
        hemisphere: str,
        group1_event_names,
        group2_event_names,
        *,
        n_perm: int = DEFAULT_N_PERM,
        n_boot: int = DEFAULT_N_BOOT,
        seed: int = RANDOM_STATE,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> HemiResult:
        hemi_label = _label_hemisphere(hemisphere)
        hemi_lower = _normalize_hemisphere(hemisphere)

        err = self._validate_user_groups(group1_event_names, group2_event_names)
        if err is not None:
            return InsufficientPeriEvent(hemi_label, err, 0, 0)

        # Data load — a missing patient DB / hemisphere surfaces as
        # InsufficientPeriEvent rather than an exception.
        try:
            snapshots = self._load_snapshots(patient_id)
            timeline_ts, timeline_val = self._load_timeline(patient_id, hemi_lower)
        except _database_error_types():
            return InsufficientPeriEvent(
                hemi_label, "no data for this patient", 0, 0,
            )

        if self._progress(progress_callback, 0, 1, "Extracting events"):
            pass

        if timeline_val.size == 0 or not np.any(np.isfinite(timeline_val)):
            return InsufficientPeriEvent(
                hemi_label, "no LFP data on this hemisphere", 0, 0,
            )

        offset_bins = engine.offset_bins_for_window(window_minutes)

        # The service never crashes on bad data; it returns
        # InsufficientPeriEvent. Suppress all-NaN nanmean RuntimeWarnings.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)

            lfps, y, drop, n_ts_raw, max_span = engine.get_data(
                snapshots, timeline_ts, timeline_val, hemi_lower,
                group1_event_names, group2_event_names,
                window_minutes=window_minutes, offset_bins=offset_bins,
            )
            n_c = int(np.sum(y == 1))
            n_n = int(np.sum(y == 0))

            if n_c < MIN_PER_CLASS or n_n < MIN_PER_CLASS:
                return InsufficientPeriEvent(
                    hemi_label,
                    f"need ≥{MIN_PER_CLASS} events per class "
                    f"(have {n_n} non-craving, {n_c} craving)",
                    n_c, n_n,
                )

            self._progress(progress_callback, 1, 1, "Extracting events")

            self._progress(progress_callback, 0, 1, "Bootstrapping CIs")
            stats = engine.per_bin_mean_ci(lfps, y, n_boot=n_boot, seed=seed)
            self._progress(progress_callback, 1, 1, "Bootstrapping CIs")

            perm_cb = None
            if progress_callback is not None:
                perm_cb = (
                    lambda done, total: progress_callback(done, total, "Permuting")
                )
            perm = engine.cluster_perm_test(
                lfps, y, n_perm=n_perm, seed=seed, offset_bins=offset_bins,
                progress_callback=perm_cb, cancel_check=cancel_check,
            )

        return PeriEventResult(
            hemisphere=hemi_label,
            n_craving=n_c,
            n_neutral=n_n,
            n_ts_raw=int(n_ts_raw),
            drop=dict(drop),
            max_component_span_min=float(max_span),
            offset_bins=tuple(int(b) for b in offset_bins),
            obs_z=perm["obs_z"],
            usable_mask=perm["usable_mask"],
            clusters=tuple(perm["clusters"]),
            null_max=perm["null_max"],
            craving_mean=stats["craving_mean"],
            craving_lo=stats["craving_lo"],
            craving_hi=stats["craving_hi"],
            neutral_mean=stats["neutral_mean"],
            neutral_lo=stats["neutral_lo"],
            neutral_hi=stats["neutral_hi"],
            n_perm=int(n_perm),
            window_minutes=int(window_minutes),
        )

    def analyze_both_hemispheres(
        self,
        patient_id: str,
        group1_event_names,
        group2_event_names,
        *,
        n_perm: int = DEFAULT_N_PERM,
        n_boot: int = DEFAULT_N_BOOT,
        seed: int = RANDOM_STATE,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """Run Left then Right sequentially. The worker composes
        stage-weighted progress; this method forwards the callback as-is."""
        results: dict = {}
        for hemi in ("Left", "Right"):
            results[hemi] = self.analyze_hemisphere(
                patient_id, hemi, group1_event_names, group2_event_names,
                n_perm=n_perm, n_boot=n_boot, seed=seed,
                window_minutes=window_minutes,
                progress_callback=progress_callback, cancel_check=cancel_check,
            )
        return results

    # ---- Data loading ----------------------------------------------------

    def _load_snapshots(self, patient_id: str) -> List[Tuple[object, str]]:
        """Return ``[(timestamp, event_name)]`` deduplicated by
        ``(timestamp, event_name)`` so multi-hemisphere snapshot rows
        collapse to one event per pair (matching the CSV oracle)."""
        records = self._snapshot_repo.get_by_time_range(
            patient_id=patient_id,
            patient_events_only=True,
            limit=_SNAPSHOT_FETCH_LIMIT,
        )
        seen = set()
        out: List[Tuple[object, str]] = []
        for s in records:
            name = getattr(s, "event_name", None)
            ts = getattr(s, "timestamp", None)
            if not name or ts is None:
                continue
            key = (ts, name)
            if key in seen:
                continue
            seen.add(key)
            out.append((ts, name))
        return out

    def _load_timeline(
        self, patient_id: str, hemi_lower: str,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``(unix_ts, value)`` arrays for non-outlier timeline rows,
        sorted by timestamp. ``value`` is the requested hemisphere's
        amplitude with ``None`` → NaN (matching the CSV column semantics)."""
        records = self._timeline_repo.get_by_time_range(
            patient_id=patient_id, limit=_TIMELINE_FETCH_LIMIT,
        )
        attr = f"{hemi_lower}_hemisphere"
        ts_list: List[float] = []
        val_list: List[float] = []
        for r in records:
            if getattr(r, "is_outlier", 0):
                continue
            ts = getattr(r, "timestamp", None)
            if ts is None:
                continue
            v = getattr(r, attr, None)
            ts_list.append(ts.timestamp())
            val_list.append(float(v) if v is not None else np.nan)
        if not ts_list:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)
        ts_arr = np.asarray(ts_list, dtype=np.float64)
        val_arr = np.asarray(val_list, dtype=np.float64)
        order = np.argsort(ts_arr, kind="mergesort")  # stable, matches CSV sort
        return ts_arr[order], val_arr[order]

    # ---- Internals -------------------------------------------------------

    @staticmethod
    def _progress(cb, done: int, total: int, label: str) -> bool:
        if cb is not None:
            cb(done, total, label)
        return cb is not None

    @staticmethod
    def _validate_user_groups(group1, group2) -> Optional[str]:
        """Return ``None`` when the selection is well-posed; otherwise an
        :class:`InsufficientPeriEvent.reason` string. Group membership
        decides class — the publication keyword matcher is NOT consulted on
        the in-app path."""
        g1 = list(group1 or [])
        g2 = list(group2 or [])
        if not g1 or not g2:
            return "both event groups must contain at least one event type"
        overlap = sorted(set(g1) & set(g2))
        if overlap:
            return f"event types must not appear in both groups: {overlap}"
        return None


def _database_error_types():
    """Exception types meaning the patient/hemisphere has no recordings.
    Imported lazily so the service has no import-time dependency on
    :mod:`src.infrastructure`."""
    try:
        from src.infrastructure.repositories.base_repository import DatabaseError
        return (DatabaseError,)
    except Exception:  # pragma: no cover
        return ()
