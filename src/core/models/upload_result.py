"""
UploadResult data model for file upload operations.

This module defines the UploadResult dataclass representing the result of
a file upload operation, including statistics and status information.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from dataclasses import dataclass, field
from typing import Dict, List
from pathlib import Path


@dataclass
class UploadResult:
    """
    Result of a file upload operation.

    Contains status, statistics, and timing information about a file upload.
    Returned by UploadService.upload_file() to inform the caller about:
    - Whether the upload succeeded
    - How many records were inserted vs duplicates
    - File hash for future duplicate detection
    - Processing time for performance monitoring

    Attributes:
        success: Whether the upload succeeded (True) or failed (False)
        message: Human-readable status message
        timeline_inserted: Number of timeline records inserted (new)
        timeline_duplicates: Number of timeline records skipped (duplicates)
        snapshot_inserted: Number of snapshot records inserted (new)
        snapshot_duplicates: Number of snapshot records skipped (duplicates)
        total_duplicates: Total number of duplicate records across all types
        file_hash: SHA256 hash of uploaded file
        processing_time: Time taken to process file (seconds)

    Example:
        >>> result = UploadResult(
        ...     success=True,
        ...     message="File uploaded successfully",
        ...     timeline_inserted=100,
        ...     timeline_duplicates=5,
        ...     snapshot_inserted=20,
        ...     snapshot_duplicates=2,
        ...     total_duplicates=7,
        ...     file_hash="abc123...",
        ...     processing_time=1.5
        ... )
        >>> print(f"Inserted {result.timeline_inserted} timeline records")
        Inserted 100 timeline records
    """

    success: bool
    message: str
    timeline_inserted: int = 0
    timeline_duplicates: int = 0
    snapshot_inserted: int = 0
    snapshot_duplicates: int = 0
    indefinite_streaming_inserted: int = 0
    indefinite_streaming_duplicates: int = 0
    definite_streaming_inserted: int = 0
    definite_streaming_duplicates: int = 0
    total_duplicates: int = 0
    file_hash: str = ""
    processing_time: float = 0.0
    # True when the upload was skipped because this exact file (by hash) was
    # already uploaded. This is NOT a failure - callers should treat it as a
    # benign "skipped duplicate", distinct from success=False parse/IO errors.
    is_duplicate: bool = False

    @property
    def total_inserted(self) -> int:
        """Total number of records inserted (timeline + snapshot + streaming)."""
        return (self.timeline_inserted + self.snapshot_inserted +
                self.indefinite_streaming_inserted + self.definite_streaming_inserted)

    @property
    def total_processed(self) -> int:
        """Total number of records processed (inserted + duplicates)."""
        return self.total_inserted + self.total_duplicates

    @property
    def duplicate_rate(self) -> float:
        """Percentage of records that were duplicates (0.0-1.0)."""
        if self.total_processed == 0:
            return 0.0
        return self.total_duplicates / self.total_processed

    def to_dict(self) -> dict:
        """
        Convert UploadResult to dictionary.

        Returns:
            dict: Dictionary representation of UploadResult

        Example:
            >>> result = UploadResult(success=True, message="Done")
            >>> data = result.to_dict()
            >>> data['success']
            True
        """
        return {
            'success': self.success,
            'message': self.message,
            'timeline_inserted': self.timeline_inserted,
            'timeline_duplicates': self.timeline_duplicates,
            'snapshot_inserted': self.snapshot_inserted,
            'snapshot_duplicates': self.snapshot_duplicates,
            'total_duplicates': self.total_duplicates,
            'file_hash': self.file_hash,
            'processing_time': self.processing_time,
            'is_duplicate': self.is_duplicate,
            'total_inserted': self.total_inserted,
            'total_processed': self.total_processed,
            'duplicate_rate': self.duplicate_rate,
        }


@dataclass
class DirectoryUploadResult:
    """
    Aggregated result from uploading a directory of files.

    Provides comprehensive statistics for batch upload operations,
    including per-file results and aggregated data counts across all files.

    Attributes:
        total_files: Total number of JSON files found
        successful_uploads: Number of successfully uploaded files
        failed_uploads: Number of failed uploads
        skipped_duplicates: Number of files skipped as duplicates
        file_results: Dictionary mapping file paths to their UploadResult
        total_timeline_inserted: Sum of timeline records inserted across all files
        total_timeline_duplicates: Sum of timeline duplicates across all files
        total_snapshot_inserted: Sum of snapshot records inserted across all files
        total_snapshot_duplicates: Sum of snapshot duplicates across all files
        total_indefinite_streaming_inserted: Sum of indefinite streaming records
        total_indefinite_streaming_duplicates: Sum of indefinite streaming duplicates
        total_definite_streaming_inserted: Sum of definite streaming records
        total_definite_streaming_duplicates: Sum of definite streaming duplicates
        errors: List of (file_path, error_message) tuples for failed uploads

    Example:
        >>> result = DirectoryUploadResult(
        ...     total_files=10,
        ...     successful_uploads=9,
        ...     failed_uploads=1,
        ...     skipped_duplicates=0,
        ...     file_results={},
        ...     total_timeline_inserted=500,
        ...     total_timeline_duplicates=50
        ... )
        >>> print(f"Success rate: {result.success_rate:.1f}%")
        Success rate: 90.0%
    """
    # File-level statistics
    total_files: int
    successful_uploads: int
    failed_uploads: int
    skipped_duplicates: int

    # Detailed per-file results
    file_results: Dict[Path, 'UploadResult']

    # Aggregated data statistics (across all files)
    total_timeline_inserted: int = 0
    total_timeline_duplicates: int = 0
    total_snapshot_inserted: int = 0
    total_snapshot_duplicates: int = 0
    total_indefinite_streaming_inserted: int = 0
    total_indefinite_streaming_duplicates: int = 0
    total_definite_streaming_inserted: int = 0
    total_definite_streaming_duplicates: int = 0

    # Error tracking
    errors: List[tuple[Path, str]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage (0-100)."""
        if self.total_files == 0:
            return 0.0
        return (self.successful_uploads / self.total_files) * 100

    @property
    def has_errors(self) -> bool:
        """Check if any uploads failed."""
        return self.failed_uploads > 0

    @property
    def total_records_inserted(self) -> int:
        """Total records inserted across all data types."""
        return (
            self.total_timeline_inserted +
            self.total_snapshot_inserted +
            self.total_indefinite_streaming_inserted +
            self.total_definite_streaming_inserted
        )

    @property
    def total_duplicates(self) -> int:
        """Total duplicate records skipped across all data types."""
        return (
            self.total_timeline_duplicates +
            self.total_snapshot_duplicates +
            self.total_indefinite_streaming_duplicates +
            self.total_definite_streaming_duplicates
        )
