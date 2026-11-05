"""
Tests for UploadService.

Tests file upload orchestration, duplicate detection, deduplication,
transaction handling, and error scenarios.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import json
import tempfile
from pathlib import Path

from src.core.services.upload_service import UploadService
from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema import initialize_global_database
from src.infrastructure.repositories.patient_repository import PatientRepository


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def path_resolver(temp_data_dir):
    """Create PathResolver with temp directory."""
    resolver = PathResolver(base_dir=temp_data_dir)
    return resolver


@pytest.fixture
def adapter():
    """Create SQLiteAdapter."""
    return SQLiteAdapter()


@pytest.fixture
def upload_service(adapter, path_resolver):
    """Create UploadService with dependencies."""
    # Initialize global database
    initialize_global_database(adapter, path_resolver)
    return UploadService(adapter, path_resolver)


@pytest.fixture
def patient_service(adapter, path_resolver):
    """Create PatientService for test setup."""
    from src.core.services.patient_service import PatientService
    initialize_global_database(adapter, path_resolver)
    patient_repo = PatientRepository(adapter, path_resolver)
    return PatientService(patient_repo, adapter, path_resolver)


@pytest.fixture
def sample_timeline_file():
    """Create sample JSON file with timeline records (BrainSenseLfp format)."""
    data = {
        "BrainSenseLfp": [
            {
                "FirstPacketDateTime": "2024-01-01T12:00:00",
                "LfpData": [
                    {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050},
                    {"Left": {"LFP": 775, "mA": 0.0}, "Right": {"LFP": 510, "mA": 0.0}, "TicksInMs": 701550},
                    {"Left": {"LFP": 780, "mA": 0.0}, "Right": {"LFP": 515, "mA": 0.0}, "TicksInMs": 702050}
                ],
                "TherapySnapshot": {
                    "Left": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5},
                    "Right": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5}
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        json.dump(data, f)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def sample_snapshot_file():
    """Create sample JSON file with snapshot records."""
    data = [
        {
            "RecordingType": "BrainSenseLfp",
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": [1.0, 2.0, 3.0],
            "power_data": [10.0, 20.0, 30.0],
        },
        {
            "RecordingType": "BrainSenseLfp",
            "timestamp": "2024-01-01T12:01:00",
            "frequency_data": [1.5, 2.5, 3.5],
            "power_data": [15.0, 25.0, 35.0],
        },
    ]

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        json.dump(data, f)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink(missing_ok=True)


@pytest.fixture
def sample_mixed_file():
    """Create sample JSON file with mixed timeline and snapshot records."""
    # Mixed format: array with both timeline-like and snapshot-like records
    data = [
        {
            "timestamp": "2024-01-01T12:00:00",
            "LfpData": [{"Left": {"LFP": 769}, "Right": {"LFP": 508}}],  # Timeline indicator
        },
        {
            "timestamp": "2024-01-01T12:00:01",
            "frequency_data": [1.0, 2.0, 3.0],  # Snapshot indicator
            "power_data": [10.0, 20.0, 30.0],
        },
    ]

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        json.dump(data, f)
        temp_path = Path(f.name)

    yield temp_path
    temp_path.unlink(missing_ok=True)


# ============================================================================
# UploadService Initialization Tests
# ============================================================================

def test_upload_service_initialization(upload_service):
    """UploadService should initialize with required dependencies."""
    assert upload_service.adapter is not None
    assert upload_service.path_resolver is not None
    assert upload_service.timeline_repo is not None
    assert upload_service.snapshot_repo is not None
    assert upload_service.processing_repo is not None
    assert upload_service.patient_repo is not None


# ============================================================================
# Successful Upload Tests
# ============================================================================

def test_upload_timeline_file_success(upload_service, patient_service, sample_timeline_file):
    """Should successfully upload file with timeline records."""
    # Create patient
    patient_service.create_patient("TEST001", "Test Patient")

    # Upload file
    result = upload_service.upload_file("TEST001", sample_timeline_file)

    # Verify success
    assert result.success is True
    assert result.timeline_inserted == 3
    assert result.timeline_duplicates == 0
    assert result.snapshot_inserted == 0
    assert result.total_inserted == 3
    assert len(result.file_hash) == 64
    assert result.processing_time > 0


def test_upload_snapshot_file_success(upload_service, patient_service, sample_snapshot_file):
    """Should successfully upload file with snapshot records."""
    # Create patient
    patient_service.create_patient("TEST002", "Test Patient")

    # Upload file
    result = upload_service.upload_file("TEST002", sample_snapshot_file)

    # Verify success
    assert result.success is True
    assert result.timeline_inserted == 0
    assert result.snapshot_inserted == 2
    assert result.snapshot_duplicates == 0
    assert result.total_inserted == 2


def test_upload_mixed_file_success(upload_service, patient_service, sample_mixed_file):
    """Should successfully upload file with mixed record types."""
    # Create patient
    patient_service.create_patient("TEST003", "Test Patient")

    # Upload file
    result = upload_service.upload_file("TEST003", sample_mixed_file)

    # Verify success - file has both BrainSenseLfp (timeline) and PatientEvents (snapshot)
    assert result.success is True
    assert result.timeline_inserted == 1  # 1 LFP sample from BrainSenseLfp
    assert result.snapshot_inserted == 1  # 1 event from PatientEvents
    assert result.total_inserted == 2


def test_upload_file_archived_to_raw_uploads(upload_service, patient_service, sample_timeline_file, path_resolver):
    """Should copy file to patient's raw_uploads/ directory."""
    # Create patient
    patient_service.create_patient("TEST004", "Test Patient")

    # Upload file
    result = upload_service.upload_file("TEST004", sample_timeline_file)

    # Verify file archived
    assert result.success is True
    raw_uploads_dir = path_resolver.get_patient_uploads_directory("TEST004")
    archived_files = list(raw_uploads_dir.glob("*.json"))
    assert len(archived_files) == 1
    assert archived_files[0].name == sample_timeline_file.name


