"""
Service layer for business logic orchestration.

This module provides high-level services that orchestrate operations
across repositories, databases, and the file system.

Services:
    - PatientService: Patient lifecycle management
    - StatisticsService: Statistics calculation and aggregation
    - UploadService: File upload and processing orchestration
    - StreamingService: Streaming recording file operations
    - AnnotationService: Clinical event annotation management
    - ComparisonService: Multi-recording comparison and group management

Exceptions:
    - ServiceError: Base exception for service-level errors
    - PatientNotFoundError: Patient does not exist
    - PatientAlreadyExistsError: Patient already exists
    - InvalidPatientIDError: Invalid patient ID format
    - DatabaseInitializationError: Database initialization failure
"""

from .patient_service import PatientService
from .statistics_service import StatisticsService
from .upload_service import UploadService
from .streaming_service import StreamingService
from .annotation_service import AnnotationService
from .comparison_service import ComparisonService
from .snapshot_timeline_service import SnapshotTimelineService
from .splash_service import SplashService
from .exceptions import (
    ServiceError,
    PatientNotFoundError,
    PatientAlreadyExistsError,
    InvalidPatientIDError,
    DatabaseInitializationError,
    DataNotFoundError,
)

__all__ = [
    # Services
    'PatientService',
    'StatisticsService',
    'UploadService',
    'StreamingService',
    'AnnotationService',
    'ComparisonService',
    'SnapshotTimelineService',
    'SplashService',

    # Exceptions
    'ServiceError',
    'PatientNotFoundError',
    'PatientAlreadyExistsError',
    'InvalidPatientIDError',
    'DatabaseInitializationError',
    'DataNotFoundError',
]
