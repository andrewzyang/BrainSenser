"""
PatientStatistics model for aggregated patient statistics.

This module defines the PatientStatistics dataclass that represents
calculated statistics aggregated across all uploads for a single patient.

Unlike other models, this data is computed/calculated rather than stored
directly in a database table. It aggregates data from multiple sources:
- processing_metadata (file counts, upload dates)
- timeline_data (record counts)
- snapshot_data (record counts)

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PatientStatistics:
    """
    Immutable patient statistics model with calculated aggregations.

    Calculated from: Multiple tables (processing_metadata, timeline_data, snapshot_data)

    This model represents aggregated statistics for a single patient across
    all their uploaded files. It provides deduplication metrics showing how
    many duplicate records were removed during processing.

    Attributes:
        patient_id: Patient this statistics belongs to

        snapshots_original: Total snapshot records before deduplication
        snapshots_deduplicated: Total snapshot records after deduplication

        timeline_original: Total timeline records before deduplication
        timeline_deduplicated: Total timeline records after deduplication

        indefinite_streaming_original: Indefinite streaming records before dedup (future use)
        indefinite_streaming_deduplicated: Indefinite streaming records after dedup (future use)
        definite_streaming_original: Definite streaming records before dedup (future use)
        definite_streaming_deduplicated: Definite streaming records after dedup (future use)

        total_files_uploaded: Total number of files uploaded for this patient
        total_duplicates_skipped: Total duplicates skipped across all files
        last_upload_date: Date of most recent file upload (None if no uploads)
        last_calculated: Timestamp when these statistics were calculated

    Example:
        >>> from datetime import datetime
        >>>
        >>> stats = PatientStatistics(
        ...     patient_id="PATIENT001",
        ...     snapshots_original=1000,
        ...     snapshots_deduplicated=750,
        ...     timeline_original=5000,
        ...     timeline_deduplicated=4000,
        ...     indefinite_streaming_original=0,
        ...     indefinite_streaming_deduplicated=0,
        ...     definite_streaming_original=0,
        ...     definite_streaming_deduplicated=0,
        ...     total_files_uploaded=5,
        ...     total_duplicates_skipped=1250,
        ...     last_upload_date=datetime(2025, 1, 15, 10, 30, 0),
        ...     last_calculated=datetime.now()
        ... )
        >>> print(stats.snapshots_reduction_percent)
        25.0
        >>> print(stats.timeline_reduction_percent)
        20.0
    """
    # Patient reference
    patient_id: str

    # Snapshot statistics
    snapshots_original: int
    snapshots_deduplicated: int

    # Timeline statistics
    timeline_original: int
    timeline_deduplicated: int

    # Streaming statistics (future use)
    indefinite_streaming_original: int = 0
    indefinite_streaming_deduplicated: int = 0
    definite_streaming_original: int = 0
    definite_streaming_deduplicated: int = 0

    # Metadata
    total_files_uploaded: int = 0
    total_duplicates_skipped: int = 0
    last_upload_date: Optional[datetime] = None
    last_calculated: datetime = None  # Will be set when creating instance

    @property
    def snapshots_reduction_percent(self) -> float:
        """
        Percentage of snapshot records removed by deduplication.

        Calculates: (original - deduplicated) / original * 100

        Returns:
            float: Percentage reduction (0.0-100.0), or 0.0 if no original records
        """
        if self.snapshots_original == 0:
            return 0.0
        reduction = self.snapshots_original - self.snapshots_deduplicated
        return (reduction / self.snapshots_original) * 100

    @property
    def timeline_reduction_percent(self) -> float:
        """
        Percentage of timeline records removed by deduplication.

        Calculates: (original - deduplicated) / original * 100

        Returns:
            float: Percentage reduction (0.0-100.0), or 0.0 if no original records
        """
        if self.timeline_original == 0:
            return 0.0
        reduction = self.timeline_original - self.timeline_deduplicated
        return (reduction / self.timeline_original) * 100
