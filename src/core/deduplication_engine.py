"""
DeduplicationEngine for calculating data hashes for BrainSense records.

This module provides hash calculation for deduplication of timeline and snapshot
records. Hashes are calculated using SHA256 on relevant fields only (ignoring metadata).

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import hashlib
import json
from pathlib import Path
from typing import Union

from src.core.models.timeline_record import TimelineRecord
from src.core.models.snapshot_record import SnapshotRecord
from src.core.models.streaming_record import StreamingRecord


class DeduplicationEngine:
    """
    Calculate SHA256 hashes for deduplication of BrainSense records.

    This engine calculates consistent, deterministic hashes for timeline and
    snapshot records using only the relevant data fields (excluding metadata
    like source_file, inserted_at, etc.).

    Hash calculation uses:
    - Timeline: timestamp + LFP values + therapy settings
    - Snapshot: timestamp + frequency_data + power_data + event info
    - File: entire file contents

    All hashes are SHA256 in hexadecimal format.

    Example:
        >>> from datetime import datetime
        >>> from src.core.models.timeline_record import TimelineRecord
        >>>
        >>> record = TimelineRecord(
        ...     timestamp=datetime(2024, 1, 1, 12, 0, 0),
        ...     left_hemisphere=100.5,
        ...     right_hemisphere=95.3,
        ...     therapy_status="ON"
        ... )
        >>>
        >>> hash_value = DeduplicationEngine.calculate_timeline_hash(record)
        >>> print(f"Hash: {hash_value}")
    """

    @staticmethod
    def calculate_timeline_hash(record: TimelineRecord) -> str:
        """
        Calculate SHA256 hash for a timeline record.

        Uses only the relevant data fields for hash calculation:
        - timestamp (ISO format)
        - unix_timestamp
        - left_hemisphere
        - right_hemisphere
        - left_amplitude
        - right_amplitude
        - left_frequency
        - right_frequency
        - left_pulse_width
        - right_pulse_width
        - therapy_status

        Ignores metadata fields (source_file, session_id, etc.) and
        database fields (id, inserted_at, updated_at).

        Args:
            record: TimelineRecord instance

        Returns:
            str: SHA256 hash in hexadecimal format (64 characters)

        Example:
            >>> record = TimelineRecord(timestamp=datetime.now(), ...)
            >>> hash_val = DeduplicationEngine.calculate_timeline_hash(record)
            >>> len(hash_val)
            64
        """
        # Build dictionary with only relevant fields for deduplication
        hash_data = {
            'timestamp': record.timestamp.isoformat() if record.timestamp else None,
            'unix_timestamp': record.unix_timestamp,
            'left_hemisphere': record.left_hemisphere,
            'right_hemisphere': record.right_hemisphere,
            'left_amplitude': record.left_amplitude,
            'right_amplitude': record.right_amplitude,
            'left_frequency': record.left_frequency,
            'right_frequency': record.right_frequency,
            'left_pulse_width': record.left_pulse_width,
            'right_pulse_width': record.right_pulse_width,
            'therapy_status': record.therapy_status,
        }

        # Convert to JSON string with sorted keys for consistency
        hash_string = json.dumps(hash_data, sort_keys=True)

        # Calculate SHA256
        return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_snapshot_hash(record: SnapshotRecord) -> str:
        """
        Calculate SHA256 hash for a snapshot record.

        Uses only the relevant data fields for hash calculation:
        - timestamp (ISO format)
        - unix_timestamp
        - event_type
        - event_subtype
        - event_name
        - frequency_data (JSON array)
        - power_data (JSON array)
        - hemisphere

        Ignores metadata fields (source_file, session_id, etc.) and
        database fields (id, inserted_at, updated_at).

        Args:
            record: SnapshotRecord instance

        Returns:
            str: SHA256 hash in hexadecimal format (64 characters)

        Example:
            >>> record = SnapshotRecord(
            ...     timestamp=datetime.now(),
            ...     frequency_data='[1.0, 2.0, 3.0]',
            ...     power_data='[10.0, 20.0, 30.0]'
            ... )
            >>> hash_val = DeduplicationEngine.calculate_snapshot_hash(record)
            >>> len(hash_val)
            64
        """
        # Build dictionary with only relevant fields for deduplication
        hash_data = {
            'timestamp': record.timestamp.isoformat() if record.timestamp else None,
            'unix_timestamp': record.unix_timestamp,
            'event_type': record.event_type,
            'event_subtype': record.event_subtype,
            'event_name': record.event_name,
            'frequency_data': record.frequency_data,
            'power_data': record.power_data,
            'hemisphere': record.hemisphere,
        }

        # Convert to JSON string with sorted keys for consistency
        hash_string = json.dumps(hash_data, sort_keys=True)

        # Calculate SHA256
        return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_streaming_hash(record: StreamingRecord) -> str:
        """
        Calculate SHA256 hash for a streaming record.

        Uses only the relevant data fields for hash calculation:
        - timestamp (ISO format)
        - unix_timestamp
        - channel
        - waveform_data (entire waveform array)
        - sample_rate
        - streaming_type

        Ignores metadata fields (source_file, session_id, etc.) and
        database fields (id, inserted_at, updated_at).

        Args:
            record: StreamingRecord instance

        Returns:
            str: SHA256 hash in hexadecimal format (64 characters)

        Example:
            >>> record = StreamingRecord(
            ...     timestamp=datetime.now(),
            ...     channel="ZERO_THREE_LEFT",
            ...     waveform_data='[20.4, 20.1, 20.0]',
            ...     sample_rate=250,
            ...     streaming_type="indefinite"
            ... )
            >>> hash_val = DeduplicationEngine.calculate_streaming_hash(record)
            >>> len(hash_val)
            64
        """
        # Build dictionary with only relevant fields for deduplication
        hash_data = {
            'timestamp': record.timestamp.isoformat() if record.timestamp else None,
            'unix_timestamp': record.unix_timestamp,
            'channel': record.channel,
            'waveform_data': record.waveform_data,  # Full waveform!
            'sample_rate': record.sample_rate,
            'streaming_type': record.streaming_type,
        }

        # Convert to JSON string with sorted keys for consistency
        hash_string = json.dumps(hash_data, sort_keys=True)

        # Calculate SHA256
        return hashlib.sha256(hash_string.encode('utf-8')).hexdigest()

    @staticmethod
    def calculate_file_hash(file_path: Union[str, Path]) -> str:
        """
        Calculate SHA256 hash of entire file.

        Reads file in binary mode and calculates SHA256 hash of contents.
        Used to detect duplicate file uploads.

        Args:
            file_path: Path to file (string or Path object)

        Returns:
            str: SHA256 hash in hexadecimal format (64 characters)

        Raises:
            FileNotFoundError: If file does not exist
            PermissionError: If file cannot be read

        Example:
            >>> hash_val = DeduplicationEngine.calculate_file_hash('data.json')
            >>> len(hash_val)
            64
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Read file in chunks for memory efficiency
        sha256_hash = hashlib.sha256()
        with open(path, 'rb') as f:
            # Read in 64KB chunks
            for chunk in iter(lambda: f.read(65536), b''):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()
