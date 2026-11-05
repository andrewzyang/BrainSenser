"""
Unit tests for PatientStatistics model.

Tests the PatientStatistics dataclass including immutability,
computed properties, and edge cases like zero division.
"""

import pytest
from datetime import datetime
from dataclasses import FrozenInstanceError

from src.core.models.statistics import PatientStatistics


@pytest.fixture
def sample_statistics_data():
    """Sample patient statistics data for testing."""
    return {
        'patient_id': 'PATIENT001',
        'snapshots_original': 1000,
        'snapshots_deduplicated': 750,
        'timeline_original': 5000,
        'timeline_deduplicated': 4000,
        'indefinite_streaming_original': 100,
        'indefinite_streaming_deduplicated': 80,
        'definite_streaming_original': 200,
        'definite_streaming_deduplicated': 150,
        'total_files_uploaded': 5,
        'total_duplicates_skipped': 1270,
        'last_upload_date': datetime(2025, 1, 15, 10, 30, 0),
        'last_calculated': datetime(2025, 1, 15, 11, 0, 0)
    }


@pytest.fixture
def sample_statistics(sample_statistics_data):
    """Sample PatientStatistics instance for testing."""
    return PatientStatistics(**sample_statistics_data)


class TestPatientStatisticsModel:
    """Test PatientStatistics model functionality."""

    def test_statistics_creation(self, sample_statistics_data):
        """Test creating PatientStatistics instance with all fields."""
        stats = PatientStatistics(**sample_statistics_data)

        assert stats.patient_id == 'PATIENT001'
        assert stats.snapshots_original == 1000
        assert stats.snapshots_deduplicated == 750
        assert stats.timeline_original == 5000
        assert stats.timeline_deduplicated == 4000
        assert stats.indefinite_streaming_original == 100
        assert stats.indefinite_streaming_deduplicated == 80
        assert stats.definite_streaming_original == 200
        assert stats.definite_streaming_deduplicated == 150
        assert stats.total_files_uploaded == 5
        assert stats.total_duplicates_skipped == 1270
        assert stats.last_upload_date == datetime(2025, 1, 15, 10, 30, 0)
        assert stats.last_calculated == datetime(2025, 1, 15, 11, 0, 0)

    def test_statistics_immutability(self, sample_statistics):
        """Test that PatientStatistics instances are immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_statistics.snapshots_original = 2000

        with pytest.raises(FrozenInstanceError):
            sample_statistics.total_files_uploaded = 10

    def test_snapshots_reduction_percent(self):
        """Test snapshots_reduction_percent calculation."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=100,
            snapshots_deduplicated=75,
            timeline_original=0,
            timeline_deduplicated=0,
            last_calculated=datetime.now()
        )

        # (100 - 75) / 100 * 100 = 25%
        assert stats.snapshots_reduction_percent == 25.0

    def test_snapshots_reduction_percent_zero_original(self):
        """Test snapshots_reduction_percent returns 0.0 when original is 0."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=0,
            snapshots_deduplicated=0,
            timeline_original=100,
            timeline_deduplicated=75,
            last_calculated=datetime.now()
        )

        assert stats.snapshots_reduction_percent == 0.0

    def test_snapshots_reduction_percent_no_reduction(self):
        """Test snapshots_reduction_percent returns 0.0 when no duplicates."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=100,
            snapshots_deduplicated=100,
            timeline_original=0,
            timeline_deduplicated=0,
            last_calculated=datetime.now()
        )

        # (100 - 100) / 100 * 100 = 0%
        assert stats.snapshots_reduction_percent == 0.0

    def test_snapshots_reduction_percent_high_reduction(self):
        """Test snapshots_reduction_percent with high deduplication."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=1000,
            snapshots_deduplicated=100,
            timeline_original=0,
            timeline_deduplicated=0,
            last_calculated=datetime.now()
        )

        # (1000 - 100) / 1000 * 100 = 90%
        assert stats.snapshots_reduction_percent == 90.0

    def test_timeline_reduction_percent(self):
        """Test timeline_reduction_percent calculation."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=0,
            snapshots_deduplicated=0,
            timeline_original=200,
            timeline_deduplicated=150,
            last_calculated=datetime.now()
        )

        # (200 - 150) / 200 * 100 = 25%
        assert stats.timeline_reduction_percent == 25.0

    def test_timeline_reduction_percent_zero_original(self):
        """Test timeline_reduction_percent returns 0.0 when original is 0."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=100,
            snapshots_deduplicated=75,
            timeline_original=0,
            timeline_deduplicated=0,
            last_calculated=datetime.now()
        )

        assert stats.timeline_reduction_percent == 0.0

    def test_timeline_reduction_percent_no_reduction(self):
        """Test timeline_reduction_percent returns 0.0 when no duplicates."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=0,
            snapshots_deduplicated=0,
            timeline_original=500,
            timeline_deduplicated=500,
            last_calculated=datetime.now()
        )

        # (500 - 500) / 500 * 100 = 0%
        assert stats.timeline_reduction_percent == 0.0

    def test_statistics_with_streaming_data(self):
        """Test statistics with streaming data (future proofing)."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=100,
            snapshots_deduplicated=80,
            timeline_original=200,
            timeline_deduplicated=180,
            indefinite_streaming_original=300,
            indefinite_streaming_deduplicated=250,
            definite_streaming_original=400,
            definite_streaming_deduplicated=350,
            total_files_uploaded=10,
            total_duplicates_skipped=120,
            last_upload_date=datetime.now(),
            last_calculated=datetime.now()
        )

        # Verify all streaming fields are accessible
        assert stats.indefinite_streaming_original == 300
        assert stats.indefinite_streaming_deduplicated == 250
        assert stats.definite_streaming_original == 400
        assert stats.definite_streaming_deduplicated == 350

    def test_statistics_without_last_upload(self):
        """Test statistics with last_upload_date=None (no uploads yet)."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=0,
            snapshots_deduplicated=0,
            timeline_original=0,
            timeline_deduplicated=0,
            total_files_uploaded=0,
            total_duplicates_skipped=0,
            last_upload_date=None,
            last_calculated=datetime.now()
        )

        assert stats.last_upload_date is None
        assert stats.total_files_uploaded == 0

    def test_statistics_realistic_scenario(self):
        """Test statistics with realistic values from actual usage."""
        stats = PatientStatistics(
            patient_id='PATIENT001',
            snapshots_original=5000,
            snapshots_deduplicated=3500,
            timeline_original=50000,
            timeline_deduplicated=45000,
            indefinite_streaming_original=0,
            indefinite_streaming_deduplicated=0,
            definite_streaming_original=0,
            definite_streaming_deduplicated=0,
            total_files_uploaded=15,
            total_duplicates_skipped=6500,
            last_upload_date=datetime(2025, 1, 15, 14, 30, 0),
            last_calculated=datetime(2025, 1, 15, 15, 0, 0)
        )

        # Verify all calculations work together
        assert stats.snapshots_reduction_percent == 30.0
        assert stats.timeline_reduction_percent == 10.0
        assert stats.total_files_uploaded == 15
        assert stats.total_duplicates_skipped == 6500

    def test_statistics_defaults(self):
        """Test that default values work correctly."""
        stats = PatientStatistics(
            patient_id='TEST001',
            snapshots_original=100,
            snapshots_deduplicated=80,
            timeline_original=200,
            timeline_deduplicated=180,
            last_calculated=datetime.now()
        )

        # Check default values
        assert stats.indefinite_streaming_original == 0
        assert stats.indefinite_streaming_deduplicated == 0
        assert stats.definite_streaming_original == 0
        assert stats.definite_streaming_deduplicated == 0
        assert stats.total_files_uploaded == 0
        assert stats.total_duplicates_skipped == 0
        assert stats.last_upload_date is None

    def test_statistics_type_hints(self, sample_statistics):
        """Test that types are correct."""
        assert isinstance(sample_statistics.patient_id, str)
        assert isinstance(sample_statistics.snapshots_original, int)
        assert isinstance(sample_statistics.snapshots_deduplicated, int)
        assert isinstance(sample_statistics.timeline_original, int)
        assert isinstance(sample_statistics.timeline_deduplicated, int)
        assert isinstance(sample_statistics.total_files_uploaded, int)
        assert isinstance(sample_statistics.total_duplicates_skipped, int)
        assert isinstance(sample_statistics.last_calculated, datetime)
        assert sample_statistics.last_upload_date is None or isinstance(sample_statistics.last_upload_date, datetime)
