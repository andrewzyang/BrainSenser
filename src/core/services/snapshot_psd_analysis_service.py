"""
Snapshot PSD Analysis Service.

This service performs statistical analysis on snapshot PSD data, including:
- Band power integration
- Mann-Whitney U tests for group comparisons
- Multiple comparison correction (Benjamini-Hochberg)
- Bootstrap confidence intervals
- Effect size calculations

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import logging
from typing import Callable, Dict, List, Tuple, Optional
from dataclasses import dataclass, replace
import numpy as np
from scipy import stats, integrate
from scipy.stats import bootstrap
import warnings

from src.domain.psd_models import (
    SnapshotPsdDataset,
    FrequencyBandDefinitions,
    FrequencyBand
)
from src.domain.models import EffectSizeResult, EffectSizeType
from src.core.services.effect_size_calculator import EffectSizeCalculator
from src.domain.effect_size_preference import EffectSizePreference

logger = logging.getLogger(__name__)

# Constants
BOOTSTRAP_ITERATIONS = 5000
BOOTSTRAP_SEED = 2025
FDR_ALPHA = 0.05
# Alpha for the displayed effect-size BCa confidence intervals (95% CI). Kept
# distinct from FDR_ALPHA: both happen to be 0.05 but are conceptually separate.
BOOTSTRAP_ALPHA = 0.05
# Canonical frequency bands included in snapshot comparisons
SNAPSHOT_ANALYSIS_BANDS = (
    "Delta",
    "Theta",
    "Alpha",
    "Beta",
    "Gamma_low",
)


class OperationCancelledException(Exception):
    """Raised inside the service when ``cancel_check()`` returns True at a
    checkpoint. Workers catch this and emit a ``cancelled`` signal instead of
    ``finished`` / ``error``. Self-contained — duplicated rather than shared
    with the ML service so each service has zero cross-imports."""


@dataclass(frozen=True)
class BandPowerResult:
    """Result of band power integration for a single event."""
    band_name: str
    power: float
    hemisphere: str
    event_name: str
    is_censored: bool  # True if any bins were NaN


@dataclass(frozen=True)
class BandComparisonResult:
    """
    Statistical comparison result for a frequency band.

    Attributes
    ----------
    band_name : str
        Frequency band name
    canonical_band : str
        Canonical band identifier (e.g., "Theta", "Timeline")
    min_freq : float
        Lower frequency bound (Hz)
    max_freq : float
        Upper frequency bound (Hz)
    hemisphere : str
        Hemisphere analyzed
    group1_name : str
        Name of first group (e.g., "Craving")
    group2_name : str
        Name of second group (e.g., "Non-Craving")
    n_group1 : int
        Number of events in group 1
    n_group2 : int
        Number of events in group 2
    median_group1 : float
        Median power for group 1
    median_group2 : float
        Median power for group 2
    mad_group1 : float
        Median absolute deviation for group 1
    mad_group2 : float
        Median absolute deviation for group 2
    u_statistic : float
        Mann-Whitney U statistic
    p_value : float
        Raw p-value
    q_value : float
        FDR-corrected p-value
    rosenthal_r : float
        Rosenthal's r effect size (DEPRECATED: use effect_size_result instead)
    rank_biserial_r : float
        Rank-biserial correlation (DEPRECATED: use effect_size_result instead)
    ci_lower : float
        Lower bound of 95% CI for effect size (DEPRECATED: use effect_size_result instead)
    ci_upper : float
        Upper bound of 95% CI for effect size (DEPRECATED: use effect_size_result instead)
    central_tendency_label : str
        Label for central tendency metric represented (e.g., "Median")
    central_tendency_difference : float
        Difference in central tendency between groups (group1 - group2)
    central_tendency_ci_lower : float
        Lower bound of 95% CI for the central tendency difference
    central_tendency_ci_upper : float
        Upper bound of 95% CI for the central tendency difference
    is_significant : bool
        Whether result is significant after FDR correction
    effect_size_result : Optional[EffectSizeResult]
        Complete effect size result with type, value, CI, and interpretation
    """
    band_name: str
    canonical_band: str
    min_freq: float
    max_freq: float
    hemisphere: str
    group1_name: str
    group2_name: str
    n_group1: int
    n_group2: int
    median_group1: float
    median_group2: float
    mad_group1: float
    mad_group2: float
    u_statistic: float
    p_value: float
    q_value: float
    rosenthal_r: float
    rank_biserial_r: float
    ci_lower: float
    ci_upper: float
    central_tendency_label: str
    central_tendency_difference: float
    central_tendency_ci_lower: float
    central_tendency_ci_upper: float
    is_significant: bool
    effect_size_result: Optional[EffectSizeResult] = None


# ============================================================================
# Canonical effect-size helpers
# ----------------------------------------------------------------------------
# Ported verbatim (semantics) from the deposit script
# ``code_release/scripts/1_snapshot_stats_canonical.py`` so the Snapshots
# Classic page reproduces Supplementary Table 2. Two conventions matter:
#   * Craving is always the FIRST sample, so rank-biserial r and Cohen's d are
#     craving-referenced (positive = craving higher).
#   * Each bootstrap call builds a FRESH ``np.random.default_rng(seed)``, so the
#     displayed CIs are reproducible and independent of any shared service RNG
#     stream (this also removes the prior shared-stream coupling for the CI).
# These are deliberately NOT routed through the shared ``EffectSizeCalculator``
# (which other pages use with a parametric CI); they live here, page-local.
# ============================================================================


def _effect_sizes(craving: np.ndarray, non_craving: np.ndarray) -> Tuple[float, float, float]:
    """Craving-first Mann-Whitney U, two-sided p, and rank-biserial r.

    ``r_rb = 2U / (n1 * n2) - 1`` with craving as the first sample, so the sign
    is craving-referenced. Mirrors ``_effect_sizes`` in the canonical script.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        u, p = stats.mannwhitneyu(craving, non_craving, alternative="two-sided")
    n1, n2 = len(craving), len(non_craving)
    r_rb = (2 * u) / (n1 * n2) - 1
    return float(u), float(p), float(r_rb)


