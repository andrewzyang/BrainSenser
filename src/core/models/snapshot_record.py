"""
SnapshotRecord data model for BrainSense frequency snapshots.

This module defines the SnapshotRecord dataclass representing a single
frequency-domain snapshot from BrainSense JSON files. Used by SnapshotRepository
for batch insertion with deduplication.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class SnapshotRecord:
    """
    BrainSense frequency-domain snapshot (power spectral density).

    Represents a single frequency snapshot with:
    - Timestamp information
    - Event information (type, subtype, name)
    - Frequency and power data (stored as JSON)
    - Hemisphere information
    - Metadata (source file, session info)
    - Patient event flags
    - Therapy state at snapshot time
    - Data hash for deduplication

    The data_hash field is calculated by DeduplicationEngine using:
        SHA256(timestamp + frequency_data + power_data + event info)

    Attributes:
        timestamp: ISO format timestamp (TEXT in STRICT mode)
        unix_timestamp: Unix epoch timestamp (REAL)
        event_type: Event type (TEXT)
        event_subtype: Event subtype (TEXT)
        event_name: Event name (TEXT)
        frequency_data: JSON array of frequency bins (TEXT)
        power_data: JSON array of power values (TEXT)
        fft_output: JSON with FFT results (TEXT)
        hemisphere: LEFT, RIGHT, or BOTH (TEXT)
        source_file: Which uploaded file this came from (TEXT)
        session_id: Session identifier (TEXT)
        duration_seconds: Snapshot duration (REAL, default 30.0)
        sampling_rate: Sampling rate (REAL)
        patient_event: Patient event flag (INTEGER: 0 or 1)
        patient_event_id: Patient event identifier (TEXT)
        event_notes: Event notes (TEXT)
        therapy_amplitude_left: Therapy amplitude left at snapshot time (REAL)
        therapy_amplitude_right: Therapy amplitude right at snapshot time (REAL)
        therapy_frequency: Therapy frequency at snapshot time (REAL)
        data_hash: SHA256 hash for deduplication (TEXT, UNIQUE)

    Example:
        >>> import json
        >>> from datetime import datetime
        >>> record = SnapshotRecord(
        ...     timestamp=datetime.now(),
        ...     frequency_data=json.dumps([1.0, 2.0, 3.0]),
        ...     power_data=json.dumps([10.0, 20.0, 30.0]),
        ...     hemisphere="LEFT",
        ...     source_file="session_2024.json",
        ...     data_hash="def456..."
        ... )
    """

    # Timing (required)
    timestamp: datetime
    unix_timestamp: Optional[float] = None

    # Event Information (all optional)
    event_type: Optional[str] = None
    event_subtype: Optional[str] = None
    event_name: Optional[str] = None

    # Frequency Data (required - stored as JSON TEXT)
    frequency_data: str = ""  # JSON array
    power_data: str = ""  # JSON array
    fft_output: Optional[str] = None  # JSON object

    # Hemisphere (optional)
    hemisphere: Optional[str] = None

    # Metadata (required)
    source_file: str = ""
    session_id: Optional[str] = None
    duration_seconds: float = 30.0
    sampling_rate: Optional[float] = None

    # Patient Events
    patient_event: int = 0  # INTEGER in STRICT mode (0 or 1)
    patient_event_id: Optional[str] = None
    event_notes: Optional[str] = None

    # Therapy State at Snapshot Time (all optional)
    therapy_amplitude_left: Optional[float] = None
    therapy_amplitude_right: Optional[float] = None
    therapy_frequency: Optional[float] = None

    # Deduplication (required)
    data_hash: str = ""

    # Database fields (set by database, not by user)
    id: Optional[int] = None
    inserted_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Convert SnapshotRecord to dictionary for database insertion.

        Returns:
            dict: Dictionary with all fields ready for SQLite insertion

        Example:
            >>> record = SnapshotRecord(...)
            >>> data = record.to_dict()
            >>> # Use with SnapshotRepository.insert_batch()
        """
        return {
            'timestamp': self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            'unix_timestamp': self.unix_timestamp,
            'event_type': self.event_type,
            'event_subtype': self.event_subtype,
            'event_name': self.event_name,
            'frequency_data': self.frequency_data,
            'power_data': self.power_data,
            'fft_output': self.fft_output,
            'hemisphere': self.hemisphere,
            'source_file': self.source_file,
            'session_id': self.session_id,
            'duration_seconds': self.duration_seconds,
            'sampling_rate': self.sampling_rate,
            'patient_event': self.patient_event,
            'patient_event_id': self.patient_event_id,
            'event_notes': self.event_notes,
            'therapy_amplitude_left': self.therapy_amplitude_left,
            'therapy_amplitude_right': self.therapy_amplitude_right,
            'therapy_frequency': self.therapy_frequency,
            'data_hash': self.data_hash,
        }

    @staticmethod
    def from_row(row: dict) -> 'SnapshotRecord':
        """
        Create SnapshotRecord from database row.

        Args:
            row: Dictionary from SQLite query result

        Returns:
            SnapshotRecord: Populated record instance

        Example:
            >>> row = cursor.fetchone()
            >>> record = SnapshotRecord.from_row(row)
        """
        return SnapshotRecord(
            id=row.get('id'),
            timestamp=datetime.fromisoformat(row['timestamp']) if row.get('timestamp') else datetime.now(),
            unix_timestamp=row.get('unix_timestamp'),
            event_type=row.get('event_type'),
            event_subtype=row.get('event_subtype'),
            event_name=row.get('event_name'),
            frequency_data=row.get('frequency_data', ''),
            power_data=row.get('power_data', ''),
            fft_output=row.get('fft_output'),
            hemisphere=row.get('hemisphere'),
            source_file=row.get('source_file', ''),
            session_id=row.get('session_id'),
            duration_seconds=row.get('duration_seconds', 30.0),
            sampling_rate=row.get('sampling_rate'),
            patient_event=row.get('patient_event', 0),
            patient_event_id=row.get('patient_event_id'),
            event_notes=row.get('event_notes'),
            therapy_amplitude_left=row.get('therapy_amplitude_left'),
            therapy_amplitude_right=row.get('therapy_amplitude_right'),
            therapy_frequency=row.get('therapy_frequency'),
            data_hash=row.get('data_hash', ''),
            inserted_at=row.get('inserted_at'),
            updated_at=row.get('updated_at'),
        )