# ============================================================================
# Duplicate File Detection Tests
# ============================================================================

def test_upload_duplicate_file_rejected(upload_service, patient_service, sample_timeline_file):
    """Should reject duplicate file upload."""
    # Create patient
    patient_service.create_patient("TEST005", "Test Patient")

    # First upload - should succeed
    result1 = upload_service.upload_file("TEST005", sample_timeline_file)
    assert result1.success is True

    # Second upload - should be rejected
    result2 = upload_service.upload_file("TEST005", sample_timeline_file)
    assert result2.success is False
    assert "already uploaded" in result2.message.lower()
    assert result2.file_hash == result1.file_hash


def test_check_file_uploaded(upload_service, patient_service, sample_timeline_file):
    """Should detect if file already uploaded."""
    # Create patient
    patient_service.create_patient("TEST006", "Test Patient")

    # Calculate file hash
    from src.core.deduplication_engine import DeduplicationEngine
    file_hash = DeduplicationEngine.calculate_file_hash(sample_timeline_file)

    # Check before upload
    assert upload_service.check_file_uploaded("TEST006", file_hash) is False

    # Upload file
    upload_service.upload_file("TEST006", sample_timeline_file)

    # Check after upload
    assert upload_service.check_file_uploaded("TEST006", file_hash) is True


# ============================================================================
# Record Deduplication Tests
# ============================================================================

