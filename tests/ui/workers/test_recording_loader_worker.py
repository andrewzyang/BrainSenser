"""
Tests for RecordingLoaderWorker.

Tests the async recording loading worker, including:
- Successful loading with progress signals
- Error handling
- Signal emissions

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
"""

import pytest
import numpy as np
from datetime import datetime
from unittest.mock import Mock

from src.ui.workers import RecordingLoaderWorker
from src.core.models import StreamingRecording
from src.core.services.streaming_service import StreamingService


@pytest.fixture
def mock_streaming_service():
    """Create mock StreamingService."""
    service = Mock(spec=StreamingService)
    return service


@pytest.fixture
def sample_recording():
    """Create sample StreamingRecording."""
    return StreamingRecording(
        id="rec_001",
        patient_id="P01",
        file_path="/path/to/recording.json",
        original_file_path=None,
        recording_date=datetime(2024, 3, 15, 9, 30, 0),
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


@pytest.fixture
def sample_waveform():
    """Create sample waveform data."""
    return np.random.randn(2500, 4)  # 10s @ 250Hz, 4 channels


# ============================================================================
# Initialization Tests
# ============================================================================

def test_worker_initialization(mock_streaming_service):
    """Test RecordingLoaderWorker initializes correctly."""
    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    assert worker.streaming_service == mock_streaming_service
    assert worker.patient_id == "P01"
    assert worker.recording_id == "rec_001"
    assert worker.signals is not None


# ============================================================================
# Loading Tests
# ============================================================================

def test_worker_successful_load_sync(mock_streaming_service, sample_recording, sample_waveform):
    """Test worker successfully loads recording (synchronous test)."""
    # Setup
    mock_streaming_service.load_recording.return_value = (sample_waveform, sample_recording)

    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    # Connect signals to capture results
    progress_signals = []
    finished_signals = []
    error_signals = []

    def on_progress(percent, message):
        progress_signals.append((percent, message))

    def on_finished(waveform, recording):
        finished_signals.append((waveform, recording))

    def on_error(message):
        error_signals.append(message)

    worker.signals.progress.connect(on_progress)
    worker.signals.finished.connect(on_finished)
    worker.signals.error.connect(on_error)

    # Execute synchronously (call run directly instead of using thread pool)
    worker.run()

    # Verify
    assert len(finished_signals) == 1
    assert len(error_signals) == 0
    assert len(progress_signals) > 0  # Should have progress updates

    waveform, recording = finished_signals[0]
    assert np.array_equal(waveform, sample_waveform)
    assert recording.id == "rec_001"

    mock_streaming_service.load_recording.assert_called_once_with("P01", "rec_001")


def test_worker_emits_progress_signals(mock_streaming_service, sample_recording, sample_waveform):
    """Test worker emits progress updates during loading."""
    # Setup
    mock_streaming_service.load_recording.return_value = (sample_waveform, sample_recording)

    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    progress_signals = []
    worker.signals.progress.connect(lambda p, m: progress_signals.append((p, m)))

    # Execute synchronously
    worker.run()

    # Verify progress signals were emitted
    assert len(progress_signals) > 0

    # Verify progress values are in range
    for percent, message in progress_signals:
        assert 0 <= percent <= 100
        assert isinstance(message, str)
        assert len(message) > 0

    # Verify final progress is 100%
    assert progress_signals[-1][0] == 100


def test_worker_handles_file_not_found(mock_streaming_service):
    """Test worker handles FileNotFoundError."""
    # Setup
    mock_streaming_service.load_recording.side_effect = FileNotFoundError("File not found")

    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    error_signals = []
    finished_signals = []

    worker.signals.error.connect(lambda msg: error_signals.append(msg))
    worker.signals.finished.connect(lambda w, r: finished_signals.append((w, r)))

    # Execute synchronously
    worker.run()

    # Verify
    assert len(error_signals) == 1
    assert len(finished_signals) == 0
    assert "file not found" in error_signals[0].lower()


def test_worker_handles_invalid_data(mock_streaming_service):
    """Test worker handles ValueError for invalid data."""
    # Setup
    mock_streaming_service.load_recording.side_effect = ValueError("Invalid data format")

    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    error_signals = []
    worker.signals.error.connect(lambda msg: error_signals.append(msg))

    # Execute synchronously
    worker.run()

    # Verify
    assert len(error_signals) == 1
    assert "invalid" in error_signals[0].lower()


def test_worker_handles_generic_exception(mock_streaming_service):
    """Test worker handles unexpected exceptions."""
    # Setup
    mock_streaming_service.load_recording.side_effect = RuntimeError("Unexpected error")

    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    error_signals = []
    worker.signals.error.connect(lambda msg: error_signals.append(msg))

    # Execute synchronously
    worker.run()

    # Verify
    assert len(error_signals) == 1
    assert "failed to load" in error_signals[0].lower()


def test_worker_cancellation(mock_streaming_service):
    """Test worker can be cancelled."""
    worker = RecordingLoaderWorker(mock_streaming_service, "P01", "rec_001")

    # Cancel before execution
    worker.cancel()

    # Verify cancellation flag is set
    assert worker._is_cancelled is True


# ============================================================================
# Integration Tests
# ============================================================================

# Note: Integration test with real StreamingService would require full Qt
# application setup and is better tested manually or in end-to-end tests
