"""
Cardiac Artifact Removal (CAR) Preprocessor for BrainSense Streaming Data.

Implements time-domain template subtraction for removing ECG/QRS artifacts from
BrainSense LFP streaming recordings based on Sanger et al. 2025 methodology.

This preprocessor:
1. Isolates cardiac signal using bandpass filtering (5-30 Hz)
2. Detects R-wave peaks using prominence-based peak detection
3. Constructs averaged QRS template with Hanning windowing
4. Subtracts template at each R-wave location in time domain

CRITICAL: This preprocessing must occur BEFORE frequency-domain analysis
to prevent spectral contamination in theta (4-8 Hz), alpha (8-12 Hz),
and beta (12-30 Hz) bands.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
Reference: Sanger et al. 2025 - "Medtronic Percept Recorded LFP Pre-Processing
           to Remove Noise and Cardiac Signals From Neural Recordings"
"""

import json
import logging
from typing import Dict, Optional, Tuple
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks, windows, welch

logger = logging.getLogger(__name__)

# Constants from Sanger et al. 2025
DEFAULT_SAMPLING_RATE = 250  # Hz - Medtronic BrainSense standard
CARDIAC_BAND_LOW = 5  # Hz - Lower cutoff for cardiac signal isolation
CARDIAC_BAND_HIGH = 30  # Hz - Upper cutoff for cardiac signal isolation
MIN_PEAK_DISTANCE_SEC = 0.5  # seconds - Minimum time between R-waves (120 BPM max)
MIN_PEAK_PROMINENCE_STD = 2.5  # std multiplier - Adaptive threshold for R-wave detection
TEMPLATE_SAMPLES_BEFORE = 36  # samples - Window before R-wave (144 ms at 250 Hz)
TEMPLATE_SAMPLES_AFTER = 36  # samples - Window after R-wave (144 ms at 250 Hz)


