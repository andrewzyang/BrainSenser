"""
Tests for checksum validation in StreamingService.

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch
from src.core.services.streaming_service import StreamingService
from src.core.models import StreamingRecording
from src.core.services.streaming_file_loader import StreamingFileLoader
from datetime import datetime


@pytest.fixture
def mock_repository():
    """Mock StreamingRecordingRepository."""
    return Mock()


@pytest.fixture
def mock_path_resolver():
    """Mock PathResolver."""
    resolver = Mock()
    resolver.get_patient_directory.return_value = Path("/mock/patient/dir")
    return resolver


@pytest.fixture
def streaming_service(mock_repository, mock_path_resolver):
    """Create StreamingService with mocked dependencies."""
    return StreamingService(mock_repository, mock_path_resolver)


@pytest.fixture
def sample_recording():
    """Create sample StreamingRecording for testing."""
    return StreamingRecording(
        id="test_rec_001",
        patient_id="TEST",
        file_path="/path/to/recording.json",
        recording_date=datetime(2025, 1, 1, 12, 0),
        duration_seconds=10.0,
        sampling_rate=250.0,
        channel_count=2,
        channel_labels=["Ch0", "Ch1"],
        file_size_bytes=1024,
        is_trimmed=False,
        file_checksum=None
    )


def test_load_recording_validates_checksum_match(streaming_service, mock_repository, sample_recording):
    """Test that load_recording validates stored checksum successfully when it matches."""
    # Setup - recording with stored checksum
    sample_recording.file_checksum = "abc123def456"
    mock_repository.get_by_id.return_value = sample_recording

    # Mock file path resolution and loader
    mock_waveform = np.random.randn(2500, 2)
    mock_metadata = {'file_checksum': 'abc123def456'}

    with patch.object(streaming_service, '_resolve_file_path', return_value=Path("/path/to/file.json")):
        with patch.object(StreamingFileLoader, 'compute_file_checksum', return_value='abc123def456'):
            with patch.object(StreamingFileLoader, 'load_from_file', return_value=(mock_waveform, mock_metadata)):
                # Should succeed without raising error
                waveform, recording = streaming_service.load_recording("TEST", "test_rec_001")

                assert np.array_equal(waveform, mock_waveform)
                assert recording.id == "test_rec_001"


def test_load_recording_validates_checksum_mismatch(streaming_service, mock_repository, sample_recording):
    """Test that load_recording raises RuntimeError when checksum doesn't match."""
    # Setup - recording with stored checksum
    sample_recording.file_checksum = "abc123def456"
    mock_repository.get_by_id.return_value = sample_recording

    # Mock file path resolution and loader to return different checksum
    with patch.object(streaming_service, '_resolve_file_path', return_value=Path("/path/to/file.json")):
        with patch.object(StreamingFileLoader, 'compute_file_checksum', return_value='xyz789different'):
            # Should raise RuntimeError (FileIntegrityError is wrapped)
            with pytest.raises(RuntimeError) as exc_info:
                streaming_service.load_recording("TEST", "test_rec_001")

            # Verify error message contains useful information
            error_msg = str(exc_info.value)
            assert "checksum mismatch" in error_msg.lower()
            assert "abc123def456" in error_msg  # Expected checksum
            assert "xyz789different" in error_msg  # Computed checksum


def test_load_recording_stores_checksum_if_missing(streaming_service, mock_repository, sample_recording):
    """Test that checksum is computed and stored if not present in database."""
    # Setup - recording WITHOUT stored checksum
    sample_recording.file_checksum = None
    mock_repository.get_by_id.return_value = sample_recording

    # Mock file path resolution and loader
    mock_waveform = np.random.randn(2500, 2)
    mock_metadata = {'file_checksum': 'computed_abc123'}

    with patch.object(streaming_service, '_resolve_file_path', return_value=Path("/path/to/file.json")):
        with patch.object(StreamingFileLoader, 'load_from_file', return_value=(mock_waveform, mock_metadata)):
            # Load recording
            waveform, recording = streaming_service.load_recording("TEST", "test_rec_001")

            # Should update repository with computed checksum
            mock_repository.update.assert_called_once()
            updated_recording = mock_repository.update.call_args[0][1]
            assert updated_recording.file_checksum == 'computed_abc123'


