"""
Quality Control (QC) Module for Cardiac Artifact Removal.

Provides visualization and validation functions for assessing the efficacy
of cardiac artifact removal from BrainSense LFP data. These functions help
verify that ECG/QRS artifacts have been properly removed without damaging
neural signals.

This module contains:
- Visual QC plots (time-domain, frequency-domain comparisons)
- Quantitative validation metrics
- Statistical tests for removal efficacy
- Automated QC report generation

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
"""

import logging
from typing import Dict, Optional, Tuple
import numpy as np
from scipy.signal import welch
from scipy import stats

logger = logging.getLogger(__name__)

# QC thresholds
QC_THRESHOLDS = {
    'min_theta_reduction': 20.0,  # % minimum power reduction in theta band
    'min_alpha_reduction': 20.0,  # % minimum power reduction in alpha band
    'min_beta_reduction': 20.0,   # % minimum power reduction in beta band
    'max_gamma_change': 10.0,     # % maximum allowed change in gamma band
    'min_snr_improvement': 1.0,   # dB minimum SNR improvement
    'min_r_waves': 10,            # minimum number of R-waves for reliable removal
    'heart_rate_min': 40,         # BPM minimum plausible heart rate
    'heart_rate_max': 150,        # BPM maximum plausible heart rate
}


