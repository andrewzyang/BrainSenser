"""
Tests for PatientService.

Tests the patient lifecycle orchestration logic, including creation,
retrieval, updates, and deletion. Focuses on service-level business
logic and orchestration across repositories and file system.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
from unittest.mock import patch

from src.core.services.patient_service import PatientService
from src.core.services.exceptions import (
    InvalidPatientIDError,
    PatientAlreadyExistsError,
    DatabaseInitializationError,
)
from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.repositories.patient_repository import PatientRepository
from src.infrastructure.database.schema import initialize_global_database


@pytest.fixture
def setup_global_db(tmp_path):
    """Setup global database for testing."""
    resolver = PathResolver(base_dir=tmp_path)
    adapter = SQLiteAdapter()

    # Initialize global database
    initialize_global_database(adapter, resolver)

    return adapter, resolver


@pytest.fixture
def patient_service(setup_global_db):
    """Create PatientService instance with initialized database."""
    adapter, resolver = setup_global_db
    repository = PatientRepository(adapter, resolver)
    service = PatientService(repository, adapter, resolver)
    return service, adapter, resolver


# ============================================================================
# Initialization Tests
# ============================================================================

def test_patient_service_initialization(setup_global_db):
    """Test PatientService initializes with correct dependencies."""
    adapter, resolver = setup_global_db
    repository = PatientRepository(adapter, resolver)

    service = PatientService(repository, adapter, resolver)

    assert service.repository == repository
    assert service.adapter == adapter
    assert service.path_resolver == resolver


# ============================================================================
# create_patient Tests (8 tests)
# ============================================================================

def test_create_patient_success(patient_service):
    """Test successful patient creation."""
    service, adapter, resolver = patient_service

    patient = service.create_patient(
        patient_id="PATIENT001",
        patient_name="John Doe"
    )

    assert patient.patient_id == "PATIENT001"
    assert patient.patient_name == "John Doe"
    assert patient.is_active is True
    assert patient.metadata is None

    # Verify directory created
    patient_dir = resolver.get_patient_directory("PATIENT001")
    assert patient_dir.exists()

    # Verify database created
    patient_db = resolver.get_patient_db_path("PATIENT001")
    assert patient_db.exists()


def test_create_patient_with_metadata(patient_service):
    """Test patient creation with metadata."""
    service, adapter, resolver = patient_service

    metadata = {"diagnosis": "Parkinson's Disease", "age": 65}

    patient = service.create_patient(
        patient_id="PATIENT002",
        patient_name="Jane Smith",
        metadata=metadata
    )

    assert patient.patient_id == "PATIENT002"
    assert patient.patient_name == "Jane Smith"
    assert patient.metadata == metadata
    assert patient.metadata["diagnosis"] == "Parkinson's Disease"
    assert patient.metadata["age"] == 65


def test_create_patient_invalid_id(patient_service):
    """Test patient creation with invalid patient ID."""
    service, adapter, resolver = patient_service

    # Invalid ID with path traversal
    with pytest.raises(InvalidPatientIDError, match="Invalid patient ID"):
        service.create_patient(
            patient_id="../etc/passwd",
            patient_name="Invalid Patient"
        )

    # Invalid ID with forward slash
    with pytest.raises(InvalidPatientIDError, match="Invalid patient ID"):
        service.create_patient(
            patient_id="PATIENT/001",
            patient_name="Invalid Patient"
        )

    # Empty ID
    with pytest.raises(InvalidPatientIDError, match="Invalid patient ID"):
        service.create_patient(
            patient_id="",
            patient_name="Invalid Patient"
        )


def test_create_patient_duplicate(patient_service):
    """Test patient creation with duplicate patient ID."""
    service, adapter, resolver = patient_service

    # Create first patient
    service.create_patient(
        patient_id="PATIENT003",
        patient_name="First Patient"
    )

    # Attempt to create duplicate
    with pytest.raises(PatientAlreadyExistsError, match="already exists"):
        service.create_patient(
            patient_id="PATIENT003",
            patient_name="Duplicate Patient"
        )


def test_create_patient_directory_created(patient_service):
    """Test that patient directory is created correctly."""
    service, adapter, resolver = patient_service

    patient = service.create_patient(
        patient_id="PATIENT004",
        patient_name="Directory Test"
    )

    # Verify directory structure
    patient_dir = resolver.get_patient_directory("PATIENT004")
    assert patient_dir.exists()
    assert patient_dir.is_dir()
    assert patient_dir.name == "PATIENT004"


def test_create_patient_database_initialized(patient_service):
    """Test that patient database is initialized with correct schema."""
    service, adapter, resolver = patient_service

    patient = service.create_patient(
        patient_id="PATIENT005",
        patient_name="Database Test"
    )

    # Verify database exists
    patient_db = resolver.get_patient_db_path("PATIENT005")
    assert patient_db.exists()

    # Verify schema (check for expected tables)
    with adapter.get_connection(patient_db) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

    expected_tables = [
        "timeline_data",
        "snapshot_data",
        "processing_metadata",
        "therapy_changes"
    ]

    for table in expected_tables:
        assert table in tables


def test_create_patient_registered_in_registry(patient_service):
    """Test that patient is registered in patient_registry."""
    service, adapter, resolver = patient_service

    patient = service.create_patient(
        patient_id="PATIENT006",
        patient_name="Registry Test"
    )

    # Verify patient exists in repository
    assert service.repository.exists("PATIENT006")

    # Verify patient can be retrieved
    retrieved = service.repository.get_by_id("PATIENT006")
    assert retrieved is not None
    assert retrieved.patient_id == "PATIENT006"
    assert retrieved.patient_name == "Registry Test"


def test_create_patient_atomic_operation(patient_service):
    """Test that patient creation is atomic (all-or-nothing)."""
    service, adapter, resolver = patient_service

    # Mock initialize_patient_database to fail
    with patch('src.core.services.patient_service.initialize_patient_database') as mock_init:
        mock_init.return_value = False  # Simulate database init failure

        with pytest.raises(DatabaseInitializationError):
            service.create_patient(
                patient_id="PATIENT007",
                patient_name="Atomic Test"
            )

        # Verify patient was NOT created in registry
        assert not service.repository.exists("PATIENT007")


# ============================================================================
# get_patient Tests (3 tests)
# ============================================================================

def test_get_patient_existing(patient_service):
    """Test retrieving existing patient."""
    service, adapter, resolver = patient_service

    # Create patient
    created = service.create_patient(
        patient_id="PATIENT010",
        patient_name="Get Test"
    )

    # Retrieve patient
    retrieved = service.get_patient("PATIENT010")

    assert retrieved is not None
    assert retrieved.patient_id == "PATIENT010"
    assert retrieved.patient_name == "Get Test"


def test_get_patient_nonexistent(patient_service):
    """Test retrieving nonexistent patient."""
    service, adapter, resolver = patient_service

    retrieved = service.get_patient("NONEXISTENT")

    assert retrieved is None


def test_get_patient_returns_none_for_invalid_id(patient_service):
    """Test that get_patient returns None for invalid (but safe) IDs."""
    service, adapter, resolver = patient_service

    # Valid format but doesn't exist
    retrieved = service.get_patient("PATIENT999")

    assert retrieved is None


# ============================================================================
# get_all_active_patients Tests (4 tests)
# ============================================================================

def test_get_all_active_patients_empty(patient_service):
    """Test getting active patients when none exist."""
    service, adapter, resolver = patient_service

    patients = service.get_all_active_patients()

    assert patients == []


def test_get_all_active_patients_multiple(patient_service):
    """Test getting multiple active patients."""
    service, adapter, resolver = patient_service

    # Create multiple patients
    service.create_patient("PATIENT020", "Alice")
    service.create_patient("PATIENT021", "Bob")
    service.create_patient("PATIENT022", "Charlie")

    patients = service.get_all_active_patients()

    assert len(patients) == 3
    patient_ids = [p.patient_id for p in patients]
    assert "PATIENT020" in patient_ids
    assert "PATIENT021" in patient_ids
    assert "PATIENT022" in patient_ids


def test_get_all_active_patients_excludes_inactive(patient_service):
    """Test that inactive patients are excluded."""
    service, adapter, resolver = patient_service

    # Create patients
    service.create_patient("PATIENT030", "Active Patient")
    service.create_patient("PATIENT031", "Inactive Patient")

    # Soft delete one patient
    service.delete_patient("PATIENT031")

    # Get active patients
    patients = service.get_all_active_patients()

    assert len(patients) == 1
    assert patients[0].patient_id == "PATIENT030"


def test_get_all_active_patients_sorted_by_name(patient_service):
    """Test that patients are returned sorted by name."""
    service, adapter, resolver = patient_service

    # Create patients in random order
    service.create_patient("PATIENT040", "Zelda")
    service.create_patient("PATIENT041", "Alice")
    service.create_patient("PATIENT042", "Mike")

    patients = service.get_all_active_patients()

    # Should be sorted by patient_name
    names = [p.patient_name for p in patients]
    assert names == ["Alice", "Mike", "Zelda"]


# ============================================================================
# update_patient Tests (3 tests)
# ============================================================================

def test_update_patient_name(patient_service):
    """Test updating patient name."""
    service, adapter, resolver = patient_service

    # Create patient
    service.create_patient("PATIENT050", "Old Name")

    # Update name
    updated = service.update_patient("PATIENT050", patient_name="New Name")

    assert updated is not None
    assert updated.patient_name == "New Name"

    # Verify update persisted
    retrieved = service.get_patient("PATIENT050")
    assert retrieved.patient_name == "New Name"


def test_update_patient_metadata(patient_service):
    """Test updating patient metadata."""
    service, adapter, resolver = patient_service

    # Create patient with initial metadata
    service.create_patient(
        "PATIENT051",
        "Metadata Test",
        metadata={"age": 60}
    )

    # Update metadata
    new_metadata = {"age": 61, "diagnosis": "PD"}
    updated = service.update_patient("PATIENT051", metadata=new_metadata)

    assert updated is not None
    assert updated.metadata == new_metadata
    assert updated.metadata["age"] == 61
    assert updated.metadata["diagnosis"] == "PD"


def test_update_patient_nonexistent(patient_service):
    """Test updating nonexistent patient."""
    service, adapter, resolver = patient_service

    updated = service.update_patient("NONEXISTENT", patient_name="New Name")

    assert updated is None


# ============================================================================
# delete_patient Tests (3 tests)
# ============================================================================

def test_delete_patient_existing(patient_service):
    """Test permanently deleting existing patient."""
    service, adapter, resolver = patient_service

    # Create patient
    service.create_patient("PATIENT060", "Delete Test")

    # Verify patient exists
    assert service.patient_exists("PATIENT060")

    # Delete patient
    result = service.delete_patient("PATIENT060")

    assert result is True

    # Verify patient is completely removed (hard delete)
    assert not service.patient_exists("PATIENT060")

    # Verify patient not in active list
    active_patients = service.get_all_active_patients()
    patient_ids = [p.patient_id for p in active_patients]
    assert "PATIENT060" not in patient_ids

    # Verify patient not in all patients list either
    all_patients = service.get_all_patients()
    all_patient_ids = [p.patient_id for p in all_patients]
    assert "PATIENT060" not in all_patient_ids


def test_delete_patient_nonexistent(patient_service):
    """Test deleting nonexistent patient."""
    service, adapter, resolver = patient_service

    result = service.delete_patient("NONEXISTENT")

    assert result is False


def test_delete_patient_data_removed(patient_service):
    """Test that patient data is completely removed after permanent delete."""
    service, adapter, resolver = patient_service

    # Create patient
    service.create_patient("PATIENT061", "Remove Test")

    # Get patient directory and database paths
    patient_dir = resolver.get_patient_directory("PATIENT061")
    patient_db = resolver.get_patient_db_path("PATIENT061")

    # Verify they exist before deletion
    assert patient_dir.exists()
    assert patient_db.exists()

    # Delete patient
    result = service.delete_patient("PATIENT061")
    assert result is True

    # Verify directory and database are removed (hard delete)
    assert not patient_dir.exists()
    assert not patient_db.exists()

    # Verify patient record is completely removed
    all_patients = service.get_all_patients()
    patient_ids = [p.patient_id for p in all_patients]
    assert "PATIENT061" not in patient_ids


# ============================================================================
# patient_exists Tests (2 tests)
# ============================================================================

def test_patient_exists_true(patient_service):
    """Test patient_exists returns True for existing patient."""
    service, adapter, resolver = patient_service

    service.create_patient("PATIENT070", "Exists Test")

    assert service.patient_exists("PATIENT070") is True


def test_patient_exists_false(patient_service):
    """Test patient_exists returns False for nonexistent patient."""
    service, adapter, resolver = patient_service

    assert service.patient_exists("NONEXISTENT") is False


# ============================================================================
# get_patient_count Tests (2 tests)
# ============================================================================

def test_get_patient_count_active_only(patient_service):
    """Test getting count of active patients only."""
    service, adapter, resolver = patient_service

    # Create patients
    service.create_patient("PATIENT080", "Active 1")
    service.create_patient("PATIENT081", "Active 2")
    service.create_patient("PATIENT082", "Inactive")

    # Soft delete one
    service.delete_patient("PATIENT082")

    # Get active count
    count = service.get_patient_count(active_only=True)

    assert count == 2


def test_get_patient_count_all(patient_service):
    """Test getting count of all patients."""
    service, adapter, resolver = patient_service

    # Create patients
    service.create_patient("PATIENT090", "Patient 1")
    service.create_patient("PATIENT091", "Patient 2")
    service.create_patient("PATIENT092", "Patient 3")

    # Soft delete one
    service.delete_patient("PATIENT092")

    # Get all count
    count = service.get_patient_count(active_only=False)

    assert count == 3


# ============================================================================
# Integration Tests (3 tests)
# ============================================================================

def test_full_patient_lifecycle(patient_service):
    """Test complete patient lifecycle: create -> update -> delete."""
    service, adapter, resolver = patient_service

    # Create
    patient = service.create_patient(
        "PATIENT100",
        "Lifecycle Test",
        metadata={"age": 60}
    )
    assert patient.patient_id == "PATIENT100"
    assert patient.is_active is True

    # Update
    updated = service.update_patient(
        "PATIENT100",
        patient_name="Updated Name",
        metadata={"age": 61}
    )
    assert updated.patient_name == "Updated Name"
    assert updated.metadata["age"] == 61

    # Delete
    result = service.delete_patient("PATIENT100")
    assert result is True

    # Verify inactive
    retrieved = service.get_patient("PATIENT100")
    assert retrieved.is_active is False


def test_multiple_patients_independent(patient_service):
    """Test that multiple patients are managed independently."""
    service, adapter, resolver = patient_service

    # Create multiple patients
    service.create_patient("PATIENT110", "Patient 1")
    service.create_patient("PATIENT111", "Patient 2")
    service.create_patient("PATIENT112", "Patient 3")

    # Verify each has own directory
    dir1 = resolver.get_patient_directory("PATIENT110")
    dir2 = resolver.get_patient_directory("PATIENT111")
    dir3 = resolver.get_patient_directory("PATIENT112")

    assert dir1 != dir2 != dir3
    assert all([dir1.exists(), dir2.exists(), dir3.exists()])

    # Verify each has own database
    db1 = resolver.get_patient_db_path("PATIENT110")
    db2 = resolver.get_patient_db_path("PATIENT111")
    db3 = resolver.get_patient_db_path("PATIENT112")

    assert db1 != db2 != db3
    assert all([db1.exists(), db2.exists(), db3.exists()])


def test_service_error_handling(patient_service):
    """Test service handles errors gracefully."""
    service, adapter, resolver = patient_service

    # Invalid patient ID (with path traversal)
    with pytest.raises(InvalidPatientIDError):
        service.create_patient("../invalid", "Bad ID")

    # Duplicate patient
    service.create_patient("PATIENT120", "Original")
    with pytest.raises(PatientAlreadyExistsError):
        service.create_patient("PATIENT120", "Duplicate")

    # Update with no fields
    with pytest.raises(ValueError, match="at least one field"):
        service.update_patient("PATIENT120")


# ============================================================================
# Patient ID Generation Tests
# ============================================================================

def test_generate_patient_id_format(patient_service):
    """Test patient ID follows correct format: SANITIZEDNAME_TIMESTAMP."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("John Doe")

    # Should be: JOHN_DOE_YYYYMMDDHHmmSS
    assert patient_id.startswith("JOHN_DOE_")
    assert len(patient_id) == 23  # JOHN_DOE_ (9) + timestamp (14)

    # Timestamp portion should be all digits
    timestamp_part = patient_id[9:]
    assert timestamp_part.isdigit()
    assert len(timestamp_part) == 14  # YYYYMMDDHHmmSS


