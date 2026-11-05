"""
Tests for SnapshotRepository.

This module tests the SnapshotRepository class which provides database operations
for snapshot_data table in per-patient databases.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import sqlite3
import json
from datetime import datetime

from src.infrastructure.repositories.snapshot_repository import SnapshotRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver
from src.core.models import SnapshotRecord
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
def snapshot_repository(adapter, path_resolver):
    """Provide SnapshotRepository instance."""
    return SnapshotRepository(adapter, path_resolver)


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
def sample_snapshot_record():
    """Provide sample SnapshotRecord."""
    return SnapshotRecord(
        timestamp=datetime(2025, 1, 15, 10, 30, 0),
        unix_timestamp=1705315800.0,
        event_type="PatientTriggered",
        event_name="Snapshot Test",
        frequency_data=json.dumps([1.0, 2.0, 3.0, 4.0, 5.0]),
        power_data=json.dumps([10.0, 20.0, 30.0, 40.0, 50.0]),
        hemisphere="LEFT",
        source_file="test_session.json",
        duration_seconds=30.0,
        data_hash="xyz789abc123"
    )


@pytest.fixture
def sample_snapshot_records():
    """Provide multiple sample SnapshotRecords."""
    return [
        SnapshotRecord(
            timestamp=datetime(2025, 1, 15, 10, 30, i),
            unix_timestamp=1705315800.0 + i,
            event_type="PatientTriggered" if i % 2 == 0 else "SystemTriggered",
            frequency_data=json.dumps([1.0 + i, 2.0 + i, 3.0 + i]),
            power_data=json.dumps([10.0 + i, 20.0 + i, 30.0 + i]),
            hemisphere="LEFT" if i % 2 == 0 else "RIGHT",
            source_file="test_session.json",
            data_hash=f"snapshot_hash_{i:04d}"
        )
        for i in range(10)
    ]


# ============================================================================
# Test: insert_batch
# ============================================================================

def test_insert_batch_empty_list(snapshot_repository, initialized_patient_db, patient_id):
    """Test inserting empty list returns (0, 0)."""
    inserted, duplicates = snapshot_repository.insert_batch(patient_id, [])

    assert inserted == 0
    assert duplicates == 0


def test_insert_batch_single_record(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_record):
    """Test inserting single record."""
    records = [sample_snapshot_record]
    inserted, duplicates = snapshot_repository.insert_batch(patient_id, records)

    assert inserted == 1
    assert duplicates == 0


def test_insert_batch_multiple_records(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test inserting multiple records."""
    inserted, duplicates = snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    assert inserted == 10
    assert duplicates == 0


def test_insert_batch_with_duplicates(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_record):
    """Test INSERT OR IGNORE skips duplicates based on data_hash."""
    # Insert same record twice
    records = [sample_snapshot_record]

    # First insertion
    inserted1, duplicates1 = snapshot_repository.insert_batch(patient_id, records)
    assert inserted1 == 1
    assert duplicates1 == 0

    # Second insertion (duplicate)
    inserted2, duplicates2 = snapshot_repository.insert_batch(patient_id, records)
    assert inserted2 == 0
    assert duplicates2 == 1


