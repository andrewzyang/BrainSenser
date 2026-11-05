"""
Tests for atomic file writer utility.

Author: iEEG BrainSense Development Team
Created: 2025-10-08
"""

import pytest
import json
from pathlib import Path
from src.core.utils.atomic_file_writer import AtomicFileWriter


def test_atomic_write_success(tmp_path):
    """Test successful atomic write."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    with writer.atomic_write(target) as temp_path:
        # Write to temp file
        temp_path.write_text('{"key": "value"}')
        assert temp_path.exists()
        assert temp_path.suffix.endswith('.tmp')

    # After context, temp file should be renamed to target
    assert target.exists()
    assert not temp_path.exists()
    assert json.loads(target.read_text()) == {"key": "value"}


def test_atomic_write_failure_cleanup(tmp_path):
    """Test that temp file is cleaned up on failure."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    temp_path_captured = None

    with pytest.raises(ValueError):
        with writer.atomic_write(target) as temp_path:
            temp_path_captured = temp_path
            # Write to temp file
            temp_path.write_text("some data")
            assert temp_path.exists()

            # Simulate error
            raise ValueError("Simulated error")

    # After exception, temp file should be cleaned up
    assert not target.exists()
    assert temp_path_captured is not None
    assert not temp_path_captured.exists()


def test_atomic_write_creates_parent_directory(tmp_path):
    """Test that parent directory is created if it doesn't exist."""
    writer = AtomicFileWriter()
    target = tmp_path / "subdir" / "nested" / "test.json"

    with writer.atomic_write(target) as temp_path:
        temp_path.write_text('{"key": "value"}')

    # Parent directories should be created
    assert target.exists()
    assert target.parent.exists()


def test_write_json_atomic_success(tmp_path):
    """Test JSON write with atomic operations."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"
    data = {"key": "value", "number": 42}

    result = writer.write_json_atomic(target, data)

    assert result == target
    assert target.exists()
    assert json.loads(target.read_text()) == data


def test_write_json_atomic_with_hook(tmp_path):
    """Test JSON write with pre-commit hook."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    hook_called = []

    def hook(temp_path: Path):
        # Verify temp file exists and has content
        assert temp_path.exists()
        content = json.loads(temp_path.read_text())
        assert content == {"key": "value"}
        hook_called.append(True)

    result = writer.write_json_atomic(target, {"key": "value"}, pre_commit_hook=hook)

    assert result == target
    assert target.exists()
    assert len(hook_called) == 1


def test_write_json_atomic_hook_failure_cleanup(tmp_path):
    """Test that file is not created if pre-commit hook fails."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    def failing_hook(temp_path: Path):
        raise ValueError("Hook failed")

    with pytest.raises(ValueError, match="Hook failed"):
        writer.write_json_atomic(target, {"key": "value"}, pre_commit_hook=failing_hook)

    # File should not exist
    assert not target.exists()

    # Temp file should be cleaned up
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_atomic_write_no_cleanup_on_error_flag(tmp_path):
    """Test that temp file can be preserved on error if cleanup_on_error=False."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    temp_path_captured = None

    with pytest.raises(ValueError):
        with writer.atomic_write(target, cleanup_on_error=False) as temp_path:
            temp_path_captured = temp_path
            temp_path.write_text("some data")
            raise ValueError("Error")

    # Temp file should still exist
    assert temp_path_captured is not None
    assert temp_path_captured.exists()


def test_write_json_atomic_nested_data(tmp_path):
    """Test atomic write with nested JSON structure."""
    writer = AtomicFileWriter()
    target = tmp_path / "nested.json"

    data = {
        'metadata': {
            'patient_id': 'TEST',
            'recording_date': '2025-10-08T10:00:00',
            'duration_seconds': 300.0
        },
        'data': {
            'channels': {
                'LFP_L1': [1.0, 2.0, 3.0],
                'LFP_L2': [4.0, 5.0, 6.0]
            }
        }
    }

    result = writer.write_json_atomic(target, data)

    assert result == target
    assert target.exists()
    loaded = json.loads(target.read_text())
    assert loaded == data
    assert loaded['metadata']['patient_id'] == 'TEST'
    assert loaded['data']['channels']['LFP_L1'] == [1.0, 2.0, 3.0]


def test_atomic_write_custom_suffix(tmp_path):
    """Test atomic writer with custom temp suffix."""
    writer = AtomicFileWriter(temp_suffix='.temporary')
    target = tmp_path / "test.json"

    temp_path_captured = None

    with writer.atomic_write(target) as temp_path:
        temp_path_captured = temp_path
        temp_path.write_text('{"key": "value"}')
        assert temp_path.suffix.endswith('.temporary')

    assert target.exists()
    assert not temp_path_captured.exists()


def test_write_json_atomic_large_data(tmp_path):
    """Test atomic write with larger dataset."""
    writer = AtomicFileWriter()
    target = tmp_path / "large.json"

    # Create a larger dataset
    data = {
        'metadata': {'count': 1000},
        'data': [i * 0.5 for i in range(1000)]
    }

    result = writer.write_json_atomic(target, data)

    assert result == target
    assert target.exists()
    loaded = json.loads(target.read_text())
    assert len(loaded['data']) == 1000
    assert loaded['data'][0] == 0.0
    assert loaded['data'][999] == 999 * 0.5


def test_hook_can_access_temp_file_content(tmp_path):
    """Test that pre-commit hook can read and validate temp file content."""
    writer = AtomicFileWriter()
    target = tmp_path / "test.json"

    validation_results = []

    def validation_hook(temp_path: Path):
        # Read temp file
        content = json.loads(temp_path.read_text())

        # Validate content
        if 'required_field' not in content:
            raise ValueError("Missing required field")

        # Store validation result
        validation_results.append(content['required_field'])

    # Should succeed
    writer.write_json_atomic(
        target,
        {'required_field': 'present'},
        pre_commit_hook=validation_hook
    )

    assert len(validation_results) == 1
    assert validation_results[0] == 'present'

    # Should fail
    target2 = tmp_path / "test2.json"
    with pytest.raises(ValueError, match="Missing required field"):
        writer.write_json_atomic(
            target2,
            {'other_field': 'value'},
            pre_commit_hook=validation_hook
        )

    # Second file should not exist
    assert not target2.exists()