def compute_qc_metrics(
    raw_lfp: np.ndarray,
    cleaned_lfp: np.ndarray,
    r_wave_indices: np.ndarray,
    fs: int = 250
) -> Dict:
    """
    Compute comprehensive QC metrics for cardiac artifact removal.

    Calculates both time-domain and frequency-domain metrics to assess
    the quality of cardiac artifact removal.

    Args:
        raw_lfp: Original raw LFP signal
        cleaned_lfp: Cleaned LFP signal after cardiac removal
        r_wave_indices: Detected R-wave indices
        fs: Sampling frequency in Hz

    Returns:
        Dict with QC metrics:
            - Detection metrics (heart rate, R-wave count)
            - Power reduction by frequency band
            - SNR improvement
            - Signal quality indicators
            - Pass/fail status for each criterion

    Example:
        >>> metrics = compute_qc_metrics(raw_signal, cleaned_signal, r_waves, fs=250)
        >>> print(f"QC Status: {'PASS' if metrics['overall_pass'] else 'FAIL'}")
        >>> print(f"Theta reduction: {metrics['power_reduction_theta']:.1f}%")
    """
    metrics = {}

    # 1. Detection metrics
    num_r_waves = len(r_wave_indices)
    metrics['num_r_waves'] = num_r_waves
    metrics['recording_duration_sec'] = len(raw_lfp) / fs

    if num_r_waves >= 2:
        ibi = np.diff(r_wave_indices) / fs  # Inter-beat intervals in seconds
        metrics['heart_rate_mean'] = 60 / np.mean(ibi)
        metrics['heart_rate_std'] = 60 * np.std(ibi) / (np.mean(ibi)**2)
        metrics['heart_rate_cv'] = np.std(ibi) / np.mean(ibi)  # Coefficient of variation
    else:
        metrics['heart_rate_mean'] = 0.0
        metrics['heart_rate_std'] = 0.0
        metrics['heart_rate_cv'] = 0.0

    # 2. Power reduction by frequency band
    freqs, psd_raw = welch(raw_lfp, fs=fs, nperseg=min(512, len(raw_lfp)//4), noverlap=256)
    freqs, psd_clean = welch(cleaned_lfp, fs=fs, nperseg=min(512, len(cleaned_lfp)//4), noverlap=256)

    bands = {
        'theta': (4, 8),
        'alpha': (8, 12),
        'beta': (12, 30),
        'gamma': (30, 50),
        'low_gamma': (30, 60),
        'high_gamma': (60, 100),
    }

    for band_name, (low, high) in bands.items():
        mask = (freqs >= low) & (freqs <= high)

        if np.sum(mask) == 0:
            metrics[f'power_reduction_{band_name}'] = 0.0
            metrics[f'power_raw_{band_name}'] = 0.0
            metrics[f'power_clean_{band_name}'] = 0.0
            continue

        power_raw = np.mean(psd_raw[mask])
        power_clean = np.mean(psd_clean[mask])

        metrics[f'power_raw_{band_name}'] = power_raw
        metrics[f'power_clean_{band_name}'] = power_clean

        if power_raw > 0:
            reduction_percent = (1 - power_clean / power_raw) * 100
            reduction_db = 10 * np.log10(power_raw / power_clean) if power_clean > 0 else 0.0
        else:
            reduction_percent = 0.0
            reduction_db = 0.0

        metrics[f'power_reduction_{band_name}'] = reduction_percent
        metrics[f'power_reduction_{band_name}_db'] = reduction_db

    # 3. SNR improvement
    gamma_mask = (freqs >= 30) & (freqs <= 50)
    theta_beta_mask = (freqs >= 4) & (freqs <= 30)

    if np.sum(gamma_mask) > 0 and np.sum(theta_beta_mask) > 0:
        snr_raw = np.mean(psd_raw[gamma_mask]) / np.mean(psd_raw[theta_beta_mask])
        snr_clean = np.mean(psd_clean[gamma_mask]) / np.mean(psd_clean[theta_beta_mask])

        if snr_raw > 0 and snr_clean > 0:
            metrics['snr_improvement_db'] = 10 * np.log10(snr_clean / snr_raw)
        else:
            metrics['snr_improvement_db'] = 0.0
    else:
        metrics['snr_improvement_db'] = 0.0

    # 4. Signal quality indicators
    # RMS (root-mean-square) amplitude
    metrics['rms_raw'] = np.sqrt(np.mean(raw_lfp**2))
    metrics['rms_clean'] = np.sqrt(np.mean(cleaned_lfp**2))
    metrics['rms_change_percent'] = (1 - metrics['rms_clean'] / metrics['rms_raw']) * 100

    # Peak-to-peak amplitude
    metrics['peak_to_peak_raw'] = np.ptp(raw_lfp)
    metrics['peak_to_peak_clean'] = np.ptp(cleaned_lfp)

    # Standard deviation
    metrics['std_raw'] = np.std(raw_lfp)
    metrics['std_clean'] = np.std(cleaned_lfp)

    # 5. Pass/fail criteria
    checks = {
        'sufficient_r_waves': num_r_waves >= QC_THRESHOLDS['min_r_waves'],
        'plausible_heart_rate': (QC_THRESHOLDS['heart_rate_min'] <= metrics['heart_rate_mean'] <= QC_THRESHOLDS['heart_rate_max']),
        'theta_reduction': metrics['power_reduction_theta'] >= QC_THRESHOLDS['min_theta_reduction'],
        'alpha_reduction': metrics['power_reduction_alpha'] >= QC_THRESHOLDS['min_alpha_reduction'],
        'beta_reduction': metrics['power_reduction_beta'] >= QC_THRESHOLDS['min_beta_reduction'],
        'gamma_preserved': abs(metrics['power_reduction_gamma']) <= QC_THRESHOLDS['max_gamma_change'],
        'snr_improved': metrics['snr_improvement_db'] >= QC_THRESHOLDS['min_snr_improvement'],
    }

    metrics['checks'] = checks
    metrics['overall_pass'] = all(checks.values())
    metrics['failed_checks'] = [name for name, passed in checks.items() if not passed]
    metrics['num_checks_passed'] = sum(checks.values())
    metrics['num_checks_total'] = len(checks)

    return metrics


def generate_qc_report(metrics: Dict, verbose: bool = True) -> str:
    """
    Generate human-readable QC report from metrics.

    Args:
        metrics: QC metrics from compute_qc_metrics()
        verbose: If True, include detailed metrics; if False, summary only

    Returns:
        Formatted QC report as string

    Example:
        >>> metrics = compute_qc_metrics(raw, cleaned, r_waves)
        >>> report = generate_qc_report(metrics)
        >>> print(report)
    """
    lines = []
    lines.append("="*70)
    lines.append("CARDIAC ARTIFACT REMOVAL - QUALITY CONTROL REPORT")
    lines.append("="*70)

    # Overall status
    status = "✓ PASS" if metrics['overall_pass'] else "✗ FAIL"
    lines.append(f"\nOVERALL STATUS: {status}")
    lines.append(f"Checks passed: {metrics['num_checks_passed']}/{metrics['num_checks_total']}")

    if metrics['failed_checks']:
        lines.append(f"Failed checks: {', '.join(metrics['failed_checks'])}")

    # Detection metrics
    lines.append(f"\n{'DETECTION METRICS':-^70}")
    lines.append(f"  Recording duration:          {metrics['recording_duration_sec']:.1f} sec ({metrics['recording_duration_sec']/60:.1f} min)")
    lines.append(f"  R-waves detected:            {metrics['num_r_waves']}")
    lines.append(f"  Mean heart rate:             {metrics['heart_rate_mean']:.1f} BPM")
    lines.append(f"  Heart rate variability:      {metrics['heart_rate_std']:.1f} BPM (CV: {metrics['heart_rate_cv']:.3f})")

    # Power reduction
    lines.append(f"\n{'POWER REDUCTION BY FREQUENCY BAND':-^70}")
    lines.append(f"  Theta (4-8 Hz):              {metrics['power_reduction_theta']:6.1f}% ({metrics['power_reduction_theta_db']:+6.1f} dB)")
    lines.append(f"  Alpha (8-12 Hz):             {metrics['power_reduction_alpha']:6.1f}% ({metrics['power_reduction_alpha_db']:+6.1f} dB)")
    lines.append(f"  Beta (12-30 Hz):             {metrics['power_reduction_beta']:6.1f}% ({metrics['power_reduction_beta_db']:+6.1f} dB)")
    lines.append(f"  Gamma (30-50 Hz):            {metrics['power_reduction_gamma']:6.1f}% ({metrics['power_reduction_gamma_db']:+6.1f} dB)")

    # SNR
    lines.append(f"\n{'SIGNAL QUALITY':-^70}")
    lines.append(f"  SNR improvement:             {metrics['snr_improvement_db']:+6.1f} dB")
    lines.append(f"  RMS amplitude change:        {metrics['rms_change_percent']:6.1f}%")

    if verbose:
        lines.append(f"\n{'DETAILED METRICS':-^70}")
        lines.append(f"  Raw RMS amplitude:           {metrics['rms_raw']:.2f}")
        lines.append(f"  Cleaned RMS amplitude:       {metrics['rms_clean']:.2f}")
        lines.append(f"  Raw peak-to-peak:            {metrics['peak_to_peak_raw']:.2f}")
        lines.append(f"  Cleaned peak-to-peak:        {metrics['peak_to_peak_clean']:.2f}")

    # Validation criteria
    lines.append(f"\n{'VALIDATION CRITERIA':-^70}")
    for check_name, passed in metrics['checks'].items():
        status_symbol = "✓" if passed else "✗"
        check_label = check_name.replace('_', ' ').title()
        lines.append(f"  {status_symbol} {check_label}")

    lines.append("="*70)

    return "\n".join(lines)


def bootstrap_validation(
    raw_lfp: np.ndarray,
    cleaned_lfp: np.ndarray,
    fs: int = 250,
    n_bootstrap: int = 1000,
    cardiac_band: Tuple[float, float] = (4, 30)
) -> Dict:
    """
    Bootstrap statistical test for cardiac removal efficacy.

    Uses bootstrap resampling to estimate confidence intervals for power
    reduction in cardiac-affected frequency bands and test if reduction
    is statistically significant.

    Args:
        raw_lfp: Original raw LFP signal
        cleaned_lfp: Cleaned LFP signal after cardiac removal
        fs: Sampling frequency in Hz
        n_bootstrap: Number of bootstrap iterations
        cardiac_band: Frequency range affected by cardiac artifacts (Hz)

    Returns:
        Dict with bootstrap results:
            - mean_power_diff: Mean power difference
            - ci_low: 95% CI lower bound
            - ci_high: 95% CI upper bound
            - p_value: Bootstrap p-value
            - significant: Whether reduction is significant (p < 0.05)

    Example:
        >>> results = bootstrap_validation(raw, cleaned, fs=250, n_bootstrap=1000)
        >>> if results['significant']:
        ...     print(f"Significant power reduction: {results['mean_power_diff']:.2e}")
    """
    # Compute PSD
    freqs, psd_raw = welch(raw_lfp, fs=fs, nperseg=min(512, len(raw_lfp)//4), noverlap=256)
    freqs, psd_clean = welch(cleaned_lfp, fs=fs, nperseg=min(512, len(cleaned_lfp)//4), noverlap=256)

    # Extract cardiac-affected band
    cardiac_mask = (freqs >= cardiac_band[0]) & (freqs <= cardiac_band[1])
    psd_raw_cardiac = psd_raw[cardiac_mask]
    psd_clean_cardiac = psd_clean[cardiac_mask]

    # Bootstrap resampling
    bootstrap_diffs = []

    for _ in range(n_bootstrap):
        # Resample with replacement
        idx = np.random.choice(len(psd_raw_cardiac), size=len(psd_raw_cardiac), replace=True)

        diff = np.mean(psd_raw_cardiac[idx]) - np.mean(psd_clean_cardiac[idx])
        bootstrap_diffs.append(diff)

    bootstrap_diffs = np.array(bootstrap_diffs)

    # Compute statistics
    mean_diff = np.mean(bootstrap_diffs)
    ci_low = np.percentile(bootstrap_diffs, 2.5)
    ci_high = np.percentile(bootstrap_diffs, 97.5)

    # Test significance (CI should not include zero for significant reduction)
    significant = ci_low > 0

    # Compute p-value (proportion of bootstrap samples with diff <= 0)
    p_value = np.sum(bootstrap_diffs <= 0) / n_bootstrap

    results = {
        'mean_power_diff': mean_diff,
        'ci_low': ci_low,
        'ci_high': ci_high,
        'p_value': p_value,
        'significant': significant,
        'n_bootstrap': n_bootstrap,
        'cardiac_band': cardiac_band
    }

    logger.info(f"Bootstrap validation (n={n_bootstrap}): "
               f"mean_diff={mean_diff:.2e}, CI=[{ci_low:.2e}, {ci_high:.2e}], "
               f"p={p_value:.4f}, significant={significant}")

    return results


def compare_spectrograms(
    raw_lfp: np.ndarray,
    cleaned_lfp: np.ndarray,
    fs: int = 250,
    nperseg: int = 512,
    noverlap: Optional[int] = None
) -> Dict:
    """
    Compare spectrograms before and after cardiac removal.

    Computes time-frequency representations to visualize how cardiac
    artifact removal affects different frequency bands over time.

    Args:
        raw_lfp: Original raw LFP signal
        cleaned_lfp: Cleaned LFP signal after cardiac removal
        fs: Sampling frequency in Hz
        nperseg: Length of each segment for STFT
        noverlap: Number of samples overlap between segments

    Returns:
        Dict with spectrogram data:
            - freqs: Frequency bins
            - times: Time bins
            - Sxx_raw: Spectrogram of raw signal
            - Sxx_clean: Spectrogram of cleaned signal
            - Sxx_diff: Difference spectrogram (raw - clean)

    Example:
        >>> spec_data = compare_spectrograms(raw, cleaned, fs=250)
        >>> # Use spec_data for plotting with matplotlib
    """
    from scipy.signal import spectrogram

    if noverlap is None:
        noverlap = nperseg // 2

    # Compute spectrograms
    freqs, times, Sxx_raw = spectrogram(raw_lfp, fs=fs, nperseg=nperseg, noverlap=noverlap)
    _, _, Sxx_clean = spectrogram(cleaned_lfp, fs=fs, nperseg=nperseg, noverlap=noverlap)

    # Compute difference (should show reduction in cardiac-affected bands)
    Sxx_diff = Sxx_raw - Sxx_clean

    return {
        'freqs': freqs,
        'times': times,
        'Sxx_raw': Sxx_raw,
        'Sxx_clean': Sxx_clean,
        'Sxx_diff': Sxx_diff
    }


def assess_signal_integrity(
    raw_lfp: np.ndarray,
    cleaned_lfp: np.ndarray
) -> Dict:
    """
    Assess signal integrity after cardiac removal.

    Checks for potential over-subtraction or signal distortion that might
    indicate problems with the cardiac removal process.

    Args:
        raw_lfp: Original raw LFP signal
        cleaned_lfp: Cleaned LFP signal after cardiac removal

    Returns:
        Dict with integrity metrics:
            - correlation: Pearson correlation between raw and cleaned
            - amplitude_ratio: RMS amplitude ratio (clean/raw)
            - zero_crossings_ratio: Zero-crossing rate ratio
            - warnings: List of potential issues detected

    Example:
        >>> integrity = assess_signal_integrity(raw, cleaned)
        >>> if integrity['warnings']:
        ...     print(f"Warnings: {integrity['warnings']}")
    """
    metrics = {}
    warnings_list = []

    # Correlation (should be high, >0.7)
    correlation, _ = stats.pearsonr(raw_lfp, cleaned_lfp)
    metrics['correlation'] = correlation

    if correlation < 0.7:
        warnings_list.append(f"Low correlation ({correlation:.2f}) - possible over-subtraction")

    # Amplitude ratio (should be 0.5-0.95 for effective cardiac removal)
    rms_raw = np.sqrt(np.mean(raw_lfp**2))
    rms_clean = np.sqrt(np.mean(cleaned_lfp**2))
    amplitude_ratio = rms_clean / rms_raw if rms_raw > 0 else 0
    metrics['amplitude_ratio'] = amplitude_ratio

    if amplitude_ratio < 0.3:
        warnings_list.append(f"Very low amplitude ratio ({amplitude_ratio:.2f}) - possible over-subtraction")
    elif amplitude_ratio > 0.95:
        warnings_list.append(f"High amplitude ratio ({amplitude_ratio:.2f}) - cardiac removal may be ineffective")

    # Zero-crossing rate (dramatic changes indicate distortion)
    zero_crossings_raw = np.sum(np.diff(np.sign(raw_lfp)) != 0)
    zero_crossings_clean = np.sum(np.diff(np.sign(cleaned_lfp)) != 0)
    zc_ratio = zero_crossings_clean / zero_crossings_raw if zero_crossings_raw > 0 else 0
    metrics['zero_crossings_ratio'] = zc_ratio

    if zc_ratio > 1.5:
        warnings_list.append(f"Increased zero-crossings ({zc_ratio:.2f}×) - possible high-frequency artifacts introduced")

    # Check for NaN or Inf
    if np.any(np.isnan(cleaned_lfp)) or np.any(np.isinf(cleaned_lfp)):
        warnings_list.append("NaN or Inf values detected in cleaned signal")

    metrics['warnings'] = warnings_list
    metrics['integrity_ok'] = len(warnings_list) == 0

    return metrics
