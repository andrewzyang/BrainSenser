"""
Comprehensive tests for RecordingGroupRepository.

Tests the RecordingGroupRepository class including:
- CRUD operations for recording groups
- Querying by patient, grouping criteria
- Adding/removing recordings from groups
- Error handling and edge cases
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil
from datetime import datetime

from src.infrastructure.repositories.recording_group_repository import RecordingGroupRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema.patient_schema import get_patient_schema
from src.core.path_resolver import PathResolver
from src.core.models import RecordingGroup


@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def path_resolver(temp_dir):
    """Create PathResolver with temporary base directory."""
    return PathResolver(base_dir=temp_dir)


@pytest.fixture
def adapter():
    """Create SQLiteAdapter instance."""
    return SQLiteAdapter()


@pytest.fixture
def patient_db_with_schema(path_resolver, adapter):
    """Create and initialize patient database with schema."""
    patient_id = "TEST_PATIENT"
    db_path = path_resolver.get_patient_db_path(patient_id)

    # Create patient directory
    path_resolver.create_patient_directory(patient_id)

    # Create schema
    schema_sql = get_patient_schema()

    with adapter.transaction(db_path) as conn:
        conn.executescript(schema_sql)

    return db_path, patient_id


@pytest.fixture
def repository(adapter, path_resolver):
    """Create RecordingGroupRepository instance."""
    return RecordingGroupRepository(adapter, path_resolver)


class TestRecordingGroupRepositoryInitialization:
    """Test RecordingGroupRepository initialization."""

    def test_repository_initialization(self, adapter, path_resolver):
        """Test that repository can be initialized."""
        repo = RecordingGroupRepository(adapter, path_resolver)

        assert repo.adapter is adapter
        assert repo.path_resolver is path_resolver
        assert repo.logger is not None


class TestRecordingGroupRepositoryCreate:
    """Test creating recording groups."""

    def test_create_group_basic(self, repository, patient_db_with_schema):
        """Test creating a basic recording group."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_001",
            patient_id=patient_id,
            name="Morning Recordings",
            description="Recordings taken in the morning",
            recording_ids=["rec_001", "rec_002", "rec_003"],
            grouping_criteria="time_of_day",
            color="#3498db",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        created = repository.create(patient_id, group)

        assert created is not None
        assert created.id == "group_001"
        assert created.patient_id == patient_id
        assert created.name == "Morning Recordings"
        assert len(created.recording_ids) == 3
        assert created.grouping_criteria == "time_of_day"

    def test_create_group_minimal(self, repository, patient_db_with_schema):
        """Test creating a group with minimal fields."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_minimal",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001"]
        )

        created = repository.create(patient_id, group)

        assert created.name == "Test Group"
        assert len(created.recording_ids) == 1
        assert created.grouping_criteria == "manual"  # default
        assert created.color == "#3498db"  # default

    def test_create_group_with_custom_criteria(self, repository, patient_db_with_schema):
        """Test creating a group with custom criteria."""
        db_path, patient_id = patient_db_with_schema

        custom_criteria = {
            "rule": "duration_range",
            "min_duration": 600,
            "max_duration": 1200
        }

        group = RecordingGroup(
            id="group_custom",
            patient_id=patient_id,
            name="Custom Group",
            recording_ids=["rec_001", "rec_002"],
            grouping_criteria="custom",
            custom_criteria=custom_criteria
        )

        created = repository.create(patient_id, group)

        assert created.grouping_criteria == "custom"
        assert created.custom_criteria == custom_criteria

    def test_create_duplicate_id_fails(self, repository, patient_db_with_schema):
        """Test that creating group with duplicate ID raises error."""
        db_path, patient_id = patient_db_with_schema

        group1 = RecordingGroup(
            id="group_dup",
            patient_id=patient_id,
            name="Group 1",
            recording_ids=["rec_001"]
        )
        repository.create(patient_id, group1)

        group2 = RecordingGroup(
            id="group_dup",  # Duplicate ID
            patient_id=patient_id,
            name="Group 2",
            recording_ids=["rec_002"]
        )

        with pytest.raises(sqlite3.IntegrityError):
            repository.create(patient_id, group2)


class TestRecordingGroupRepositoryRead:
    """Test reading recording groups."""

    def test_get_by_id_existing(self, repository, patient_db_with_schema):
        """Test retrieving an existing group by ID."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_get",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002"]
        )
        repository.create(patient_id, group)

        retrieved = repository.get_by_id(patient_id, "group_get")

        assert retrieved is not None
        assert retrieved.id == "group_get"
        assert retrieved.name == "Test Group"
        assert len(retrieved.recording_ids) == 2

    def test_get_by_id_nonexistent(self, repository, patient_db_with_schema):
        """Test retrieving nonexistent group returns None."""
        db_path, patient_id = patient_db_with_schema

        retrieved = repository.get_by_id(patient_id, "nonexistent")

        assert retrieved is None

    def test_get_by_patient(self, repository, patient_db_with_schema):
        """Test retrieving all groups for a patient."""
        db_path, patient_id = patient_db_with_schema

        # Create multiple groups
        for i in range(3):
            group = RecordingGroup(
                id=f"group_{i}",
                patient_id=patient_id,
                name=f"Group {i}",
                recording_ids=[f"rec_{i}"]
            )
            repository.create(patient_id, group)

        groups = repository.get_by_patient(patient_id)

        assert len(groups) == 3
        assert all(g.patient_id == patient_id for g in groups)

    def test_get_by_patient_empty(self, repository, patient_db_with_schema):
        """Test getting groups when patient has none."""
        db_path, patient_id = patient_db_with_schema

        groups = repository.get_by_patient(patient_id)

        assert len(groups) == 0

    def test_get_by_criteria(self, repository, patient_db_with_schema):
        """Test retrieving groups by grouping criteria."""
        db_path, patient_id = patient_db_with_schema

        # Create groups with different criteria
        group1 = RecordingGroup(
            id="group_morning",
            patient_id=patient_id,
            name="Morning",
            recording_ids=["rec_001"],
            grouping_criteria="time_of_day"
        )
        group2 = RecordingGroup(
            id="group_afternoon",
            patient_id=patient_id,
            name="Afternoon",
            recording_ids=["rec_002"],
            grouping_criteria="time_of_day"
        )
        group3 = RecordingGroup(
            id="group_manual",
            patient_id=patient_id,
            name="Manual Group",
            recording_ids=["rec_003"],
            grouping_criteria="manual"
        )

        repository.create(patient_id, group1)
        repository.create(patient_id, group2)
        repository.create(patient_id, group3)

        # Get time_of_day groups
        tod_groups = repository.get_by_criteria(patient_id, "time_of_day")
        assert len(tod_groups) == 2
        assert all(g.grouping_criteria == "time_of_day" for g in tod_groups)

        # Get manual groups
        manual_groups = repository.get_by_criteria(patient_id, "manual")
        assert len(manual_groups) == 1
        assert manual_groups[0].grouping_criteria == "manual"


