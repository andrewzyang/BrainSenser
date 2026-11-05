"""
Streaming Artifact Detector - Detect obvious artifacts in streaming waveform data.

Implements automatic detection of common artifacts in BrainSense streaming data:
- Saturation (ADC limits)
- Statistical outliers
- Flat-lining (sensor disconnection)
- Large jumps (movement artifacts)
- Invalid values (NaN, Inf)

This is pure domain logic with no Qt dependencies, fully testable.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ArtifactDetectionConfig:
    """
    Configuration for artifact detection.

    All thresholds can be tuned based on data characteristics.
    """

    # Saturation detection (percentile-based)
    saturation_percentile: float = 99.9  # Top 0.1% considered saturation

    # Outlier detection (z-score based)
    outlier_std_threshold: float = 5.0  # Values > 5 std from mean

    # Flatline detection (consecutive identical values)
    flatline_min_consecutive: int = 5  # 5+ identical values = artifact
    flatline_tolerance: float = 1e-6  # Tolerance for "identical" (floating point)

    # Jump detection (absolute change between samples)
    jump_threshold: float = 1000.0  # Microvolts - sudden jumps

    # High-frequency noise detection (requires scipy)
    highfreq_cutoff: float = 100.0  # Hz - frequencies above this are noise
    highfreq_power_threshold: float = 2.0  # Power ratio threshold (vs total power)

    # Line noise detection (60 Hz and harmonics)
    line_freq: float = 60.0  # Hz - power line frequency (60 Hz US, 50 Hz EU)
    line_noise_threshold: float = 3.0  # Power ratio threshold for 60 Hz

    # Non-stationarity detection (variance changes)
    nonstationarity_window_sec: float = 1.0  # Window size in seconds
    nonstationarity_threshold: float = 3.0  # Variance ratio threshold

    # Cross-channel coherence (requires multiple channels)
    coherence_threshold: float = 0.3  # Low coherence = isolated artifact

    # Enable/disable individual detectors
    detect_saturation: bool = True
    detect_outliers: bool = True
    detect_flatline: bool = True
    detect_jumps: bool = True
    detect_invalid: bool = True  # NaN, Inf
    detect_highfreq_noise: bool = False  # Requires scipy
    detect_line_noise: bool = False  # Requires scipy
    detect_nonstationarity: bool = False
    detect_low_coherence: bool = False  # Requires multiple channels


class StreamingArtifactDetector:
    """
    Detect obvious artifacts in streaming waveform data.

    This detector identifies common artifact patterns in iEEG/LFP data:

    Core Detectors (always available):
    1. Invalid: NaN or Inf values
    2. Saturation: Values at/near ADC limits (percentile-based)
    3. Outliers: Statistical anomalies (z-score > threshold)
    4. Flatline: Consecutive identical values (sensor disconnection)
    5. Jumps: Large instantaneous changes (movement artifacts)

    Advanced Detectors (optional, require scipy):
    6. High-Frequency Noise: Excessive power >100 Hz (EMG contamination)
    7. Line Noise: 60 Hz power line interference and harmonics
    8. Non-Stationarity: Sudden variance changes (noise bursts)
    9. Low Coherence: Channel-specific artifacts (requires multi-channel)

    Returns a boolean mask where True indicates artifact.

    Example:
        >>> detector = StreamingArtifactDetector()
        >>> artifact_mask = detector.detect_artifacts(waveform_data, sampling_rate)
        >>> print(f"Found {np.sum(artifact_mask)} artifact samples")
    """

    def __init__(self, config: Optional[ArtifactDetectionConfig] = None):
        """
        Initialize artifact detector.

        Args:
            config: Detection configuration (uses defaults if None)
        """
        self.config = config or ArtifactDetectionConfig()
        logger.info(f"StreamingArtifactDetector initialized with config: {self.config}")

    def detect_artifacts(
        self,
        waveform_data: np.ndarray,
        sampling_rate: float,
        config: Optional[ArtifactDetectionConfig] = None
    ) -> np.ndarray:
        """
        Detect artifacts in waveform data.

        Args:
            waveform_data: 2D array (samples × channels) or 1D array (samples)
            sampling_rate: Sampling rate in Hz (for future time-based detectors)
            config: Optional config override (uses instance config if None)

        Returns:
            Boolean mask (samples × channels) where True = artifact detected

        Raises:
            ValueError: If waveform_data is empty or invalid
        """
        # Use provided config or fall back to instance config
        cfg = config or self.config

        # Validate input
        if waveform_data is None or waveform_data.size == 0:
            raise ValueError("waveform_data cannot be empty")

        # Handle 1D arrays (single channel)
        if waveform_data.ndim == 1:
            waveform_data = waveform_data.reshape(-1, 1)

        # Initialize artifact mask (all False)
        artifact_mask = np.zeros(waveform_data.shape, dtype=bool)

        logger.info(f"Starting artifact detection on {waveform_data.shape[0]} samples × {waveform_data.shape[1]} channels")

        # Run detectors (combine with OR logic)
        if cfg.detect_invalid:
            invalid_mask = self._detect_invalid_values(waveform_data)
            artifact_mask |= invalid_mask
            logger.debug(f"Invalid values detected: {np.sum(invalid_mask)}")

        if cfg.detect_saturation:
            saturation_mask = self._detect_saturation(waveform_data, cfg.saturation_percentile)
            artifact_mask |= saturation_mask
            logger.debug(f"Saturation artifacts detected: {np.sum(saturation_mask)}")

        if cfg.detect_outliers:
            outlier_mask = self._detect_outliers(waveform_data, cfg.outlier_std_threshold)
            artifact_mask |= outlier_mask
            logger.debug(f"Outlier artifacts detected: {np.sum(outlier_mask)}")

        if cfg.detect_flatline:
            flatline_mask = self._detect_flatline(
                waveform_data,
                cfg.flatline_min_consecutive,
                cfg.flatline_tolerance
            )
            artifact_mask |= flatline_mask
            logger.debug(f"Flatline artifacts detected: {np.sum(flatline_mask)}")

        if cfg.detect_jumps:
            jump_mask = self._detect_jumps(waveform_data, cfg.jump_threshold)
            artifact_mask |= jump_mask
            logger.debug(f"Jump artifacts detected: {np.sum(jump_mask)}")

        # Advanced detectors (optional)
        if cfg.detect_highfreq_noise:
            try:
                highfreq_mask = self._detect_highfreq_noise(
                    waveform_data,
                    sampling_rate,
                    cfg.highfreq_cutoff,
                    cfg.highfreq_power_threshold
                )
                artifact_mask |= highfreq_mask
                logger.debug(f"High-frequency noise artifacts detected: {np.sum(highfreq_mask)}")
            except ImportError:
                logger.warning("scipy not available, skipping high-frequency noise detection")

        if cfg.detect_line_noise:
            try:
                line_noise_mask = self._detect_line_noise(
                    waveform_data,
                    sampling_rate,
                    cfg.line_freq,
                    cfg.line_noise_threshold
                )
                artifact_mask |= line_noise_mask
                logger.debug(f"Line noise artifacts detected: {np.sum(line_noise_mask)}")
            except ImportError:
                logger.warning("scipy not available, skipping line noise detection")

        if cfg.detect_nonstationarity:
            nonstationarity_mask = self._detect_nonstationarity(
                waveform_data,
                sampling_rate,
                cfg.nonstationarity_window_sec,
                cfg.nonstationarity_threshold
            )
            artifact_mask |= nonstationarity_mask
            logger.debug(f"Non-stationarity artifacts detected: {np.sum(nonstationarity_mask)}")

        if cfg.detect_low_coherence and waveform_data.shape[1] > 1:
            coherence_mask = self._detect_low_coherence(
                waveform_data,
                cfg.coherence_threshold
            )
            artifact_mask |= coherence_mask
            logger.debug(f"Low coherence artifacts detected: {np.sum(coherence_mask)}")

        total_artifacts = np.sum(artifact_mask)
        total_samples = artifact_mask.size
        artifact_rate = (total_artifacts / total_samples * 100) if total_samples > 0 else 0

        logger.info(f"Artifact detection complete: {total_artifacts:,} / {total_samples:,} samples ({artifact_rate:.2f}%)")

        return artifact_mask

    def _detect_invalid_values(self, data: np.ndarray) -> np.ndarray:
        """
        Detect NaN and Inf values.

        Args:
            data: Waveform data array

        Returns:
            Boolean mask where True = invalid value
        """
        return np.isnan(data) | np.isinf(data)

    def _detect_saturation(self, data: np.ndarray, percentile: float) -> np.ndarray:
        """
        Detect saturation artifacts (values at/near ADC limits).

        Uses percentile-based approach: values above the Nth percentile
        are considered saturation artifacts.

        Args:
            data: Waveform data array
            percentile: Percentile threshold (e.g., 99.9 for top 0.1%)

        Returns:
            Boolean mask where True = saturation artifact
        """
        # Calculate per-channel thresholds (handle NaN values)
        saturation_mask = np.zeros(data.shape, dtype=bool)

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]
            valid_data = channel_data[~np.isnan(channel_data)]

            if valid_data.size > 0:
                # Calculate saturation threshold
                threshold = np.percentile(valid_data, percentile)

                # Mark values above threshold as artifacts
                saturation_mask[:, ch_idx] = channel_data >= threshold

        return saturation_mask

    def _detect_outliers(self, data: np.ndarray, n_std: float) -> np.ndarray:
        """
        Detect statistical outliers (z-score > threshold).

        Uses per-channel z-score: (value - mean) / std

        Args:
            data: Waveform data array
            n_std: Z-score threshold (e.g., 5.0 for 5 std from mean)

        Returns:
            Boolean mask where True = outlier artifact
        """
        outlier_mask = np.zeros(data.shape, dtype=bool)

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]
            valid_data = channel_data[~np.isnan(channel_data)]

            if valid_data.size > 0 and np.std(valid_data) > 0:
                # Calculate z-scores
                mean = np.mean(valid_data)
                std = np.std(valid_data)
                z_scores = np.abs((channel_data - mean) / std)

                # Mark outliers
                outlier_mask[:, ch_idx] = z_scores > n_std

        return outlier_mask

    def _detect_flatline(
        self,
        data: np.ndarray,
        min_consecutive: int,
        tolerance: float
    ) -> np.ndarray:
        """
        Detect flat-lining artifacts (consecutive identical values).

        Indicates sensor disconnection or hardware failure.

        Args:
            data: Waveform data array
            min_consecutive: Minimum consecutive identical values to flag
            tolerance: Tolerance for "identical" (for floating point comparison)

        Returns:
            Boolean mask where True = flatline artifact
        """
        flatline_mask = np.zeros(data.shape, dtype=bool)

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]

            # Find consecutive identical values
            # Calculate absolute differences between consecutive samples
            diffs = np.abs(np.diff(channel_data))
            is_identical = diffs < tolerance

            # Find runs of consecutive identical values
            run_length = 1
            for i in range(len(is_identical)):
                if is_identical[i]:
                    run_length += 1
                    if run_length >= min_consecutive:
                        # Mark this run as artifact (from start to current)
                        start_idx = i - run_length + 2
                        end_idx = i + 2
                        flatline_mask[start_idx:end_idx, ch_idx] = True
                else:
                    run_length = 1

        return flatline_mask

    def _detect_jumps(self, data: np.ndarray, threshold: float) -> np.ndarray:
        """
        Detect large instantaneous jumps (movement artifacts).

        Args:
            data: Waveform data array
            threshold: Jump threshold in same units as data (e.g., microvolts)

        Returns:
            Boolean mask where True = jump artifact
        """
        jump_mask = np.zeros(data.shape, dtype=bool)

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]

            # Calculate absolute differences between consecutive samples
            diffs = np.abs(np.diff(channel_data))

            # Mark samples with large jumps
            # Note: marks the sample AFTER the jump
            jump_indices = np.where(diffs > threshold)[0] + 1
            jump_mask[jump_indices, ch_idx] = True

            # Also mark the sample BEFORE the jump (optional - can tune this)
            if len(jump_indices) > 0:
                jump_mask[jump_indices - 1, ch_idx] = True

        return jump_mask

    def _detect_highfreq_noise(
        self,
        data: np.ndarray,
        sampling_rate: float,
        cutoff_freq: float,
        power_threshold: float
    ) -> np.ndarray:
        """
        Detect high-frequency noise artifacts (EMG contamination).

        For LFP data, physiological signals are typically <80 Hz.
        Excessive power >100 Hz indicates muscle/electrical noise.

        Requires scipy for filtering.

        Args:
            data: Waveform data array
            sampling_rate: Sampling rate in Hz
            cutoff_freq: High-pass cutoff frequency (e.g., 100 Hz)
            power_threshold: Power ratio threshold (highfreq/total)

        Returns:
            Boolean mask where True = high-frequency noise artifact
        """
        from scipy import signal

        highfreq_mask = np.zeros(data.shape, dtype=bool)

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]

            # Skip if all NaN
            if np.all(np.isnan(channel_data)):
                continue

            # Design high-pass filter
            nyquist = sampling_rate / 2
            if cutoff_freq >= nyquist:
                logger.warning(f"Cutoff frequency {cutoff_freq} >= Nyquist {nyquist}, skipping highfreq detection")
                continue

            # Butterworth high-pass filter
            sos = signal.butter(4, cutoff_freq / nyquist, btype='highpass', output='sos')

            # Apply filter to get high-frequency component
            try:
                highfreq_component = signal.sosfilt(sos, channel_data)
            except Exception as e:
                logger.warning(f"High-frequency filtering failed for channel {ch_idx}: {e}")
                continue

            # Calculate power in high-frequency band vs. total power
            np.var(channel_data[~np.isnan(channel_data)])
            np.var(highfreq_component[~np.isnan(highfreq_component)])

            # Use sliding window to detect local high-frequency bursts
            window_size = int(sampling_rate * 0.5)  # 500 ms windows
            if window_size < 10:
                window_size = 10

            for i in range(0, len(highfreq_component) - window_size, window_size // 2):
                window = highfreq_component[i:i + window_size]
                window_power = np.var(window[~np.isnan(window)])
                window_total_power = np.var(channel_data[i:i + window_size])

                # Flag if high-frequency power is excessive
                if window_total_power > 0:
                    power_ratio = window_power / window_total_power
                    if power_ratio > power_threshold:
                        highfreq_mask[i:i + window_size, ch_idx] = True

        return highfreq_mask

    def _detect_line_noise(
        self,
        data: np.ndarray,
        sampling_rate: float,
        line_freq: float,
        power_threshold: float
    ) -> np.ndarray:
        """
        Detect 60 Hz power line noise and harmonics.

        Checks for abnormally high power at 60 Hz, 120 Hz, 180 Hz.

        Requires scipy for spectral analysis.

        Args:
            data: Waveform data array
            sampling_rate: Sampling rate in Hz
            line_freq: Power line frequency (60 Hz US, 50 Hz EU)
            power_threshold: Power threshold (relative to broadband)

        Returns:
            Boolean mask where True = line noise artifact
        """
        from scipy import signal

        line_noise_mask = np.zeros(data.shape, dtype=bool)

        # Check harmonics: 60, 120, 180 Hz
        harmonics = [line_freq, line_freq * 2, line_freq * 3]

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]

            # Skip if all NaN
            if np.all(np.isnan(channel_data)):
                continue

            # Use Welch's method for power spectral density
            try:
                freqs, psd = signal.welch(
                    channel_data[~np.isnan(channel_data)],
                    fs=sampling_rate,
                    nperseg=min(1024, len(channel_data) // 4)
                )
            except Exception as e:
                logger.warning(f"PSD calculation failed for channel {ch_idx}: {e}")
                continue

            # Calculate broadband power (excluding harmonics)
            broadband_mask = np.ones(len(freqs), dtype=bool)
            for harmonic in harmonics:
                # Exclude ±2 Hz around each harmonic
                broadband_mask &= (np.abs(freqs - harmonic) > 2.0)

            broadband_power = np.mean(psd[broadband_mask])

            # Check power at each harmonic
            has_line_noise = False
            for harmonic in harmonics:
                if harmonic > sampling_rate / 2:
                    break  # Above Nyquist

                # Find power at harmonic (±1 Hz window)
                harmonic_idx = np.argmin(np.abs(freqs - harmonic))
                harmonic_power = psd[harmonic_idx]

                # Flag if harmonic power is excessive
                if broadband_power > 0:
                    power_ratio = harmonic_power / broadband_power
                    if power_ratio > power_threshold:
                        has_line_noise = True
                        break

            # If line noise detected, flag entire channel
            # (could be more sophisticated with time-frequency analysis)
            if has_line_noise:
                line_noise_mask[:, ch_idx] = True

        return line_noise_mask

    def _detect_nonstationarity(
        self,
        data: np.ndarray,
        sampling_rate: float,
        window_sec: float,
        variance_threshold: float
    ) -> np.ndarray:
        """
        Detect non-stationarity artifacts (sudden variance changes).

        Neural signals have relatively stable variance over short windows.
        Sudden variance changes indicate transient noise bursts.

        Args:
            data: Waveform data array
            sampling_rate: Sampling rate in Hz
            window_sec: Window size in seconds for variance calculation
            variance_threshold: Variance ratio threshold (current/median)

        Returns:
            Boolean mask where True = non-stationarity artifact
        """
        nonstationarity_mask = np.zeros(data.shape, dtype=bool)

        window_samples = int(window_sec * sampling_rate)
        if window_samples < 10:
            window_samples = 10

        for ch_idx in range(data.shape[1]):
            channel_data = data[:, ch_idx]

            # Calculate rolling variance
            variances = []
            for i in range(0, len(channel_data) - window_samples, window_samples // 2):
                window = channel_data[i:i + window_samples]
                valid_window = window[~np.isnan(window)]
                if len(valid_window) > 5:
                    variances.append((i, np.var(valid_window)))

            if len(variances) < 2:
                continue

            # Calculate median variance (baseline)
            median_variance = np.median([v for _, v in variances])

            if median_variance == 0:
                continue

            # Flag windows with excessive variance
            for window_start, window_var in variances:
                variance_ratio = window_var / median_variance

                if variance_ratio > variance_threshold:
                    # Flag this window as artifact
                    window_end = min(window_start + window_samples, len(channel_data))
                    nonstationarity_mask[window_start:window_end, ch_idx] = True

        return nonstationarity_mask

    def _detect_low_coherence(
        self,
        data: np.ndarray,
        coherence_threshold: float
    ) -> np.ndarray:
        """
        Detect low cross-channel coherence artifacts.

        True neural activity often appears across multiple channels.
        Isolated spikes in single channels are likely artifacts.

        Requires multiple channels (>1).

        Args:
            data: Waveform data array (samples × channels)
            coherence_threshold: Low coherence threshold (0-1)

        Returns:
            Boolean mask where True = low coherence artifact
        """
        if data.shape[1] < 2:
            # Need at least 2 channels for coherence
            return np.zeros(data.shape, dtype=bool)

        coherence_mask = np.zeros(data.shape, dtype=bool)

        # Use sliding window correlation approach
        window_size = min(100, data.shape[0] // 10)
        if window_size < 10:
            window_size = 10

        for i in range(0, data.shape[0] - window_size, window_size // 2):
            window = data[i:i + window_size, :]

            # Calculate pairwise correlations between channels
            for ch_idx in range(data.shape[1]):
                channel_data = window[:, ch_idx]

                # Calculate correlation with all other channels
                correlations = []
                for other_ch in range(data.shape[1]):
                    if other_ch == ch_idx:
                        continue

                    other_data = window[:, other_ch]

                    # Remove NaN values
                    valid_mask = ~(np.isnan(channel_data) | np.isnan(other_data))
                    if np.sum(valid_mask) < 10:
                        continue

                    # Calculate correlation
                    try:
                        corr = np.corrcoef(
                            channel_data[valid_mask],
                            other_data[valid_mask]
                        )[0, 1]
                        if not np.isnan(corr):
                            correlations.append(abs(corr))
                    except Exception:
                        continue

                # If average correlation is low, flag as artifact
                if correlations and np.mean(correlations) < coherence_threshold:
                    coherence_mask[i:i + window_size, ch_idx] = True

        return coherence_mask

    def get_artifact_summary(self, artifact_mask: np.ndarray) -> dict:
        """
        Generate summary statistics for artifact detection results.

        Args:
            artifact_mask: Boolean artifact mask

        Returns:
            Dictionary with artifact statistics
        """
        total_samples = artifact_mask.size
        total_artifacts = np.sum(artifact_mask)
        artifact_rate = (total_artifacts / total_samples * 100) if total_samples > 0 else 0

        # Per-channel statistics
        channel_stats = []
        for ch_idx in range(artifact_mask.shape[1]):
            ch_artifacts = np.sum(artifact_mask[:, ch_idx])
            ch_samples = artifact_mask.shape[0]
            ch_rate = (ch_artifacts / ch_samples * 100) if ch_samples > 0 else 0

            channel_stats.append({
                'channel': ch_idx,
                'artifacts': int(ch_artifacts),
                'samples': ch_samples,
                'artifact_rate': float(ch_rate)
            })

        summary = {
            'total_samples': total_samples,
            'total_artifacts': int(total_artifacts),
            'artifact_rate': float(artifact_rate),
            'num_channels': artifact_mask.shape[1],
            'num_timepoints': artifact_mask.shape[0],
            'channel_stats': channel_stats
        }

        return summary
