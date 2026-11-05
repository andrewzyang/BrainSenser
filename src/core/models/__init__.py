"""
Data models module for iEEG BrainSense application.

This module provides dataclass models representing core domain entities:
- Patient: Patient information from patient_registry table
- UploadedFile: File upload tracking from processing_metadata table
- PatientStatistics: Aggregated statistics calculated across multiple tables
- TimelineRecord: BrainSense time-domain recording (LFP + therapy)
- SnapshotRecord: BrainSense frequency-domain snapshot (power spectral density)

Core models (Patient, UploadedFile, PatientStatistics) are immutable (frozen=True)
for data integrity. Record models (TimelineRecord, SnapshotRecord) are mutable
for use with repositories and file parsing.

Example:
    >>> from src.core.models import Patient, TimelineRecord, SnapshotRecord
    >>> from pathlib import Path
    >>> from datetime import datetime
    >>>
    >>> patient = Patient(
    ...     patient_id="PATIENT001",
    ...     patient_name="John Doe",
    ...     data_directory=Path("/data/patients/PATIENT001"),
    ...     database_path=Path("/data/patients/PATIENT001/brainsense_data.db"),
    ...     created_at=datetime.now(),
    ...     updated_at=datetime.now()
    ... )

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

from .patient import Patient
from .uploaded_file import UploadedFile
from .statistics import PatientStatistics
from .timeline_record import TimelineRecord
from .snapshot_record import SnapshotRecord
from .streaming_record import StreamingRecord
from .streaming_recording import StreamingRecording
from .annotation import Annotation
from .recording_group import RecordingGroup
from .upload_result import UploadResult
from .splash_config import SplashConfig

__all__ = [
    'Patient',
    'UploadedFile',
    'PatientStatistics',
    'TimelineRecord',
    'SnapshotRecord',
    'StreamingRecord',
    'StreamingRecording',
    'Annotation',
    'RecordingGroup',
    'UploadResult',
    'SplashConfig',
]