class TestRecordingGroupRepositoryUpdate:
    """Test updating recording groups."""

    def test_update_group_basic(self, repository, patient_db_with_schema):
        """Test updating a group's basic fields."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_update",
            patient_id=patient_id,
            name="Original Name",
            recording_ids=["rec_001"]
        )
        repository.create(patient_id, group)

        # Update fields
        group.name = "Updated Name"
        group.description = "New description"
        group.color = "#e74c3c"

        updated = repository.update(patient_id, group)

        assert updated.name == "Updated Name"
        assert updated.description == "New description"
        assert updated.color == "#e74c3c"

    def test_update_group_recordings(self, repository, patient_db_with_schema):
        """Test updating a group's recording list."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_update_recs",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002"]
        )
        repository.create(patient_id, group)

        # Update recordings
        group.recording_ids = ["rec_001", "rec_002", "rec_003", "rec_004"]

        updated = repository.update(patient_id, group)

        assert len(updated.recording_ids) == 4
        assert "rec_003" in updated.recording_ids

    def test_update_nonexistent_fails(self, repository, patient_db_with_schema):
        """Test updating nonexistent group raises error."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="nonexistent",
            patient_id=patient_id,
            name="Test",
            recording_ids=[]
        )

        with pytest.raises(ValueError, match="not found"):
            repository.update(patient_id, group)


class TestRecordingGroupRepositoryDelete:
    """Test deleting recording groups."""

    def test_delete_existing_group(self, repository, patient_db_with_schema):
        """Test deleting an existing group."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_delete",
            patient_id=patient_id,
            name="To Delete",
            recording_ids=["rec_001"]
        )
        repository.create(patient_id, group)

        # Verify it exists
        assert repository.get_by_id(patient_id, "group_delete") is not None

        # Delete it
        repository.delete(patient_id, "group_delete")

        # Verify it's gone
        assert repository.get_by_id(patient_id, "group_delete") is None

    def test_delete_nonexistent_fails(self, repository, patient_db_with_schema):
        """Test deleting nonexistent group raises error."""
        db_path, patient_id = patient_db_with_schema

        with pytest.raises(ValueError, match="not found"):
            repository.delete(patient_id, "nonexistent")


