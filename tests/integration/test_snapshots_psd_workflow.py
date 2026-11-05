"""
Integration test for Snapshots PSD analysis workflow.

This test verifies the complete end-to-end workflow:
1. Data loading from repository
2. Statistical analysis with all frequency bands
3. Results population in UI table
4. Verification of correct band definitions

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import pytest
import numpy as np
from datetime import datetime
import json
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication

from src.domain.psd_models import (
    FrequencyBandDefinitions
)
from src.core.models import SnapshotRecord
from src.infrastructure.psd_data_loader import load_snapshot_psd_dataset
from src.core.services.snapshot_psd_analysis_service import SnapshotPsdAnalysisService
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView
from src.infrastructure.repositories import SnapshotRepository


class TestSnapshotsPsdWorkflow:
    """
    Integration test for complete Snapshots PSD analysis workflow.

    Tests two prespecified endpoints per hemisphere:
    1. Timeline-matched band (7.81 ± 2.5 Hz; 5.31-10.31 Hz with 5 bins)
    2. Canonical low-frequency bands (δ, θ, α, β)
    """

    @pytest.fixture
    def app(self):
        """Create QApplication instance for testing."""
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    @pytest.fixture
    def mock_snapshot_records(self):
        """Create mock snapshot records with realistic PSD data."""
        freq_data = list(np.arange(0.98, 96.05, 0.98))  # 98 bins, 0.98 Hz resolution

        records = []

        # Create 20 craving events
        for i in range(20):
            # Higher power in beta band for craving
            power_data = list(np.random.randn(98) + 2.0)
            records.append(
                SnapshotRecord(
                    timestamp=datetime.now(),
                    event_name="Craving",
                    patient_event=1,
                    patient_event_id=f"CR_{i:03d}",
                    frequency_data=json.dumps(freq_data),
                    power_data=json.dumps(power_data),
                    hemisphere="LEFT",
                    source_file="test.json",
                    data_hash=f"hash_cr_left_{i}"
                )
            )
            records.append(
                SnapshotRecord(
                    timestamp=datetime.now(),
                    event_name="Craving",
                    patient_event=1,
                    patient_event_id=f"CR_{i:03d}",
                    frequency_data=json.dumps(freq_data),
                    power_data=json.dumps(power_data),
                    hemisphere="RIGHT",
                    source_file="test.json",
                    data_hash=f"hash_cr_right_{i}"
                )
            )

        # Create 20 non-craving events
        for i in range(20):
            # Lower power overall
            power_data = list(np.random.randn(98))
            event_type = ["Anxious", "Happy", "Neutral"][i % 3]
            records.append(
                SnapshotRecord(
                    timestamp=datetime.now(),
                    event_name=event_type,
                    patient_event=1,
                    patient_event_id=f"NC_{i:03d}",
                    frequency_data=json.dumps(freq_data),
                    power_data=json.dumps(power_data),
                    hemisphere="LEFT",
                    source_file="test.json",
                    data_hash=f"hash_nc_left_{i}"
                )
            )
            records.append(
                SnapshotRecord(
                    timestamp=datetime.now(),
                    event_name=event_type,
                    patient_event=1,
                    patient_event_id=f"NC_{i:03d}",
                    frequency_data=json.dumps(freq_data),
                    power_data=json.dumps(power_data),
                    hemisphere="RIGHT",
                    source_file="test.json",
                    data_hash=f"hash_nc_right_{i}"
                )
            )

        return records

    @pytest.fixture
    def mock_repository(self, mock_snapshot_records):
        """Create mock snapshot repository."""
        repo = Mock(spec=SnapshotRepository)
        repo.get_by_patient.return_value = mock_snapshot_records
        return repo

    def test_frequency_band_definitions(self):
        """
        Test 1: Verify correct frequency band definitions.

        Validates:
        - Timeline-matched band (7.81 ± 2.5 Hz)
        - Canonical frequency bands with correct bin counts
        """
        bands = FrequencyBandDefinitions.get_percept_bands()

        # Test Timeline-matched band
        timeline_band = bands["Timeline"]
        assert timeline_band.min_freq == 5.31
        assert timeline_band.max_freq == 10.31
        assert timeline_band.center_freqs == [5.88, 6.86, 7.84, 8.82, 9.80]
        assert len(timeline_band.center_freqs) == 5, "Timeline should have 5 bins"

        # Test canonical frequency bands
        delta_band = bands["Delta"]
        assert delta_band.min_freq == 1.0
        assert delta_band.max_freq == 4.0
        assert len(delta_band.center_freqs) == 3, "Delta should have 3 bins"
        assert delta_band.center_freqs == [1.96, 2.94, 3.92]

        theta_band = bands["Theta"]
        assert theta_band.min_freq == 4.0
        assert theta_band.max_freq == 8.0
        assert len(theta_band.center_freqs) == 4, "Theta should have 4 bins"

        alpha_band = bands["Alpha"]
        assert alpha_band.min_freq == 8.0
        assert alpha_band.max_freq == 13.0
        assert len(alpha_band.center_freqs) == 5, "Alpha should have 5 bins"

        beta_band = bands["Beta"]
        assert beta_band.min_freq == 13.0
        assert beta_band.max_freq == 30.0
        assert len(beta_band.center_freqs) == 17, "Beta should have 17 bins"

        gamma_low_band = bands["Gamma_low"]
        assert gamma_low_band.min_freq == 30.0
        assert gamma_low_band.max_freq == 40.0
        assert len(gamma_low_band.center_freqs) == 10, "Gamma_low should have 10 bins"

        gamma_high_band = bands["Gamma_high"]
        assert gamma_high_band.min_freq == 50.0
        assert gamma_high_band.max_freq == 96.68
        assert len(gamma_high_band.center_freqs) == 47, "Gamma_high should have 47 bins"

    def test_data_loading_and_band_integration(self, mock_snapshot_records):
        """
        Test 2: Verify data loading correctly integrates with band definitions.

        Validates:
        - PSD data matches frequency axis
        - All band bins can be extracted from PSD data
        """
        dataset = load_snapshot_psd_dataset("TEST_PATIENT", mock_snapshot_records)

        # Verify frequency axis
        assert len(dataset.frequency_axis) == 98
        assert dataset.frequency_axis[0] == pytest.approx(0.98, abs=0.01)
        assert dataset.frequency_axis[-1] == pytest.approx(96.04, abs=0.01)

        # Verify events loaded
        assert len(dataset.events) > 0

        # Test band bin extraction
        bands = FrequencyBandDefinitions.get_percept_bands()
        for band_name, band in bands.items():
            bin_mask = band.get_bin_indices(dataset.frequency_axis)
            assert np.sum(bin_mask) == len(band.center_freqs), \
                f"{band_name} should extract {len(band.center_freqs)} bins"

    @pytest.mark.slow
    def test_statistical_analysis_low_frequency_bands(self, mock_snapshot_records):
        """
        Test 3: Verify statistical analysis runs for the retained frequency bands.

        Validates:
        - Canonical low-frequency bands are analyzed by default
        - Statistical tests produce valid results
        - FDR correction is applied across the reduced set
        """
        dataset = load_snapshot_psd_dataset("TEST_PATIENT", mock_snapshot_records)
        service = SnapshotPsdAnalysisService()

        # Run analysis for left hemisphere
        results_left = service.analyze_craving_vs_non_craving(
            dataset,
            hemisphere="LEFT",
            use_log_scale=True,
            filter_stimulation=False
        )

        # Verify retained bands present
        expected_bands = ["Delta", "Theta", "Alpha", "Beta"]
        for band_name in expected_bands:
            assert band_name in results_left, f"{band_name} should be in results"

        assert "Timeline" not in results_left, "Timeline band should be optional and absent by default"

        # Verify statistical properties
        for band_name, result in results_left.items():
            assert result.hemisphere == "LEFT"
            assert result.n_group1 > 0, f"{band_name}: Group 1 should have events"
            assert result.n_group2 > 0, f"{band_name}: Group 2 should have events"
            assert 0 <= result.p_value <= 1, f"{band_name}: p-value should be in [0,1]"
            assert 0 <= result.q_value <= 1, f"{band_name}: q-value should be in [0,1]"
            assert result.q_value >= result.p_value, f"{band_name}: q-value should be >= p-value"
            assert -1 <= result.rank_biserial_r <= 1, f"{band_name}: rank-biserial should be in [-1,1]"
            # CI may be NaN for perfect separation cases, which is acceptable
            if not np.isnan(result.ci_lower) and not np.isnan(result.ci_upper):
                assert result.ci_lower <= result.ci_upper, f"{band_name}: CI should be ordered"

    def test_viewmodel_populates_results(self, mock_repository):
        """
        Test 4: Verify ViewModel correctly processes and stores results.

        Validates:
        - Data loading through repository
        - Analysis execution for both hemispheres
        - Results storage in ViewModel
        """
        viewmodel = SnapshotsPsdViewModel(snapshot_repo=mock_repository)

        # Track signal emissions
        data_loaded_signal = Mock()
        analysis_complete_signal = Mock()
        band_stats_signal = Mock()

        viewmodel.data_loaded.connect(data_loaded_signal)
        viewmodel.analysis_complete.connect(analysis_complete_signal)
        viewmodel.band_statistics_ready.connect(band_stats_signal)

        # Load data
        viewmodel.load_patient_data("TEST_PATIENT")
        assert data_loaded_signal.called, "data_loaded signal should be emitted"

        # Run analysis
        viewmodel.analyze_craving_vs_non_craving()
        assert analysis_complete_signal.called, "analysis_complete signal should be emitted"
        assert band_stats_signal.called, "band_statistics_ready signal should be emitted"

        # Verify results stored
        assert len(viewmodel.band_results_left) > 0, "Left hemisphere results should be stored"
        assert len(viewmodel.band_results_right) > 0, "Right hemisphere results should be stored"

        # Verify all bands present
        expected_bands = ["Delta", "Theta", "Alpha", "Beta"]
        for band in expected_bands:
            assert band in viewmodel.band_results_left, f"{band} should be in left results"
            assert band in viewmodel.band_results_right, f"{band} should be in right results"

        assert "Timeline" not in viewmodel.band_results_left
        assert "Timeline" not in viewmodel.band_results_right

    def test_ui_table_population(self, mock_repository, app):
        """
        Test 5: Verify UI table is populated with analysis results.

        Validates:
        - View receives ViewModel signals
        - Statistics table is populated
        - Both hemispheres shown
        """
        viewmodel = SnapshotsPsdViewModel(snapshot_repo=mock_repository)
        view = SnapshotsPsdView(viewmodel=viewmodel)

        # Load data
        viewmodel.load_patient_data("TEST_PATIENT")

        # Verify grouping panel receives event types
        assert view.grouping_panel.event_types_list.count() > 0, \
            "Event types list should be populated"

        # Run analysis
        viewmodel.analyze_craving_vs_non_craving()

        # Verify statistics table populated
        stats_table = view.grouping_panel.stats_table
        assert stats_table.rowCount() > 0, "Statistics table should have rows"

        # Verify both hemispheres present
        left_bands = []
        right_bands = []
        for row in range(stats_table.rowCount()):
            band_item = stats_table.item(row, 0)
            if band_item:
                band_name = band_item.text()
                if "(L)" in band_name:
                    left_bands.append(band_name)
                elif "(R)" in band_name:
                    right_bands.append(band_name)

        assert len(left_bands) >= 4, "Should have at least 4 left hemisphere bands"
        assert len(right_bands) >= 4, "Should have at least 4 right hemisphere bands"

    def test_ui_table_updates_with_timeline_band(self, mock_repository, app):
        """
        Test 5b: Verify table includes optional timeline band when configured.

        Validates:
        - Timeline row appears with dynamic frequency label
        - Frequency range column reflects ±2.5 Hz window
        """
        viewmodel = SnapshotsPsdViewModel(snapshot_repo=mock_repository)
        view = SnapshotsPsdView(viewmodel=viewmodel)

        # Load data and run analysis with timeline band enabled
        viewmodel.load_patient_data("TEST_PATIENT")
        timeline_center = 7.81
        viewmodel.analyze_event_groups(
            group1_event_types=viewmodel.non_craving_group,
            group2_event_types=viewmodel.craving_group,
            group1_name="Group 1",
            group2_name="Group 2",
            timeline_band_center=timeline_center
        )
        app.processEvents()

        stats_table = view.grouping_panel.stats_table
        assert stats_table.rowCount() > 0, "Statistics table should contain rows"

        timeline_rows = []
        for row in range(stats_table.rowCount()):
            band_item = stats_table.item(row, 0)
            range_item = stats_table.item(row, 1)
            if band_item and "Timeline" in band_item.text():
                timeline_rows.append((band_item.text(), range_item.text() if range_item else ""))

        assert timeline_rows, "Timeline band row should be present when configured"
        assert any(f"{timeline_center:.2f}" in name for name, _ in timeline_rows), \
            "Timeline band label should include center frequency"
        assert any("Hz" in freq and "5.31" in freq and "10.31" in freq for _, freq in timeline_rows), \
            "Timeline frequency range should reflect ±2.5 Hz window"

    @pytest.mark.slow
    def test_timeline_band_specific_analysis(self, mock_snapshot_records):
        """
        Test 6: Verify Timeline band specific integration.

        Validates:
        - Timeline band (7.81 ± 2.5 Hz) is correctly analyzed
        - Integration uses exactly 5 bins: 5.88, 6.86, 7.84, 8.82, 9.80 Hz
        - Censored bins are handled correctly
        """
        dataset = load_snapshot_psd_dataset("TEST_PATIENT", mock_snapshot_records)
        service = SnapshotPsdAnalysisService()

        # Get Timeline band definition
        timeline_band = FrequencyBandDefinitions.get_band("Timeline")
        assert timeline_band is not None

        # Verify bin extraction
        bin_mask = timeline_band.get_bin_indices(dataset.frequency_axis)
        extracted_freqs = dataset.frequency_axis[bin_mask]
        expected_freqs = np.array([5.88, 6.86, 7.84, 8.82, 9.80])

        assert len(extracted_freqs) == 5, "Timeline should extract 5 bins"
        np.testing.assert_array_almost_equal(
            extracted_freqs, expected_freqs, decimal=2,
            err_msg="Timeline bins should match specification"
        )

        # Run analysis
        results = service.analyze_craving_vs_non_craving(
            dataset,
            hemisphere="LEFT",
            use_log_scale=True,
            filter_stimulation=False,
            timeline_band_center=7.81
        )

        # Verify Timeline band result
        assert "Timeline" in results
        timeline_result = results["Timeline"]
        assert timeline_result.band_name.startswith("Timeline"), "Display name should include Timeline label"
        assert "7.81" in timeline_result.band_name, "Display name should include center frequency"
        assert pytest.approx(timeline_result.min_freq, abs=0.01) == 5.31
        assert pytest.approx(timeline_result.max_freq, abs=0.01) == 10.31
        assert timeline_result.n_group1 > 0
        assert timeline_result.n_group2 > 0

    def test_band_power_integration_with_censoring(self):
        """
        Test 7: Verify band power integration handles censored bins.

        Validates:
        - NaN values from artifact censoring are excluded
        - Integration still works with partial data
        - At least 2 valid bins required
        """
        service = SnapshotPsdAnalysisService()

        # Create test data with some NaN values
        freq_axis = np.array([5.88, 6.86, 7.84, 8.82, 9.80])
        psd = np.array([1.0, np.nan, 2.0, 3.0, np.nan])  # 3 valid bins

        # Get Timeline band
        timeline_band = FrequencyBandDefinitions.get_band("Timeline")

        # Test integration
        result = service._integrate_band_power(
            freq_axis,
            psd,
            timeline_band,
            use_log_scale=False
        )

        assert result is not None, "Integration should work with 3 valid bins"

        # Test with too few valid bins
        psd_too_few = np.array([1.0, np.nan, np.nan, np.nan, np.nan])  # Only 1 valid
        result_none = service._integrate_band_power(
            freq_axis,
            psd_too_few,
            timeline_band,
            use_log_scale=False
        )

        assert result_none is None, "Integration should return None with < 2 valid bins"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
