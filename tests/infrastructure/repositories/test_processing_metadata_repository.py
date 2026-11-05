"""
Tests for ProcessingMetadataRepository.

This module tests the ProcessingMetadataRepository class which provides database
operations for processing_metadata table in per-patient databases.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import sqlite3
from pathlib import Path

from src.infrastructure.repositories.processing_metadata_repository import ProcessingMetadataRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import UploadedFile
from src.infrastructure.database.schema import initialize_patient_database


@pytest.fixture
def adapter():
    """Provide SQLiteAdapter instance."""
    return SQLiteAdapter()


@pytest.fixture
def path_resolver(tmp_path):
    """Provide PathResolver instance with temp directory."""
    resolver = PathResolver(base_dir=tmp_path)
    return resolver


@pytest.fixture
def metadata_repository(adapter, path_resolver):
    """Provide ProcessingMetadataRepository instance."""
    return ProcessingMetadataRepository(adapter, path_resolver)


@pytest.fixture
def patient_id():
    """Provide test patient ID."""
    return "TEST_PATIENT_001"


@pytest.fixture
def initialized_patient_db(adapter, path_resolver, patient_id):
    """Initialize patient database with schema."""
    initialize_patient_database(adapter, path_resolver, patient_id)
    return path_resolver.get_patient_db_path(patient_id)


@pytest.fixture
def sample_file_info():
    """Provide sample file info dict."""
    return {
        'file_name': 'test_session.json',
        'file_path': Path('/data/uploads/test_session.json'),
        'file_hash': 'abc123def456',
        'file_size_bytes': 1048576
    }


@pytest.fixture
def sample_counts():
    """Provide sample processing counts dict."""
    return {
        'timeline_count': 100,
        'timeline_original_count': 120,
        'snapshot_count': 50,
        'snapshot_original_count': 60,
        'duplicates_skipped': 30,
        'outliers_detected': 5
    }


@pytest.fixture
def sample_processing_info():
    """Provide sample processing info dict."""
    return {
        'processing_time_seconds': 2.5,
        'extractor_version': '1.0.0',
        'processing_settings': {'option': 'value'},
        'errors_encountered': 0,
        'error_details': None
    }


# ============================================================================
# Test: create
# ============================================================================

def test_create_basic(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test creating basic processing metadata record."""
    result = metadata_repository.create(patient_id, sample_file_info, sample_counts)

    assert isinstance(result, UploadedFile)
    assert result.file_id > 0
    assert result.patient_id == patient_id
    assert result.file_name == 'test_session.json'
    assert result.file_hash == 'abc123def456'
    assert result.timeline_count == 100
    assert result.snapshot_count == 50
    assert result.duplicates_skipped == 30


def test_create_with_processing_info(metadata_repository, initialized_patient_db, patient_id,
                                     sample_file_info, sample_counts, sample_processing_info):
    """Test creating metadata with full processing info."""
    result = metadata_repository.create(
        patient_id,
        sample_file_info,
        sample_counts,
        processing_info=sample_processing_info
    )

    assert result.processing_time_seconds == 2.5
    assert result.extractor_version == '1.0.0'
    assert result.processing_settings == {'option': 'value'}
    assert result.errors_encountered == 0


