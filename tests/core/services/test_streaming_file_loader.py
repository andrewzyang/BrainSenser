"""
Tests for StreamingFileLoader.

Tests file-based loading of streaming recording waveform data,
including standard JSON format, legacy format, NumPy format,
and various error conditions.

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import pytest
import json
import numpy as np
from src.core.services.streaming_file_loader import StreamingFileLoader


@pytest.fixture
def loader():
    """Create StreamingFileLoader instance."""
    return StreamingFileLoader()


@pytest.fixture
def temp_standard_json_file(tmp_path):
    """Create temporary JSON file with standard format."""
    file_path = tmp_path / "test_recording.json"
    sampling_rate = 250.0
    duration = 10.0
    n_samples = int(duration * sampling_rate)

    data = {
        'metadata': {
            'recording_date': '2024-03-15T09:30:00',
            'duration_seconds': duration,
            'sampling_rate': sampling_rate,
            'channel_count': 2,
            'channel_labels': ['Ch0_LEFT', 'Ch1_RIGHT']
        },
        'data': {
            'timestamps': list(np.arange(0, duration, 1/sampling_rate)),
            'channels': {
                'Ch0_LEFT': list(np.random.randn(n_samples)),
                'Ch1_RIGHT': list(np.random.randn(n_samples))
            }
        }
    }

    with open(file_path, 'w') as f:
        json.dump(data, f)

    return file_path


@pytest.fixture
def temp_legacy_json_file(tmp_path):
    """Create temporary JSON file with legacy TimeDomain format."""
    file_path = tmp_path / "test_legacy_recording.json"
    sampling_rate = 250.0
    duration = 5.0
    n_samples = int(duration * sampling_rate)

    data = {
        'TimeDomain': [
            {
                'Channel': 'Ch0_LEFT',
                'SampleRate': sampling_rate,
                'Timestamp': '2024-03-15T09:30:00',
                'LFPData': list(np.random.randn(n_samples))
            },
            {
                'Channel': 'Ch1_RIGHT',
                'SampleRate': sampling_rate,
                'Timestamp': '2024-03-15T09:30:00',
                'LFPData': list(np.random.randn(n_samples))
            }
        ]
    }

    with open(file_path, 'w') as f:
        json.dump(data, f)

    return file_path


@pytest.fixture
def temp_numpy_file(tmp_path):
    """Create temporary NumPy binary file."""
    file_path = tmp_path / "test_recording.npy"
    n_samples = 2500
    n_channels = 2
    waveform = np.random.randn(n_samples, n_channels)
    np.save(file_path, waveform)
    return file_path


# ========================================================================
# Standard Format Tests
# ========================================================================

def test_load_standard_format_success(loader, temp_standard_json_file):
    """Test loading standard JSON format successfully."""
    waveform, metadata = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    # Validate waveform shape
    assert waveform.shape == (2500, 2), f"Expected shape (2500, 2), got {waveform.shape}"
    assert waveform.dtype == np.float64

    # Validate metadata
    assert metadata['duration_seconds'] == 10.0
    assert metadata['sampling_rate'] == 250.0
    assert 'file_checksum' in metadata


def test_load_standard_format_channel_order(loader, temp_standard_json_file):
    """Test that channels are loaded in expected order."""
    # Load with swapped channel order
    waveform, metadata = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch1_RIGHT', 'Ch0_LEFT'],  # Swapped
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    # Waveform should still be (samples, 2) but columns swapped
    assert waveform.shape[1] == 2


def test_load_standard_format_missing_channel(loader, temp_standard_json_file):
    """Test loading when expected channel is missing from file."""
    # Expect a channel that doesn't exist
    waveform, metadata = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT', 'Ch2_MISSING'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    # Should still load, but with zeros for missing channel
    assert waveform.shape == (2500, 3)
    # Third channel should be all zeros
    assert np.allclose(waveform[:, 2], 0)


def test_load_standard_format_duration_tolerance(loader, temp_standard_json_file):
    """Test that small duration mismatches are tolerated."""
    # Slightly off duration should still work (within 1 second tolerance)
    waveform, metadata = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=10.5,  # Slightly off
        expected_sampling_rate=250.0
    )

    # Should still load without error
    assert waveform.shape[0] > 0


def test_checksum_computed(loader, temp_standard_json_file):
    """Test that file checksum is computed."""
    waveform, metadata = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    # Checksum should be present and 64 hex characters (SHA-256)
    assert 'file_checksum' in metadata
    assert len(metadata['file_checksum']) == 64
    assert all(c in '0123456789abcdef' for c in metadata['file_checksum'])


def test_checksum_consistent(loader, temp_standard_json_file):
    """Test that checksum is consistent across multiple loads."""
    _, metadata1 = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    _, metadata2 = loader.load_from_file(
        file_path=temp_standard_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    assert metadata1['file_checksum'] == metadata2['file_checksum']


# ========================================================================
# Legacy Format Tests
# ========================================================================

def test_load_legacy_format_success(loader, temp_legacy_json_file):
    """Test loading legacy TimeDomain format successfully."""
    waveform, metadata = loader.load_from_file(
        file_path=temp_legacy_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT'],
        expected_duration=5.0,
        expected_sampling_rate=250.0
    )

    # Validate waveform shape
    assert waveform.shape == (1250, 2)
    assert waveform.dtype == np.float64

    # Validate metadata
    assert metadata['format'] == 'legacy_time_domain'
    assert metadata['sampling_rate'] == 250.0


def test_load_legacy_format_missing_channel(loader, temp_legacy_json_file):
    """Test loading legacy format with missing channel."""
    waveform, metadata = loader.load_from_file(
        file_path=temp_legacy_json_file,
        expected_channels=['Ch0_LEFT', 'Ch1_RIGHT', 'Ch2_MISSING'],
        expected_duration=5.0,
        expected_sampling_rate=250.0
    )

    # Should load with zeros for missing channel
    assert waveform.shape == (1250, 3)
    assert np.allclose(waveform[:, 2], 0)


# ========================================================================
# NumPy Format Tests
# ========================================================================

def test_load_numpy_format_success(loader, temp_numpy_file):
    """Test loading NumPy binary format successfully."""
    waveform, metadata = loader.load_from_file(
        file_path=temp_numpy_file,
        expected_channels=['Ch0', 'Ch1'],
        expected_duration=10.0,
        expected_sampling_rate=250.0
    )

    # Validate waveform shape
    assert waveform.shape == (2500, 2)

    # Validate metadata
    assert metadata['format'] == 'numpy_binary'
    assert 'file_checksum' in metadata


def test_load_numpy_format_wrong_shape(loader, tmp_path):
    """Test error when NumPy array has wrong shape."""
    file_path = tmp_path / "wrong_shape.npy"
    # Create 1D array (wrong)
    waveform = np.random.randn(1000)
    np.save(file_path, waveform)

    with pytest.raises(ValueError, match="Expected 2D array"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0'],
            expected_duration=4.0,
            expected_sampling_rate=250.0
        )


def test_load_numpy_format_wrong_channel_count(loader, tmp_path):
    """Test error when NumPy array has wrong number of channels."""
    file_path = tmp_path / "wrong_channels.npy"
    # Create array with 3 channels, expect 2
    waveform = np.random.randn(1000, 3)
    np.save(file_path, waveform)

    with pytest.raises(ValueError, match="Channel count mismatch"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0', 'Ch1'],  # Expect 2
            expected_duration=4.0,
            expected_sampling_rate=250.0
        )


# ========================================================================
# Error Handling Tests
# ========================================================================

def test_load_missing_file(loader, tmp_path):
    """Test error when file doesn't exist."""
    nonexistent_file = tmp_path / "nonexistent.json"

    with pytest.raises(FileNotFoundError, match="Recording file not found"):
        loader.load_from_file(
            file_path=nonexistent_file,
            expected_channels=['Ch0'],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


def test_load_invalid_json(loader, tmp_path):
    """Test error when JSON is invalid."""
    file_path = tmp_path / "invalid.json"
    with open(file_path, 'w') as f:
        f.write("{ this is not valid json }")

    with pytest.raises(ValueError, match="Invalid JSON file"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0'],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


def test_load_unsupported_format(loader, tmp_path):
    """Test error for unsupported file format."""
    file_path = tmp_path / "unsupported.txt"
    with open(file_path, 'w') as f:
        f.write("Some text data")

    with pytest.raises(ValueError, match="Unsupported file format"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0'],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


def test_load_unrecognized_json_structure(loader, tmp_path):
    """Test error when JSON structure is unrecognized."""
    file_path = tmp_path / "unrecognized.json"
    data = {
        'some_key': 'some_value',
        'other_key': [1, 2, 3]
    }

    with open(file_path, 'w') as f:
        json.dump(data, f)

    with pytest.raises(ValueError, match="Unrecognized JSON structure"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0'],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


def test_load_json_missing_channels_key(loader, tmp_path):
    """Test error when JSON is missing required keys."""
    file_path = tmp_path / "missing_channels.json"
    data = {
        'metadata': {'duration': 10},
        'data': {}  # Missing 'channels' key
    }

    with open(file_path, 'w') as f:
        json.dump(data, f)

    with pytest.raises((ValueError, KeyError)):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=['Ch0'],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


# ========================================================================
# Checksum Tests
# ========================================================================

def test_compute_file_checksum(loader, temp_standard_json_file):
    """Test checksum computation."""
    checksum = loader.compute_file_checksum(temp_standard_json_file)

    # Should be 64 hex characters
    assert len(checksum) == 64
    assert all(c in '0123456789abcdef' for c in checksum)


def test_checksum_changes_with_content(loader, tmp_path):
    """Test that checksum changes when file content changes."""
    file_path = tmp_path / "test.json"

    # Write initial content
    with open(file_path, 'w') as f:
        json.dump({'data': [1, 2, 3]}, f)
    checksum1 = loader.compute_file_checksum(file_path)

    # Write different content
    with open(file_path, 'w') as f:
        json.dump({'data': [4, 5, 6]}, f)
    checksum2 = loader.compute_file_checksum(file_path)

    assert checksum1 != checksum2


# ========================================================================
# Integration-like Tests
# ========================================================================

def test_load_real_world_sized_file(loader, tmp_path):
    """Test loading a realistic-sized file (1 minute @ 250 Hz)."""
    file_path = tmp_path / "large_recording.json"
    sampling_rate = 250.0
    duration = 60.0  # 1 minute
    n_samples = int(duration * sampling_rate)  # 15,000 samples

    data = {
        'metadata': {
            'recording_date': '2024-03-15T09:30:00',
            'duration_seconds': duration,
            'sampling_rate': sampling_rate,
            'channel_count': 4,
            'channel_labels': ['Ch0', 'Ch1', 'Ch2', 'Ch3']
        },
        'data': {
            'timestamps': list(np.arange(0, duration, 1/sampling_rate)),
            'channels': {
                'Ch0': list(np.random.randn(n_samples)),
                'Ch1': list(np.random.randn(n_samples)),
                'Ch2': list(np.random.randn(n_samples)),
                'Ch3': list(np.random.randn(n_samples))
            }
        }
    }

    with open(file_path, 'w') as f:
        json.dump(data, f)

    # Load and verify
    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=['Ch0', 'Ch1', 'Ch2', 'Ch3'],
        expected_duration=duration,
        expected_sampling_rate=sampling_rate
    )

    assert waveform.shape == (15000, 4)
    assert 'file_checksum' in metadata


# ========================================================================
# Raw Medtronic Format Tests
# ========================================================================

def test_load_raw_medtronic_indefinite_streaming(loader, tmp_path):
    """Test loading raw IndefiniteStreaming format."""
    # Create raw format file
    raw_data = {
        "IndefiniteStreaming": [
            {
                "Channel": "ZERO_THREE_LEFT",
                "SampleRateInHz": 250,
                "FirstPacketDateTime": "2020-03-01T13:48:43.000Z",
                "Gain": 230,
                "TimeDomainData": [1.0, 2.0, 3.0, 4.0, 5.0]  # 5 samples
            },
            {
                "Channel": "ZERO_THREE_RIGHT",
                "SampleRateInHz": 250,
                "FirstPacketDateTime": "2020-03-01T13:48:43.000Z",
                "Gain": 228,
                "TimeDomainData": [6.0, 7.0, 8.0, 9.0, 10.0]
            }
        ]
    }

    file_path = tmp_path / "raw_streaming.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    # Load with StreamingFileLoader
    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.02,  # 5 samples / 250 Hz = 0.02s
        expected_sampling_rate=250.0
    )

    # Verify shape
    assert waveform.shape == (5, 2), f"Expected shape (5, 2), got {waveform.shape}"

    # Verify channel order (LEFT first, RIGHT second)
    assert np.allclose(waveform[:, 0], [1.0, 2.0, 3.0, 4.0, 5.0]), "LEFT channel data mismatch"
    assert np.allclose(waveform[:, 1], [6.0, 7.0, 8.0, 9.0, 10.0]), "RIGHT channel data mismatch"

    # Verify metadata
    assert metadata['sampling_rate'] == 250
    assert metadata['format'] == 'raw_medtronic_IndefiniteStreaming'
    assert metadata['channel_count'] == 2
    assert metadata['sample_count'] == 5


def test_load_raw_medtronic_brainsense_time_domain(loader, tmp_path):
    """Test loading raw BrainSenseTimeDomain format."""
    raw_data = {
        "BrainSenseTimeDomain": [
            {
                "Channel": "ZERO_TWO_LEFT_LEFT",
                "SampleRate": 250,
                "Timestamp": "2024-03-15T09:30:00",
                "TimeDomainData": [0.1, 0.2, 0.3]
            },
            {
                "Channel": "ZERO_TWO_RIGHT_RIGHT",
                "SampleRate": 250,
                "Timestamp": "2024-03-15T09:30:00",
                "TimeDomainData": [0.4, 0.5, 0.6]
            }
        ]
    }

    file_path = tmp_path / "raw_brainsense.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.012,  # 3 samples / 250 Hz
        expected_sampling_rate=250.0
    )

    assert waveform.shape == (3, 2)
    assert metadata['format'] == 'raw_medtronic_BrainSenseTimeDomain'
    assert np.allclose(waveform[:, 0], [0.1, 0.2, 0.3])
    assert np.allclose(waveform[:, 1], [0.4, 0.5, 0.6])


def test_load_raw_medtronic_missing_channel(loader, tmp_path):
    """Test handling of missing channels (should use zeros)."""
    raw_data = {
        "IndefiniteStreaming": [
            {
                "Channel": "ZERO_THREE_LEFT",
                "SampleRateInHz": 250,
                "TimeDomainData": [1.0, 2.0, 3.0]
            }
            # Missing RIGHT channel
        ]
    }

    file_path = tmp_path / "raw_missing_channel.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.012,
        expected_sampling_rate=250.0
    )

    # Verify shape (should still be 2 channels)
    assert waveform.shape == (3, 2)

    # Verify LEFT channel has data
    assert np.allclose(waveform[:, 0], [1.0, 2.0, 3.0])

    # Verify RIGHT channel is zeros
    assert np.allclose(waveform[:, 1], [0.0, 0.0, 0.0])