class CardiacArtifactRemoval:
    """
    Preprocessor for detecting and removing cardiac (ECG/QRS) artifacts from streaming LFP data.

    Based on the time-domain template subtraction method from Sanger et al. 2025,
    this preprocessor automatically detects R-waves, constructs an averaged QRS
    template, and subtracts it from the raw signal to remove cardiac contamination.

    The preprocessor:
    - Isolates cardiac signal using bandpass filter (5-30 Hz)
    - Detects R-wave peaks with adaptive thresholding
    - Constructs averaged QRS template with Hanning windowing
    - Subtracts template at each R-wave location in time domain
    - Validates removal efficacy and tracks statistics

    Usage:
        >>> preprocessor = CardiacArtifactRemoval(enabled=True)
        >>> cleaned_signal, stats = preprocessor.remove_cardiac_artifact(raw_lfp, fs=250)
        >>> print(f"Removed cardiac artifacts: {stats['r_waves_detected']} R-waves detected")
    """

    def __init__(self, enabled: bool = True, fs: int = DEFAULT_SAMPLING_RATE):
        """
        Initialize the cardiac artifact removal preprocessor.

        Args:
            enabled: Whether preprocessing is enabled (default: True)
            fs: Sampling frequency in Hz (default: 250)
        """
        self.enabled = enabled
        self.fs = fs
        self.stats = {
            'r_waves_detected': 0,
            'template_length': 0,
            'heart_rate_bpm': 0.0,
            'power_reduction_theta': 0.0,
            'power_reduction_alpha': 0.0,
            'power_reduction_beta': 0.0,
        }

        logger.info(f"CardiacArtifactRemoval initialized (enabled={enabled}, fs={fs} Hz)")

    def remove_cardiac_artifact(
        self,
        raw_lfp: np.ndarray,
        fs: Optional[int] = None,
        return_intermediate: bool = False
    ) -> Tuple[np.ndarray, Dict]:
        """
        Remove cardiac artifacts from raw LFP signal using time-domain template subtraction.

        This is the main entry point for cardiac artifact removal. Performs all four steps:
        1. Isolate cardiac signal (bandpass 5-30 Hz)
        2. Detect R-wave peaks
        3. Construct QRS template
        4. Subtract template from raw signal

        Args:
            raw_lfp: Raw LFP signal as numpy array (1D)
            fs: Sampling frequency in Hz (uses self.fs if not provided)
            return_intermediate: If True, returns intermediate processing steps

        Returns:
            Tuple of:
                - np.ndarray: Cleaned LFP signal with cardiac artifacts removed
                - Dict: Processing statistics and quality metrics

        Raises:
            ValueError: If insufficient R-waves detected or signal too short

        Example:
            >>> raw_signal = np.array([...])  # Your raw LFP data
            >>> preprocessor = CardiacArtifactRemoval()
            >>> cleaned_signal, stats = preprocessor.remove_cardiac_artifact(raw_signal)
            >>> print(f"SNR improved by {stats['snr_improvement_db']:.1f} dB")
        """
        if not self.enabled:
            logger.info("Cardiac artifact removal is disabled")
            return raw_lfp, {
                'enabled': False,
                'message': 'Cardiac artifact removal disabled'
            }

        if fs is not None:
            self.fs = fs

        logger.info(f"Starting cardiac artifact removal for signal of length {len(raw_lfp)} samples")

        # Validate input
        if len(raw_lfp) < 1000:
            raise ValueError(f"Signal too short ({len(raw_lfp)} samples). Need at least 1000 samples.")

        # Reset statistics
        self.stats = {
            'r_waves_detected': 0,
            'template_length': 0,
            'heart_rate_bpm': 0.0,
            'power_reduction_theta': 0.0,
            'power_reduction_alpha': 0.0,
            'power_reduction_beta': 0.0,
        }

        intermediate = {} if return_intermediate else None

        # Step 1: Isolate cardiac signal
        logger.debug("Step 1: Isolating cardiac signal (5-30 Hz bandpass)")
        cardiac_signal = self._isolate_cardiac_signal(raw_lfp)
        if return_intermediate:
            intermediate['cardiac_signal'] = cardiac_signal

        # Step 2: Detect R-waves
        logger.debug("Step 2: Detecting R-wave peaks")
        r_wave_indices, peak_props = self._detect_r_waves(cardiac_signal)

        if len(r_wave_indices) < 3:
            logger.warning(f"Insufficient R-waves detected ({len(r_wave_indices)}). Skipping cardiac removal.")
            return raw_lfp, {
                'enabled': True,
                'r_waves_detected': len(r_wave_indices),
                'error': 'Insufficient R-waves detected (need at least 3)',
                'signal_returned': 'original'
            }

        self.stats['r_waves_detected'] = len(r_wave_indices)

        # Calculate heart rate
        ibi = np.diff(r_wave_indices) / self.fs  # Inter-beat intervals in seconds
        heart_rate = 60 / np.mean(ibi)  # BPM
        self.stats['heart_rate_bpm'] = heart_rate
        logger.info(f"Detected {len(r_wave_indices)} R-waves, heart rate: {heart_rate:.1f} BPM")

        if return_intermediate:
            intermediate['r_wave_indices'] = r_wave_indices
            intermediate['peak_properties'] = peak_props

        # Step 3: Construct QRS template
        logger.debug("Step 3: Constructing QRS template")
        qrs_template, valid_r_waves = self._construct_qrs_template(raw_lfp, r_wave_indices)
        self.stats['template_length'] = len(qrs_template)

        if return_intermediate:
            intermediate['qrs_template'] = qrs_template
            intermediate['valid_r_waves'] = valid_r_waves

        # Step 4: Subtract template
        logger.debug("Step 4: Subtracting QRS template from signal")
        cleaned_lfp = self._subtract_qrs_template(raw_lfp, qrs_template, valid_r_waves)

        # Step 5: Validate removal
        logger.debug("Step 5: Validating cardiac artifact removal")
        validation_metrics = self._validate_removal(raw_lfp, cleaned_lfp)
        self.stats.update(validation_metrics)

        # Package results
        results = {
            'enabled': True,
            'method': 'Time-domain template subtraction',
            'reference': 'Sanger et al. 2025',
            'sampling_rate': self.fs,
            **self.stats
        }

        if return_intermediate:
            results['intermediate'] = intermediate

        logger.info(f"Cardiac artifact removal complete: "
                   f"{self.stats['r_waves_detected']} R-waves, "
                   f"{self.stats['power_reduction_theta']:.1f}% theta power reduction")

        return cleaned_lfp, results

    def _isolate_cardiac_signal(self, raw_lfp: np.ndarray) -> np.ndarray:
        """
        Step 1: Isolate cardiac signal using bandpass filter (5-30 Hz).

        QRS complexes have dominant frequency content in 5-30 Hz range,
        which overlaps with neural theta, alpha, and beta bands.

        Args:
            raw_lfp: Raw LFP signal

        Returns:
            Filtered signal in cardiac frequency range (5-30 Hz)
        """
        # Design Butterworth bandpass filter
        nyquist = self.fs / 2
        low_norm = CARDIAC_BAND_LOW / nyquist
        high_norm = CARDIAC_BAND_HIGH / nyquist

        b, a = butter(4, [low_norm, high_norm], btype='band')

        # Apply zero-phase filtering (filtfilt = forward-backward)
        cardiac_signal = filtfilt(b, a, raw_lfp)

        return cardiac_signal

    def _detect_r_waves(self, cardiac_signal: np.ndarray) -> Tuple[np.ndarray, Dict]:
        """
        Step 2: Detect R-wave peaks in cardiac signal.

        Uses adaptive prominence thresholding (2.5 × std) and minimum distance
        constraints (0.5 seconds) to identify R-wave peaks.

        Args:
            cardiac_signal: Bandpass filtered signal (5-30 Hz)

        Returns:
            Tuple of:
                - np.ndarray: Indices of detected R-waves
                - Dict: Peak properties from scipy.signal.find_peaks
        """
        # Detection parameters
        min_peak_distance = int(MIN_PEAK_DISTANCE_SEC * self.fs)
        min_peak_prominence = MIN_PEAK_PROMINENCE_STD * np.std(cardiac_signal)

        # Find peaks
        r_wave_indices, peak_props = find_peaks(
            cardiac_signal,
            distance=min_peak_distance,
            prominence=min_peak_prominence
        )

        logger.debug(f"Detected {len(r_wave_indices)} R-waves using "
                    f"distance={min_peak_distance} samples, "
                    f"prominence={min_peak_prominence:.2f}")

        return r_wave_indices, peak_props

    def _construct_qrs_template(
        self,
        raw_lfp: np.ndarray,
        r_wave_indices: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Step 3: Construct averaged QRS template with Hanning windowing.

        Extracts QRS segments aligned to R-waves, averages them to reduce noise,
        and applies Hanning window to prevent edge artifacts.

        Args:
            raw_lfp: Raw (unfiltered) LFP signal
            r_wave_indices: Sample indices of detected R-waves

        Returns:
            Tuple of:
                - np.ndarray: Averaged QRS template (Hanning windowed)
                - np.ndarray: Valid R-wave indices used (excludes edges)
        """
        qrs_segments = []
        valid_r_waves = []

        # Extract QRS segments aligned to R-wave
        for r_idx in r_wave_indices:
            # Check boundaries
            if (r_idx - TEMPLATE_SAMPLES_BEFORE >= 0) and \
               (r_idx + TEMPLATE_SAMPLES_AFTER < len(raw_lfp)):

                # Extract segment from raw signal (NOT filtered)
                segment = raw_lfp[r_idx - TEMPLATE_SAMPLES_BEFORE:
                                 r_idx + TEMPLATE_SAMPLES_AFTER + 1]
                qrs_segments.append(segment)
                valid_r_waves.append(r_idx)

        if len(qrs_segments) == 0:
            raise ValueError("No valid QRS segments found (check signal boundaries)")

        # Average across all QRS segments
        qrs_template = np.mean(qrs_segments, axis=0)

        # Apply Hanning window to prevent edge artifacts
        template_length = len(qrs_template)
        hanning_window = windows.hann(template_length)
        qrs_template = qrs_template * hanning_window

        logger.debug(f"QRS template constructed from {len(qrs_segments)} segments, "
                    f"length: {template_length} samples ({template_length/self.fs*1000:.1f} ms)")

        return qrs_template, np.array(valid_r_waves)

    def _subtract_qrs_template(
        self,
        raw_lfp: np.ndarray,
        qrs_template: np.ndarray,
        r_wave_indices: np.ndarray
    ) -> np.ndarray:
        """
        Step 4: Subtract QRS template at each R-wave location.

        Performs time-domain subtraction of the averaged QRS template at each
        detected R-wave location to remove cardiac artifact.

        Args:
            raw_lfp: Raw LFP signal
            qrs_template: Averaged QRS template (from _construct_qrs_template)
            r_wave_indices: Valid R-wave locations

        Returns:
            Cleaned LFP signal with cardiac artifacts removed
        """
        # Initialize cleaned signal (copy of raw)
        cleaned_lfp = raw_lfp.copy()

        # Subtract template at each R-wave location
        num_subtractions = 0

        for r_idx in r_wave_indices:
            # Verify boundaries (should already be valid from template construction)
            if (r_idx - TEMPLATE_SAMPLES_BEFORE >= 0) and \
               (r_idx + TEMPLATE_SAMPLES_AFTER < len(raw_lfp)):

                # Subtract template
                start_idx = r_idx - TEMPLATE_SAMPLES_BEFORE
                end_idx = r_idx + TEMPLATE_SAMPLES_AFTER + 1
                cleaned_lfp[start_idx:end_idx] -= qrs_template

                num_subtractions += 1

        # Compute percentage of signal affected
        samples_affected = num_subtractions * len(qrs_template)
        percent_affected = (samples_affected / len(raw_lfp)) * 100

        logger.debug(f"Template subtracted at {num_subtractions} R-wave locations "
                    f"({percent_affected:.1f}% of signal)")

        return cleaned_lfp

    def _validate_removal(self, raw_lfp: np.ndarray, cleaned_lfp: np.ndarray) -> Dict:
        """
        Step 5: Validate cardiac artifact removal using power spectral analysis.

        Computes power reduction in cardiac-affected frequency bands (theta, alpha, beta)
        and SNR improvement to validate efficacy of cardiac artifact removal.

        Args:
            raw_lfp: Original raw LFP signal
            cleaned_lfp: Cleaned LFP signal after cardiac removal

        Returns:
            Dict with validation metrics:
                - power_reduction_theta: % power reduction in 4-8 Hz
                - power_reduction_alpha: % power reduction in 8-12 Hz
                - power_reduction_beta: % power reduction in 12-30 Hz
                - power_reduction_gamma: % change in 30-50 Hz (should be minimal)
                - snr_improvement_db: SNR improvement in dB
        """
        # Compute PSD before and after
        freqs, psd_raw = welch(raw_lfp, fs=self.fs, nperseg=min(512, len(raw_lfp)//4), noverlap=256)
        freqs, psd_clean = welch(cleaned_lfp, fs=self.fs, nperseg=min(512, len(cleaned_lfp)//4), noverlap=256)

        # Define frequency bands
        bands = {
            'theta': (4, 8),
            'alpha': (8, 12),
            'beta': (12, 30),
            'gamma': (30, 50)
        }

        metrics = {}

        for band_name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs <= high)

            if np.sum(mask) == 0:
                metrics[f'power_reduction_{band_name}'] = 0.0
                continue

            power_raw = np.mean(psd_raw[mask])
            power_clean = np.mean(psd_clean[mask])

            if power_raw > 0:
                reduction_percent = (1 - power_clean / power_raw) * 100
            else:
                reduction_percent = 0.0

            metrics[f'power_reduction_{band_name}'] = reduction_percent

        # Compute SNR improvement
        # Assume gamma band (30-50 Hz) is less affected by cardiac, use as "signal"
        # Theta-beta (4-30 Hz) contains cardiac contamination, use as "noise"
        gamma_mask = (freqs >= 30) & (freqs <= 50)
        theta_beta_mask = (freqs >= 4) & (freqs <= 30)

        if np.sum(gamma_mask) > 0 and np.sum(theta_beta_mask) > 0:
            snr_raw = np.mean(psd_raw[gamma_mask]) / np.mean(psd_raw[theta_beta_mask])
            snr_clean = np.mean(psd_clean[gamma_mask]) / np.mean(psd_clean[theta_beta_mask])

            if snr_raw > 0:
                snr_improvement_db = 10 * np.log10(snr_clean / snr_raw)
            else:
                snr_improvement_db = 0.0
        else:
            snr_improvement_db = 0.0

        metrics['snr_improvement_db'] = snr_improvement_db

        return metrics

    def preprocess_streaming_waveform(
        self,
        waveform_data_json: str,
        fs: Optional[int] = None
    ) -> Tuple[str, Dict]:
        """
        Preprocess streaming waveform data (convenience method for StreamingRecord).

        Takes waveform data as JSON string (as stored in StreamingRecord.waveform_data),
        performs cardiac artifact removal, and returns cleaned waveform as JSON string.

        Args:
            waveform_data_json: JSON string of waveform samples (e.g., "[20.4, 20.1, ...]")
            fs: Sampling frequency in Hz (uses self.fs if not provided)

        Returns:
            Tuple of:
                - str: Cleaned waveform data as JSON string
                - Dict: Processing statistics

        Example:
            >>> preprocessor = CardiacArtifactRemoval()
            >>> record = StreamingRecord(...)
            >>> cleaned_json, stats = preprocessor.preprocess_streaming_waveform(
            ...     record.waveform_data, fs=record.sample_rate
            ... )
            >>> record.waveform_data = cleaned_json
            >>> record.processing_applied.append('cardiac_removal')
        """
        if not self.enabled:
            return waveform_data_json, {'enabled': False}

        # Parse JSON to numpy array
        try:
            waveform = np.array(json.loads(waveform_data_json), dtype=np.float64)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse waveform data JSON: {e}")
            return waveform_data_json, {'error': f'JSON parse error: {e}'}

        # Remove cardiac artifacts
        cleaned_waveform, stats = self.remove_cardiac_artifact(waveform, fs=fs)

        # Convert back to JSON
        cleaned_json = json.dumps(cleaned_waveform.tolist())

        return cleaned_json, stats


def validate_cardiac_removal(
    raw_lfp: np.ndarray,
    cleaned_lfp: np.ndarray,
    fs: int = DEFAULT_SAMPLING_RATE,
    expected_theta_reduction: float = 20.0,
    expected_alpha_reduction: float = 20.0,
    expected_beta_reduction: float = 20.0,
    max_gamma_change: float = 10.0,
    min_snr_improvement: float = 1.0
) -> Tuple[bool, Dict]:
    """
    Validate that cardiac artifact removal was effective.

    Checks multiple criteria:
    1. Theta/alpha/beta power reduced by at least 20% (default)
    2. Gamma band minimally affected (<10% change)
    3. SNR improved by at least 1 dB

    Args:
        raw_lfp: Original raw LFP signal
        cleaned_lfp: Cleaned LFP signal after cardiac removal
        fs: Sampling frequency in Hz
        expected_theta_reduction: Minimum expected theta power reduction (%)
        expected_alpha_reduction: Minimum expected alpha power reduction (%)
        expected_beta_reduction: Minimum expected beta power reduction (%)
        max_gamma_change: Maximum allowed gamma band change (%)
        min_snr_improvement: Minimum expected SNR improvement (dB)

    Returns:
        Tuple of:
            - bool: True if all validation checks pass
            - Dict: Detailed validation results

    Example:
        >>> car = CardiacArtifactRemoval()
        >>> cleaned, _ = car.remove_cardiac_artifact(raw_signal)
        >>> passed, results = validate_cardiac_removal(raw_signal, cleaned)
        >>> if passed:
        ...     print("Cardiac removal successful!")
        ... else:
        ...     print(f"Failed checks: {results['failed_checks']}")
    """
    # Compute validation metrics
    car = CardiacArtifactRemoval(enabled=True, fs=fs)
    metrics = car._validate_removal(raw_lfp, cleaned_lfp)

    # Check criteria
    checks = {
        'theta_reduction': metrics['power_reduction_theta'] >= expected_theta_reduction,
        'alpha_reduction': metrics['power_reduction_alpha'] >= expected_alpha_reduction,
        'beta_reduction': metrics['power_reduction_beta'] >= expected_beta_reduction,
        'gamma_preserved': abs(metrics['power_reduction_gamma']) <= max_gamma_change,
        'snr_improved': metrics['snr_improvement_db'] >= min_snr_improvement
    }

    all_passed = all(checks.values())
    failed_checks = [name for name, passed in checks.items() if not passed]

    results = {
        'all_passed': all_passed,
        'checks': checks,
        'failed_checks': failed_checks,
        'metrics': metrics,
        'criteria': {
            'expected_theta_reduction': expected_theta_reduction,
            'expected_alpha_reduction': expected_alpha_reduction,
            'expected_beta_reduction': expected_beta_reduction,
            'max_gamma_change': max_gamma_change,
            'min_snr_improvement': min_snr_improvement
        }
    }

    return all_passed, results
