"""
Pure constants and helpers for the LFP-threshold analysis pipeline.

Extracted from `lfp_threshold_publication.py` so that consumers (notably
`bulletproof_threshold.py` and the in-app service) can import these names
without dragging matplotlib into `sys.modules`.

This module has zero non-stdlib, non-numpy/scipy imports. Do not add any.
"""

import numpy as np
from scipy.stats import beta as beta_dist, mannwhitneyu

__all__ = [
    "CRAVING_KEYWORDS",
    "NEUTRAL_KEYWORDS",
    "MIN_EVENTS_PER_CLASS",
    "MIN_INTER_EVENT_MINUTES",
    "BIN_TOLERANCE",
    "classify_event",
    "compute_classic_stats",
    "clopper_pearson_ci",
]


# ─── Public constants ────────────────────────────────────────────────────────

CRAVING_KEYWORDS = ["Craving", "Drinking"]
NEUTRAL_KEYWORDS = ["Happy", "Neutral"]
MIN_EVENTS_PER_CLASS = 10
MIN_INTER_EVENT_MINUTES = 60
BIN_TOLERANCE = 5


# ─── Private constants (used by compute_classic_stats) ───────────────────────

_RANDOM_STATE = 42
_N_BOOTSTRAP = 2000


# ─── Event classification ────────────────────────────────────────────────────

def classify_event(event_name):
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def clopper_pearson_ci(k, n, alpha=0.05):
    if n == 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else float(beta_dist.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta_dist.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


# ─── Classic statistics ──────────────────────────────────────────────────────

def compute_classic_stats(X, y, seed=_RANDOM_STATE, n_boot=_N_BOOTSTRAP):
    """Cohen's d with stratified bootstrap CI, Mann-Whitney U, descriptives.

    ``seed`` and ``n_boot`` parameterise the Cohen's d bootstrap CI so the
    caller can honour the same bootstrap-count / seed selectors it passes to
    the AUC and threshold CIs. Defaults reproduce the published Figure 3 d-f
    values and match code_release/scripts/4_timeline_amplitude_threshold_
    classifier.py (seed 42, 2000 resamples) bit-for-bit.
    """
    craving, neutral = X[y == 1], X[y == 0]
    n1, n2 = len(craving), len(neutral)

    pooled_sd = np.sqrt(
        ((n1 - 1) * np.var(craving, ddof=1)
         + (n2 - 1) * np.var(neutral, ddof=1))
        / (n1 + n2 - 2)
    )
    d = float((np.mean(craving) - np.mean(neutral)) / pooled_sd) if pooled_sd > 0 else 0.0

    # Stratified bootstrap CI on d
    rng = np.random.RandomState(seed)
    boot_d = []
    for _ in range(n_boot):
        c = craving[rng.choice(n1, size=n1, replace=True)]
        n = neutral[rng.choice(n2, size=n2, replace=True)]
        sd = np.sqrt(
            ((n1 - 1) * np.var(c, ddof=1)
             + (n2 - 1) * np.var(n, ddof=1))
            / (n1 + n2 - 2)
        )
        boot_d.append(float((np.mean(c) - np.mean(n)) / sd) if sd > 0 else 0.0)
    d_ci = (float(np.percentile(boot_d, 2.5)), float(np.percentile(boot_d, 97.5)))

    U, p_mw = mannwhitneyu(craving, neutral, alternative="two-sided")
    rank_biserial = 2 * float(U) / (n1 * n2) - 1

    return {
        "cohens_d": d, "cohens_d_ci": d_ci,
        "mann_whitney_u": float(U), "mann_whitney_p": float(p_mw),
        "rank_biserial": rank_biserial,
        "craving_mean": float(np.mean(craving)),
        "craving_std": float(np.std(craving, ddof=1)),
        "craving_median": float(np.median(craving)),
        "neutral_mean": float(np.mean(neutral)),
        "neutral_std": float(np.std(neutral, ddof=1)),
        "neutral_median": float(np.median(neutral)),
        "n_craving": n1, "n_neutral": n2,
    }
