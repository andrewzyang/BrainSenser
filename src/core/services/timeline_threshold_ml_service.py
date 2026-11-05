"""
Timeline → LFP Threshold service.

Pure analysis service that wraps `run_hemisphere` from `timeline_mean20_core`.
Validates the user's group selection (Group 1 → label 0, Group 2 → label 1)
and returns either a `ThresholdMlResult` (full pipeline output) or an
`InsufficientResult` (guard tripped) per hemisphere. Labels are decided by
group membership, NOT by the publication's `classify_event` keyword matcher
— matching the convention of the Snapshots 5 Hz Band / PSD pages.

Headless and Qt-free **and** matplotlib-free — `pytest -q` can run service
tests without a `QApplication`.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable, Optional, Union

import numpy as np

# `timeline_mean20_core` and `bulletproof_threshold` are vendored under
# `src/core/analysis/threshold/` (Qt-free, matplotlib-free) so the service
# module is self-contained and PyInstaller can follow the import graph.
from src.core.analysis.threshold._threshold_constants import (
    MIN_EVENTS_PER_CLASS,
)
from src.core.analysis.threshold.timeline_mean20_core import (
    WINDOW_MINUTES_EXT,
    run_hemisphere,
)

__all__ = [
    "ThresholdMlResult",
    "InsufficientResult",
    "HemiResult",
    "TimelineThresholdMlService",
    "DEFAULT_WINDOW_MINUTES",
    "RANDOM_STATE",
]


RANDOM_STATE: int = 42
DEFAULT_WINDOW_MINUTES: int = WINDOW_MINUTES_EXT


# ─── Result dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ThresholdMlResult:
    hemisphere: str
    n_craving: int
    n_neutral: int
    n_valid: int
    n_dropped: int
    bin_coverage_mean: float

    # Distributions (used by the violin/box plot)
    X: np.ndarray
    y: np.ndarray

    # Classifier
    lr_threshold: float
    lr_threshold_ci: tuple
    lr_coef_sign: int
    direction: str

    # LOO-CV performance
    auc_loo: float
    auc_ci: tuple
    oof_prob: np.ndarray
    sensitivity_yj: float
    specificity_yj: float
    sensitivity_lr: float
    specificity_lr: float

    # Inference
    mann_whitney_p: float
    perm_p: float
    perm_p_floor: float
    null_aucs: np.ndarray

    # Diagnostics
    fold_thr_median: float
    fold_thr_iqr: tuple
    fold_sign_stability: float
    verdict: bool

    # Reference-script #4 parity: operating-point and effect-size CIs.
    # sens_ci/spec_ci are the stratified-bootstrap CIs for the LR sens/spec at
    # oof_prob >= 0.5 (seed 20260423); r_rb/r_rb_ci are the rank-biserial point
    # + BCa CI (seed 2025). Defaults are NaN sentinels for backward compat.
    sens_ci: tuple = (float("nan"), float("nan"))
    spec_ci: tuple = (float("nan"), float("nan"))
    r_rb: float = float("nan")
    r_rb_ci: tuple = (float("nan"), float("nan"))


@dataclass(frozen=True)
class InsufficientResult:
    hemisphere: str
    reason: str
    n_craving: int
    n_neutral: int


HemiResult = Union[ThresholdMlResult, InsufficientResult]


# ─── Helpers ─────────────────────────────────────────────────────────────


def _to_threshold_ml_result(d: dict, hemisphere: str) -> ThresholdMlResult:
    """Map a `run_hemisphere` return dict into a `ThresholdMlResult`."""
    auc_ci = (float(d["auc_ci"][0]), float(d["auc_ci"][1]))
    perm_p = float(d["perm_p"])
    return ThresholdMlResult(
        hemisphere=hemisphere,
        n_craving=int(d["n_craving"]),
        n_neutral=int(d["n_neutral"]),
        n_valid=int(d["n_valid"]),
        n_dropped=int(d["n_dropped"]),
        bin_coverage_mean=float(d["bin_coverage_mean"]),
        X=d["X"],
        y=d["y"],
        lr_threshold=float(d["lr_threshold"]),
        lr_threshold_ci=(
            float(d["lr_threshold_ci"][0]),
            float(d["lr_threshold_ci"][1]),
        ),
        lr_coef_sign=int(d["lr_coef_sign"]),
        direction=str(d["direction"]),
        auc_loo=float(d["auc_loo"]),
        auc_ci=auc_ci,
        oof_prob=d["oof_prob"],
        sensitivity_yj=float(d["sensitivity_yj"]),
        specificity_yj=float(d["specificity_yj"]),
        sensitivity_lr=float(d["sensitivity_lr"]),
        specificity_lr=float(d["specificity_lr"]),
        mann_whitney_p=float(d["mann_whitney_p"]),
        perm_p=perm_p,
        perm_p_floor=float(d["perm_p_floor"]),
        null_aucs=d["null_aucs"],
        fold_thr_median=float(d["fold_thr_median"]),
        fold_thr_iqr=(
            float(d["fold_thr_iqr"][0]),
            float(d["fold_thr_iqr"][1]),
        ),
        fold_sign_stability=float(d["fold_sign_stability"]),
        verdict=bool(auc_ci[0] > 0.5 and perm_p < 0.05),
        sens_ci=(float(d["sens_ci"][0]), float(d["sens_ci"][1])),
        spec_ci=(float(d["spec_ci"][0]), float(d["spec_ci"][1])),
        r_rb=float(d["r_rb"]),
        r_rb_ci=(float(d["r_rb_ci_lo"]), float(d["r_rb_ci_hi"])),
    )


def _normalize_hemisphere(hemisphere: str) -> str:
    """Accept 'Left'/'Right' (UI casing) and return the lowercase form
    consumed by `extract_offset_matrix_ext` (`{hemisphere}_hemisphere` attr)."""
    h = hemisphere.strip().lower()
    if h not in {"left", "right"}:
        raise ValueError(f"hemisphere must be 'Left' or 'Right', got {hemisphere!r}")
    return h


def _label_hemisphere(hemisphere: str) -> str:
    """Return the canonical UI label for the hemisphere."""
    return "Left" if hemisphere.strip().lower() == "left" else "Right"


# ─── Service ─────────────────────────────────────────────────────────────


class TimelineThresholdMlService:
    """Threshold-classifier analysis for the Timeline → LFP Threshold page.

    Defers extraction and modeling to `timeline_mean20_core.run_hemisphere`.
    Group 1 (Jade) → label 0, Group 2 (Rose) → label 1; any event_name is
    allowed in either group, as long as the two lists are non-empty and
    disjoint. Returns dataclasses the View can render directly.

    Note: when both `group1_event_names` and `group2_event_names` are
    forwarded as None to the core, it falls back to the publication's
    `classify_event` keyword matcher (manuscript-script byte equivalence).
    The service always passes lists, so the in-app path is always
    position-driven.
    """

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
        n_perm: int = 1_000,
        n_boot: int = 2_000,
        n_jobs: int = 1,
        seed: int = RANDOM_STATE,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> HemiResult:
        # `n_boot`, `seed`, and `window_minutes` are forwarded to the core
        # pipeline; defaults (2000, RANDOM_STATE=42, ±20 min) reproduce the
        # published Figure 3 d-f numbers bit-exactly. Non-default values
        # produce different but still-valid analyses (the user-facing
        # selectors let the operator trade precision for speed and
        # explore alternative pre/post windows).
        hemi_label = _label_hemisphere(hemisphere)
        hemi_lower = _normalize_hemisphere(hemisphere)

        # Position-driven labels: Group 1 → 0 (non-craving, Jade),
        # Group 2 → 1 (craving, Rose). The publication's classify_event
        # keyword matcher is NOT consulted on the in-app path — any
        # event_name is allowed in either group, as long as the two lists
        # are non-empty and disjoint.
        err = self._validate_user_groups(
            group1_event_names, group2_event_names,
        )
        if err is not None:
            return InsufficientResult(
                hemisphere=hemi_label,
                reason=err,
                n_craving=0,
                n_neutral=0,
            )

        # The service NEVER crashes on bad data; it returns InsufficientResult.
        # Suppress all-NaN nanmean / nanmedian RuntimeWarnings so the worker
        # thread does not spam stderr.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            try:
                result_dict = run_hemisphere(
                    patient_id,
                    self._snapshot_repo,
                    self._timeline_repo,
                    hemi_lower,
                    n_perm,
                    n_jobs,
                    n_boot=n_boot,
                    seed=seed,
                    group1_event_names=list(group1_event_names or []),
                    group2_event_names=list(group2_event_names or []),
                    window_minutes=int(window_minutes),
                    progress_callback=progress_callback,
                    cancel_check=cancel_check,
                )
            except _hemisphere_missing_exceptions() as exc:  # noqa: F841
                return InsufficientResult(
                    hemisphere=hemi_label,
                    reason="no implant on this hemisphere",
                    n_craving=0,
                    n_neutral=0,
                )

        if result_dict is None:
            # `run_hemisphere` returns None on either no overlapping
            # recordings or n_class < MIN_EVENTS_PER_CLASS. The two cases
            # are best disambiguated by re-counting the labels via the
            # extractor, but that doubles the work. The view treats either
            # case identically; report the umbrella reason.
            return InsufficientResult(
                hemisphere=hemi_label,
                reason="no overlapping recordings or n < %d/class"
                % MIN_EVENTS_PER_CLASS,
                n_craving=0,
                n_neutral=0,
            )

        y_v = result_dict["y"]
        n_c = int(np.sum(y_v == 1))
        n_n = int(np.sum(y_v == 0))

        if len(np.unique(y_v)) < 2:
            return InsufficientResult(
                hemisphere=hemi_label,
                reason="single-class y",
                n_craving=n_c,
                n_neutral=n_n,
            )
        if n_c < MIN_EVENTS_PER_CLASS:
            return InsufficientResult(
                hemisphere=hemi_label,
                reason=f"n_craving < {MIN_EVENTS_PER_CLASS}",
                n_craving=n_c,
                n_neutral=n_n,
            )
        if n_n < MIN_EVENTS_PER_CLASS:
            return InsufficientResult(
                hemisphere=hemi_label,
                reason=f"n_neutral < {MIN_EVENTS_PER_CLASS}",
                n_craving=n_c,
                n_neutral=n_n,
            )

        return _to_threshold_ml_result(result_dict, hemi_label)

    def analyze_both_hemispheres(
        self,
        patient_id: str,
        group1_event_names,
        group2_event_names,
        *,
        n_perm: int = 1_000,
        n_boot: int = 2_000,
        n_jobs: int = 1,
        seed: int = RANDOM_STATE,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict:
        """Run Left then Right sequentially. Stage-weighted progress is
        composed by the worker (Phase 4); this method just forwards the
        callback as-is to each hemisphere call."""
        results: dict = {}
        for hemi in ("Left", "Right"):
            results[hemi] = self.analyze_hemisphere(
                patient_id,
                hemi,
                group1_event_names,
                group2_event_names,
                n_perm=n_perm,
                n_boot=n_boot,
                n_jobs=n_jobs,
                seed=seed,
                window_minutes=window_minutes,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
        return results

    # ---- Internals -------------------------------------------------------

    @staticmethod
    def _validate_user_groups(group1, group2) -> Optional[str]:
        """Validate the user's group selection.

        Returns ``None`` when the selection is well-posed for the
        position-driven Timeline LFP Threshold pipeline (Group 1 → label 0,
        Group 2 → label 1). Returns an :class:`InsufficientResult.reason`
        string otherwise.

        The publication's ``classify_event`` keyword matcher is NOT
        consulted on the in-app path — any event_name is allowed in
        either group. This matches the convention adopted by the
        Snapshots 5 Hz Band and Snapshots PSD pages after the group-role
        inversion fix.
        """
        g1 = list(group1 or [])
        g2 = list(group2 or [])
        if not g1 or not g2:
            return "both event groups must contain at least one event type"
        overlap = sorted(set(g1) & set(g2))
        if overlap:
            return f"event types must not appear in both groups: {overlap}"
        return None


def _hemisphere_missing_exceptions():
    """Exception types that mean the patient has no recordings on the
    requested hemisphere. Pulled from the repository module lazily so
    the service does not import `src.infrastructure` at module level."""
    try:
        from src.infrastructure.repositories.base_repository import (
            DatabaseError,
        )
        return (DatabaseError,)
    except Exception:  # pragma: no cover
        return ()