class TestRecordingGroupRepositoryRecordingManagement:
    """Test adding/removing recordings from groups."""

    def test_add_recording_to_group(self, repository, patient_db_with_schema):
        """Test adding a recording to a group."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_add",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002"]
        )
        repository.create(patient_id, group)

        # Add recording
        updated = repository.add_recording_to_group(patient_id, "group_add", "rec_003")

        assert len(updated.recording_ids) == 3
        assert "rec_003" in updated.recording_ids

    def test_add_duplicate_recording_ignored(self, repository, patient_db_with_schema):
        """Test adding a recording that's already in the group."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_dup_add",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002"]
        )
        repository.create(patient_id, group)

        # Try to add existing recording
        updated = repository.add_recording_to_group(patient_id, "group_dup_add", "rec_001")

        # Should still have 2 recordings (not duplicated)
        assert len(updated.recording_ids) == 2

    def test_remove_recording_from_group(self, repository, patient_db_with_schema):
        """Test removing a recording from a group."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_remove",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002", "rec_003"]
        )
        repository.create(patient_id, group)

        # Remove recording
        updated = repository.remove_recording_from_group(patient_id, "group_remove", "rec_002")

        assert len(updated.recording_ids) == 2
        assert "rec_002" not in updated.recording_ids
        assert "rec_001" in updated.recording_ids
        assert "rec_003" in updated.recording_ids

    def test_remove_nonexistent_recording_safe(self, repository, patient_db_with_schema):
        """Test removing a recording that's not in the group (should be safe)."""
        db_path, patient_id = patient_db_with_schema

        group = RecordingGroup(
            id="group_remove_safe",
            patient_id=patient_id,
            name="Test Group",
            recording_ids=["rec_001", "rec_002"]
        )
        repository.create(patient_id, group)

        # Try to remove nonexistent recording
        updated = repository.remove_recording_from_group(patient_id, "group_remove_safe", "rec_999")

        # Should still have 2 recordings
        assert len(updated.recording_ids) == 2


class TestRecordingGroupRepositoryCount:
    """Test counting groups."""

    def test_count_by_patient(self, repository, patient_db_with_schema):
        """Test counting groups for a patient."""
        db_path, patient_id = patient_db_with_schema

        # Create multiple groups
        for i in range(5):
            group = RecordingGroup(
                id=f"group_{i}",
                patient_id=patient_id,
                name=f"Group {i}",
                recording_ids=[f"rec_{i}"]
            )
            repository.create(patient_id, group)

        count = repository.count_by_patient(patient_id)

        assert count == 5

    def test_count_by_patient_zero(self, repository, patient_db_with_schema):
        """Test counting when patient has no groups."""
        db_path, patient_id = patient_db_with_schema

        count = repository.count_by_patient(patient_id)

        assert count == 0