def test_load_raw_medtronic_channel_mapping_by_hemisphere(loader, tmp_path):
    """Test channel mapping by hemisphere detection."""
    raw_data = {
        "IndefiniteStreaming": [
            {
                "Channel": "EIGHT_ELEVEN_LEFT",
                "SampleRateInHz": 250,
                "TimeDomainData": [10.0, 20.0, 30.0]
            },
            {
                "Channel": "EIGHT_ELEVEN_RIGHT",
                "SampleRateInHz": 250,
                "TimeDomainData": [40.0, 50.0, 60.0]
            }
        ]
    }

    file_path = tmp_path / "raw_hemisphere.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.012,
        expected_sampling_rate=250.0
    )

    # Should match by hemisphere
    assert waveform.shape == (3, 2)
    assert np.allclose(waveform[:, 0], [10.0, 20.0, 30.0])  # LEFT
    assert np.allclose(waveform[:, 1], [40.0, 50.0, 60.0])  # RIGHT


def test_load_raw_medtronic_lfp_data_field(loader, tmp_path):
    """Test loading raw format with LFPData field instead of TimeDomainData."""
    raw_data = {
        "BrainSenseTimeDomain": [
            {
                "Channel": "ZERO_THREE_LEFT",
                "SampleRate": 250,
                "Timestamp": "2024-03-15T09:30:00",
                "LFPData": [1.1, 2.2, 3.3]  # Using LFPData instead
            },
            {
                "Channel": "ZERO_THREE_RIGHT",
                "SampleRate": 250,
                "Timestamp": "2024-03-15T09:30:00",
                "LFPData": [4.4, 5.5, 6.6]
            }
        ]
    }

    file_path = tmp_path / "raw_lfp.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.012,
        expected_sampling_rate=250.0
    )

    assert waveform.shape == (3, 2)
    assert np.allclose(waveform[:, 0], [1.1, 2.2, 3.3])
    assert np.allclose(waveform[:, 1], [4.4, 5.5, 6.6])


