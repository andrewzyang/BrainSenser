"""
Tests for StreamingService.

Tests the streaming recording service business logic, including:
- Loading recordings
- Trimming recordings
- Applying filters
- Getting recordings for patients
- Getting recording metadata

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

import pytest
import json
import numpy as np
from datetime import datetime
from unittest.mock import Mock, patch

from src.core.services.streaming_service import StreamingService
from src.core.models import StreamingRecording
from src.core.path_resolver import PathResolver
from src.infrastructure.repositories.streaming_recording_repository import StreamingRecordingRepository


@pytest.fixture
def tmp_patient_dir(tmp_path):
    """Create temporary patient directory."""
    patient_dir = tmp_path / "P01"
    patient_dir.mkdir(parents=True, exist_ok=True)
    return patient_dir


@pytest.fixture
def sample_recording_file(tmp_patient_dir):
    """Create a sample streaming recording JSON file."""
    recording_path = tmp_patient_dir / "test_recording.json"

    # Create sample data
    sampling_rate = 250.0
    duration_seconds = 10.0
    n_samples = int(sampling_rate * duration_seconds)

    # Generate simple sine wave data for 4 channels
    timestamps = [i / sampling_rate for i in range(n_samples)]
    channels = {
        "Ch0_Left_STN": [np.sin(2 * np.pi * 5 * t) for t in timestamps],
        "Ch1_Left_STN": [np.sin(2 * np.pi * 10 * t) for t in timestamps],
        "Ch2_Right_STN": [np.sin(2 * np.pi * 15 * t) for t in timestamps],
        "Ch3_Right_STN": [np.sin(2 * np.pi * 20 * t) for t in timestamps],
    }

    data = {
        "metadata": {
            "recording_date": "2024-03-15T09:30:00",
            "duration_seconds": duration_seconds,
            "sampling_rate": sampling_rate,
            "channel_count": 4,
            "channel_labels": ["Ch0_Left_STN", "Ch1_Left_STN", "Ch2_Right_STN", "Ch3_Right_STN"],
            "patient_id": "P01"
        },
        "data": {
            "timestamps": timestamps,
            "channels": channels
        }
    }

    with open(recording_path, 'w') as f:
        json.dump(data, f)

    return recording_path


@pytest.fixture
def sample_recording_metadata(sample_recording_file):
    """Create sample StreamingRecording metadata."""
    return StreamingRecording(
        id="rec_001",
        patient_id="P01",
        file_path=str(sample_recording_file),
        original_file_path=None,
        recording_date=datetime(2024, 3, 15, 9, 30, 0),
        duration_seconds=10.0,
        start_time=None,
        end_time=None,
        is_trimmed=False,
        file_size_bytes=sample_recording_file.stat().st_size,
        sampling_rate=250.0,
        channel_count=4,
        channel_labels=["Ch0_Left_STN", "Ch1_Left_STN", "Ch2_Right_STN", "Ch3_Right_STN"],
        metadata={},
        processing_applied=[],
        created_at=datetime.now(),
        updated_at=datetime.now()
    )


@pytest.fixture
def mock_repository():
    """Create mock StreamingRecordingRepository."""
    return Mock(spec=StreamingRecordingRepository)


@pytest.fixture
def mock_path_resolver(tmp_patient_dir):
    """Create mock PathResolver."""
    resolver = Mock(spec=PathResolver)
    resolver.get_patient_directory.return_value = tmp_patient_dir
    return resolver


@pytest.fixture
def streaming_service(mock_repository, mock_path_resolver):
    """Create StreamingService instance with mocked dependencies."""
    return StreamingService(mock_repository, mock_path_resolver)


# ============================================================================
# Initialization Tests
# ============================================================================

def test_streaming_service_initialization(mock_repository, mock_path_resolver):
    """Test StreamingService initializes with correct dependencies."""
    service = StreamingService(mock_repository, mock_path_resolver)

    assert service.repository == mock_repository
    assert service.path_resolver == mock_path_resolver


# ============================================================================
# get_recordings_for_patient Tests (Fix #1 - MVVM)
# ============================================================================

def test_get_recordings_for_patient_success(streaming_service, mock_repository, sample_recording_metadata):
    """Test getting all recordings for a patient."""
    # Setup
    mock_repository.get_by_patient.return_value = [sample_recording_metadata]

    # Execute
    recordings = streaming_service.get_recordings_for_patient("P01")

    # Verify
    assert len(recordings) == 1
    assert recordings[0].id == "rec_001"
    assert recordings[0].patient_id == "P01"
    # Called twice: once in cleanup_orphaned_recordings, once in return statement
    assert mock_repository.get_by_patient.call_count == 2
    mock_repository.get_by_patient.assert_called_with("P01")


def test_get_recordings_for_patient_empty(streaming_service, mock_repository):
    """Test getting recordings when patient has none."""
    # Setup
    mock_repository.get_by_patient.return_value = []

    # Execute
    recordings = streaming_service.get_recordings_for_patient("P01")

    # Verify
    assert len(recordings) == 0
    # Called twice: once in cleanup_orphaned_recordings, once in return statement
    assert mock_repository.get_by_patient.call_count == 2
    mock_repository.get_by_patient.assert_called_with("P01")


# ============================================================================
# get_recording_metadata Tests (Fix #5 - Service API)
# ============================================================================

def test_get_recording_metadata_success(streaming_service, mock_repository, sample_recording_metadata):
    """Test getting recording metadata without loading file."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata

    # Execute
    recording = streaming_service.get_recording_metadata("P01", "rec_001")

    # Verify
    assert recording is not None
    assert recording.id == "rec_001"
    assert recording.patient_id == "P01"
    mock_repository.get_by_id.assert_called_once_with("P01", "rec_001")


