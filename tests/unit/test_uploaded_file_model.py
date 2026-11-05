"""
Unit tests for UploadedFile model.

Tests the UploadedFile dataclass including immutability, properties,
computed values, and type correctness.
"""

import pytest
from pathlib import Path
from datetime import datetime
from dataclasses import FrozenInstanceError

from src.core.models.uploaded_file import UploadedFile


@pytest.fixture
def sample_file_data():
    """Sample uploaded file data for testing."""
    return {
        'file_id': 1,
        'patient_id': 'PATIENT001',
        'file_name': 'Report_2025-01-15.json',
        'file_path': Path('/data/patients/PATIENT001/uploads/Report_2025-01-15.json'),
        'file_hash': 'abc123def456',
        'file_size_bytes': 1048576,  # 1 MB
        'timeline_count': 1000,
        'timeline_original_count': 1200,
        'snapshot_count': 50,
        'snapshot_original_count': 60,
        'duplicates_skipped': 210,
        'outliers_detected': 5,
        'processing_time_seconds': 2.5,
        'extractor_version': '1.0.0',
        'processing_settings': {'threshold': 0.5},
        'errors_encountered': 0,
        'error_details': None,
        'processed_at': datetime(2025, 1, 15, 10, 30, 0)
    }


@pytest.fixture
def sample_uploaded_file(sample_file_data):
    """Sample UploadedFile instance for testing."""
    return UploadedFile(**sample_file_data)