def test_load_raw_medtronic_large_recording(loader, tmp_path):
    """Test loading a realistic-sized raw Medtronic file."""
    sampling_rate = 250.0
    duration = 10.0  # 10 seconds
    n_samples = int(duration * sampling_rate)  # 2500 samples

    # Generate realistic waveform data
    left_data = list(np.sin(2 * np.pi * 5 * np.arange(n_samples) / sampling_rate))
    right_data = list(np.cos(2 * np.pi * 5 * np.arange(n_samples) / sampling_rate))

    raw_data = {
        "IndefiniteStreaming": [
            {
                "Channel": "ZERO_THREE_LEFT",
                "SampleRateInHz": sampling_rate,
                "FirstPacketDateTime": "2020-03-01T13:48:43.000Z",
                "Gain": 230,
                "TimeDomainData": left_data
            },
            {
                "Channel": "ZERO_THREE_RIGHT",
                "SampleRateInHz": sampling_rate,
                "FirstPacketDateTime": "2020-03-01T13:48:43.000Z",
                "Gain": 228,
                "TimeDomainData": right_data
            }
        ]
    }

    file_path = tmp_path / "raw_large.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=duration,
        expected_sampling_rate=sampling_rate
    )

    assert waveform.shape == (2500, 2)
    assert metadata['format'] == 'raw_medtronic_IndefiniteStreaming'
    assert metadata['sampling_rate'] == 250
    assert 'file_checksum' in metadata