def _cohens_d(craving: np.ndarray, non_craving: np.ndarray) -> float:
    """Pooled-SD Cohen's d (ddof=1), sign = mean(craving) - mean(non_craving).

    The caller passes ``np.log10(...)`` power for the manuscript's
    canonical-band d. Mirrors ``_cohens_d`` in the canonical script.
    """
    n1, n2 = len(craving), len(non_craving)
    if n1 < 2 or n2 < 2:
        return float("nan")
    s1, s2 = np.var(craving, ddof=1), np.var(non_craving, ddof=1)
    pooled = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / (n1 + n2 - 2))
    if pooled == 0:
        return float("nan")
    return float((np.mean(craving) - np.mean(non_craving)) / pooled)


def _bca_interval(
    theta_hat: float,
    theta_boot: np.ndarray,
    theta_jack: np.ndarray,
    alpha: float = BOOTSTRAP_ALPHA,
) -> Tuple[float, float]:
    """Bias-corrected and accelerated bootstrap interval (Efron 1987).

    z0 from the bootstrap bias proportion (clipped); acceleration from the
    jackknife skew; percentile fallback when the BCa adjustment is undefined.
    Mirrors ``_bca_interval`` in the canonical script.
    """
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


def bca_bootstrap_rrb(
    craving: np.ndarray,
    non_craving: np.ndarray,
    n_boot: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = BOOTSTRAP_ALPHA,
) -> Tuple[float, float, float]:
    """Craving-referenced rank-biserial r with stratified BCa 95% CI.

    Each group is resampled independently and both groups are jackknifed.
    Returns ``(r_hat, ci_lower, ci_upper)``. Mirrors ``bca_bootstrap_rrb`` in
    the canonical script.
    """
    craving = np.asarray(craving, dtype=float)
    non_craving = np.asarray(non_craving, dtype=float)
    n1, n2 = craving.size, non_craving.size
    rng = np.random.default_rng(seed)

    _, _, r_hat = _effect_sizes(craving, non_craving)

    r_boot = np.empty(n_boot)
    for b in range(n_boot):
        i1 = rng.integers(0, n1, size=n1)
        i2 = rng.integers(0, n2, size=n2)
        _, _, r_boot[b] = _effect_sizes(craving[i1], non_craving[i2])

    r_jack = np.empty(n1 + n2)
    for i in range(n1):
        _, _, r_jack[i] = _effect_sizes(np.delete(craving, i), non_craving)
    for j in range(n2):
        _, _, r_jack[n1 + j] = _effect_sizes(craving, np.delete(non_craving, j))

    lo, hi = _bca_interval(r_hat, r_boot, r_jack, alpha)
    return r_hat, lo, hi


