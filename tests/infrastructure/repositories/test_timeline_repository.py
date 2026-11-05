"""
Tests for TimelineRepository.

This module tests the TimelineRepository class which provides database operations
for timeline_data table in per-patient databases.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import sqlite3
from datetime import datetime

from src.infrastructure.repositories.timeline_repository import TimelineRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import TimelineRecord
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
def timeline_repository(adapter, path_resolver):
    """Provide TimelineRepository instance."""
    return TimelineRepository(adapter, path_resolver)


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
def sample_timeline_record():
    """Provide sample TimelineRecord."""
    return TimelineRecord(
        timestamp=datetime(2025, 1, 15, 10, 30, 0),
        unix_timestamp=1705315800.0,
        left_hemisphere=100.5,
        right_hemisphere=95.3,
        left_amplitude=2.0,
        right_amplitude=1.8,
        therapy_status="ON",
        source_file="test_session.json",
        data_hash="abc123def456"
    )


@pytest.fixture
def sample_timeline_records():
    """Provide multiple sample TimelineRecords."""
    return [
        TimelineRecord(
            timestamp=datetime(2025, 1, 15, 10, 30, i),
            unix_timestamp=1705315800.0 + i,
            left_hemisphere=100.0 + i,
            right_hemisphere=95.0 + i,
            therapy_status="ON",
            source_file="test_session.json",
            data_hash=f"hash_{i:04d}"
        )
        for i in range(10)
    ]


# ============================================================================
# Test: insert_batch
# ============================================================================

def test_insert_batch_empty_list(timeline_repository, initialized_patient_db, patient_id):
    """Test inserting empty list returns (0, 0)."""
    inserted, duplicates = timeline_repository.insert_batch(patient_id, [])

    assert inserted == 0
    assert duplicates == 0


def test_insert_batch_single_record(timeline_repository, initialized_patient_db, patient_id, sample_timeline_record):
    """Test inserting single record."""
    records = [sample_timeline_record]
    inserted, duplicates = timeline_repository.insert_batch(patient_id, records)

    assert inserted == 1
    assert duplicates == 0


def test_insert_batch_multiple_records(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test inserting multiple records."""
    inserted, duplicates = timeline_repository.insert_batch(patient_id, sample_timeline_records)

    assert inserted == 10
    assert duplicates == 0


def test_insert_batch_with_duplicates(timeline_repository, initialized_patient_db, patient_id, sample_timeline_record):
    """Test INSERT OR IGNORE skips duplicates based on data_hash."""
    # Insert same record twice
    records = [sample_timeline_record]

    # First insertion
    inserted1, duplicates1 = timeline_repository.insert_batch(patient_id, records)
    assert inserted1 == 1
    assert duplicates1 == 0

    # Second insertion (duplicate)
    inserted2, duplicates2 = timeline_repository.insert_batch(patient_id, records)
    assert inserted2 == 0
    assert duplicates2 == 1


def test_insert_batch_mixed_new_and_duplicate(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test inserting mix of new and duplicate records."""
    # Insert first 5 records
    first_batch = sample_timeline_records[:5]
    inserted1, duplicates1 = timeline_repository.insert_batch(patient_id, first_batch)
    assert inserted1 == 5
    assert duplicates1 == 0

    # Insert all 10 records (5 new + 5 duplicates)
    inserted2, duplicates2 = timeline_repository.insert_batch(patient_id, sample_timeline_records)
    assert inserted2 == 5
    assert duplicates2 == 5


# ============================================================================
# Test: get_by_patient
# ============================================================================

def test_get_by_patient_empty_db(timeline_repository, initialized_patient_db, patient_id):
    """Test get_by_patient returns empty list when no records."""
    records = timeline_repository.get_by_patient(patient_id)
    assert records == []


def test_get_by_patient_with_records(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test get_by_patient returns inserted records."""
    # Insert records
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    # Fetch records
    records = timeline_repository.get_by_patient(patient_id, limit=100)
    assert len(records) == 10
    assert all(isinstance(r, TimelineRecord) for r in records)


def test_get_by_patient_with_limit(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test get_by_patient respects limit parameter."""
    # Insert 10 records
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    # Fetch with limit=5
    records = timeline_repository.get_by_patient(patient_id, limit=5)
    assert len(records) == 5


def test_get_by_patient_with_offset(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test get_by_patient with offset pagination."""
    # Insert 10 records
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    # Fetch first 5
    first_page = timeline_repository.get_by_patient(patient_id, limit=5, offset=0)
    assert len(first_page) == 5

    # Fetch next 5
    second_page = timeline_repository.get_by_patient(patient_id, limit=5, offset=5)
    assert len(second_page) == 5

    # Should be different records
    assert first_page[0].data_hash != second_page[0].data_hash


# ============================================================================
# Test: get_count
# ============================================================================

def test_get_count_empty_db(timeline_repository, initialized_patient_db, patient_id):
    """Test get_count returns 0 when no records."""
    count = timeline_repository.get_count(patient_id)
    assert count == 0


def test_get_count_with_records(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test get_count returns correct count."""
    # Insert 10 records
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    count = timeline_repository.get_count(patient_id)
    assert count == 10


# ============================================================================
# Test: get_date_range
# ============================================================================

def test_get_date_range_empty_db(timeline_repository, initialized_patient_db, patient_id):
    """Test get_date_range returns None when no records."""
    date_range = timeline_repository.get_date_range(patient_id)
    assert date_range is None


def test_get_date_range_with_records(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records):
    """Test get_date_range returns correct min/max dates."""
    # Insert records with timestamps from 10:30:00 to 10:30:09
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    date_range = timeline_repository.get_date_range(patient_id)
    assert date_range is not None

    min_date, max_date = date_range
    assert min_date == datetime(2025, 1, 15, 10, 30, 0)
    assert max_date == datetime(2025, 1, 15, 10, 30, 9)


# ============================================================================
# Test: Error handling
# ============================================================================

def test_insert_batch_database_error(timeline_repository, patient_id, sample_timeline_record):
    """Test insert_batch raises error when database doesn't exist."""
    # Don't initialize database - should fail
    records = [sample_timeline_record]

    with pytest.raises(sqlite3.Error):
        timeline_repository.insert_batch(patient_id, records)


def test_get_by_patient_database_error(timeline_repository, patient_id):
    """Test get_by_patient raises error when database doesn't exist."""
    # Don't initialize database - should fail
    with pytest.raises(sqlite3.Error):
        timeline_repository.get_by_patient(patient_id)


# ============================================================================
# Test: Transaction support
# ============================================================================

def test_insert_batch_with_connection(timeline_repository, initialized_patient_db, patient_id, sample_timeline_record, adapter):
    """Test insert_batch works with provided connection (for transactions)."""
    db_path = initialized_patient_db
    records = [sample_timeline_record]

    with adapter.get_connection(db_path) as conn:
        inserted, duplicates = timeline_repository.insert_batch(patient_id, records, conn=conn)
        conn.commit()

    assert inserted == 1
    assert duplicates == 0

    # Verify record was inserted
    count = timeline_repository.get_count(patient_id)
    assert count == 1


def test_get_by_patient_with_connection(timeline_repository, initialized_patient_db, patient_id, sample_timeline_records, adapter):
    """Test get_by_patient works with provided connection."""
    # Insert records first
    timeline_repository.insert_batch(patient_id, sample_timeline_records)

    db_path = initialized_patient_db
    with adapter.get_connection(db_path) as conn:
        records = timeline_repository.get_by_patient(patient_id, limit=10, conn=conn)

    assert len(records) == 10
