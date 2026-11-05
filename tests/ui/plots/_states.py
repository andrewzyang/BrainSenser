"""Synthetic states of the four plot widgets (no patient data).

:func:`show` puts a widget in one of :data:`STATES` — both hemispheres with
results, ``mixed`` (left result, right insufficient or not implanted) or the
pre-analysis skeleton — with the event-type counts, groups and result shapes of
:mod:`tests.ui._synthetic`. Group labels name 2 or 5 event types per group,
" + "-joined: the longest labels a group can carry. Widget modules are imported
only when a widget is made, so a child process can change the installed fonts
first.
"""

from types import SimpleNamespace

import numpy as np

from tests.ui._synthetic import EVENT_COUNTS, GROUP_1, GROUP_2

KINDS = ("psd", "auc", "violin", "peri")
STATES = ("result", "mixed", "skeleton")
N_GROUP_1 = sum(EVENT_COUNTS[name] for name in GROUP_1)
N_GROUP_2 = sum(EVENT_COUNTS[name] for name in GROUP_2)
# GROUP_2 names 3 event types; two more make the longest second label.
_LONGEST_GROUP_2 = GROUP_2 + ["Urge", "Relapse"]


def group_labels(event_types: int) -> tuple:
    """The violin's two group labels when each group has ``event_types`` (2–5) types."""
    return (" + ".join(GROUP_1[:event_types]), " + ".join(_LONGEST_GROUP_2[:event_types]))


def make(kind: str):
    """A new plot widget of ``kind`` (one of :data:`KINDS`)."""
    if kind == "psd":
        from src.ui.views.snapshots_psd.components.dual_hemisphere_psd_widget import (
            DualHemispherePsdWidget,
        )
        return DualHemispherePsdWidget()
    if kind == "auc":
        from src.ui.views.snapshots_5hz_band.components.dual_hemisphere_auc_widget import (
            DualHemisphereAucWidget,
        )
        return DualHemisphereAucWidget()
    if kind == "violin":
        from src.ui.views.timeline_lfp_threshold.components.dual_hemisphere_violin_widget import (
            DualHemisphereViolinWidget,
        )
        return DualHemisphereViolinWidget()
    from src.ui.views.timeline_peri_event.components.peri_event_plot import PeriEventPlot
    return PeriEventPlot()


def show(kind: str, widget, state: str = "result", event_types: int = 2) -> None:
    """Put ``widget`` (a ``make(kind)``) in ``state``."""
    if kind == "violin":
        widget.set_group_labels(*group_labels(event_types))
    if state == "skeleton":
        return
    rng = np.random.default_rng(7)
    {"psd": _psd, "auc": _auc, "violin": _violin, "peri": _peri}[kind](widget, rng, state)


def _psd(widget, rng, state):
    freqs = np.arange(0, 97, 0.9765625)

    def curve(k, peak, n):
        base = (2.0 / (1 + freqs) ** 1.1 + peak * np.exp(-0.5 * ((freqs - 6.0) / 1.5) ** 2)
                + 0.02 * np.exp(-0.5 * ((freqs - 20) / 4) ** 2))
        return (base * k, base * k * 0.82, base * k * 1.22, n)

    missing = (None, None, None, 0)
    right = ((curve(1.08, 0.5, N_GROUP_2), curve(1.0, 0.4, N_GROUP_1)) if state == "result"
             else (missing, missing))
    widget.update_psd_data(freqs, curve(1.15, 0.6, N_GROUP_2), curve(1.0, 0.35, N_GROUP_1),
                           *right)
    bands = ("Delta", "Theta", "Alpha", "Beta", "Gamma_low")
    left_sig = dict(zip(bands, (False, True, False, True, True)))
    right_sig = dict(zip(bands, (True, True, False, False, False))) if state == "result" else {}
    widget.update_band_statistics(
        {band: SimpleNamespace(is_significant=sig) for band, sig in left_sig.items()},
        {band: SimpleNamespace(is_significant=sig) for band, sig in right_sig.items()})


