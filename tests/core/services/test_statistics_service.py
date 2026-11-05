"""
Tests for StatisticsService.

Tests the statistics calculation logic, including per-patient statistics,
system-wide statistics, and aggregation across multiple tables.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
from datetime import datetime

from src.core.services.statistics_service import StatisticsService
from src.core.services.patient_service import PatientService
from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories.patient_repository import PatientRepository
from src.infrastructure.database.schema import (
    initialize_global_database
)


@pytest.fixture
def setup_services(tmp_path):
    """Setup services with initialized databases."""
    resolver = PathResolver(base_dir=tmp_path)
    adapter = SQLiteAdapter()

    # Initialize global database
    initialize_global_database(adapter, resolver)

    # Create repositories and services
    patient_repo = PatientRepository(adapter, resolver)
    patient_service = PatientService(patient_repo, adapter, resolver)
    stats_service = StatisticsService(adapter, resolver, patient_repo)

    return stats_service, patient_service, adapter, resolver


def insert_processing_metadata(adapter, patient_db_path, data):
    """Helper to insert test data into processing_metadata table."""
    query = """
        INSERT INTO processing_metadata
        (patient_id, file_name, file_path, file_hash, file_size_bytes,
         timeline_count, timeline_original_count,
         snapshot_count, snapshot_original_count,
         duplicates_skipped, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    with adapter.get_connection(patient_db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, data)
        conn.commit()


# ============================================================================
# Initialization Tests
# ============================================================================

def test_statistics_service_initialization(setup_services):
    """Test StatisticsService initializes with correct dependencies."""
    stats_service, patient_service, adapter, resolver = setup_services

    assert stats_service.adapter == adapter
    assert stats_service.path_resolver == resolver
    assert stats_service.patient_repository is not None


# ============================================================================
# get_patient_statistics Tests (6 tests)
# ============================================================================

def test_get_patient_statistics_no_data(setup_services):
    """Test statistics for patient with no uploaded files."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT001", "Test Patient")

    # Get statistics (should have 0 for everything)
    stats = stats_service.get_patient_statistics("PATIENT001")

    assert stats is not None
    assert stats.patient_id == "PATIENT001"
    assert stats.total_files_uploaded == 0
    assert stats.snapshots_original == 0
    assert stats.snapshots_deduplicated == 0
    assert stats.timeline_original == 0
    assert stats.timeline_deduplicated == 0
    assert stats.total_duplicates_skipped == 0
    assert stats.last_upload_date is None


def test_get_patient_statistics_with_data(setup_services):
    """Test statistics for patient with uploaded files."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT002", "Data Patient")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT002")

    # Insert test data
    upload_time = datetime.now().isoformat()
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT002",
        "file1.json",
        "/path/to/file1.json",
        "hash1",
        1024,
        100,  # timeline_count (deduplicated)
        120,  # timeline_original_count
        50,   # snapshot_count (deduplicated)
        60,   # snapshot_original_count
        30,   # duplicates_skipped
        upload_time
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT002")

    assert stats is not None
    assert stats.patient_id == "PATIENT002"
    assert stats.total_files_uploaded == 1
    assert stats.snapshots_original == 60
    assert stats.snapshots_deduplicated == 50
    assert stats.timeline_original == 120
    assert stats.timeline_deduplicated == 100
    assert stats.total_duplicates_skipped == 30
    assert stats.last_upload_date is not None