class TestUploadedFileModel:
    """Test UploadedFile model functionality."""

    def test_uploaded_file_creation(self, sample_file_data):
        """Test creating UploadedFile instance with all fields."""
        uploaded_file = UploadedFile(**sample_file_data)

        assert uploaded_file.file_id == 1
        assert uploaded_file.patient_id == 'PATIENT001'
        assert uploaded_file.file_name == 'Report_2025-01-15.json'
        assert uploaded_file.file_path == Path('/data/patients/PATIENT001/uploads/Report_2025-01-15.json')
        assert uploaded_file.file_hash == 'abc123def456'
        assert uploaded_file.file_size_bytes == 1048576
        assert uploaded_file.timeline_count == 1000
        assert uploaded_file.timeline_original_count == 1200
        assert uploaded_file.snapshot_count == 50
        assert uploaded_file.snapshot_original_count == 60
        assert uploaded_file.duplicates_skipped == 210
        assert uploaded_file.outliers_detected == 5
        assert uploaded_file.processing_time_seconds == 2.5
        assert uploaded_file.extractor_version == '1.0.0'
        assert uploaded_file.processing_settings == {'threshold': 0.5}
        assert uploaded_file.errors_encountered == 0
        assert uploaded_file.error_details is None
        assert uploaded_file.processed_at == datetime(2025, 1, 15, 10, 30, 0)

    def test_uploaded_file_immutability(self, sample_uploaded_file):
        """Test that UploadedFile instances are immutable."""
        with pytest.raises(FrozenInstanceError):
            sample_uploaded_file.file_name = "NewFile.json"

        with pytest.raises(FrozenInstanceError):
            sample_uploaded_file.timeline_count = 2000

    def test_file_size_mb_property(self):
        """Test file_size_mb property converts bytes to MB correctly."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=2097152,  # 2 MB
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.file_size_mb == 2.0

    def test_file_size_mb_property_fractional(self):
        """Test file_size_mb with fractional MB."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1572864,  # 1.5 MB
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.file_size_mb == 1.5

    def test_has_timeline_true(self):
        """Test has_timeline returns True when timeline_count > 0."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=100,
            timeline_original_count=120,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.has_timeline is True

    def test_has_timeline_false(self):
        """Test has_timeline returns False when timeline_count = 0."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=50,
            snapshot_original_count=60,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.has_timeline is False

    def test_has_snapshots_true(self):
        """Test has_snapshots returns True when snapshot_count > 0."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=50,
            snapshot_original_count=60,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.has_snapshots is True

    def test_has_snapshots_false(self):
        """Test has_snapshots returns False when snapshot_count = 0."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=100,
            timeline_original_count=120,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.has_snapshots is False

    def test_data_type_tags_both(self):
        """Test data_type_tags includes both types when both present."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=100,
            timeline_original_count=120,
            snapshot_count=50,
            snapshot_original_count=60,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        tags = uploaded_file.data_type_tags
        assert 'Snapshots' in tags
        assert 'Timeline' in tags
        assert len(tags) == 2

    def test_data_type_tags_timeline_only(self):
        """Test data_type_tags includes only Timeline when no snapshots."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=100,
            timeline_original_count=120,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        tags = uploaded_file.data_type_tags
        assert tags == ['Timeline']

    def test_data_type_tags_snapshots_only(self):
        """Test data_type_tags includes only Snapshots when no timeline."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=50,
            snapshot_original_count=60,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        tags = uploaded_file.data_type_tags
        assert tags == ['Snapshots']

    def test_data_type_tags_none(self):
        """Test data_type_tags is empty when no data present."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        tags = uploaded_file.data_type_tags
        assert tags == []

    def test_uploaded_file_with_errors(self):
        """Test UploadedFile with errors encountered."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=0,
            timeline_original_count=0,
            snapshot_count=0,
            snapshot_original_count=0,
            duplicates_skipped=0,
            outliers_detected=0,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=5,
            error_details='Invalid JSON format in lines 10-15',
            processed_at=datetime.now()
        )

        assert uploaded_file.errors_encountered == 5
        assert uploaded_file.error_details == 'Invalid JSON format in lines 10-15'

    def test_uploaded_file_with_processing_settings(self):
        """Test UploadedFile with processing settings."""
        settings = {
            'outlier_threshold': 3.5,
            'deduplication_method': 'hash',
            'preprocessing': 'OvER'
        }

        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=100,
            timeline_original_count=120,
            snapshot_count=50,
            snapshot_original_count=60,
            duplicates_skipped=20,
            outliers_detected=5,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=settings,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        assert uploaded_file.processing_settings == settings
        assert uploaded_file.processing_settings['outlier_threshold'] == 3.5

    def test_uploaded_file_deduplication_stats(self):
        """Test deduplication statistics tracking."""
        uploaded_file = UploadedFile(
            file_id=1,
            patient_id='TEST001',
            file_name='test.json',
            file_path=Path('/test.json'),
            file_hash='hash',
            file_size_bytes=1024,
            timeline_count=900,
            timeline_original_count=1000,
            snapshot_count=45,
            snapshot_original_count=50,
            duplicates_skipped=105,  # 100 timeline + 5 snapshots
            outliers_detected=10,
            processing_time_seconds=1.0,
            extractor_version='1.0.0',
            processing_settings=None,
            errors_encountered=0,
            error_details=None,
            processed_at=datetime.now()
        )

        # Check all deduplication stats are accessible
        assert uploaded_file.timeline_original_count == 1000
        assert uploaded_file.timeline_count == 900
        assert uploaded_file.snapshot_original_count == 50
        assert uploaded_file.snapshot_count == 45
        assert uploaded_file.duplicates_skipped == 105

    def test_uploaded_file_type_hints(self, sample_uploaded_file):
        """Test that types are correct."""
        assert isinstance(sample_uploaded_file.file_id, int)
        assert isinstance(sample_uploaded_file.patient_id, str)
        assert isinstance(sample_uploaded_file.file_name, str)
        assert isinstance(sample_uploaded_file.file_path, Path)
        assert isinstance(sample_uploaded_file.file_hash, str)
        assert isinstance(sample_uploaded_file.file_size_bytes, int)
        assert isinstance(sample_uploaded_file.timeline_count, int)
        assert isinstance(sample_uploaded_file.processing_time_seconds, float)
        assert isinstance(sample_uploaded_file.extractor_version, str)
        assert isinstance(sample_uploaded_file.errors_encountered, int)
        assert isinstance(sample_uploaded_file.processed_at, datetime)