def test_load_raw_medtronic_no_streaming_records(loader, tmp_path):
    """Test error when file has no streaming records."""
    raw_data = {
        "IndefiniteStreaming": []  # Empty array
    }

    file_path = tmp_path / "raw_empty.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    with pytest.raises(ValueError, match="No streaming records found"):
        loader.load_from_file(
            file_path=file_path,
            expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
            expected_duration=10.0,
            expected_sampling_rate=250.0
        )


def test_load_raw_medtronic_no_timedomain_data(loader, tmp_path):
    """Test handling of records without TimeDomainData."""
    raw_data = {
        "IndefiniteStreaming": [
            {
                "Channel": "ZERO_THREE_LEFT",
                "SampleRateInHz": 250,
                # Missing TimeDomainData
            },
            {
                "Channel": "ZERO_THREE_RIGHT",
                "SampleRateInHz": 250,
                "TimeDomainData": [1.0, 2.0, 3.0]
            }
        ]
    }

    file_path = tmp_path / "raw_no_timedomain.json"
    with open(file_path, 'w') as f:
        json.dump(raw_data, f)

    waveform, metadata = loader.load_from_file(
        file_path=file_path,
        expected_channels=["Ch0_LEFT", "Ch1_RIGHT"],
        expected_duration=0.012,
        expected_sampling_rate=250.0
    )

    # Should still load, LEFT channel should be zeros
    assert waveform.shape == (3, 2)
    assert np.allclose(waveform[:, 0], [0.0, 0.0, 0.0])  # LEFT missing
    assert np.allclose(waveform[:, 1], [1.0, 2.0, 3.0])  # RIGHT has data


