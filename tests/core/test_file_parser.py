"""
Tests for FileParser.

Tests BrainSense JSON file parsing, record classification, and data extraction.
Verifies proper handling of timeline and snapshot records.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import pytest
import json
import tempfile
from datetime import datetime
from pathlib import Path

from src.core.file_parser import FileParser, RecordType, ParsedFileData
from src.core.models.timeline_record import TimelineRecord
from src.core.models.snapshot_record import SnapshotRecord


class TestFileParser:
    """Test suite for FileParser."""

    # ========================================================================
    # Record Classification Tests
    # ========================================================================

    def test_classify_timeline_record_explicit_type(self):
        """Should classify timeline record with explicit RecordingType."""
        record = {
            "RecordingType": "BrainSenseTimeDomain",
            "timestamp": "2024-01-01T12:00:00",
            "left_hemisphere": 100.5,
        }

        record_type = FileParser.classify_record(record)
        assert record_type == RecordType.TIMELINE

    def test_classify_snapshot_record_explicit_type(self):
        """Should classify snapshot record with explicit RecordingType."""
        record = {
            "RecordingType": "BrainSenseLfp",
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": [1.0, 2.0, 3.0],
        }

        record_type = FileParser.classify_record(record)
        assert record_type == RecordType.SNAPSHOT

    def test_classify_timeline_record_heuristic(self):
        """Should classify timeline record using heuristic (no explicit type)."""
        record = {
            "timestamp": "2024-01-01T12:00:00",
            "left_hemisphere": 100.5,
            "right_hemisphere": 95.3,
            "therapy": "ON",
        }

        record_type = FileParser.classify_record(record)
        assert record_type == RecordType.TIMELINE

    def test_classify_snapshot_record_heuristic(self):
        """Should classify snapshot record using heuristic (no explicit type)."""
        record = {
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": [1.0, 2.0, 3.0],
            "power_data": [10.0, 20.0, 30.0],
            "event": "PatientTriggered",
        }

        record_type = FileParser.classify_record(record)
        assert record_type == RecordType.SNAPSHOT

    def test_classify_unknown_record(self):
        """Should classify unknown records as UNKNOWN."""
        record = {
            "some_field": "some_value",
            "another_field": 123,
        }

        record_type = FileParser.classify_record(record)
        assert record_type == RecordType.UNKNOWN

    # ========================================================================
    # Timeline Extraction Tests
    # ========================================================================

    def test_extract_timeline_record_basic(self):
        """Should extract basic timeline record."""
        record_data = {
            "timestamp": "2024-01-01T12:00:00",
            "left_hemisphere": 100.5,
            "right_hemisphere": 95.3,
            "therapy_status": "ON",
        }

        record = FileParser.extract_timeline_record(record_data, source_file="test.json")

        assert isinstance(record, TimelineRecord)
        assert record.timestamp == datetime(2024, 1, 1, 12, 0, 0)
        assert record.left_hemisphere == 100.5
        assert record.right_hemisphere == 95.3
        assert record.therapy_status == "ON"
        assert record.source_file == "test.json"
        assert len(record.data_hash) == 64  # SHA256 hex

    def test_extract_timeline_record_with_therapy_settings(self):
        """Should extract timeline record with therapy settings."""
        record_data = {
            "timestamp": "2024-01-01T12:00:00",
            "left_hemisphere": 100.5,
            "right_hemisphere": 95.3,
            "left_amplitude": 2.5,
            "right_amplitude": 2.0,
            "left_frequency": 130.0,
            "right_frequency": 130.0,
            "left_pulse_width": 60.0,
            "right_pulse_width": 60.0,
        }

        record = FileParser.extract_timeline_record(record_data)

        assert record.left_amplitude == 2.5
        assert record.right_amplitude == 2.0
        assert record.left_frequency == 130.0
        assert record.right_frequency == 130.0
        assert record.left_pulse_width == 60.0
        assert record.right_pulse_width == 60.0

    def test_extract_timeline_record_case_insensitive_keys(self):
        """Should extract timeline record with different key casings."""
        record_data = {
            "Timestamp": "2024-01-01T12:00:00",
            "LeftHemisphere": 100.5,
            "RightHemisphere": 95.3,
            "TherapyStatus": "ON",
        }

        record = FileParser.extract_timeline_record(record_data)

        assert record.left_hemisphere == 100.5
        assert record.right_hemisphere == 95.3
        assert record.therapy_status == "ON"

    def test_extract_timeline_record_missing_timestamp_raises(self):
        """Should raise ValueError when timestamp is missing."""
        record_data = {
            "left_hemisphere": 100.5,
            "right_hemisphere": 95.3,
        }

        with pytest.raises(ValueError, match="No valid timestamp"):
            FileParser.extract_timeline_record(record_data)

    # ========================================================================
    # Snapshot Extraction Tests
    # ========================================================================

    def test_extract_snapshot_record_basic(self):
        """Should extract basic snapshot record."""
        record_data = {
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": [1.0, 2.0, 3.0],
            "power_data": [10.0, 20.0, 30.0],
            "hemisphere": "LEFT",
        }

        record = FileParser.extract_snapshot_record(record_data, source_file="test.json")

        assert isinstance(record, SnapshotRecord)
        assert record.timestamp == datetime(2024, 1, 1, 12, 0, 0)
        assert record.frequency_data == '[1.0, 2.0, 3.0]'
        assert record.power_data == '[10.0, 20.0, 30.0]'
        assert record.hemisphere == "LEFT"
        assert record.source_file == "test.json"
        assert len(record.data_hash) == 64  # SHA256 hex

    def test_extract_snapshot_record_with_event_info(self):
        """Should extract snapshot record with event information."""
        record_data = {
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": [1.0, 2.0, 3.0],
            "power_data": [10.0, 20.0, 30.0],
            "event_type": "PatientTriggered",
            "event_subtype": "Manual",
            "event_name": "Test Event",
        }

        record = FileParser.extract_snapshot_record(record_data)

        assert record.event_type == "PatientTriggered"
        assert record.event_subtype == "Manual"
        assert record.event_name == "Test Event"

    def test_extract_snapshot_record_with_json_string_data(self):
        """Should handle frequency/power data as JSON strings."""
        record_data = {
            "timestamp": "2024-01-01T12:00:00",
            "frequency_data": "[1.0, 2.0, 3.0]",  # Already JSON string
            "power_data": "[10.0, 20.0, 30.0]",  # Already JSON string
        }

        record = FileParser.extract_snapshot_record(record_data)

        assert record.frequency_data == '[1.0, 2.0, 3.0]'
        assert record.power_data == '[10.0, 20.0, 30.0]'

    def test_extract_snapshot_record_missing_timestamp_raises(self):
        """Should raise ValueError when timestamp is missing."""
        record_data = {
            "frequency_data": [1.0, 2.0, 3.0],
            "power_data": [10.0, 20.0, 30.0],
        }

        with pytest.raises(ValueError, match="No valid timestamp"):
            FileParser.extract_snapshot_record(record_data)

    # ========================================================================
    # JSON File Parsing Tests
    # ========================================================================

    def test_parse_json_file_with_timeline_records(self):
        """Should parse JSON file containing timeline records."""
        # Create temp JSON file with timeline data
        data = [
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:00",
                "left_hemisphere": 100.5,
                "right_hemisphere": 95.3,
            },
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:01",
                "left_hemisphere": 101.0,
                "right_hemisphere": 96.0,
            },
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            parsed = FileParser.parse_json(temp_path, patient_id="PATIENT001")

            assert isinstance(parsed, ParsedFileData)
            assert len(parsed.timeline_records) == 2
            assert len(parsed.snapshot_records) == 0
            assert parsed.total_records == 2
            assert parsed.skipped_records == 0
            assert parsed.parse_errors == 0
            assert len(parsed.file_hash) == 64
            assert parsed.file_name == temp_path.name
        finally:
            temp_path.unlink()

    def test_parse_json_file_with_snapshot_records(self):
        """Should parse JSON file containing snapshot records."""
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

        try:
            parsed = FileParser.parse_json(temp_path)

            assert len(parsed.timeline_records) == 0
            assert len(parsed.snapshot_records) == 2
            assert parsed.total_records == 2
        finally:
            temp_path.unlink()

    def test_parse_json_file_with_mixed_records(self):
        """Should parse JSON file with mixed timeline and snapshot records."""
        data = [
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:00",
                "left_hemisphere": 100.5,
            },
            {
                "RecordingType": "BrainSenseLfp",
                "timestamp": "2024-01-01T12:00:00",
                "frequency_data": [1.0, 2.0, 3.0],
                "power_data": [10.0, 20.0, 30.0],
            },
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            parsed = FileParser.parse_json(temp_path)

            assert len(parsed.timeline_records) == 1
            assert len(parsed.snapshot_records) == 1
            assert parsed.total_records == 2
        finally:
            temp_path.unlink()

    def test_parse_json_file_with_nested_structure(self):
        """Should parse JSON file with nested record structure."""
        data = {
            "BrainSenseTimeDomain": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "left_hemisphere": 100.5,
                },
            ],
            "BrainSenseLfp": [
                {
                    "timestamp": "2024-01-01T12:00:00",
                    "frequency_data": [1.0, 2.0, 3.0],
                    "power_data": [10.0, 20.0, 30.0],
                },
            ],
        }

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            parsed = FileParser.parse_json(temp_path)

            assert len(parsed.timeline_records) == 1
            assert len(parsed.snapshot_records) == 1
            assert parsed.total_records == 2
        finally:
            temp_path.unlink()

    def test_parse_json_file_skips_unknown_records(self):
        """Should skip unknown record types."""
        data = [
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:00",
                "left_hemisphere": 100.5,
            },
            {
                "RecordingType": "UnknownType",
                "some_field": "some_value",
            },
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            parsed = FileParser.parse_json(temp_path)

            assert len(parsed.timeline_records) == 1
            assert parsed.skipped_records == 1
            assert parsed.total_records == 2
        finally:
            temp_path.unlink()

    def test_parse_json_file_missing_file_raises(self):
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            FileParser.parse_json(Path("/nonexistent/file.json"))

    def test_parse_json_file_invalid_json_raises(self):
        """Should raise JSONDecodeError for invalid JSON."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            f.write("{ invalid json }")
            temp_path = Path(f.name)

        try:
            with pytest.raises(json.JSONDecodeError):
                FileParser.parse_json(temp_path)
        finally:
            temp_path.unlink()

    def test_parse_json_handles_parse_errors_gracefully(self):
        """Should handle parse errors gracefully and continue parsing."""
        data = [
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:00",
                "left_hemisphere": 100.5,
            },
            {
                "RecordingType": "BrainSenseTimeDomain",
                # Missing timestamp - will cause parse error
                "left_hemisphere": 101.0,
            },
            {
                "RecordingType": "BrainSenseTimeDomain",
                "timestamp": "2024-01-01T12:00:02",
                "left_hemisphere": 102.0,
            },
        ]

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            parsed = FileParser.parse_json(temp_path)

            # Should have 2 successful records and 1 error
            assert len(parsed.timeline_records) == 2
            assert parsed.parse_errors == 1
            assert parsed.total_records == 3
        finally:
            temp_path.unlink()

    # ========================================================================
    # Timestamp Extraction Tests
    # ========================================================================

    def test_extract_timestamp_iso_format(self):
        """Should extract ISO format timestamp."""
        record = {"timestamp": "2024-01-01T12:00:00"}
        ts = FileParser._extract_timestamp(record)
        assert ts == datetime(2024, 1, 1, 12, 0, 0)

    def test_extract_timestamp_unix_timestamp(self):
        """Should extract Unix timestamp."""
        record = {"timestamp": 1704110400}  # 2024-01-01 12:00:00 UTC
        ts = FileParser._extract_timestamp(record)
        assert isinstance(ts, datetime)

    def test_extract_timestamp_various_keys(self):
        """Should try multiple key variations."""
        for key in ['timestamp', 'Timestamp', 'DateTime', 'time']:
            record = {key: "2024-01-01T12:00:00"}
            ts = FileParser._extract_timestamp(record)
            assert ts == datetime(2024, 1, 1, 12, 0, 0)
