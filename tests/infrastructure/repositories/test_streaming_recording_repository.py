"""
Comprehensive tests for StreamingRecordingRepository.

Tests the StreamingRecordingRepository class including:
- CRUD operations for streaming recordings
- Querying by patient, date range, trimmed status
- Relationship tracking (original vs trimmed recordings)
- Processing metadata storage
- Error handling and edge cases
"""

import pytest
from pathlib import Path
import tempfile
import shutil
from datetime import datetime

from src.infrastructure.repositories.streaming_recording_repository import StreamingRecordingRepository
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema.patient_schema import get_patient_schema
from src.core.path_resolver import PathResolver
from src.core.models import StreamingRecording


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
    """Create StreamingRecordingRepository instance."""
    return StreamingRecordingRepository(adapter, path_resolver)


class TestStreamingRecordingRepositoryInitialization:
    """Test StreamingRecordingRepository initialization."""

    def test_repository_initialization(self, adapter, path_resolver):
        """Test that repository can be initialized."""
        repo = StreamingRecordingRepository(adapter, path_resolver)

        assert repo.adapter is adapter
        assert repo.path_resolver is path_resolver
        assert repo.logger is not None


class TestStreamingRecordingRepositoryCreate:
    """Test creating streaming recordings."""

    def test_create_recording_basic(self, repository, patient_db_with_schema):
        """Test creating a basic streaming recording."""
        db_path, patient_id = patient_db_with_schema

        recording = StreamingRecording(
            id="rec_001",
            patient_id=patient_id,
            file_path="/path/to/recording.json",
            recording_date=datetime(2024, 3, 15, 9, 30),
            duration_seconds=2732.5,
            is_trimmed=False,
            file_size_bytes=128400000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"],
            metadata={},
            processing_applied=[],
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        created = repository.create(patient_id, recording)

        assert created is not None
        assert created.id == "rec_001"
        assert created.patient_id == patient_id
        assert created.duration_seconds == 2732.5
        assert created.is_trimmed is False
        assert created.channel_count == 4

    def test_create_trimmed_recording(self, repository, patient_db_with_schema):
        """Test creating a trimmed recording with original reference."""
        db_path, patient_id = patient_db_with_schema

        # Create original
        original = StreamingRecording(
            id="rec_original",
            patient_id=patient_id,
            file_path="/path/to/original.json",
            recording_date=datetime(2024, 3, 15, 9, 30),
            duration_seconds=2732.5,
            is_trimmed=False,
            file_size_bytes=128400000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
        )
        repository.create(patient_id, original)

        # Create trimmed
        trimmed = StreamingRecording(
            id="rec_trimmed",
            patient_id=patient_id,
            file_path="/path/to/trimmed.json",
            original_file_path="/path/to/original.json",
            recording_date=datetime(2024, 3, 15, 9, 30),
            duration_seconds=1200.0,
            is_trimmed=True,
            file_size_bytes=50000000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"],
            processing_applied=["highpass_0.5Hz", "dc_offset_removal"]
        )

        created = repository.create(patient_id, trimmed)

        assert created.is_trimmed is True
        assert created.original_file_path == "/path/to/original.json"
        assert len(created.processing_applied) == 2


class TestStreamingRecordingRepositoryRead:
    """Test reading streaming recordings."""

    def test_get_by_id_existing(self, repository, patient_db_with_schema):
        """Test retrieving an existing recording by ID."""
        db_path, patient_id = patient_db_with_schema

        recording = StreamingRecording(
            id="rec_get",
            patient_id=patient_id,
            file_path="/path/to/recording.json",
            recording_date=datetime(2024, 3, 15, 9, 30),
            duration_seconds=1000.0,
            file_size_bytes=10000000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
        )
        repository.create(patient_id, recording)

        retrieved = repository.get_by_id(patient_id, "rec_get")

        assert retrieved is not None
        assert retrieved.id == "rec_get"
        assert retrieved.duration_seconds == 1000.0

    def test_get_by_id_nonexistent(self, repository, patient_db_with_schema):
        """Test retrieving nonexistent recording returns None."""
        db_path, patient_id = patient_db_with_schema

        retrieved = repository.get_by_id(patient_id, "nonexistent")

        assert retrieved is None

    def test_get_by_patient(self, repository, patient_db_with_schema):
        """Test retrieving all recordings for a patient."""
        db_path, patient_id = patient_db_with_schema

        # Create multiple recordings
        for i in range(3):
            recording = StreamingRecording(
                id=f"rec_{i}",
                patient_id=patient_id,
                file_path=f"/path/to/recording_{i}.json",
                recording_date=datetime(2024, 3, 15 + i, 9, 30),
                duration_seconds=1000.0 + i * 100,
                file_size_bytes=10000000,
                sampling_rate=250.0,
                channel_count=4,
                channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
            )
            repository.create(patient_id, recording)

        recordings = repository.get_by_patient(patient_id)

        assert len(recordings) == 3
        # Should be ordered by date DESC
        assert recordings[0].id == "rec_2"
        assert recordings[1].id == "rec_1"
        assert recordings[2].id == "rec_0"

    def test_get_by_date_range(self, repository, patient_db_with_schema):
        """Test retrieving recordings within date range."""
        db_path, patient_id = patient_db_with_schema

        # Create recordings across different dates
        dates = [
            datetime(2024, 3, 10),
            datetime(2024, 3, 15),
            datetime(2024, 3, 20),
            datetime(2024, 3, 25)
        ]

        for i, date in enumerate(dates):
            recording = StreamingRecording(
                id=f"rec_date_{i}",
                patient_id=patient_id,
                file_path=f"/path/to/recording_{i}.json",
                recording_date=date,
                duration_seconds=1000.0,
                file_size_bytes=10000000,
                sampling_rate=250.0,
                channel_count=4,
                channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
            )
            repository.create(patient_id, recording)

        # Query date range (March 12 to March 22)
        recordings = repository.get_by_date_range(
            patient_id,
            datetime(2024, 3, 12),
            datetime(2024, 3, 22)
        )

        assert len(recordings) == 2
        assert recordings[0].recording_date == datetime(2024, 3, 20)
        assert recordings[1].recording_date == datetime(2024, 3, 15)

    def test_get_trimmed_recordings(self, repository, patient_db_with_schema):
        """Test retrieving only trimmed recordings."""
        db_path, patient_id = patient_db_with_schema

        # Create mix of original and trimmed
        for i in range(4):
            recording = StreamingRecording(
                id=f"rec_trim_{i}",
                patient_id=patient_id,
                file_path=f"/path/to/recording_{i}.json",
                recording_date=datetime(2024, 3, 15 + i),
                duration_seconds=1000.0,
                is_trimmed=(i % 2 == 1),  # Trim odd indices
                file_size_bytes=10000000,
                sampling_rate=250.0,
                channel_count=4,
                channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
            )
            repository.create(patient_id, recording)

        trimmed = repository.get_trimmed_recordings(patient_id)

        assert len(trimmed) == 2
        assert all(rec.is_trimmed for rec in trimmed)

    def test_get_original_recordings(self, repository, patient_db_with_schema):
        """Test retrieving only original recordings."""
        db_path, patient_id = patient_db_with_schema

        # Create mix of original and trimmed
        for i in range(4):
            recording = StreamingRecording(
                id=f"rec_orig_{i}",
                patient_id=patient_id,
                file_path=f"/path/to/recording_{i}.json",
                recording_date=datetime(2024, 3, 15 + i),
                duration_seconds=1000.0,
                is_trimmed=(i % 2 == 1),
                file_size_bytes=10000000,
                sampling_rate=250.0,
                channel_count=4,
                channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
            )
            repository.create(patient_id, recording)

        originals = repository.get_original_recordings(patient_id)

        assert len(originals) == 2
        assert all(not rec.is_trimmed for rec in originals)


class TestStreamingRecordingRepositoryUpdate:
    """Test updating streaming recordings."""

    def test_update_recording(self, repository, patient_db_with_schema):
        """Test updating a recording."""
        db_path, patient_id = patient_db_with_schema

        # Create recording
        recording = StreamingRecording(
            id="rec_update",
            patient_id=patient_id,
            file_path="/path/to/recording.json",
            recording_date=datetime(2024, 3, 15),
            duration_seconds=1000.0,
            file_size_bytes=10000000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"],
            metadata={"key": "value"}
        )
        created = repository.create(patient_id, recording)

        # Update recording
        created.duration_seconds = 1500.0
        created.metadata["new_key"] = "new_value"
        created.processing_applied = ["filter_applied"]

        updated = repository.update(patient_id, created)

        assert updated.duration_seconds == 1500.0
        assert updated.metadata["new_key"] == "new_value"
        assert len(updated.processing_applied) == 1

    def test_update_nonexistent_recording(self, repository, patient_db_with_schema):
        """Test updating nonexistent recording raises ValueError."""
        db_path, patient_id = patient_db_with_schema

        recording = StreamingRecording(
            id="nonexistent",
            patient_id=patient_id,
            file_path="/path",
            recording_date=datetime.now(),
            duration_seconds=1000.0,
            file_size_bytes=1000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0"]
        )

        with pytest.raises(ValueError, match="not found"):
            repository.update(patient_id, recording)


class TestStreamingRecordingRepositoryDelete:
    """Test deleting streaming recordings."""

    def test_delete_recording(self, repository, patient_db_with_schema):
        """Test deleting a recording."""
        db_path, patient_id = patient_db_with_schema

        # Create recording
        recording = StreamingRecording(
            id="rec_delete",
            patient_id=patient_id,
            file_path="/path/to/recording.json",
            recording_date=datetime(2024, 3, 15),
            duration_seconds=1000.0,
            file_size_bytes=10000000,
            sampling_rate=250.0,
            channel_count=4,
            channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
        )
        repository.create(patient_id, recording)

        # Delete recording
        repository.delete(patient_id, "rec_delete")

        # Verify deleted
        retrieved = repository.get_by_id(patient_id, "rec_delete")
        assert retrieved is None

    def test_delete_nonexistent_recording(self, repository, patient_db_with_schema):
        """Test deleting nonexistent recording raises ValueError."""
        db_path, patient_id = patient_db_with_schema

        with pytest.raises(ValueError, match="not found"):
            repository.delete(patient_id, "nonexistent")


class TestStreamingRecordingRepositoryCount:
    """Test counting recordings."""

    def test_count_by_patient(self, repository, patient_db_with_schema):
        """Test counting recordings for a patient."""
        db_path, patient_id = patient_db_with_schema

        # Initially zero
        assert repository.count_by_patient(patient_id) == 0

        # Create recordings
        for i in range(5):
            recording = StreamingRecording(
                id=f"rec_count_{i}",
                patient_id=patient_id,
                file_path=f"/path/to/recording_{i}.json",
                recording_date=datetime(2024, 3, 15 + i),
                duration_seconds=1000.0,
                file_size_bytes=10000000,
                sampling_rate=250.0,
                channel_count=4,
                channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"]
            )
            repository.create(patient_id, recording)

        assert repository.count_by_patient(patient_id) == 5