def test_insert_batch_mixed_new_and_duplicate(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test inserting mix of new and duplicate records."""
    # Insert first 5 records
    first_batch = sample_snapshot_records[:5]
    inserted1, duplicates1 = snapshot_repository.insert_batch(patient_id, first_batch)
    assert inserted1 == 5
    assert duplicates1 == 0

    # Insert all 10 records (5 new + 5 duplicates)
    inserted2, duplicates2 = snapshot_repository.insert_batch(patient_id, sample_snapshot_records)
    assert inserted2 == 5
    assert duplicates2 == 5


def test_insert_batch_json_fields(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_record):
    """Test JSON fields (frequency_data, power_data) are stored correctly."""
    records = [sample_snapshot_record]
    snapshot_repository.insert_batch(patient_id, records)

    # Fetch record
    fetched = snapshot_repository.get_by_patient(patient_id, limit=1)
    assert len(fetched) == 1

    record = fetched[0]
    assert record.frequency_data == json.dumps([1.0, 2.0, 3.0, 4.0, 5.0])
    assert record.power_data == json.dumps([10.0, 20.0, 30.0, 40.0, 50.0])


# ============================================================================
# Test: get_by_patient
# ============================================================================

def test_get_by_patient_empty_db(snapshot_repository, initialized_patient_db, patient_id):
    """Test get_by_patient returns empty list when no records."""
    records = snapshot_repository.get_by_patient(patient_id)
    assert records == []


def test_get_by_patient_with_records(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test get_by_patient returns inserted records."""
    # Insert records
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    # Fetch records
    records = snapshot_repository.get_by_patient(patient_id, limit=100)
    assert len(records) == 10
    assert all(isinstance(r, SnapshotRecord) for r in records)


def test_get_by_patient_with_limit(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test get_by_patient respects limit parameter."""
    # Insert 10 records
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    # Fetch with limit=5
    records = snapshot_repository.get_by_patient(patient_id, limit=5)
    assert len(records) == 5


def test_get_by_patient_with_offset(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test get_by_patient with offset pagination."""
    # Insert 10 records
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    # Fetch first 5
    first_page = snapshot_repository.get_by_patient(patient_id, limit=5, offset=0)
    assert len(first_page) == 5

    # Fetch next 5
    second_page = snapshot_repository.get_by_patient(patient_id, limit=5, offset=5)
    assert len(second_page) == 5

    # Should be different records
    assert first_page[0].data_hash != second_page[0].data_hash


# ============================================================================
# Test: get_count
# ============================================================================

def test_get_count_empty_db(snapshot_repository, initialized_patient_db, patient_id):
    """Test get_count returns 0 when no records."""
    count = snapshot_repository.get_count(patient_id)
    assert count == 0


def test_get_count_with_records(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test get_count returns correct count."""
    # Insert 10 records
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    count = snapshot_repository.get_count(patient_id)
    assert count == 10


# ============================================================================
# Test: get_date_range
# ============================================================================

def test_get_date_range_empty_db(snapshot_repository, initialized_patient_db, patient_id):
    """Test get_date_range returns None when no records."""
    date_range = snapshot_repository.get_date_range(patient_id)
    assert date_range is None


def test_get_date_range_with_records(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records):
    """Test get_date_range returns correct min/max dates."""
    # Insert records with timestamps from 10:30:00 to 10:30:09
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    date_range = snapshot_repository.get_date_range(patient_id)
    assert date_range is not None

    min_date, max_date = date_range
    assert min_date == datetime(2025, 1, 15, 10, 30, 0)
    assert max_date == datetime(2025, 1, 15, 10, 30, 9)


# ============================================================================
# Test: Error handling
# ============================================================================

def test_insert_batch_database_error(snapshot_repository, patient_id, sample_snapshot_record):
    """Test insert_batch raises error when database doesn't exist."""
    # Don't initialize database - should fail
    records = [sample_snapshot_record]

    with pytest.raises(sqlite3.Error):
        snapshot_repository.insert_batch(patient_id, records)


def test_get_by_patient_database_error(snapshot_repository, patient_id):
    """Test get_by_patient raises error when database doesn't exist."""
    # Don't initialize database - should fail
    with pytest.raises(sqlite3.Error):
        snapshot_repository.get_by_patient(patient_id)


# ============================================================================
# Test: Transaction support
# ============================================================================

def test_insert_batch_with_connection(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_record, adapter):
    """Test insert_batch works with provided connection (for transactions)."""
    db_path = initialized_patient_db
    records = [sample_snapshot_record]

    with adapter.get_connection(db_path) as conn:
        inserted, duplicates = snapshot_repository.insert_batch(patient_id, records, conn=conn)
        conn.commit()

    assert inserted == 1
    assert duplicates == 0

    # Verify record was inserted
    count = snapshot_repository.get_count(patient_id)
    assert count == 1


def test_get_by_patient_with_connection(snapshot_repository, initialized_patient_db, patient_id, sample_snapshot_records, adapter):
    """Test get_by_patient works with provided connection."""
    # Insert records first
    snapshot_repository.insert_batch(patient_id, sample_snapshot_records)

    db_path = initialized_patient_db
    with adapter.get_connection(db_path) as conn:
        records = snapshot_repository.get_by_patient(patient_id, limit=10, conn=conn)

    assert len(records) == 10