def test_generate_patient_id_sanitizes_spaces(patient_service):
    """Test spaces are replaced with underscores."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("Jane Smith")

    assert "JANE_SMITH_" in patient_id
    assert " " not in patient_id


def test_generate_patient_id_uppercase(patient_service):
    """Test name is converted to uppercase."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("alice jones")

    assert "ALICE_JONES_" in patient_id
    assert "alice" not in patient_id


def test_generate_patient_id_truncates_long_names(patient_service):
    """Test names longer than 20 chars are truncated."""
    service, adapter, resolver = patient_service

    long_name = "ThisIsAVeryLongPatientNameThatExceedsTheLimit"
    patient_id = service.generate_patient_id(long_name)

    # Extract name part (before timestamp)
    name_part = patient_id.rsplit("_", 1)[0]

    assert len(name_part) <= 20
    assert name_part == "THISISAVERYLONGPATIE"  # Truncated to 20 chars


def test_generate_patient_id_strips_whitespace(patient_service):
    """Test leading/trailing whitespace is removed."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("  John Doe  ")

    assert "JOHN_DOE_" in patient_id
    assert patient_id.startswith("JOHN_DOE_")  # No leading space


def test_generate_patient_id_uniqueness(patient_service):
    """Test IDs are unique across calls (different timestamps)."""
    import time
    service, adapter, resolver = patient_service

    id1 = service.generate_patient_id("John Doe")

    # Wait to ensure different timestamp
    time.sleep(1)

    id2 = service.generate_patient_id("John Doe")

    assert id1 != id2  # Different timestamps
    assert id1.startswith("JOHN_DOE_")
    assert id2.startswith("JOHN_DOE_")


def test_generate_patient_id_special_characters(patient_service):
    """Test special characters in names."""
    service, adapter, resolver = patient_service

    # Only spaces are handled; other chars pass through
    patient_id = service.generate_patient_id("O'Brien-Smith")

    assert "O'BRIEN-SMITH_" in patient_id


def test_generate_patient_id_empty_name_after_strip(patient_service):
    """Test behavior with whitespace-only name."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("   ")

    # Empty name after strip → just underscore + timestamp
    assert patient_id.startswith("_")
    assert len(patient_id) == 15  # _ + 14-digit timestamp