def bca_bootstrap_d(
    craving: np.ndarray,
    non_craving: np.ndarray,
    n_boot: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = BOOTSTRAP_ALPHA,
) -> Tuple[float, float, float]:
    """Craving-referenced Cohen's d with stratified BCa 95% CI.

    Operates on the values passed in; the caller log10-transforms before
    invoking, matching the manuscript convention for canonical-band d.
    Non-finite bootstrap / jackknife draws are filtered (degenerate resamples).
    Returns ``(d_hat, ci_lower, ci_upper)``. Mirrors ``bca_bootstrap_d`` in the
    canonical script.
    """
    craving = np.asarray(craving, dtype=float)
    non_craving = np.asarray(non_craving, dtype=float)
    n1, n2 = craving.size, non_craving.size
    rng = np.random.default_rng(seed)

    d_hat = _cohens_d(craving, non_craving)
    d_boot = np.empty(n_boot)
    for b in range(n_boot):
        i1 = rng.integers(0, n1, size=n1)
        i2 = rng.integers(0, n2, size=n2)
        d_boot[b] = _cohens_d(craving[i1], non_craving[i2])
    d_boot = d_boot[np.isfinite(d_boot)]

    d_jack = np.empty(n1 + n2)
    for i in range(n1):
        d_jack[i] = _cohens_d(np.delete(craving, i), non_craving)
    for j in range(n2):
        d_jack[n1 + j] = _cohens_d(craving, np.delete(non_craving, j))
    d_jack = d_jack[np.isfinite(d_jack)]

    lo, hi = _bca_interval(d_hat, d_boot, d_jack, alpha)
    return d_hat, lo, hi


