"""
UploadedFile model representing a processed file from processing_metadata table.

This module defines the UploadedFile dataclass that maps to the processing_metadata
table in per-patient databases. It tracks file upload information, processing results,
and deduplication statistics.

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class UploadedFile:
    """
    Immutable uploaded file model matching processing_metadata table.

    Maps to: {patient_db}/brainsense_data.db → processing_metadata

    This model represents a single file upload and its processing results.
    It tracks both original counts (before deduplication) and final counts
    (after deduplication) to provide statistics for the UI.

    Attributes:
        file_id: Unique file identifier (PRIMARY KEY)
        patient_id: Patient this file belongs to (FOREIGN KEY)
        file_name: Original filename
        file_path: Full path to stored file
        file_hash: SHA256 hash for duplicate detection
        file_size_bytes: File size in bytes

        timeline_count: Records inserted into timeline_data (after dedup)
        timeline_original_count: Original timeline records (before dedup)
        snapshot_count: Records inserted into snapshot_data (after dedup)
        snapshot_original_count: Original snapshot records (before dedup)
        duplicates_skipped: Total duplicates across all types
        outliers_detected: Number of outlier records detected
        indefinite_streaming_count: Records inserted into indefinite_streaming (after dedup)
        indefinite_streaming_original_count: Original indefinite streaming records (before dedup)
        definite_streaming_count: Records inserted into definite_streaming (after dedup)
        definite_streaming_original_count: Original definite streaming records (before dedup)

        processing_time_seconds: Time taken to process file
        extractor_version: Version of extractor used
        processing_settings: Optional JSON with processing settings

        errors_encountered: Number of errors during processing
        error_details: Optional error message details

        processed_at: Timestamp when file was processed

    Example:
        >>> from pathlib import Path
        >>> from datetime import datetime
        >>>
        >>> uploaded_file = UploadedFile(
        ...     file_id=1,
        ...     patient_id="PATIENT001",
        ...     file_name="Report_2025-01-15.json",
        ...     file_path=Path("/data/patients/PATIENT001/uploads/Report_2025-01-15.json"),
        ...     file_hash="abc123...",
        ...     file_size_bytes=1048576,
        ...     timeline_count=1000,
        ...     timeline_original_count=1200,
        ...     snapshot_count=50,
        ...     snapshot_original_count=60,
        ...     duplicates_skipped=210,
        ...     outliers_detected=5,
        ...     processing_time_seconds=2.5,
        ...     extractor_version="1.0.0",
        ...     processing_settings=None,
        ...     errors_encountered=0,
        ...     error_details=None,
        ...     processed_at=datetime.now()
        ... )
        >>> print(uploaded_file.file_size_mb)
        1.0
        >>> print(uploaded_file.has_timeline)
        True
        >>> print(uploaded_file.data_type_tags)
        ['Snapshots', 'Timeline']
    """
    # File information
    file_id: int
    patient_id: str
    file_name: str
    file_path: Path
    file_hash: str
    file_size_bytes: int

    # Processing results (deduplicated counts)
    timeline_count: int
    timeline_original_count: int
    snapshot_count: int
    snapshot_original_count: int
    duplicates_skipped: int
    outliers_detected: int

    # Processing metadata
    processing_time_seconds: float
    extractor_version: str
    processing_settings: Optional[Dict[str, Any]]

    # Error tracking
    errors_encountered: int
    error_details: Optional[str]

    # Timestamp
    processed_at: datetime

    # Optional streaming counts (default to 0 for backward compatibility)
    indefinite_streaming_count: int = 0
    indefinite_streaming_original_count: int = 0
    definite_streaming_count: int = 0
    definite_streaming_original_count: int = 0

    @property
    def file_size_mb(self) -> float:
        """
        File size in megabytes.

        Converts file_size_bytes to MB for UI display.

        Returns:
            float: File size in MB (rounded to 2 decimal places implicitly)
        """
        return self.file_size_bytes / (1024 * 1024)

    @property
    def has_timeline(self) -> bool:
        """
        Whether this file contains timeline data.

        Returns:
            bool: True if timeline_count > 0
        """
        return self.timeline_count > 0

    @property
    def has_snapshots(self) -> bool:
        """
        Whether this file contains snapshot data.

        Returns:
            bool: True if snapshot_count > 0
        """
        return self.snapshot_count > 0

    @property
    def has_indefinite_streaming(self) -> bool:
        """
        Whether this file contains indefinite streaming data.

        Returns:
            bool: True if indefinite_streaming_count > 0
        """
        return self.indefinite_streaming_count > 0

    @property
    def has_definite_streaming(self) -> bool:
        """
        Whether this file contains definite streaming data.

        Returns:
            bool: True if definite_streaming_count > 0
        """
        return self.definite_streaming_count > 0

    @property
    def data_type_tags(self) -> list[str]:
        """
        List of data types for UI display.

        Returns tags based on which data types are present in the file.
        Checks ORIGINAL counts (before deduplication) to show what data was in the file,
        even if all records were duplicates.

        Returns:
            list[str]: List containing "Snapshots", "Timeline", "Indefinite Streaming", "Definite Streaming" if present
        """
        tags = []
        if self.snapshot_original_count > 0:
            tags.append("Snapshots")
        if self.timeline_original_count > 0:
            tags.append("Timeline")
        if self.indefinite_streaming_original_count > 0:
            tags.append("Indefinite Streaming")
        if self.definite_streaming_original_count > 0:
            tags.append("Definite Streaming")
        return tags
