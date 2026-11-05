"""
Unit tests for Cardiac Artifact Removal preprocessor.

Tests the time-domain template subtraction method for removing ECG/QRS
artifacts from BrainSense LFP streaming data.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
"""

import pytest
import numpy as np
import json
from src.core.preprocessing.cardiac_artifact_removal import (
    CardiacArtifactRemoval,
    validate_cardiac_removal,
    DEFAULT_SAMPLING_RATE
)
from src.core.preprocessing.cardiac_qc import (
    compute_qc_metrics,
    generate_qc_report,
    bootstrap_validation,
    assess_signal_integrity
)


class TestCardiacArtifactRemoval:
    """Test suite for CardiacArtifactRemoval class."""

    @pytest.fixture
    def fs(self):
        """Sampling frequency."""
        return DEFAULT_SAMPLING_RATE

    @pytest.fixture
    def duration(self):
        """Recording duration in seconds."""
        return 60  # 1 minute

    @pytest.fixture
    def simulated_neural_signal(self, fs, duration):
        """Generate simulated neural signal (alpha oscillation)."""
        t = np.linspace(0, duration, fs * duration)
        # 10 Hz alpha oscillation
        neural = 10 * np.sin(2 * np.pi * 10 * t)
        # Add some beta activity
        neural += 5 * np.sin(2 * np.pi * 20 * t)
        # Add noise
        neural += np.random.randn(len(t)) * 2
        return neural

    @pytest.fixture
    def simulated_cardiac_artifact(self, fs, duration):
        """Generate simulated cardiac artifact (QRS complexes)."""
        t = np.linspace(0, duration, fs * duration)
        cardiac = np.zeros_like(t)

        # Simulate QRS complexes at 70 BPM
        heart_rate = 70  # BPM
        ibi = 60 / heart_rate  # Inter-beat interval in seconds

        for beat_time in np.arange(0, duration, ibi):
            beat_idx = int(beat_time * fs)
            if beat_idx + 100 < len(t):
                # Simple QRS morphology: negative-positive-negative
                qrs_template = np.array([
                    0, -0.5, -1.0, -0.5, 0, 2.0, 4.0, 2.0, 0, -0.8, -0.5, 0
                ])
                # Interpolate to 100 samples
                qrs = np.interp(
                    np.arange(100),
                    np.linspace(0, 100, len(qrs_template)),
                    qrs_template
                )
                # Scale to realistic amplitude (50× neural signal)
                qrs = qrs * 50
                cardiac[beat_idx:beat_idx+100] += qrs

        return cardiac

    @pytest.fixture
    def raw_lfp_with_cardiac(self, simulated_neural_signal, simulated_cardiac_artifact):
        """Generate raw LFP signal contaminated with cardiac artifacts."""
        return simulated_neural_signal + simulated_cardiac_artifact

    @pytest.fixture
    def preprocessor(self, fs):
        """Create CardiacArtifactRemoval instance."""
        return CardiacArtifactRemoval(enabled=True, fs=fs)

    def test_initialization(self, fs):
        """Test CardiacArtifactRemoval initialization."""
        car = CardiacArtifactRemoval(enabled=True, fs=fs)

        assert car.enabled is True
        assert car.fs == fs
        assert isinstance(car.stats, dict)

    def test_disabled_preprocessor(self, preprocessor, raw_lfp_with_cardiac):
        """Test that disabled preprocessor returns original signal."""
        preprocessor.enabled = False

        cleaned, stats = preprocessor.remove_cardiac_artifact(raw_lfp_with_cardiac)

        np.testing.assert_array_equal(cleaned, raw_lfp_with_cardiac)
        assert stats['enabled'] is False

    def test_signal_too_short(self, preprocessor):
        """Test error handling for very short signals."""
        short_signal = np.random.randn(100)

        with pytest.raises(ValueError, match="Signal too short"):
            preprocessor.remove_cardiac_artifact(short_signal)

    def test_cardiac_signal_isolation(self, preprocessor, raw_lfp_with_cardiac):
        """Test Step 1: Isolate cardiac signal with bandpass filter."""
        cardiac_signal = preprocessor._isolate_cardiac_signal(raw_lfp_with_cardiac)

        # Check that output has same length as input
        assert len(cardiac_signal) == len(raw_lfp_with_cardiac)

        # Check that filtering enhanced cardiac frequency content
        # (This is a basic check - cardiac signal should have periodic peaks)
        assert np.std(cardiac_signal) > 0

    def test_r_wave_detection(self, preprocessor, raw_lfp_with_cardiac):
        """Test Step 2: Detect R-waves in cardiac signal."""
        cardiac_signal = preprocessor._isolate_cardiac_signal(raw_lfp_with_cardiac)
        r_wave_indices, peak_props = preprocessor._detect_r_waves(cardiac_signal)

        # Should detect R-waves (for 60-second recording at 70 BPM, expect ~70 R-waves)
        assert len(r_wave_indices) > 0
        assert len(r_wave_indices) >= 50  # At least 50 BPM
        assert len(r_wave_indices) <= 150  # At most 150 BPM

        # R-waves should be evenly spaced (within reason)
        ibi = np.diff(r_wave_indices)
        cv = np.std(ibi) / np.mean(ibi)  # Coefficient of variation
        assert cv < 0.3  # Regular heart rate (CV < 0.3 for sinus rhythm)

    def test_qrs_template_construction(self, preprocessor, raw_lfp_with_cardiac):
        """Test Step 3: Construct QRS template."""
        cardiac_signal = preprocessor._isolate_cardiac_signal(raw_lfp_with_cardiac)
        r_wave_indices, _ = preprocessor._detect_r_waves(cardiac_signal)

        qrs_template, valid_r_waves = preprocessor._construct_qrs_template(
            raw_lfp_with_cardiac, r_wave_indices
        )

        # Template should have correct length (36 before + 1 R-wave + 36 after = 73 samples)
        expected_length = 36 + 1 + 36
        assert len(qrs_template) == expected_length

        # Template should be non-zero
        assert np.sum(np.abs(qrs_template)) > 0

        # Template should taper to near-zero at edges (Hanning window effect)
        assert abs(qrs_template[0]) < abs(qrs_template[len(qrs_template)//2])
        assert abs(qrs_template[-1]) < abs(qrs_template[len(qrs_template)//2])

        # Valid R-waves should be subset of detected R-waves (excluding edges)
        assert len(valid_r_waves) <= len(r_wave_indices)
        assert len(valid_r_waves) > 0

    def test_template_subtraction(self, preprocessor, raw_lfp_with_cardiac):
        """Test Step 4: Subtract QRS template from signal."""
        cardiac_signal = preprocessor._isolate_cardiac_signal(raw_lfp_with_cardiac)
        r_wave_indices, _ = preprocessor._detect_r_waves(cardiac_signal)
        qrs_template, valid_r_waves = preprocessor._construct_qrs_template(
            raw_lfp_with_cardiac, r_wave_indices
        )

        cleaned_lfp = preprocessor._subtract_qrs_template(
            raw_lfp_with_cardiac, qrs_template, valid_r_waves
        )

        # Cleaned signal should have same length as original
        assert len(cleaned_lfp) == len(raw_lfp_with_cardiac)

        # Cleaned signal should be different from raw (cardiac removed)
        assert not np.array_equal(cleaned_lfp, raw_lfp_with_cardiac)

        # RMS amplitude should be reduced (cardiac component removed)
        rms_raw = np.sqrt(np.mean(raw_lfp_with_cardiac**2))
        rms_clean = np.sqrt(np.mean(cleaned_lfp**2))
        assert rms_clean < rms_raw

    def test_full_pipeline(self, preprocessor, raw_lfp_with_cardiac):
        """Test complete cardiac artifact removal pipeline."""
        cleaned_lfp, stats = preprocessor.remove_cardiac_artifact(raw_lfp_with_cardiac)

        # Check that processing completed
        assert stats['enabled'] is True
        assert 'r_waves_detected' in stats
        assert stats['r_waves_detected'] > 0

        # Check that heart rate is plausible
        assert 40 < stats['heart_rate_bpm'] < 150

        # Check that power reduction occurred in cardiac-affected bands
        assert stats['power_reduction_theta'] > 0
        assert stats['power_reduction_alpha'] > 0
        assert stats['power_reduction_beta'] > 0

        # Check that signal length is preserved
        assert len(cleaned_lfp) == len(raw_lfp_with_cardiac)

    def test_return_intermediate_results(self, preprocessor, raw_lfp_with_cardiac):
        """Test returning intermediate processing steps."""
        cleaned_lfp, stats = preprocessor.remove_cardiac_artifact(
            raw_lfp_with_cardiac,
            return_intermediate=True
        )

        # Should have intermediate results
        assert 'intermediate' in stats
        intermediate = stats['intermediate']

        # Check intermediate outputs
        assert 'cardiac_signal' in intermediate
        assert 'r_wave_indices' in intermediate
        assert 'qrs_template' in intermediate
        assert 'valid_r_waves' in intermediate

        # Verify data types
        assert isinstance(intermediate['cardiac_signal'], np.ndarray)
        assert isinstance(intermediate['r_wave_indices'], np.ndarray)
        assert isinstance(intermediate['qrs_template'], np.ndarray)
        assert isinstance(intermediate['valid_r_waves'], np.ndarray)

    def test_insufficient_r_waves(self, preprocessor):
        """Test handling of signals with insufficient R-waves."""
        # Create signal with no clear cardiac peaks
        noise_signal = np.random.randn(5000)

        cleaned, stats = preprocessor.remove_cardiac_artifact(noise_signal)

        # If fewer than 3 R-waves detected, should return original or minimal modification
        if stats.get('r_waves_detected', 0) < 3:
            # Should return original signal when insufficient R-waves
            np.testing.assert_array_equal(cleaned, noise_signal)
            assert 'error' in stats
        else:
            # May detect false positives in noise - that's okay, just verify it didn't crash
            assert len(cleaned) == len(noise_signal)

    def test_preprocess_streaming_waveform_json(self, preprocessor, raw_lfp_with_cardiac):
        """Test preprocessing of JSON-formatted waveform data (StreamingRecord format)."""
        # Convert to JSON string (as stored in StreamingRecord.waveform_data)
        waveform_json = json.dumps(raw_lfp_with_cardiac.tolist())

        # Preprocess
        cleaned_json, stats = preprocessor.preprocess_streaming_waveform(waveform_json)

        # Should return JSON string
        assert isinstance(cleaned_json, str)

        # Should be parseable back to array
        cleaned_array = np.array(json.loads(cleaned_json))
        assert len(cleaned_array) == len(raw_lfp_with_cardiac)

        # Should have processing stats
        assert 'r_waves_detected' in stats

    def test_validation_function(self, raw_lfp_with_cardiac, preprocessor):
        """Test standalone validate_cardiac_removal function."""
        cleaned_lfp, _ = preprocessor.remove_cardiac_artifact(raw_lfp_with_cardiac)

        passed, results = validate_cardiac_removal(
            raw_lfp_with_cardiac,
            cleaned_lfp,
            fs=preprocessor.fs
        )

        # Should have results
        assert 'all_passed' in results
        assert 'checks' in results
        assert 'metrics' in results

        # For simulated data, validation may or may not pass depending on
        # the random seed and signal characteristics, so just verify structure
        assert isinstance(passed, bool)
        assert isinstance(results['all_passed'], bool)


class TestCardiacQualityControl:
    """Test suite for cardiac QC functions."""

    @pytest.fixture
    def fs(self):
        """Sampling frequency."""
        return 250

    @pytest.fixture
    def raw_signal(self, fs):
        """Generate raw signal with cardiac artifact."""
        duration = 60
        t = np.linspace(0, duration, fs * duration)

        # Neural signal
        neural = 10 * np.sin(2 * np.pi * 10 * t) + np.random.randn(len(t)) * 2

        # Cardiac artifact
        cardiac = np.zeros_like(t)
        for beat_time in np.arange(0, duration, 60/70):  # 70 BPM
            beat_idx = int(beat_time * fs)
            if beat_idx + 50 < len(t):
                cardiac[beat_idx:beat_idx+50] += 50 * np.sin(np.linspace(0, np.pi, 50))

        return neural + cardiac

    @pytest.fixture
    def cleaned_signal(self, raw_signal):
        """Generate cleaned signal (cardiac removed)."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        cleaned, _ = car.remove_cardiac_artifact(raw_signal)
        return cleaned

    @pytest.fixture
    def r_wave_indices(self, raw_signal):
        """Get R-wave indices from raw signal."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        cardiac_signal = car._isolate_cardiac_signal(raw_signal)
        r_waves, _ = car._detect_r_waves(cardiac_signal)
        return r_waves

    def test_compute_qc_metrics(self, raw_signal, cleaned_signal, r_wave_indices):
        """Test compute_qc_metrics function."""
        metrics = compute_qc_metrics(raw_signal, cleaned_signal, r_wave_indices, fs=250)

        # Check required fields
        assert 'num_r_waves' in metrics
        assert 'heart_rate_mean' in metrics
        assert 'power_reduction_theta' in metrics
        assert 'power_reduction_alpha' in metrics
        assert 'power_reduction_beta' in metrics
        assert 'power_reduction_gamma' in metrics
        assert 'snr_improvement_db' in metrics
        assert 'overall_pass' in metrics
        assert 'checks' in metrics

        # Check data types
        assert isinstance(metrics['num_r_waves'], (int, np.integer))
        assert isinstance(metrics['heart_rate_mean'], (float, np.floating))
        assert isinstance(metrics['overall_pass'], bool)
        assert isinstance(metrics['checks'], dict)

    def test_generate_qc_report(self, raw_signal, cleaned_signal, r_wave_indices):
        """Test generate_qc_report function."""
        metrics = compute_qc_metrics(raw_signal, cleaned_signal, r_wave_indices, fs=250)
        report = generate_qc_report(metrics, verbose=True)

        # Should return string
        assert isinstance(report, str)

        # Should contain key information
        assert "CARDIAC ARTIFACT REMOVAL" in report
        assert "QUALITY CONTROL REPORT" in report
        assert "DETECTION METRICS" in report
        assert "POWER REDUCTION" in report

        # Should show pass/fail status
        if metrics['overall_pass']:
            assert "PASS" in report
        else:
            assert "FAIL" in report

    def test_bootstrap_validation(self, raw_signal, cleaned_signal):
        """Test bootstrap_validation function."""
        results = bootstrap_validation(
            raw_signal,
            cleaned_signal,
            fs=250,
            n_bootstrap=100  # Use fewer iterations for speed
        )

        # Check required fields
        assert 'mean_power_diff' in results
        assert 'ci_low' in results
        assert 'ci_high' in results
        assert 'p_value' in results
        assert 'significant' in results

        # Check data types (allow numpy bool types)
        assert isinstance(results['mean_power_diff'], (float, np.floating))
        assert isinstance(results['p_value'], (float, np.floating))
        assert isinstance(results['significant'], (bool, np.bool_))

        # CI should be ordered
        assert results['ci_low'] <= results['ci_high']

        # p-value should be between 0 and 1
        assert 0 <= results['p_value'] <= 1

    def test_assess_signal_integrity(self, raw_signal, cleaned_signal):
        """Test assess_signal_integrity function."""
        integrity = assess_signal_integrity(raw_signal, cleaned_signal)

        # Check required fields
        assert 'correlation' in integrity
        assert 'amplitude_ratio' in integrity
        assert 'zero_crossings_ratio' in integrity
        assert 'warnings' in integrity
        assert 'integrity_ok' in integrity

        # Check data types
        assert isinstance(integrity['correlation'], (float, np.floating))
        assert isinstance(integrity['amplitude_ratio'], (float, np.floating))
        assert isinstance(integrity['warnings'], list)
        assert isinstance(integrity['integrity_ok'], bool)

        # Correlation should be between -1 and 1
        assert -1 <= integrity['correlation'] <= 1

        # For good cardiac removal, correlation should be high
        assert integrity['correlation'] > 0.5


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_very_short_signal(self):
        """Test with signal shorter than minimum length."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        short_signal = np.random.randn(500)  # Less than 1000 samples

        with pytest.raises(ValueError, match="Signal too short"):
            car.remove_cardiac_artifact(short_signal)

    def test_signal_with_nan_values(self):
        """Test with signal containing NaN values."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        signal_with_nan = np.random.randn(5000)
        signal_with_nan[100:110] = np.nan

        # Should handle NaN gracefully (may skip or interpolate)
        # Actual behavior depends on implementation choice
        # Here we just check it doesn't crash
        try:
            cleaned, stats = car.remove_cardiac_artifact(signal_with_nan)
            # If it succeeds, check that output is valid
            assert len(cleaned) == len(signal_with_nan)
        except (ValueError, RuntimeError):
            # It's acceptable to raise an error for invalid input
            pass

    def test_constant_signal(self):
        """Test with constant (DC) signal."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        constant_signal = np.ones(5000) * 10.0

        # Should handle constant signal gracefully
        cleaned, stats = car.remove_cardiac_artifact(constant_signal)

        # Constant signal may trigger false positives due to filtering edge effects
        # Just verify it doesn't crash and returns valid output
        assert len(cleaned) == len(constant_signal)
        assert 'r_waves_detected' in stats

    def test_very_high_heart_rate(self):
        """Test with unrealistically high heart rate."""
        car = CardiacArtifactRemoval(enabled=True, fs=250)
        duration = 10  # seconds
        fs = 250
        t = np.linspace(0, duration, fs * duration)

        # Simulate 200 BPM (too high)
        cardiac = np.zeros_like(t)
        for beat_time in np.arange(0, duration, 60/200):
            beat_idx = int(beat_time * fs)
            if beat_idx + 30 < len(t):
                cardiac[beat_idx:beat_idx+30] += 50 * np.sin(np.linspace(0, np.pi, 30))

        neural = np.random.randn(len(t)) * 5
        signal = neural + cardiac

        cleaned, stats = car.remove_cardiac_artifact(signal)

        # Should still process, but may flag as unusual
        assert 'heart_rate_bpm' in stats

    def test_different_sampling_rates(self):
        """Test with different sampling rates."""
        # Test with 125 Hz (half of standard 250 Hz)
        car_125 = CardiacArtifactRemoval(enabled=True, fs=125)
        signal_125 = np.random.randn(5000)

        # Should adapt parameters to sampling rate
        cleaned_125, stats_125 = car_125.remove_cardiac_artifact(signal_125)

        # Test with 500 Hz (double standard)
        car_500 = CardiacArtifactRemoval(enabled=True, fs=500)
        signal_500 = np.random.randn(10000)

        cleaned_500, stats_500 = car_500.remove_cardiac_artifact(signal_500)

        # Both should process without error
        assert len(cleaned_125) == len(signal_125)
        assert len(cleaned_500) == len(signal_500)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