def test_load_recording_skips_validation_if_no_checksum(streaming_service, mock_repository, sample_recording):
    """Test that validation is skipped if no checksum is stored (backward compatibility)."""
    # Setup - recording WITHOUT stored checksum
    sample_recording.file_checksum = None
    mock_repository.get_by_id.return_value = sample_recording

    # Mock file path resolution and loader
    mock_waveform = np.random.randn(2500, 2)
    mock_metadata = {'file_checksum': 'new_checksum'}

    with patch.object(streaming_service, '_resolve_file_path', return_value=Path("/path/to/file.json")):
        # compute_file_checksum should NOT be called if no checksum stored
        with patch.object(StreamingFileLoader, 'compute_file_checksum') as mock_compute:
            with patch.object(StreamingFileLoader, 'load_from_file', return_value=(mock_waveform, mock_metadata)):
                waveform, recording = streaming_service.load_recording("TEST", "test_rec_001")

                # compute_file_checksum should not have been called for validation
                # (only called inside load_from_file if needed)
                mock_compute.assert_not_called()


def test_trim_recording_computes_and_stores_checksum(streaming_service, mock_repository, sample_recording, tmp_path):
    """Test that trimmed recording has checksum computed and stored."""
    # Setup - mock original recording load
    mock_repository.get_by_id.return_value = sample_recording
    mock_waveform = np.random.randn(2500, 2)

    # Mock the output directory
    output_path = tmp_path / "trimmed.json"

    with patch.object(streaming_service, 'load_recording', return_value=(mock_waveform, sample_recording)):
        with patch.object(streaming_service, '_save_recording_to_file'):
            with patch.object(streaming_service.path_resolver, 'get_patient_directory', return_value=tmp_path):
                with patch.object(StreamingFileLoader, 'compute_file_checksum', return_value='trimmed_checksum_abc'):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 2048

                        # Create mock for repository.create that captures the recording
                        created_recording = None

                        def capture_create(patient_id, recording):
                            nonlocal created_recording
                            created_recording = recording
                            return recording

                        mock_repository.create.side_effect = capture_create

                        # Trim recording
                        result = streaming_service.trim_recording(
                            patient_id="TEST",
                            recording_id="test_rec_001",
                            start_sec=0.0,
                            end_sec=5.0,
                            filters=[],
                            output_name="trimmed.json"
                        )

                        # Verify checksum was computed and stored
                        assert created_recording is not None
                        assert created_recording.file_checksum == 'trimmed_checksum_abc'
                        assert created_recording.file_checksum is not None


def test_trim_recording_checksum_has_correct_length(streaming_service, mock_repository, sample_recording, tmp_path):
    """Test that computed checksum has expected SHA-256 length."""
    # Setup
    mock_repository.get_by_id.return_value = sample_recording
    mock_waveform = np.random.randn(2500, 2)

    # Real SHA-256 hash is 64 hex characters
    real_checksum = "a" * 64

    with patch.object(streaming_service, 'load_recording', return_value=(mock_waveform, sample_recording)):
        with patch.object(streaming_service, '_save_recording_to_file'):
            with patch.object(streaming_service.path_resolver, 'get_patient_directory', return_value=tmp_path):
                with patch.object(StreamingFileLoader, 'compute_file_checksum', return_value=real_checksum):
                    with patch('pathlib.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 2048

                        created_recording = None

                        def capture_create(patient_id, recording):
                            nonlocal created_recording
                            created_recording = recording
                            return recording

                        mock_repository.create.side_effect = capture_create

                        result = streaming_service.trim_recording(
                            patient_id="TEST",
                            recording_id="test_rec_001",
                            start_sec=0.0,
                            end_sec=5.0,
                            filters=[],
                            output_name="trimmed.json"
                        )

                        # Verify checksum length (SHA-256 = 64 hex chars)
                        assert len(created_recording.file_checksum) == 64
                        assert all(c in '0123456789abcdef' for c in created_recording.file_checksum.lower())


def test_file_integrity_error_contains_useful_info(streaming_service, mock_repository, sample_recording):
    """Test that FileIntegrityError message contains actionable information."""
    sample_recording.file_checksum = "expected_checksum"
    mock_repository.get_by_id.return_value = sample_recording

    file_path = Path("/path/to/file.json")

    with patch.object(streaming_service, '_resolve_file_path', return_value=file_path):
        with patch.object(StreamingFileLoader, 'compute_file_checksum', return_value='computed_checksum'):
            with pytest.raises(RuntimeError) as exc_info:
                streaming_service.load_recording("TEST", "test_rec_001")

            error_msg = str(exc_info.value)

            # Should contain key information
            assert "test_rec_001" in error_msg  # Recording ID
            assert "expected_checksum" in error_msg  # Expected value
            assert "computed_checksum" in error_msg  # Actual value
            assert str(file_path) in error_msg  # File location
            assert any(word in error_msg.lower() for word in ['corrupt', 'modified', 'integrity'])