def test_is_raw_medtronic_format_detection(loader):
    """Test raw Medtronic format detection helper."""
    # Test IndefiniteStreaming detection
    data1 = {
        "IndefiniteStreaming": [
            {"Channel": "LEFT", "TimeDomainData": [1, 2, 3]}
        ]
    }
    assert loader._is_raw_medtronic_format(data1) is True

    # Test BrainSenseTimeDomain detection
    data2 = {
        "BrainSenseTimeDomain": [
            {"Channel": "LEFT", "TimeDomainData": [1, 2, 3]}
        ]
    }
    assert loader._is_raw_medtronic_format(data2) is True

    # Test non-raw format (standard)
    data3 = {
        "data": {"channels": {"Ch0": [1, 2, 3]}}
    }
    assert loader._is_raw_medtronic_format(data3) is False

    # Test non-raw format (legacy)
    data4 = {
        "TimeDomain": [{"Channel": "LEFT", "LFPData": [1, 2, 3]}]
    }
    assert loader._is_raw_medtronic_format(data4) is False

    # Test empty array (still raw format, will fail later with specific error)
    data5 = {
        "IndefiniteStreaming": []
    }
    assert loader._is_raw_medtronic_format(data5) is True


def test_channels_match_hemisphere_helper(loader):
    """Test hemisphere matching helper."""
    # Test LEFT matching
    assert loader._channels_match_hemisphere("ZERO_THREE_LEFT", "Ch0_LEFT") is True
    assert loader._channels_match_hemisphere("EIGHT_ELEVEN_LEFT", "Ch0_LEFT") is True

    # Test RIGHT matching
    assert loader._channels_match_hemisphere("ZERO_THREE_RIGHT", "Ch1_RIGHT") is True
    assert loader._channels_match_hemisphere("EIGHT_ELEVEN_RIGHT", "Ch1_RIGHT") is True

    # Test non-matching
    assert loader._channels_match_hemisphere("ZERO_THREE_LEFT", "Ch1_RIGHT") is False
    assert loader._channels_match_hemisphere("ZERO_THREE_RIGHT", "Ch0_LEFT") is False

    # Test case insensitivity
    assert loader._channels_match_hemisphere("zero_three_left", "ch0_left") is True
    assert loader._channels_match_hemisphere("ZERO_THREE_LEFT", "ch0_left") is True