def test_get_patient_statistics_multiple_files(setup_services):
    """Test statistics aggregation across multiple files."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT003", "Multi File Patient")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT003")

    # Insert multiple files
    upload_time1 = datetime(2025, 1, 1, 10, 0, 0).isoformat()
    upload_time2 = datetime(2025, 1, 2, 10, 0, 0).isoformat()
    upload_time3 = datetime(2025, 1, 3, 10, 0, 0).isoformat()

    insert_processing_metadata(adapter, patient_db, (
        "PATIENT003", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time1
    ))
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT003", "file2.json", "/path/file2.json", "hash2", 2048,
        200, 250, 75, 90, 65, upload_time2
    ))
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT003", "file3.json", "/path/file3.json", "hash3", 3072,
        150, 180, 100, 120, 50, upload_time3
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT003")

    assert stats is not None
    assert stats.total_files_uploaded == 3
    assert stats.snapshots_original == 270  # 60 + 90 + 120
    assert stats.snapshots_deduplicated == 225  # 50 + 75 + 100
    assert stats.timeline_original == 550  # 120 + 250 + 180
    assert stats.timeline_deduplicated == 450  # 100 + 200 + 150
    assert stats.total_duplicates_skipped == 145  # 30 + 65 + 50
    assert stats.last_upload_date == datetime(2025, 1, 3, 10, 0, 0)


def test_get_patient_statistics_nonexistent_patient(setup_services):
    """Test statistics for nonexistent patient."""
    stats_service, patient_service, adapter, resolver = setup_services

    stats = stats_service.get_patient_statistics("NONEXISTENT")

    assert stats is None


def test_get_patient_statistics_reduction_percent(setup_services):
    """Test reduction percentage calculations."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT004", "Reduction Test")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT004")

    # Insert data with known reduction
    upload_time = datetime.now().isoformat()
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT004", "file1.json", "/path/file1.json", "hash1", 1024,
        80,   # timeline_count (deduplicated) - 20% reduction from 100
        100,  # timeline_original_count
        75,   # snapshot_count (deduplicated) - 25% reduction from 100
        100,  # snapshot_original_count
        45,   # duplicates_skipped
        upload_time
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT004")

    assert stats is not None
    assert stats.snapshots_reduction_percent == pytest.approx(25.0, rel=1e-2)
    assert stats.timeline_reduction_percent == pytest.approx(20.0, rel=1e-2)


def test_get_patient_statistics_zero_reduction(setup_services):
    """Test reduction percentage when no duplicates exist."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT005", "Zero Reduction")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT005")

    # Insert data with no reduction (all unique)
    upload_time = datetime.now().isoformat()
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT005", "file1.json", "/path/file1.json", "hash1", 1024,
        100,  # timeline_count (same as original)
        100,  # timeline_original_count
        50,   # snapshot_count (same as original)
        50,   # snapshot_original_count
        0,    # duplicates_skipped
        upload_time
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT005")

    assert stats is not None
    assert stats.snapshots_reduction_percent == 0.0
    assert stats.timeline_reduction_percent == 0.0


# ============================================================================
# get_all_patient_statistics Tests (4 tests)
# ============================================================================

def test_get_all_patient_statistics_empty(setup_services):
    """Test getting statistics when no patients exist."""
    stats_service, patient_service, adapter, resolver = setup_services

    all_stats = stats_service.get_all_patient_statistics(active_only=True)

    assert all_stats == {}


def test_get_all_patient_statistics_multiple_patients(setup_services):
    """Test getting statistics for multiple patients."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create multiple patients
    patient_service.create_patient("PATIENT010", "Patient A")
    patient_service.create_patient("PATIENT011", "Patient B")
    patient_service.create_patient("PATIENT012", "Patient C")

    # Add data to one patient
    patient_db = resolver.get_patient_db_path("PATIENT010")
    upload_time = datetime.now().isoformat()
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT010", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time
    ))

    # Get all statistics
    all_stats = stats_service.get_all_patient_statistics(active_only=True)

    assert len(all_stats) == 3
    assert "PATIENT010" in all_stats
    assert "PATIENT011" in all_stats
    assert "PATIENT012" in all_stats

    # Verify patient with data
    assert all_stats["PATIENT010"].total_files_uploaded == 1
    assert all_stats["PATIENT010"].timeline_deduplicated == 100

    # Verify patients without data
    assert all_stats["PATIENT011"].total_files_uploaded == 0
    assert all_stats["PATIENT012"].total_files_uploaded == 0


def test_get_all_patient_statistics_excludes_inactive(setup_services):
    """Test that inactive patients are excluded when active_only=True."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patients
    patient_service.create_patient("PATIENT020", "Active Patient")
    patient_service.create_patient("PATIENT021", "Inactive Patient")

    # Soft delete one patient
    patient_service.delete_patient("PATIENT021")

    # Get active statistics
    active_stats = stats_service.get_all_patient_statistics(active_only=True)

    assert len(active_stats) == 1
    assert "PATIENT020" in active_stats
    assert "PATIENT021" not in active_stats


def test_get_all_patient_statistics_includes_inactive(setup_services):
    """Test that inactive patients are included when active_only=False."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patients
    patient_service.create_patient("PATIENT030", "Active Patient")
    patient_service.create_patient("PATIENT031", "Inactive Patient")

    # Soft delete one patient
    patient_service.delete_patient("PATIENT031")

    # Get all statistics
    all_stats = stats_service.get_all_patient_statistics(active_only=False)

    assert len(all_stats) == 2
    assert "PATIENT030" in all_stats
    assert "PATIENT031" in all_stats