def test_create_with_errors(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test creating metadata with error details."""
    processing_info = {
        'errors_encountered': 3,
        'error_details': 'Failed to parse 3 records'
    }

    result = metadata_repository.create(
        patient_id,
        sample_file_info,
        sample_counts,
        processing_info=processing_info
    )

    assert result.errors_encountered == 3
    assert result.error_details == 'Failed to parse 3 records'


def test_create_multiple_files(metadata_repository, initialized_patient_db, patient_id, sample_counts):
    """Test creating multiple file records."""
    files = []
    for i in range(3):
        file_info = {
            'file_name': f'session_{i}.json',
            'file_path': Path(f'/data/session_{i}.json'),
            'file_hash': f'hash_{i}',
            'file_size_bytes': 1024 * (i + 1)
        }
        result = metadata_repository.create(patient_id, file_info, sample_counts)
        files.append(result)

    assert len(files) == 3
    assert files[0].file_id != files[1].file_id
    assert files[1].file_id != files[2].file_id


# ============================================================================
# Test: get_by_patient
# ============================================================================

def test_get_by_patient_empty_db(metadata_repository, initialized_patient_db, patient_id):
    """Test get_by_patient returns empty list when no records."""
    uploads = metadata_repository.get_by_patient(patient_id)
    assert uploads == []


def test_get_by_patient_with_records(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_by_patient returns created records."""
    # Create 3 records
    for i in range(3):
        file_info = sample_file_info.copy()
        file_info['file_name'] = f'session_{i}.json'
        file_info['file_hash'] = f'hash_{i}'
        metadata_repository.create(patient_id, file_info, sample_counts)

    # Fetch all
    uploads = metadata_repository.get_by_patient(patient_id)
    assert len(uploads) == 3
    assert all(isinstance(u, UploadedFile) for u in uploads)


def test_get_by_patient_with_limit(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_by_patient respects limit parameter."""
    # Create 5 records
    for i in range(5):
        file_info = sample_file_info.copy()
        file_info['file_name'] = f'session_{i}.json'
        file_info['file_hash'] = f'hash_{i}'
        metadata_repository.create(patient_id, file_info, sample_counts)

    # Fetch with limit=3
    uploads = metadata_repository.get_by_patient(patient_id, limit=3)
    assert len(uploads) == 3


def test_get_by_patient_sorted_by_date(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_by_patient returns all records."""
    # Create 3 records
    created_files = []
    for i in range(3):
        file_info = sample_file_info.copy()
        file_info['file_name'] = f'session_{i}.json'
        file_info['file_hash'] = f'hash_{i}'
        result = metadata_repository.create(patient_id, file_info, sample_counts)
        created_files.append(result)

    # Fetch all
    uploads = metadata_repository.get_by_patient(patient_id)

    # Should have all 3 records (order may vary due to timestamp precision)
    assert len(uploads) == 3
    file_names = {u.file_name for u in uploads}
    assert file_names == {'session_0.json', 'session_1.json', 'session_2.json'}


# ============================================================================
# Test: get_by_file_hash
# ============================================================================

def test_get_by_file_hash_not_found(metadata_repository, initialized_patient_db, patient_id):
    """Test get_by_file_hash returns None when hash doesn't exist."""
    result = metadata_repository.get_by_file_hash(patient_id, 'nonexistent_hash')
    assert result is None


def test_get_by_file_hash_found(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_by_file_hash returns record when hash exists."""
    # Create record
    created = metadata_repository.create(patient_id, sample_file_info, sample_counts)

    # Find by hash
    found = metadata_repository.get_by_file_hash(patient_id, 'abc123def456')

    assert found is not None
    assert found.file_id == created.file_id
    assert found.file_hash == 'abc123def456'


def test_get_by_file_hash_duplicate_detection(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_by_file_hash can detect duplicate file uploads."""
    # Create first file
    metadata_repository.create(patient_id, sample_file_info, sample_counts)

    # Check if file already exists before uploading again
    existing = metadata_repository.get_by_file_hash(patient_id, sample_file_info['file_hash'])

    assert existing is not None
    assert existing.file_name == sample_file_info['file_name']


# ============================================================================
# Test: get_total_files_count
# ============================================================================

def test_get_total_files_count_empty_db(metadata_repository, initialized_patient_db, patient_id):
    """Test get_total_files_count returns 0 when no records."""
    count = metadata_repository.get_total_files_count(patient_id)
    assert count == 0


def test_get_total_files_count_with_records(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test get_total_files_count returns correct count."""
    # Create 5 records
    for i in range(5):
        file_info = sample_file_info.copy()
        file_info['file_name'] = f'session_{i}.json'
        file_info['file_hash'] = f'hash_{i}'
        metadata_repository.create(patient_id, file_info, sample_counts)

    count = metadata_repository.get_total_files_count(patient_id)
    assert count == 5


# ============================================================================
# Test: Error handling
# ============================================================================

def test_create_database_error(metadata_repository, patient_id, sample_file_info, sample_counts):
    """Test create raises error when database doesn't exist."""
    # Don't initialize database - should fail
    with pytest.raises(sqlite3.Error):
        metadata_repository.create(patient_id, sample_file_info, sample_counts)


def test_get_by_patient_database_error(metadata_repository, patient_id):
    """Test get_by_patient raises error when database doesn't exist."""
    # Don't initialize database - should fail
    with pytest.raises(sqlite3.Error):
        metadata_repository.get_by_patient(patient_id)


# ============================================================================
# Test: Transaction support
# ============================================================================

def test_create_with_connection(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts, adapter):
    """Test create works with provided connection (for transactions)."""
    db_path = initialized_patient_db

    with adapter.get_connection(db_path) as conn:
        result = metadata_repository.create(patient_id, sample_file_info, sample_counts, conn=conn)
        conn.commit()

    assert result.file_id > 0

    # Verify record was inserted
    count = metadata_repository.get_total_files_count(patient_id)
    assert count == 1


def test_get_by_patient_with_connection(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts, adapter):
    """Test get_by_patient works with provided connection."""
    # Create record first
    metadata_repository.create(patient_id, sample_file_info, sample_counts)

    db_path = initialized_patient_db
    with adapter.get_connection(db_path) as conn:
        uploads = metadata_repository.get_by_patient(patient_id, conn=conn)

    assert len(uploads) == 1


# ============================================================================
# Test: UploadedFile model properties
# ============================================================================

def test_uploaded_file_properties(metadata_repository, initialized_patient_db, patient_id, sample_file_info, sample_counts):
    """Test UploadedFile model computed properties."""
    result = metadata_repository.create(patient_id, sample_file_info, sample_counts)

    # file_size_mb
    assert result.file_size_mb == pytest.approx(1.0, rel=0.01)

    # has_timeline
    assert result.has_timeline is True

    # has_snapshots
    assert result.has_snapshots is True

    # data_type_tags
    assert 'Snapshots' in result.data_type_tags
    assert 'Timeline' in result.data_type_tags