def test_generate_patient_id_timestamp_format(patient_service):
    """Test timestamp format is YYYYMMDDHHMMSS."""
    service, adapter, resolver = patient_service

    patient_id = service.generate_patient_id("Test")
    timestamp_part = patient_id.split("_")[-1]

    # Timestamp should be 14 digits
    assert len(timestamp_part) == 14
    assert timestamp_part.isdigit()

    # Extract parts
    year = int(timestamp_part[0:4])
    month = int(timestamp_part[4:6])
    day = int(timestamp_part[6:8])
    hour = int(timestamp_part[8:10])
    minute = int(timestamp_part[10:12])
    second = int(timestamp_part[12:14])

    # Validate ranges
    assert 2020 <= year <= 2030  # Reasonable range
    assert 1 <= month <= 12
    assert 1 <= day <= 31
    assert 0 <= hour <= 23
    assert 0 <= minute <= 59
    assert 0 <= second <= 59


def test_generate_patient_id_integration_with_create_patient(patient_service):
    """Test that generated IDs work correctly with create_patient."""
    service, adapter, resolver = patient_service

    patient_name = "Integration Test"
    patient_id = service.generate_patient_id(patient_name)

    # Create patient with generated ID
    patient = service.create_patient(
        patient_id=patient_id,
        patient_name=patient_name
    )

    assert patient.patient_id == patient_id
    assert patient.patient_name == patient_name

    # Verify patient exists
    retrieved = service.get_patient(patient_id)
    assert retrieved is not None
    assert retrieved.patient_id == patient_id