# ============================================================================
# get_system_statistics Tests (3 tests)
# ============================================================================

def test_get_system_statistics_empty(setup_services):
    """Test system statistics when no patients exist."""
    stats_service, patient_service, adapter, resolver = setup_services

    sys_stats = stats_service.get_system_statistics()

    assert sys_stats['total_patients'] == 0
    assert sys_stats['active_patients'] == 0
    assert sys_stats['inactive_patients'] == 0
    assert sys_stats['total_files_uploaded'] == 0
    assert sys_stats['total_snapshots'] == 0
    assert sys_stats['total_timeline'] == 0
    assert sys_stats['total_duplicates_skipped'] == 0
    assert 'calculated_at' in sys_stats


def test_get_system_statistics_multiple_patients(setup_services):
    """Test system statistics aggregation across patients."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patients
    patient_service.create_patient("PATIENT040", "Patient A")
    patient_service.create_patient("PATIENT041", "Patient B")

    # Add data to both patients
    patient_db1 = resolver.get_patient_db_path("PATIENT040")
    patient_db2 = resolver.get_patient_db_path("PATIENT041")

    upload_time = datetime.now().isoformat()

    insert_processing_metadata(adapter, patient_db1, (
        "PATIENT040", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time
    ))

    insert_processing_metadata(adapter, patient_db2, (
        "PATIENT041", "file2.json", "/path/file2.json", "hash2", 2048,
        200, 250, 75, 90, 65, upload_time
    ))

    # Get system statistics
    sys_stats = stats_service.get_system_statistics()

    assert sys_stats['total_patients'] == 2
    assert sys_stats['active_patients'] == 2
    assert sys_stats['inactive_patients'] == 0
    assert sys_stats['total_files_uploaded'] == 2
    assert sys_stats['total_snapshots'] == 125  # 50 + 75
    assert sys_stats['total_timeline'] == 300  # 100 + 200
    assert sys_stats['total_duplicates_skipped'] == 95  # 30 + 65


def test_get_system_statistics_with_inactive(setup_services):
    """Test system statistics includes inactive patients."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patients
    patient_service.create_patient("PATIENT050", "Active")
    patient_service.create_patient("PATIENT051", "Inactive")

    # Soft delete one
    patient_service.delete_patient("PATIENT051")

    # Get system statistics
    sys_stats = stats_service.get_system_statistics()

    assert sys_stats['total_patients'] == 2
    assert sys_stats['active_patients'] == 1
    assert sys_stats['inactive_patients'] == 1


# ============================================================================
# Edge Cases Tests (3 tests)
# ============================================================================

def test_statistics_handles_null_values(setup_services):
    """Test statistics handle NULL values gracefully."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT060", "Null Test")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT060")

    # Insert data with NULL values (using 0 as default)
    query = """
        INSERT INTO processing_metadata
        (patient_id, file_name, file_path, file_hash, processed_at)
        VALUES (?, ?, ?, ?, ?)
    """

    with adapter.get_connection(patient_db) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (
            "PATIENT060",
            "file1.json",
            "/path/file1.json",
            "hash1",
            datetime.now().isoformat()
        ))
        conn.commit()

    # Get statistics (should handle NULLs/defaults)
    stats = stats_service.get_patient_statistics("PATIENT060")

    assert stats is not None
    assert stats.total_files_uploaded == 1
    assert stats.snapshots_original == 0
    assert stats.snapshots_deduplicated == 0
    assert stats.timeline_original == 0
    assert stats.timeline_deduplicated == 0


def test_statistics_handles_large_numbers(setup_services):
    """Test statistics handle large numbers correctly."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT061", "Large Numbers")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT061")

    # Insert data with large numbers
    upload_time = datetime.now().isoformat()
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT061", "file1.json", "/path/file1.json", "hash1", 1024000000,
        1000000, 1200000, 500000, 600000, 300000, upload_time
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT061")

    assert stats is not None
    assert stats.timeline_original == 1200000
    assert stats.timeline_deduplicated == 1000000
    assert stats.snapshots_original == 600000
    assert stats.snapshots_deduplicated == 500000