class SnapshotPsdAnalysisService:
    """
    Service for analyzing snapshot PSD data.

    This service provides statistical analysis methods for comparing
    PSD data between different event groups (e.g., Craving vs Non-Craving).
    """

    def __init__(self, effect_size_calculator: Optional[EffectSizeCalculator] = None):
        """
        Initialize the analysis service.

        Parameters
        ----------
        effect_size_calculator : Optional[EffectSizeCalculator]
            Calculator for effect sizes (creates default if None)
        """
        all_bands = FrequencyBandDefinitions.get_percept_bands()
        # Limit snapshot analysis to canonical low-frequency bands; excludes gamma comparisons
        self._base_bands = {
            name: all_bands[name]
            for name in SNAPSHOT_ANALYSIS_BANDS
            if name in all_bands
        }
        self.rng = np.random.default_rng(seed=BOOTSTRAP_SEED)

        # Effect size calculator and preference
        self._effect_size_calculator = effect_size_calculator or EffectSizeCalculator()
        self._effect_size_preference = EffectSizePreference()

    def analyze_group_comparison(
        self,
        dataset: SnapshotPsdDataset,
        group1_event_types: List[str],
        group2_event_types: List[str],
        group1_name: str = "Group 1",
        group2_name: str = "Group 2",
        hemisphere: str = "LEFT",
        use_log_scale: bool = True,
        filter_stimulation: bool = True,
        timeline_band_center: Optional[float] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, BandComparisonResult]:
        """
        Perform statistical comparison between two custom event groups.

        Parameters
        ----------
        dataset : SnapshotPsdDataset
            Dataset containing PSD events
        group1_event_types : List[str]
            Event types for first group
        group2_event_types : List[str]
            Event types for second group
        group1_name : str
            Display name for first group
        group2_name : str
            Display name for second group
        hemisphere : str
            Hemisphere to analyze ("LEFT" or "RIGHT")
        use_log_scale : bool
            Reserved for future use (log-scale integration). Currently unused.
        filter_stimulation : bool
            Whether to filter for matching stimulation states
        timeline_band_center : Optional[float]
            Optional center frequency (Hz) for a 5 Hz custom band (±2.5 Hz)

        Returns
        -------
        Dict[str, BandComparisonResult]
            Results for each frequency band
        """
        # The service treats the inputs as positional groups; the caller decides
        # the craving/non-craving labelling via group{1,2}_name. Panel convention
        # (Jade = Group 1 = non-craving, Rose = Group 2 = craving) lives in the
        # caller, not here.
        if filter_stimulation:
            events = dataset.filter_by_stimulation_state(require_matching=True)
            filtered_dataset = SnapshotPsdDataset(
                patient_id=dataset.patient_id,
                events=events,
                frequency_axis=dataset.frequency_axis
            )
        else:
            filtered_dataset = dataset

        bands_sequence = self._build_band_sequence(
            filtered_dataset.frequency_axis,
            timeline_band_center
        )

        if not bands_sequence:
            logger.warning("No frequency bands available for analysis. Check configuration.")
            return {}

        # Compute band powers for each group (group-agnostic; semantics live in
        # group1_name / group2_name passed in by the caller).
        # Total work units: 2 (group power computations) + n_bands.
        n_bands = len(bands_sequence)
        total_units = 2 + n_bands

        if progress_callback is not None:
            progress_callback(0, total_units, f"Computing {group1_name} powers")
        if cancel_check is not None and cancel_check():
            raise OperationCancelledException()
        group1_powers = self._compute_band_powers_for_group(
            filtered_dataset,
            group1_event_types,
            hemisphere,
            bands_sequence
        )

        if progress_callback is not None:
            progress_callback(1, total_units, f"Computing {group2_name} powers")
        if cancel_check is not None and cancel_check():
            raise OperationCancelledException()
        group2_powers = self._compute_band_powers_for_group(
            filtered_dataset,
            group2_event_types,
            hemisphere,
            bands_sequence
        )

        # Perform comparisons for each band
        results = {}
        p_values = []
        band_keys = []

        for band_idx, (band_key, band_def, display_name) in enumerate(bands_sequence):
            if cancel_check is not None and cancel_check():
                raise OperationCancelledException()
            if progress_callback is not None:
                progress_callback(2 + band_idx, total_units, display_name)
            if band_key in group1_powers and band_key in group2_powers:
                result = self._compare_band_powers(
                    band_key,
                    display_name,
                    band_def,
                    hemisphere,
                    group1_name,
                    group2_name,
                    group1_powers[band_key],
                    group2_powers[band_key]
                )
                results[band_key] = result
                p_values.append(result.p_value)
                band_keys.append(band_key)

        # Apply FDR correction
        if p_values:
            q_values = self._benjamini_hochberg(p_values)
            for band_key, q_value in zip(band_keys, q_values):
                old_result = results[band_key]
                results[band_key] = replace(
                    old_result,
                    q_value=q_value,
                    is_significant=(q_value < FDR_ALPHA)
                )

        if progress_callback is not None:
            progress_callback(total_units, total_units, "Bands complete")
        return results

    def analyze_craving_vs_non_craving(
        self,
        dataset: SnapshotPsdDataset,
        hemisphere: str = "LEFT",
        use_log_scale: bool = True,
        filter_stimulation: bool = True,
        timeline_band_center: Optional[float] = None
    ) -> Dict[str, BandComparisonResult]:
        """
        Perform craving vs non-craving analysis across all frequency bands.

        This is a convenience method that uses predefined event groups.
        For custom groups, use analyze_group_comparison() instead.

        Parameters
        ----------
        dataset : SnapshotPsdDataset
            Dataset containing PSD events
        hemisphere : str
            Hemisphere to analyze ("LEFT" or "RIGHT")
        use_log_scale : bool
            Reserved for future use (log-scale integration). Currently unused.
        filter_stimulation : bool
            Whether to filter for matching stimulation states
        timeline_band_center : Optional[float]
            Optional center frequency (Hz) for a 5 Hz custom band

        Returns
        -------
        Dict[str, BandComparisonResult]
            Results for each frequency band
        """
        # Panel convention: Group 1 (Jade) = non-craving, Group 2 (Rose) = craving.
        # Mirror the convention here so the default helper produces results whose
        # group1/group2 fields agree with the rest of the pipeline.
        non_craving_group = ["Anxious", "Happy", "Neutral", "Sad", "Depressed"]
        craving_group = ["Craving", "Drinking", "Drinking/Craving"]

        return self.analyze_group_comparison(
            dataset=dataset,
            group1_event_types=non_craving_group,
            group2_event_types=craving_group,
            group1_name="Non-Craving",
            group2_name="Craving",
            hemisphere=hemisphere,
            use_log_scale=use_log_scale,
            filter_stimulation=filter_stimulation,
            timeline_band_center=timeline_band_center
        )

    def _compute_band_powers_for_group(
        self,
        dataset: SnapshotPsdDataset,
        event_group: List[str],
        hemisphere: str,
        bands_sequence: List[Tuple[str, FrequencyBand, str]]
    ) -> Dict[str, np.ndarray]:
        """
        Compute band powers for all events in a group.

        Returns
        -------
        Dict[str, np.ndarray]
            Band name -> array of powers for each event
        """
        events = dataset.filter_by_event_group(event_group)
        if not events:
            return {}

        band_powers = {band_key: [] for band_key, _, _ in bands_sequence}

        for i, event in enumerate(events):
            # Get PSD for hemisphere
            psd = event.get_psd_for_hemisphere(hemisphere)
            if psd is None:
                continue
            # Use event's own frequency axis since it may vary
            event_freq_axis = event.frequency_axis
            if len(psd) != len(event_freq_axis):
                continue

            # Integrate power in each band
            for band_key, band, _ in bands_sequence:
                power = self._integrate_band_power(
                    event_freq_axis,  # Use event's frequency axis
                    psd,
                    band
                )
                if power is not None:
                    band_powers[band_key].append(power)

        # Convert lists to arrays
        return {
            band_name: np.array(powers)
            for band_name, powers in band_powers.items()
            if powers
        }

    def _integrate_band_power(
        self,
        frequency_axis: np.ndarray,
        psd: np.ndarray,
        band: FrequencyBand,
        use_log_scale: bool = True
    ) -> Optional[float]:
        """
        Integrate power within a frequency band.

        Uses trapezoidal integration over available bins,
        handling NaN values from artifact censoring.

        Parameters
        ----------
        frequency_axis : np.ndarray
            Frequency axis corresponding to PSD values
        psd : np.ndarray
            Power spectral density values
        band : FrequencyBand
            Band definition to integrate
        use_log_scale : bool
            Reserved for potential log-scale integration (unused)

        Returns
        -------
        Optional[float]
            Integrated band power in µV² (raw power, not log-transformed)
        """
        # Get bin indices for this band
        bin_mask = band.get_bin_indices(frequency_axis)

        # Extract band data
        band_freqs = frequency_axis[bin_mask]
        band_psd = psd[bin_mask]

        # Handle NaN values (censored bins)
        valid_mask = ~np.isnan(band_psd)
        if np.sum(valid_mask) < 2:  # Need at least 2 points to integrate
            return None

        valid_freqs = band_freqs[valid_mask]
        valid_psd = band_psd[valid_mask]

        # TODO: Add log-scale integration if required by future analyses

        # Integrate using trapezoidal rule
        return integrate.trapezoid(valid_psd, valid_freqs)

    def _compare_band_powers(
        self,
        band_key: str,
        display_name: str,
        band_def: FrequencyBand,
        hemisphere: str,
        group1_name: str,
        group2_name: str,
        group1_powers: np.ndarray,
        group2_powers: np.ndarray
    ) -> BandComparisonResult:
        """
        Compare band powers between two groups using Mann-Whitney U test.
        """
        # Compute medians and MADs
        median1 = np.median(group1_powers)
        median2 = np.median(group2_powers)
        mad1 = np.median(np.abs(group1_powers - median1))
        mad2 = np.median(np.abs(group2_powers - median2))

        # Perform Mann-Whitney U test
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning)
            u_stat, p_value = stats.mannwhitneyu(
                group1_powers,
                group2_powers,
                alternative='two-sided'
            )

        # Compute effect sizes
        n1, n2 = len(group1_powers), len(group2_powers)
        n_total = n1 + n2
        expected_u = n1 * n2 / 2.0

        # Determine effect direction from U-statistic (fallback to medians)
        if expected_u == 0:
            direction = 0.0
        else:
            direction = float(np.sign(u_stat - expected_u))

        if direction == 0.0 and not np.isclose(median1, median2):
            direction = float(np.sign(median1 - median2))
        if direction == 0.0:
            mean_diff = np.mean(group1_powers) - np.mean(group2_powers)
            if not np.isclose(mean_diff, 0.0):
                direction = float(np.sign(mean_diff))

        # Legacy effect sizes (for backward compatibility)
        # Rosenthal's r (preserve sign)
        if np.isnan(p_value):
            z_score = 0.0
        else:
            # Clip p-value to avoid infinities
            eps_min = np.finfo(float).tiny
            eps_max = 1.0 - np.finfo(float).eps
            clipped_p = np.clip(p_value, eps_min, eps_max)
            z_magnitude = stats.norm.ppf(1 - clipped_p / 2)
            z_score = direction * z_magnitude if direction != 0.0 else 0.0
        rosenthal_r = z_score / np.sqrt(n_total) if n_total > 0 else 0.0

        # Rank-biserial correlation (signed), craving-referenced for internal
        # consistency with the displayed effect size. ``u_stat`` above is
        # computed non-craving-first (group1 = non-craving); the canonical
        # script computes U craving-first, and U_craving = n1*n2 - U_nonCraving,
        # so we complement it here. DEPRECATED fallback only — the displayed
        # value comes from ``effect_size_result`` below.
        rank_biserial_r = (2 * (n1 * n2 - u_stat)) / (n1 * n2) - 1

        # Bootstrap confidence intervals for effect size (legacy)
        ci_lower, ci_upper = self._bootstrap_effect_size_ci(
            group1_powers,
            group2_powers,
            effect_type='rank_biserial'
        )

        # Bootstrap CI for median difference (central tendency)
        median_diff_ci_lower, median_diff_ci_upper = self._bootstrap_median_difference_ci(
            group1_powers,
            group2_powers
        )

        # Displayed effect size — reproduce the canonical deposit script
        # (code_release/scripts/1_snapshot_stats_canonical.py -> Supp Table 2):
        # craving-referenced (positive = craving higher) with a 5,000-iter
        # stratified BCa 95% CI (seed 2025). By the caller's panel convention
        # Group 2 = craving and Group 1 = non-craving. Rosenthal's r is not in
        # the script and keeps the shared calculator's parametric path.
        craving = group2_powers
        non_craving = group1_powers

        effect_size_result = None
        try:
            effect_type = self._effect_size_preference.get_effect_size()
            logger.debug(
                f"Calculating effect size for {display_name} ({hemisphere}): "
                f"type={effect_type.value}"
            )

            if effect_type == EffectSizeType.ROSENTHAL_R:
                # Out of scope for the canonical script: retain the shared
                # calculator's parametric Rosenthal's r (needs the z-statistic).
                effect_size_result = self._effect_size_calculator.calculate_effect_size(
                    group1_powers,
                    group2_powers,
                    effect_type,
                    test_statistic=z_score,
                    test_name="Mann-Whitney U"
                )
            elif effect_type in (EffectSizeType.RANK_BISERIAL, EffectSizeType.COHENS_D):
                # Craving-referenced point estimate + stratified BCa CI. On a
                # CI failure (e.g. degenerate bootstrap resamples) fall back to
                # the point estimate with a NaN CI, which the table renders "-".
                if effect_type == EffectSizeType.RANK_BISERIAL:
                    try:
                        value, ci_lower_es, ci_upper_es = bca_bootstrap_rrb(
                            craving, non_craving
                        )
                    except Exception as ci_exc:
                        logger.warning(
                            f"BCa CI failed for {display_name} "
                            f"(rank_biserial): {ci_exc}; using NaN CI."
                        )
                        value = _effect_sizes(craving, non_craving)[2]
                        ci_lower_es = ci_upper_es = float("nan")
                else:  # COHENS_D — computed on log10 band power
                    log_craving = np.log10(craving)
                    log_non_craving = np.log10(non_craving)
                    try:
                        value, ci_lower_es, ci_upper_es = bca_bootstrap_d(
                            log_craving, log_non_craving
                        )
                    except Exception as ci_exc:
                        logger.warning(
                            f"BCa CI failed for {display_name} "
                            f"(cohens_d): {ci_exc}; using NaN CI."
                        )
                        value = _cohens_d(log_craving, log_non_craving)
                        ci_lower_es = ci_upper_es = float("nan")

                effect_size_result = EffectSizeResult(
                    effect_size_type=effect_type,
                    value=value,
                    ci_lower=ci_lower_es,
                    ci_upper=ci_upper_es,
                    interpretation=self._effect_size_calculator._interpret_effect_size(
                        value, effect_type, n1, n2
                    ),
                )
            else:
                # Defensive: any future type falls back to the calculator.
                effect_size_result = self._effect_size_calculator.calculate_effect_size(
                    group1_powers,
                    group2_powers,
                    effect_type
                )

            logger.debug(
                f"Effect size calculated: {effect_type.value}={effect_size_result.value:.4f} "
                f"[{effect_size_result.ci_lower:.4f}, {effect_size_result.ci_upper:.4f}] "
                f"({effect_size_result.interpretation})"
            )

        except Exception as e:
            logger.warning(
                f"Failed to calculate effect size for {display_name}: {e}. "
                f"Result will use legacy effect sizes only."
            )
            effect_size_result = None

        return BandComparisonResult(
            band_name=display_name,
            canonical_band=band_key,
            min_freq=band_def.min_freq,
            max_freq=band_def.max_freq,
            hemisphere=hemisphere,
            group1_name=group1_name,
            group2_name=group2_name,
            n_group1=n1,
            n_group2=n2,
            median_group1=median1,
            median_group2=median2,
            mad_group1=mad1,
            mad_group2=mad2,
            u_statistic=u_stat,
            p_value=p_value,
            q_value=p_value,  # Will be updated with FDR correction
            rosenthal_r=rosenthal_r,
            rank_biserial_r=rank_biserial_r,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            central_tendency_label="Median",
            central_tendency_difference=median1 - median2,
            central_tendency_ci_lower=median_diff_ci_lower,
            central_tendency_ci_upper=median_diff_ci_upper,
            is_significant=False,  # Will be updated after FDR correction
            effect_size_result=effect_size_result  # NEW: Unified effect size
        )

    def _bootstrap_effect_size_ci(
        self,
        group1: np.ndarray,
        group2: np.ndarray,
        effect_type: str = 'rank_biserial',
        n_bootstrap: int = BOOTSTRAP_ITERATIONS
    ) -> Tuple[float, float]:
        """
        Compute bootstrap confidence intervals for effect size.

        Uses BCa (bias-corrected and accelerated) method.
        """
        def effect_statistic(x1, x2):
            """Compute effect size statistic."""
            n1, n2 = len(x1), len(x2)
            u_stat, _ = stats.mannwhitneyu(x1, x2, alternative='two-sided')

            if effect_type == 'rank_biserial':
                return (2 * u_stat) / (n1 * n2) - 1
            else:  # rosenthal_r
                z_score = stats.norm.ppf(1 - 0.05)  # Use fixed p for bootstrap
                return abs(z_score) / np.sqrt(n1 + n2)

        # Perform bootstrap
        try:
            result = bootstrap(
                (group1, group2),
                lambda x1, x2: effect_statistic(x1, x2),
                n_resamples=n_bootstrap,
                confidence_level=0.95,
                method='BCa',
                random_state=self.rng
            )
            return result.confidence_interval.low, result.confidence_interval.high
        except Exception as e:
            logger.warning(f"Bootstrap CI calculation failed: {e}")
            # Return point estimate ± standard error as fallback
            point_est = effect_statistic(group1, group2)
            se = 0.1  # Conservative estimate
            return point_est - 1.96 * se, point_est + 1.96 * se

    def _bootstrap_median_difference_ci(
        self,
        group1: np.ndarray,
        group2: np.ndarray,
        confidence_level: float = 0.95,
        n_bootstrap: int = BOOTSTRAP_ITERATIONS
    ) -> Tuple[float, float]:
        """Compute bootstrap CI for median difference (group1 - group2)."""

        group1 = np.asarray(group1)
        group2 = np.asarray(group2)

        # Remove NaNs to avoid propagation
        group1 = group1[~np.isnan(group1)]
        group2 = group2[~np.isnan(group2)]

        if len(group1) == 0 or len(group2) == 0:
            return float('nan'), float('nan')

        median_diff = float(np.median(group1) - np.median(group2))

        # Not enough samples for robust bootstrap
        if len(group1) < 3 or len(group2) < 3:
            return median_diff, median_diff

        try:
            result = bootstrap(
                (group1, group2),
                lambda x1, x2: np.median(x1) - np.median(x2),
                n_resamples=n_bootstrap,
                confidence_level=confidence_level,
                method='BCa',
                random_state=self.rng
            )
            return (
                float(result.confidence_interval.low),
                float(result.confidence_interval.high)
            )
        except Exception as exc:
            logger.warning(f"Median difference CI bootstrap failed: {exc}")
            return median_diff, median_diff

    def _benjamini_hochberg(
        self,
        p_values: List[float],
        alpha: float = FDR_ALPHA
    ) -> List[float]:
        """
        Apply Benjamini-Hochberg FDR correction.

        Parameters
        ----------
        p_values : List[float]
            Raw p-values
        alpha : float
            Target FDR level

        Returns
        -------
        List[float]
            Adjusted q-values
        """
        n = len(p_values)
        if n == 0:
            return []

        # Sort p-values with indices
        sorted_indices = np.argsort(p_values)
        sorted_p = np.array(p_values)[sorted_indices]

        # Compute adjusted p-values
        q_values = np.zeros(n)
        for i in range(n):
            q_values[i] = sorted_p[i] * n / (i + 1)

        # Ensure monotonicity
        for i in range(n - 2, -1, -1):
            q_values[i] = min(q_values[i], q_values[i + 1])

        # Cap at 1.0
        q_values = np.minimum(q_values, 1.0)

        # Restore original order
        result = np.zeros(n)
        for i, idx in enumerate(sorted_indices):
            result[idx] = q_values[i]

        return result.tolist()

    def _build_band_sequence(
        self,
        frequency_axis: np.ndarray,
        timeline_band_center: Optional[float]
    ) -> List[Tuple[str, FrequencyBand, str]]:
        """
        Construct the ordered list of bands to analyze.

        Parameters
        ----------
        frequency_axis : np.ndarray
            Reference frequency axis for determining available bins
        timeline_band_center : Optional[float]
            User-specified center frequency for optional 5 Hz band

        Returns
        -------
        List[Tuple[str, FrequencyBand, str]]
            Tuples of (canonical_key, band_definition, display_name)
        """
        bands: List[Tuple[str, FrequencyBand, str]] = []

        if frequency_axis is None or len(frequency_axis) == 0:
            logger.warning("Frequency axis is empty; cannot build band sequence.")
            return bands

        if timeline_band_center is not None:
            timeline_band = self._create_timeline_band(timeline_band_center, frequency_axis)
            if timeline_band:
                band_def, display_name = timeline_band
                bands.append(("Timeline", band_def, display_name))
            else:
                logger.warning(
                    "Timeline band center %.2f Hz could not be created (insufficient bins or out of range).",
                    timeline_band_center
                )

        for band_name in SNAPSHOT_ANALYSIS_BANDS:
            band = self._base_bands.get(band_name)
            if band:
                bands.append((band_name, band, band.name))

        return bands

    def _create_timeline_band(
        self,
        center_freq: float,
        frequency_axis: np.ndarray
    ) -> Optional[Tuple[FrequencyBand, str]]:
        """
        Create a 5 Hz-wide FrequencyBand centered on the provided frequency.

        Parameters
        ----------
        center_freq : float
            Target center frequency in Hz
        frequency_axis : np.ndarray
            Available frequency bins for snapshots data

        Returns
        -------
        Optional[Tuple[FrequencyBand, str]]
            FrequencyBand definition and display label, or None if not feasible
        """
        if frequency_axis is None or len(frequency_axis) == 0:
            return None

        freqs = np.asarray(frequency_axis, dtype=float)
        min_axis = float(np.min(freqs))
        max_axis = float(np.max(freqs))

        half_width = 2.5
        band_min = center_freq - half_width
        band_max = center_freq + half_width

        if band_max < min_axis or band_min > max_axis:
            return None

        band_min = max(band_min, min_axis)
        band_max = min(band_max, max_axis)

        mask = (freqs >= band_min) & (freqs <= band_max)
        band_centers = [float(f) for f in freqs[mask]]

        if len(band_centers) < 2:
            return None

        band_definition = FrequencyBand(
            name="Timeline",
            min_freq=round(band_min, 2),
            max_freq=round(band_max, 2),
            center_freqs=band_centers
        )
        display_name = f"Timeline ({center_freq:.2f} Hz)"
        return band_definition, display_name

    def get_psd_curves_for_groups(
        self,
        dataset: SnapshotPsdDataset,
        hemisphere: str = "LEFT",
        group1_event_types: Optional[List[str]] = None,
        group2_event_types: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, int]]:
        """
        Get median PSD curves with bootstrap confidence intervals for two event groups.

        Parameters
        ----------
        dataset : SnapshotPsdDataset
            Dataset containing PSD events
        hemisphere : str
            Hemisphere to analyze
        group1_event_types : Optional[List[str]]
            Event types for Group 1 (panel: Jade, manuscript: non-craving).
            Defaults to the manuscript non-craving keywords.
        group2_event_types : Optional[List[str]]
            Event types for Group 2 (panel: Rose, manuscript: craving).
            Defaults to the manuscript craving keywords.

        Returns
        -------
        Dict with keys 'craving' and 'non_craving' (analytical labels, not
        group ordinals), each containing:
            - median_psd: Median PSD curve (raw power in µV²/Hz)
            - ci_lower: Lower bound of 95% bootstrap CI
            - ci_upper: Upper bound of 95% bootstrap CI
            - n_events: Number of events
        """
        # Defaults match the panel convention: Group 1 = non-craving, Group 2 = craving.
        if group1_event_types is None:
            group1_event_types = ["Anxious", "Happy", "Neutral", "Sad", "Depressed"]
        if group2_event_types is None:
            group2_event_types = ["Craving", "Drinking", "Drinking/Craving"]

        results = {}

        # Two work units: one bootstrap-CI per group.
        if progress_callback is not None:
            progress_callback(0, 2, "PSD curve: non-craving")
        if cancel_check is not None and cancel_check():
            raise OperationCancelledException()

        # Group 1 (Jade) → non-craving curve.
        median_psd, ci_lower, ci_upper, n = dataset.get_group_median_psd(
            group1_event_types, hemisphere
        )
        results['non_craving'] = (median_psd, ci_lower, ci_upper, n)

        if progress_callback is not None:
            progress_callback(1, 2, "PSD curve: craving")
        if cancel_check is not None and cancel_check():
            raise OperationCancelledException()

        # Group 2 (Rose) → craving curve.
        median_psd, ci_lower, ci_upper, n = dataset.get_group_median_psd(
            group2_event_types, hemisphere
        )
        results['craving'] = (median_psd, ci_lower, ci_upper, n)

        if progress_callback is not None:
            progress_callback(2, 2, "PSD curves complete")
        return results