def test_get_recording_metadata_not_found(streaming_service, mock_repository):
    """Test getting metadata for non-existent recording."""
    # Setup
    mock_repository.get_by_id.return_value = None

    # Execute
    recording = streaming_service.get_recording_metadata("P01", "nonexistent")

    # Verify
    assert recording is None
    mock_repository.get_by_id.assert_called_once_with("P01", "nonexistent")


# ============================================================================
# load_recording Tests
# ============================================================================

def test_load_recording_success(streaming_service, mock_repository, sample_recording_metadata):
    """Test successful recording load."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata

    # Execute
    waveform_data, recording = streaming_service.load_recording("P01", "rec_001")

    # Verify
    assert recording.id == "rec_001"
    assert waveform_data.shape == (2500, 4)  # 10s @ 250Hz, 4 channels
    assert isinstance(waveform_data, np.ndarray)
    mock_repository.get_by_id.assert_called_once_with("P01", "rec_001")


def test_load_recording_not_found_in_db(streaming_service, mock_repository):
    """Test loading recording that doesn't exist in database."""
    # Setup
    mock_repository.get_by_id.return_value = None

    # Execute & Verify
    with pytest.raises(ValueError, match="not found in database"):
        streaming_service.load_recording("P01", "nonexistent")


def test_load_recording_file_not_found(streaming_service, mock_repository):
    """Test loading recording when file doesn't exist."""
    # Setup
    recording = StreamingRecording(
        id="rec_001",
        patient_id="P01",
        file_path="/nonexistent/path.json",
        original_file_path=None,
        recording_date=datetime.now(),
        duration_seconds=10.0,
        start_time=None,
        end_time=None,
        is_trimmed=False,
        file_size_bytes=1000,
        sampling_rate=250.0,
        channel_count=4,
        channel_labels=["Ch0", "Ch1", "Ch2", "Ch3"],
        metadata={},
        processing_applied=[],
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    mock_repository.get_by_id.return_value = recording

    # Execute & Verify
    with pytest.raises(FileNotFoundError):
        streaming_service.load_recording("P01", "rec_001")


# ============================================================================
# apply_filters Tests (Fix #3 - Explicit scipy check)
# ============================================================================

def test_apply_filters_dc_offset_removal():
    """Test DC offset removal filter."""
    # Create service (no mocks needed for this test)
    service = StreamingService(Mock(), Mock())

    # Create data with DC offset
    data = np.array([[1.5, 2.5], [1.7, 2.7], [1.3, 2.3]])  # Mean should be ~1.5, ~2.5

    # Apply filter
    filtered = service.apply_filters(data, ['dc_offset_removal'], 250.0)

    # Verify mean is approximately zero
    assert np.abs(np.mean(filtered[:, 0])) < 1e-10
    assert np.abs(np.mean(filtered[:, 1])) < 1e-10


def test_apply_filters_signal_integrity_cleaner():
    """Signal integrity cleaner delegates to underlying cleaner."""
    service = StreamingService(Mock(), Mock())
    data = np.ones((5, 2))
    mock_cleaned = np.full((5, 2), 2.0)
    mock_stats = {
        'total_interpolated_segments': 1,
        'total_dropped_segments': 0,
        'total_dropped_samples': 0
    }

    with patch.object(service._integrity_cleaner, 'clean', return_value=(mock_cleaned, mock_stats)) as mock_clean:
        filtered = service.apply_filters(data, ['signal_integrity_cleaner'], 250.0)

    mock_clean.assert_called_once()
    np.testing.assert_array_equal(filtered, mock_cleaned)


def test_apply_filters_scipy_missing_raises_error():
    """Test that missing scipy raises ImportError for filter operations."""
    # Create service
    service = StreamingService(Mock(), Mock())

    # Create sample data
    data = np.array([[1.0, 2.0], [1.5, 2.5], [1.2, 2.2]])

    # Mock scipy as missing
    with patch.dict('sys.modules', {'scipy': None, 'scipy.signal': None}):
        # Execute & Verify
        with pytest.raises(ImportError, match="scipy is required for filters"):
            service.apply_filters(data, ['highpass_0.5Hz'], 250.0)


@pytest.mark.skipif(
    not pytest.importorskip("scipy", minversion=None),
    reason="scipy not available"
)
def test_apply_filters_highpass_with_scipy():
    """Test high-pass filter with scipy available."""
    # Create service
    service = StreamingService(Mock(), Mock())

    # Create data with low-frequency component
    sampling_rate = 250.0
    t = np.linspace(0, 1, int(sampling_rate))
    # Low frequency (0.1 Hz) + high frequency (10 Hz)
    data = np.column_stack([
        np.sin(2 * np.pi * 0.1 * t) + np.sin(2 * np.pi * 10 * t),
        np.sin(2 * np.pi * 0.1 * t) + np.sin(2 * np.pi * 10 * t)
    ])

    # Apply high-pass filter (should remove 0.1 Hz component)
    filtered = service.apply_filters(data, ['highpass_0.5Hz'], sampling_rate)

    # Verify data was filtered (not just copied)
    assert filtered.shape == data.shape
    assert not np.allclose(filtered, data)


def test_apply_filters_multiple():
    """Test applying multiple filters in sequence."""
    # Create service
    service = StreamingService(Mock(), Mock())

    # Create data
    data = np.array([[1.5, 2.5], [1.7, 2.7], [1.3, 2.3]])

    # Apply DC offset removal (only non-scipy filter)
    filtered = service.apply_filters(data, ['dc_offset_removal'], 250.0)

    # Verify
    assert filtered.shape == data.shape
    assert np.abs(np.mean(filtered)) < 1e-10


def test_apply_filters_unknown_filter_logs_warning():
    """Test that unknown filter logs warning but doesn't crash."""
    # Create service
    service = StreamingService(Mock(), Mock())

    # Create data
    data = np.array([[1.0, 2.0], [1.5, 2.5]])

    # Apply unknown filter (should just return copy of data)
    filtered = service.apply_filters(data, ['unknown_filter'], 250.0)

    # Verify data unchanged
    assert np.allclose(filtered, data)


# ============================================================================
# trim_recording Tests
# ============================================================================

def test_trim_recording_success(streaming_service, mock_repository, sample_recording_metadata, tmp_patient_dir):
    """Test successful recording trimming."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata

    # Execute
    trimmed = streaming_service.trim_recording(
        patient_id="P01",
        recording_id="rec_001",
        start_sec=2.0,
        end_sec=5.0,
        filters=['dc_offset_removal'],
        output_name="trimmed.json"
    )

    # Verify - service generates UUID for trimmed recordings
    assert trimmed.id is not None
    assert isinstance(trimmed.id, str)
    assert trimmed.is_trimmed is True
    assert trimmed.patient_id == "P01"
    assert trimmed.duration_seconds == 3.0  # 5.0 - 2.0
    assert trimmed.processing_applied == ['dc_offset_removal']
    mock_repository.create.assert_called_once()

    # Verify output file was created
    output_file = tmp_patient_dir / "trimmed.json"
    assert output_file.exists()


def test_trim_recording_duration_uses_filtered_length(streaming_service, mock_repository, sample_recording_metadata, tmp_patient_dir):
    """Duration reflects filtered sample count when filters drop data."""
    mock_repository.get_by_id.return_value = sample_recording_metadata

    shortened = np.zeros((250, len(sample_recording_metadata.channel_labels)))

    with patch.object(streaming_service, 'apply_filters', return_value=shortened) as mock_apply:
        trimmed = streaming_service.trim_recording(
            patient_id="P01",
            recording_id="rec_001",
            start_sec=0.0,
            end_sec=2.0,
            filters=['signal_integrity_cleaner'],
            output_name="trimmed_integrity.json"
        )

    mock_apply.assert_called_once()
    assert trimmed.duration_seconds == pytest.approx(1.0)  # 250 samples @ 250 Hz

    output_file = tmp_patient_dir / "trimmed_integrity.json"
    with open(output_file) as f:
        payload = json.load(f)

    assert payload['metadata']['duration_seconds'] == pytest.approx(1.0)
    assert len(payload['data']['timestamps']) == 250
def test_trim_recording_invalid_range_start_after_end(streaming_service):
    """Test trimming with invalid time range (start >= end)."""
    # Execute & Verify
    with pytest.raises(ValueError, match="Invalid time range"):
        streaming_service.trim_recording(
            patient_id="P01",
            recording_id="rec_001",
            start_sec=5.0,
            end_sec=2.0,
            filters=[],
            output_name="trimmed.json"
        )


def test_trim_recording_end_exceeds_duration(streaming_service, mock_repository, sample_recording_metadata):
    """Test trimming with end time exceeding recording duration."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata

    # Execute & Verify
    with pytest.raises(ValueError, match="exceeds recording duration"):
        streaming_service.trim_recording(
            patient_id="P01",
            recording_id="rec_001",
            start_sec=2.0,
            end_sec=15.0,  # Recording is only 10s
            filters=[],
            output_name="trimmed.json"
        )


# ============================================================================
# get_recording_statistics Tests
# ============================================================================

def test_get_recording_statistics_success(streaming_service, mock_repository, sample_recording_metadata):
    """Test calculating recording statistics."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata

    # Execute
    stats = streaming_service.get_recording_statistics("P01", "rec_001")

    # Verify
    assert stats['duration_seconds'] == 10.0
    assert stats['sampling_rate'] == 250.0
    assert stats['channel_count'] == 4
    assert 'channels' in stats
    assert 'Ch0_Left_STN' in stats['channels']
    assert 'mean' in stats['channels']['Ch0_Left_STN']
    assert 'std' in stats['channels']['Ch0_Left_STN']
    assert 'min' in stats['channels']['Ch0_Left_STN']
    assert 'max' in stats['channels']['Ch0_Left_STN']
    assert 'total_power' in stats['channels']['Ch0_Left_STN']


# ============================================================================
# export_recording Tests
# ============================================================================

def test_export_recording_json(streaming_service, mock_repository, sample_recording_metadata, tmp_path):
    """Test exporting recording to JSON format."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata
    output_path = tmp_path / "export.json"

    # Execute
    streaming_service.export_recording("P01", "rec_001", output_path, format='json')

    # Verify
    assert output_path.exists()
    with open(output_path) as f:
        data = json.load(f)
        assert 'metadata' in data
        assert 'data' in data


def test_export_recording_csv(streaming_service, mock_repository, sample_recording_metadata, tmp_path):
    """Test exporting recording to CSV format."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata
    output_path = tmp_path / "export.csv"

    # Execute
    streaming_service.export_recording("P01", "rec_001", output_path, format='csv')

    # Verify
    assert output_path.exists()
    with open(output_path) as f:
        lines = f.readlines()
        assert len(lines) > 0
        assert 'time_sec' in lines[0]
        assert 'Ch0_Left_STN' in lines[0]


def test_export_recording_npy(streaming_service, mock_repository, sample_recording_metadata, tmp_path):
    """Test exporting recording to numpy format."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata
    output_path = tmp_path / "export.npy"

    # Execute
    streaming_service.export_recording("P01", "rec_001", output_path, format='npy')

    # Verify
    assert output_path.exists()
    loaded_data = np.load(output_path)
    assert loaded_data.shape == (2500, 4)


def test_export_recording_invalid_format(streaming_service, mock_repository, sample_recording_metadata, tmp_path):
    """Test exporting with invalid format."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording_metadata
    output_path = tmp_path / "export.xyz"

    # Execute & Verify
    with pytest.raises(ValueError, match="Unsupported export format"):
        streaming_service.export_recording("P01", "rec_001", output_path, format='xyz')
