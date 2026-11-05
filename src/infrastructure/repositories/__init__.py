"""
Repository layer for database operations.

This module provides the Repository pattern implementation for database access.
All repositories extend BaseRepository and provide type-safe CRUD operations
for their respective domain models.

Available repositories:
- BaseRepository: Abstract base with common database operations
- PatientRepository: CRUD operations for Patient model
- TimelineRepository: CRUD operations for TimelineRecord (time-domain data)
- SnapshotRepository: CRUD operations for SnapshotRecord (frequency snapshots)
- ProcessingMetadataRepository: CRUD operations for UploadedFile (file tracking)
- StreamingRecordingRepository: CRUD operations for StreamingRecording (complete recording files)
- AnnotationRepository: CRUD operations for Annotation (clinical event annotations)
- RecordingGroupRepository: CRUD operations for RecordingGroup (recording group management)

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-07
"""

from .base_repository import BaseRepository
from .patient_repository import PatientRepository
from .timeline_repository import TimelineRepository
from .snapshot_repository import SnapshotRepository
from .processing_metadata_repository import ProcessingMetadataRepository
from .streaming_recording_repository import StreamingRecordingRepository
from .annotation_repository import AnnotationRepository
from .recording_group_repository import RecordingGroupRepository

__all__ = [
    'BaseRepository',
    'PatientRepository',
    'TimelineRepository',
    'SnapshotRepository',
    'ProcessingMetadataRepository',
    'StreamingRecordingRepository',
    'AnnotationRepository',
    'RecordingGroupRepository',
]