def _auc(widget, rng, state):
    from src.core.services.snapshot_ml_analysis_service import AucProfileResult

    centers = 5.31 + 2.44 + np.arange(11) * 2.93

    def result(hemisphere, modal):
        auc = (0.5 + 0.18 * np.exp(-0.5 * ((centers - 9) / 4) ** 2)
               + rng.normal(0, 0.02, centers.size))
        return AucProfileResult(
            hemisphere=hemisphere, band_centers_hz=centers,
            band_edges_hz=np.c_[centers - 2.44, centers + 2.44], per_band_auc=auc,
            per_band_ci_lo=auc - 0.08, per_band_ci_hi=auc + 0.08, modal_band_idx=modal,
            pipeline_loo_auc=0.712, pipeline_loo_ci_lo=0.611, pipeline_loo_ci_hi=0.803,
            fwer_p=0.0021, n_craving=N_GROUP_2, n_non_craving=N_GROUP_1, n_perm=10000,
            n_boot=2000)

    widget.set_results(result("L", 1), result("R", 2) if state == "result" else None)


def _violin(widget, rng, state):
    from src.core.services.timeline_threshold_ml_service import (
        InsufficientResult,
        ThresholdMlResult,
    )

    def result(hemisphere):
        n1, n2 = N_GROUP_1, N_GROUP_2
        return ThresholdMlResult(
            hemisphere=hemisphere, n_craving=n2, n_neutral=n1, n_valid=n1 + n2, n_dropped=3,
            bin_coverage_mean=0.97, X=np.r_[rng.normal(900, 150, n1), rng.normal(1050, 180, n2)],
            y=np.r_[np.zeros(n1, int), np.ones(n2, int)], lr_threshold=985.0,
            lr_threshold_ci=(940.0, 1030.0), lr_coef_sign=1, direction="higher",
            auc_loo=0.684, auc_ci=(0.601, 0.763), oof_prob=rng.uniform(0, 1, n1 + n2),
            sensitivity_yj=0.62, specificity_yj=0.66, sensitivity_lr=0.6, specificity_lr=0.68,
            mann_whitney_p=0.0003, perm_p=1 / 1001, perm_p_floor=1 / 1001,
            null_aucs=rng.normal(0.5, 0.04, 200), fold_thr_median=985.0,
            fold_thr_iqr=(975.0, 995.0), fold_sign_stability=1.0, verdict=True)

    right = (result("Right") if state == "result" else InsufficientResult(
        "Right", "no overlapping recordings or n < 3/class", 2, 14))
    widget.update_results({"Left": result("Left"), "Right": right})


def _peri(widget, rng, state):
    from src.core.services.timeline_peri_event_service import (
        InsufficientPeriEvent,
        PeriEventResult,
    )

    bins = tuple(range(-50, 51, 10))
    minutes = np.asarray(bins, float)

    def result(hemisphere, p):
        craving = 1000 + 120 * np.exp(-0.5 * (minutes / 15) ** 2) + rng.normal(0, 10, len(bins))
        neutral = 980 + rng.normal(0, 10, len(bins))
        return PeriEventResult(
            hemisphere=hemisphere, n_craving=N_GROUP_2, n_neutral=N_GROUP_1, n_ts_raw=48000,
            drop={}, max_component_span_min=100.0, offset_bins=bins,
            obs_z=rng.normal(0, 1.5, len(bins)), usable_mask=np.ones(len(bins), bool),
            clusters=({"start_bin": -10, "end_bin": 10, "start_idx": 4, "end_idx": 6,
                       "mass": 8.42, "p": p},
                      {"start_bin": 40, "end_bin": 40, "start_idx": 9, "end_idx": 9,
                       "mass": 2.1, "p": 0.41}),
            null_max=rng.gamma(2, 2, 1000), craving_mean=craving, craving_lo=craving - 40,
            craving_hi=craving + 40, neutral_mean=neutral, neutral_lo=neutral - 30,
            neutral_hi=neutral + 30, n_perm=10000, window_minutes=50)

    right = (result("Right", 0.0007) if state == "result" else InsufficientPeriEvent(
        "Right", "need ≥3 events per class (have 2 non-craving, 41 craving)", 41, 2))
    widget.update_results({"Left": result("Left", 0.0123), "Right": right})
