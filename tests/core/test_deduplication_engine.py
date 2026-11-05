"""
Tests for DeduplicationEngine.

Tests hash calculation for timeline records, snapshot records, and files.
Verifies hash consistency, determinism, and collision avoidance.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import tempfile
from datetime import datetime
from pathlib import Path

from src.core.deduplication_engine import DeduplicationEngine
from src.core.models.timeline_record import TimelineRecord
from src.core.models.snapshot_record import SnapshotRecord


class TestDeduplicationEngine:
    """Test suite for DeduplicationEngine."""

    # ========================================================================
    # Timeline Hash Tests
    # ========================================================================

    def test_timeline_hash_is_deterministic(self):
        """Timeline hash should be consistent for same data."""
        record1 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            unix_timestamp=1704110400.0,
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            therapy_status="ON",
        )

        record2 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            unix_timestamp=1704110400.0,
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            therapy_status="ON",
        )

        hash1 = DeduplicationEngine.calculate_timeline_hash(record1)
        hash2 = DeduplicationEngine.calculate_timeline_hash(record2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_timeline_hash_ignores_metadata(self):
        """Timeline hash should ignore source_file and other metadata."""
        record1 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            source_file="file1.json",
            session_id="session1",
        )

        record2 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            source_file="file2.json",  # Different
            session_id="session2",  # Different
        )

        hash1 = DeduplicationEngine.calculate_timeline_hash(record1)
        hash2 = DeduplicationEngine.calculate_timeline_hash(record2)

        # Hashes should be same despite different metadata
        assert hash1 == hash2

    def test_timeline_hash_detects_data_changes(self):
        """Timeline hash should change when data changes."""
        record1 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=95.3,
        )

        record2 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=96.0,  # Different
        )

        hash1 = DeduplicationEngine.calculate_timeline_hash(record1)
        hash2 = DeduplicationEngine.calculate_timeline_hash(record2)

        # Hashes should be different
        assert hash1 != hash2

    def test_timeline_hash_with_therapy_settings(self):
        """Timeline hash should include therapy settings."""
        record1 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            left_amplitude=2.5,
            left_frequency=130.0,
        )

        record2 = TimelineRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            left_hemisphere=100.5,
            right_hemisphere=95.3,
            left_amplitude=3.0,  # Different
            left_frequency=130.0,
        )

        hash1 = DeduplicationEngine.calculate_timeline_hash(record1)
        hash2 = DeduplicationEngine.calculate_timeline_hash(record2)

        # Different therapy settings should produce different hashes
        assert hash1 != hash2

    # ========================================================================
    # Snapshot Hash Tests
    # ========================================================================

    def test_snapshot_hash_is_deterministic(self):
        """Snapshot hash should be consistent for same data."""
        record1 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            unix_timestamp=1704110400.0,
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            hemisphere="LEFT",
        )

        record2 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            unix_timestamp=1704110400.0,
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            hemisphere="LEFT",
        )

        hash1 = DeduplicationEngine.calculate_snapshot_hash(record1)
        hash2 = DeduplicationEngine.calculate_snapshot_hash(record2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_snapshot_hash_ignores_metadata(self):
        """Snapshot hash should ignore source_file and other metadata."""
        record1 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            source_file="file1.json",
            session_id="session1",
        )

        record2 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            source_file="file2.json",  # Different
            session_id="session2",  # Different
        )

        hash1 = DeduplicationEngine.calculate_snapshot_hash(record1)
        hash2 = DeduplicationEngine.calculate_snapshot_hash(record2)

        # Hashes should be same despite different metadata
        assert hash1 == hash2

    def test_snapshot_hash_detects_data_changes(self):
        """Snapshot hash should change when data changes."""
        record1 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
        )

        record2 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 35.0]',  # Different
        )

        hash1 = DeduplicationEngine.calculate_snapshot_hash(record1)
        hash2 = DeduplicationEngine.calculate_snapshot_hash(record2)

        # Hashes should be different
        assert hash1 != hash2

    def test_snapshot_hash_includes_event_info(self):
        """Snapshot hash should include event information."""
        record1 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            event_type="PatientTriggered",
            event_name="Test1",
        )

        record2 = SnapshotRecord(
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            frequency_data='[1.0, 2.0, 3.0]',
            power_data='[10.0, 20.0, 30.0]',
            event_type="PatientTriggered",
            event_name="Test2",  # Different
        )

        hash1 = DeduplicationEngine.calculate_snapshot_hash(record1)
        hash2 = DeduplicationEngine.calculate_snapshot_hash(record2)

        # Different event info should produce different hashes
        assert hash1 != hash2

    # ========================================================================
    # File Hash Tests
    # ========================================================================

    def test_file_hash_is_deterministic(self):
        """File hash should be consistent for same content."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Test content for hashing")
            temp_path = Path(f.name)

        try:
            hash1 = DeduplicationEngine.calculate_file_hash(temp_path)
            hash2 = DeduplicationEngine.calculate_file_hash(temp_path)

            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex length
        finally:
            temp_path.unlink()

    def test_file_hash_detects_content_changes(self):
        """File hash should change when content changes."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("Original content")
            temp_path = Path(f.name)

        try:
            hash1 = DeduplicationEngine.calculate_file_hash(temp_path)

            # Modify file
            with open(temp_path, 'w') as f:
                f.write("Modified content")

            hash2 = DeduplicationEngine.calculate_file_hash(temp_path)

            # Hashes should be different
            assert hash1 != hash2
        finally:
            temp_path.unlink()

    def test_file_hash_raises_on_missing_file(self):
        """File hash should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            DeduplicationEngine.calculate_file_hash("/nonexistent/file.txt")

    def test_file_hash_raises_on_directory(self):
        """File hash should raise ValueError for directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(ValueError, match="Not a file"):
                DeduplicationEngine.calculate_file_hash(temp_dir)

    def test_file_hash_handles_large_files(self):
        """File hash should handle large files efficiently."""
        # Create a 1MB file
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.bin') as f:
            f.write(b'X' * 1024 * 1024)
            temp_path = Path(f.name)

        try:
            hash_value = DeduplicationEngine.calculate_file_hash(temp_path)
            assert len(hash_value) == 64  # SHA256 hex length
        finally:
            temp_path.unlink()

    def test_file_hash_handles_empty_file(self):
        """File hash should handle empty files."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            # Write nothing
            temp_path = Path(f.name)

        try:
            hash_value = DeduplicationEngine.calculate_file_hash(temp_path)
            assert len(hash_value) == 64  # SHA256 hex length
        finally:
            temp_path.unlink()