def test_statistics_timestamp_handling(setup_services):
    """Test statistics correctly parse and order timestamps."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT062", "Timestamp Test")

    # Get patient database
    patient_db = resolver.get_patient_db_path("PATIENT062")

    # Insert files with different timestamps
    upload_time1 = datetime(2025, 1, 1, 10, 0, 0).isoformat()
    upload_time2 = datetime(2025, 1, 15, 14, 30, 0).isoformat()
    upload_time3 = datetime(2025, 1, 10, 9, 45, 0).isoformat()

    insert_processing_metadata(adapter, patient_db, (
        "PATIENT062", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time1
    ))
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT062", "file2.json", "/path/file2.json", "hash2", 2048,
        200, 250, 75, 90, 65, upload_time2  # Latest
    ))
    insert_processing_metadata(adapter, patient_db, (
        "PATIENT062", "file3.json", "/path/file3.json", "hash3", 3072,
        150, 180, 100, 120, 50, upload_time3
    ))

    # Get statistics
    stats = stats_service.get_patient_statistics("PATIENT062")

    assert stats is not None
    # Should return the latest timestamp
    assert stats.last_upload_date == datetime(2025, 1, 15, 14, 30, 0)


# ============================================================================
# Integration Tests (2 tests)
# ============================================================================

def test_statistics_integration_full_workflow(setup_services):
    """Test complete workflow: create patient, add files, get statistics."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patient
    patient_service.create_patient("PATIENT100", "Integration Test")

    # Verify initial statistics
    stats1 = stats_service.get_patient_statistics("PATIENT100")
    assert stats1.total_files_uploaded == 0

    # Add files
    patient_db = resolver.get_patient_db_path("PATIENT100")
    upload_time = datetime.now().isoformat()

    insert_processing_metadata(adapter, patient_db, (
        "PATIENT100", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time
    ))

    # Verify updated statistics
    stats2 = stats_service.get_patient_statistics("PATIENT100")
    assert stats2.total_files_uploaded == 1
    assert stats2.timeline_deduplicated == 100
    assert stats2.snapshots_deduplicated == 50

    # Get system statistics
    sys_stats = stats_service.get_system_statistics()
    assert sys_stats['total_patients'] == 1
    assert sys_stats['total_files_uploaded'] == 1


def test_statistics_consistency_across_methods(setup_services):
    """Test consistency between get_patient_statistics and get_all_patient_statistics."""
    stats_service, patient_service, adapter, resolver = setup_services

    # Create patients with data
    patient_service.create_patient("PATIENT110", "Patient A")
    patient_service.create_patient("PATIENT111", "Patient B")

    # Add data
    patient_db1 = resolver.get_patient_db_path("PATIENT110")
    patient_db2 = resolver.get_patient_db_path("PATIENT111")

    upload_time = datetime.now().isoformat()

    insert_processing_metadata(adapter, patient_db1, (
        "PATIENT110", "file1.json", "/path/file1.json", "hash1", 1024,
        100, 120, 50, 60, 30, upload_time
    ))

    insert_processing_metadata(adapter, patient_db2, (
        "PATIENT111", "file2.json", "/path/file2.json", "hash2", 2048,
        200, 250, 75, 90, 65, upload_time
    ))

    # Get individual statistics
    stats1 = stats_service.get_patient_statistics("PATIENT110")
    stats2 = stats_service.get_patient_statistics("PATIENT111")

    # Get all statistics
    all_stats = stats_service.get_all_patient_statistics(active_only=True)

    # Verify consistency
    assert all_stats["PATIENT110"].total_files_uploaded == stats1.total_files_uploaded
    assert all_stats["PATIENT110"].timeline_deduplicated == stats1.timeline_deduplicated
    assert all_stats["PATIENT111"].total_files_uploaded == stats2.total_files_uploaded
    assert all_stats["PATIENT111"].timeline_deduplicated == stats2.timeline_deduplicated