def test_upload_duplicate_records_deduplicated(upload_service, patient_service):
    """Should deduplicate records within same file."""
    # Create patient
    patient_service.create_patient("TEST007", "Test Patient")

    # Create file with duplicate timeline records (BrainSenseLfp format)
    data = {
        "BrainSenseLfp": [
            {
                "FirstPacketDateTime": "2024-01-01T12:00:00",
                "LfpData": [
                    {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050},
                    {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050},  # Duplicate
                    {"Left": {"LFP": 775, "mA": 0.0}, "Right": {"LFP": 510, "mA": 0.0}, "TicksInMs": 701550}
                ],
                "TherapySnapshot": {
                    "Left": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5},
                    "Right": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5}
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        json.dump(data, f)
        temp_path = Path(f.name)

    try:
        result = upload_service.upload_file("TEST007", temp_path)

        # Should insert 2 unique records, skip 1 duplicate
        assert result.success is True
        assert result.timeline_inserted == 2
        assert result.timeline_duplicates == 1
        assert result.total_duplicates == 1
    finally:
        temp_path.unlink()


def test_upload_multiple_files_deduplicates_across_files(upload_service, patient_service):
    """Should deduplicate records across multiple file uploads."""
    # Create patient
    patient_service.create_patient("TEST008", "Test Patient")

    # Create first file (BrainSenseLfp format)
    data1 = {
        "BrainSenseLfp": [
            {
                "FirstPacketDateTime": "2024-01-01T12:00:00",
                "LfpData": [
                    {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050}
                ],
                "TherapySnapshot": {
                    "Left": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5},
                    "Right": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5}
                }
            }
        ]
    }

    # Create second file with same data plus new data
    data2 = {
        "BrainSenseLfp": [
            {
                "FirstPacketDateTime": "2024-01-01T12:00:00",
                "LfpData": [
                    {"Left": {"LFP": 769, "mA": 0.0}, "Right": {"LFP": 508, "mA": 0.0}, "TicksInMs": 701050},  # Duplicate
                    {"Left": {"LFP": 775, "mA": 0.0}, "Right": {"LFP": 510, "mA": 0.0}, "TicksInMs": 701550}   # New
                ],
                "TherapySnapshot": {
                    "Left": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5},
                    "Right": {"RateInHertz": 130.2, "PulseWidthInMicroSecond": 60, "AmplitudeInMilliAmps": 2.5}
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_1.json') as f1:
        json.dump(data1, f1)
        temp_path1 = Path(f1.name)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_2.json') as f2:
        json.dump(data2, f2)
        temp_path2 = Path(f2.name)

    try:
        # Upload first file
        result1 = upload_service.upload_file("TEST008", temp_path1)
        assert result1.timeline_inserted == 1
        assert result1.timeline_duplicates == 0

        # Upload second file - should deduplicate first record
        result2 = upload_service.upload_file("TEST008", temp_path2)
        assert result2.timeline_inserted == 1  # Only new record
        assert result2.timeline_duplicates == 1  # Duplicate from file 1
    finally:
        temp_path1.unlink()
        temp_path2.unlink()


# ============================================================================
# Error Handling Tests
# ============================================================================

def test_upload_file_not_found(upload_service, patient_service):
    """Should return error when file does not exist."""
    patient_service.create_patient("TEST009", "Test Patient")

    result = upload_service.upload_file("TEST009", Path("/nonexistent/file.json"))

    assert result.success is False
    assert "not found" in result.message.lower()


def test_upload_patient_not_found(upload_service, sample_timeline_file):
    """Should return error when patient does not exist."""
    result = upload_service.upload_file("NONEXISTENT", sample_timeline_file)

    assert result.success is False
    assert "patient not found" in result.message.lower()


def test_upload_directory_instead_of_file(upload_service, patient_service, temp_data_dir):
    """Should return error when path is directory not file."""
    patient_service.create_patient("TEST010", "Test Patient")

    result = upload_service.upload_file("TEST010", temp_data_dir)

    assert result.success is False
    assert "not a file" in result.message.lower()


# ============================================================================
# Upload History Tests
# ============================================================================

def test_get_upload_history_empty(upload_service, patient_service):
    """Should return empty list when no uploads."""
    patient_service.create_patient("TEST011", "Test Patient")

    history = upload_service.get_upload_history("TEST011")

    assert isinstance(history, list)
    assert len(history) == 0


def test_get_upload_history_with_uploads(upload_service, patient_service, sample_timeline_file, sample_snapshot_file):
    """Should return upload history after uploads."""
    patient_service.create_patient("TEST012", "Test Patient")

    # Upload two files
    upload_service.upload_file("TEST012", sample_timeline_file)
    upload_service.upload_file("TEST012", sample_snapshot_file)

    # Get history
    history = upload_service.get_upload_history("TEST012")

    assert len(history) == 2
    assert all(hasattr(upload, 'file_name') for upload in history)
    assert all(hasattr(upload, 'timeline_count') for upload in history)
    assert all(hasattr(upload, 'snapshot_count') for upload in history)


def test_get_upload_history_sorted_by_date(upload_service, patient_service, sample_timeline_file):
    """Should return upload history sorted by date (newest first)."""
    patient_service.create_patient("TEST013", "Test Patient")

    # Upload same file twice (with different names due to archiving)
    upload_service.upload_file("TEST013", sample_timeline_file)

    # Create second file with different content
    data = [{"RecordingType": "BrainSenseTimeDomain", "timestamp": "2024-01-02T12:00:00", "left_hemisphere": 200.0}]
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_2.json') as f:
        json.dump(data, f)
        temp_path2 = Path(f.name)

    try:
        upload_service.upload_file("TEST013", temp_path2)

        # Get history
        history = upload_service.get_upload_history("TEST013")

        # Should be sorted by date (newest first)
        assert len(history) == 2
        # Most recent upload should be first
        assert history[0].processed_at >= history[1].processed_at
    finally:
        temp_path2.unlink()


def test_get_upload_history_with_limit(upload_service, patient_service, sample_timeline_file):
    """Should respect limit parameter."""
    patient_service.create_patient("TEST014", "Test Patient")

    # Upload file
    upload_service.upload_file("TEST014", sample_timeline_file)

    # Get history with limit
    history = upload_service.get_upload_history("TEST014", limit=1)

    assert len(history) <= 1


# ============================================================================
# Progress Callback Tests
# ============================================================================

def test_upload_with_progress_callback(upload_service, patient_service, sample_timeline_file):
    """Should call progress callback during upload."""
    patient_service.create_patient("TEST015", "Test Patient")

    progress_messages = []

    def progress_callback(message: str):
        progress_messages.append(message)

    result = upload_service.upload_file("TEST015", sample_timeline_file, progress_callback=progress_callback)

    assert result.success is True
    assert len(progress_messages) > 0
    assert any("validating" in msg.lower() for msg in progress_messages)
    assert any("parsing" in msg.lower() for msg in progress_messages)
    assert any("inserting" in msg.lower() for msg in progress_messages)


# ============================================================================
# UploadResult Tests
# ============================================================================

def test_upload_result_properties(upload_service, patient_service, sample_timeline_file):
    """UploadResult should have correct computed properties."""
    patient_service.create_patient("TEST016", "Test Patient")

    result = upload_service.upload_file("TEST016", sample_timeline_file)

    assert result.total_inserted == result.timeline_inserted + result.snapshot_inserted
    assert result.total_processed == result.total_inserted + result.total_duplicates
    assert 0.0 <= result.duplicate_rate <= 1.0


def test_upload_result_to_dict(upload_service, patient_service, sample_timeline_file):
    """UploadResult should convert to dictionary."""
    patient_service.create_patient("TEST017", "Test Patient")

    result = upload_service.upload_file("TEST017", sample_timeline_file)
    result_dict = result.to_dict()

    assert isinstance(result_dict, dict)
    assert 'success' in result_dict
    assert 'message' in result_dict
    assert 'timeline_inserted' in result_dict
    assert 'total_inserted' in result_dict
    assert 'duplicate_rate' in result_dict


# ============================================================================
# Integration Tests
# ============================================================================

def test_complete_upload_workflow(upload_service, patient_service, sample_mixed_file, path_resolver):
    """Should complete entire upload workflow successfully."""
    # Create patient
    patient = patient_service.create_patient("TEST018", "Test Patient")
    assert patient is not None

    # Upload file
    result = upload_service.upload_file("TEST018", sample_mixed_file)

    # Verify upload success
    assert result.success is True
    assert result.total_inserted > 0

    # Verify file archived
    raw_uploads_dir = path_resolver.get_patient_uploads_directory("TEST018")
    assert raw_uploads_dir.exists()
    archived_files = list(raw_uploads_dir.glob("*.json"))
    assert len(archived_files) == 1

    # Verify upload history
    history = upload_service.get_upload_history("TEST018")
    assert len(history) == 1
    assert history[0].file_name == sample_mixed_file.name
    assert history[0].timeline_count == result.timeline_inserted
    assert history[0].snapshot_count == result.snapshot_inserted

    # Verify duplicate detection
    assert upload_service.check_file_uploaded("TEST018", result.file_hash) is True
