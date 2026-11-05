"""
TimelineRecord data model for BrainSense time-domain recordings.

This module defines the TimelineRecord dataclass representing a single
time-domain recording from BrainSense JSON files. Used by TimelineRepository
for batch insertion with deduplication.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TimelineRecord:
    """
    BrainSense time-domain recording (LFP + therapy settings).

    Represents a single time-domain recording with:
    - Timestamp information
    - LFP measurements from left and right hemispheres
    - Therapy settings (amplitude, frequency, pulse width)
    - Quality control flags (outlier detection)
    - Metadata (source file, session info)
    - Data hash for deduplication

    The data_hash field is calculated by DeduplicationEngine using:
        SHA256(timestamp + LFP values + therapy settings)

    Attributes:
        timestamp: ISO format timestamp (TEXT in STRICT mode)
        unix_timestamp: Unix epoch timestamp (REAL)
        left_hemisphere: LFP microvolts left (REAL)
        right_hemisphere: LFP microvolts right (REAL)
        left_amplitude: Therapy amplitude left (REAL)
        right_amplitude: Therapy amplitude right (REAL)
        left_frequency: Therapy frequency left (REAL)
        right_frequency: Therapy frequency right (REAL)
        left_pulse_width: Therapy pulse width left (REAL)
        right_pulse_width: Therapy pulse width right (REAL)
        therapy_status: Status text (TEXT)
        is_outlier: Outlier flag (INTEGER: 0 or 1)
        outlier_reason: Reason if outlier (TEXT)
        outlier_score: Outlier score (REAL)
        preprocessing_applied: JSON preprocessing details (TEXT)
        preprocessing_timestamp: When preprocessing occurred (TEXT)
        original_left_hemisphere: Original LFP left before preprocessing (REAL)
        original_right_hemisphere: Original LFP right before preprocessing (REAL)
        source_file: Which uploaded file this came from (TEXT)
        session_id: Session identifier (TEXT)
        segment_id: Segment identifier (TEXT)
        segment_type: Segment type (TEXT)
        data_hash: SHA256 hash for deduplication (TEXT, UNIQUE)

    Example:
        >>> from datetime import datetime
        >>> record = TimelineRecord(
        ...     timestamp=datetime.now(),
        ...     unix_timestamp=1704067200.0,
        ...     left_hemisphere=100.5,
        ...     right_hemisphere=95.3,
        ...     therapy_status="ON",
        ...     source_file="session_2024.json",
        ...     data_hash="abc123..."
        ... )
    """

    # Timing (required)
    timestamp: datetime
    unix_timestamp: Optional[float] = None

    # LFP Data (optional - may be NULL)
    left_hemisphere: Optional[float] = None
    right_hemisphere: Optional[float] = None

    # Therapy Settings (all optional)
    left_amplitude: Optional[float] = None
    right_amplitude: Optional[float] = None
    left_frequency: Optional[float] = None
    right_frequency: Optional[float] = None
    left_pulse_width: Optional[float] = None
    right_pulse_width: Optional[float] = None
    therapy_status: Optional[str] = None

    # Quality Indicators (BRAVO approach)
    is_outlier: int = 0  # INTEGER in STRICT mode (0 or 1)
    outlier_reason: Optional[str] = None
    outlier_score: Optional[float] = None

    # Preprocessing Tracking
    preprocessing_applied: Optional[str] = None  # JSON string
    preprocessing_timestamp: Optional[str] = None  # TEXT timestamp
    original_left_hemisphere: Optional[float] = None
    original_right_hemisphere: Optional[float] = None

    # Metadata (required)
    source_file: str = ""
    session_id: Optional[str] = None
    segment_id: Optional[str] = None
    segment_type: Optional[str] = None

    # Deduplication (required)
    data_hash: str = ""

    # Database fields (set by database, not by user)
    id: Optional[int] = None
    inserted_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Convert TimelineRecord to dictionary for database insertion.

        Returns:
            dict: Dictionary with all fields ready for SQLite insertion

        Example:
            >>> record = TimelineRecord(...)
            >>> data = record.to_dict()
            >>> # Use with TimelineRepository.insert_batch()
        """
        return {
            'timestamp': self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            'unix_timestamp': self.unix_timestamp,
            'left_hemisphere': self.left_hemisphere,
            'right_hemisphere': self.right_hemisphere,
            'left_amplitude': self.left_amplitude,
            'right_amplitude': self.right_amplitude,
            'left_frequency': self.left_frequency,
            'right_frequency': self.right_frequency,
            'left_pulse_width': self.left_pulse_width,
            'right_pulse_width': self.right_pulse_width,
            'therapy_status': self.therapy_status,
            'is_outlier': self.is_outlier,
            'outlier_reason': self.outlier_reason,
            'outlier_score': self.outlier_score,
            'preprocessing_applied': self.preprocessing_applied,
            'preprocessing_timestamp': self.preprocessing_timestamp,
            'original_left_hemisphere': self.original_left_hemisphere,
            'original_right_hemisphere': self.original_right_hemisphere,
            'source_file': self.source_file,
            'session_id': self.session_id,
            'segment_id': self.segment_id,
            'segment_type': self.segment_type,
            'data_hash': self.data_hash,
        }

    @staticmethod
    def from_row(row: dict) -> 'TimelineRecord':
        """
        Create TimelineRecord from database row.

        Args:
            row: Dictionary from SQLite query result

        Returns:
            TimelineRecord: Populated record instance

        Example:
            >>> row = cursor.fetchone()
            >>> record = TimelineRecord.from_row(row)
        """
        return TimelineRecord(
            id=row.get('id'),
            timestamp=datetime.fromisoformat(row['timestamp']) if row.get('timestamp') else datetime.now(),
            unix_timestamp=row.get('unix_timestamp'),
            left_hemisphere=row.get('left_hemisphere'),
            right_hemisphere=row.get('right_hemisphere'),
            left_amplitude=row.get('left_amplitude'),
            right_amplitude=row.get('right_amplitude'),
            left_frequency=row.get('left_frequency'),
            right_frequency=row.get('right_frequency'),
            left_pulse_width=row.get('left_pulse_width'),
            right_pulse_width=row.get('right_pulse_width'),
            therapy_status=row.get('therapy_status'),
            is_outlier=row.get('is_outlier', 0),
            outlier_reason=row.get('outlier_reason'),
            outlier_score=row.get('outlier_score'),
            preprocessing_applied=row.get('preprocessing_applied'),
            preprocessing_timestamp=row.get('preprocessing_timestamp'),
            original_left_hemisphere=row.get('original_left_hemisphere'),
            original_right_hemisphere=row.get('original_right_hemisphere'),
            source_file=row.get('source_file', ''),
            session_id=row.get('session_id'),
            segment_id=row.get('segment_id'),
            segment_type=row.get('segment_type'),
            data_hash=row.get('data_hash', ''),
            inserted_at=row.get('inserted_at'),
            updated_at=row.get('updated_at'),
        )
