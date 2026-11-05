"""
StreamingRecording data model for complete BrainSense streaming recording files.

This module defines the StreamingRecording dataclass representing complete
streaming recording files (original or trimmed) for streaming data management.
This is different from StreamingRecord which represents individual waveform segments.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import json


@dataclass
class StreamingRecording:
    """
    Represents a complete streaming recording file (original or trimmed).

    This model tracks complete recording files for streaming data management including
    trimming, annotation, and analysis. It maintains relationships between original
    and trimmed recordings, and stores metadata about processing applied.

    Attributes:
        id: Unique identifier for the recording
        patient_id: Patient identifier (foreign key to patients table)
        file_path: Absolute path to the recording file
        original_file_path: Path to original file if this is a trimmed recording
        recording_date: Date/time when recording was made
        duration_seconds: Total duration of recording in seconds
        start_time: Start time within original recording (for trimmed recordings)
        end_time: End time within original recording (for trimmed recordings)
        is_trimmed: Whether this recording is trimmed from another
        file_size_bytes: Size of file on disk
        sampling_rate: Sample rate in Hz (e.g., 250.0)
        channel_count: Number of channels in recording
        channel_labels: List of channel labels (e.g., ["Ch0_Left_STN", ...])
        metadata: Additional flexible metadata (time_of_day, medication_state, display_name, etc.)
            Special keys:
                - display_name: User-provided annotation/name for easy identification
                - trim_start_sec/trim_end_sec: Trim range for trimmed recordings
        processing_applied: List of processing steps applied (e.g., ['highpass_0.5Hz'])
        created_at: When this database record was created
        updated_at: When this database record was last updated

    Example:
        >>> recording = StreamingRecording(
        ...     id="rec_001",
        ...     patient_id="P01",
        ...     file_path="/data/P01/2024-03-15_streaming.json",
        ...     recording_date=datetime(2024, 3, 15, 9, 30),
        ...     duration_seconds=2732.5,
        ...     is_trimmed=False,
        ...     file_size_bytes=128400000,
        ...     sampling_rate=250.0,
        ...     channel_count=4,
        ...     channel_labels=["Ch0_Left_STN", "Ch1_Left_STN", "Ch2_Right_STN", "Ch3_Right_STN"],
        ...     metadata={"time_of_day": "morning", "medication_state": "pre_med"},
        ...     processing_applied=[],
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now()
        ... )
    """

    # Identifiers
    id: str
    patient_id: str

    # File information
    file_path: str
    original_file_path: Optional[str] = None

    # Recording timing
    recording_date: datetime = field(default_factory=datetime.now)
    duration_seconds: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Recording type
    is_trimmed: bool = False

    # File metadata
    file_size_bytes: int = 0
    sampling_rate: float = 250.0
    channel_count: int = 0
    channel_labels: List[str] = field(default_factory=list)

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_applied: List[str] = field(default_factory=list)

    # File integrity validation
    file_checksum: Optional[str] = None  # SHA-256 hash of file contents

    # Database timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def is_original(self) -> bool:
        """Whether this is an original (non-trimmed) recording."""
        return not self.is_trimmed

    @property
    def has_processing(self) -> bool:
        """Whether any processing has been applied to this recording."""
        return len(self.processing_applied) > 0

    @property
    def duration_minutes(self) -> float:
        """Duration in minutes."""
        return self.duration_seconds / 60.0

    @property
    def file_size_mb(self) -> float:
        """File size in megabytes."""
        return self.file_size_bytes / (1024 * 1024)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database storage.

        Returns:
            Dictionary with all fields, converting complex types to JSON strings
        """
        return {
            'id': self.id,
            'patient_id': self.patient_id,
            'file_path': self.file_path,
            'original_file_path': self.original_file_path,
            'recording_date': self.recording_date.isoformat(),
            'duration_seconds': self.duration_seconds,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'is_trimmed': int(self.is_trimmed),
            'file_size_bytes': self.file_size_bytes,
            'sampling_rate': self.sampling_rate,
            'channel_count': self.channel_count,
            'channel_labels': json.dumps(self.channel_labels),
            'metadata': json.dumps(self.metadata),
            'processing_applied': json.dumps(self.processing_applied),
            'file_checksum': self.file_checksum,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StreamingRecording':
        """
        Create StreamingRecording from dictionary (database row).

        Args:
            data: Dictionary with database fields

        Returns:
            StreamingRecording instance
        """
        # Parse JSON fields
        channel_labels = json.loads(data['channel_labels']) if isinstance(data['channel_labels'], str) else data['channel_labels']
        metadata = json.loads(data['metadata']) if isinstance(data['metadata'], str) else data['metadata']
        processing_applied = json.loads(data['processing_applied']) if isinstance(data['processing_applied'], str) else data['processing_applied']

        # Parse datetime fields
        recording_date = datetime.fromisoformat(data['recording_date']) if isinstance(data['recording_date'], str) else data['recording_date']
        start_time = datetime.fromisoformat(data['start_time']) if data.get('start_time') and isinstance(data['start_time'], str) else data.get('start_time')
        end_time = datetime.fromisoformat(data['end_time']) if data.get('end_time') and isinstance(data['end_time'], str) else data.get('end_time')
        created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']
        updated_at = datetime.fromisoformat(data['updated_at']) if isinstance(data['updated_at'], str) else data['updated_at']

        return cls(
            id=data['id'],
            patient_id=data['patient_id'],
            file_path=data['file_path'],
            original_file_path=data.get('original_file_path'),
            recording_date=recording_date,
            duration_seconds=data['duration_seconds'],
            start_time=start_time,
            end_time=end_time,
            is_trimmed=bool(data['is_trimmed']),
            file_size_bytes=data['file_size_bytes'],
            sampling_rate=data['sampling_rate'],
            channel_count=data['channel_count'],
            channel_labels=channel_labels,
            metadata=metadata,
            processing_applied=processing_applied,
            file_checksum=data.get('file_checksum'),
            created_at=created_at,
            updated_at=updated_at
        )
