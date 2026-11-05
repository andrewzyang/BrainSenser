"""
Dependency Injection Container for iEEG BrainSense Application

Centralizes all dependency wiring and configuration.
Provides automatic dependency graph validation.

Benefits:
- Single source of truth for dependency configuration
- Automatic dependency graph validation (detects circular dependencies)
- Easy testing via dependency overrides
- Configuration from files (YAML/JSON)
- Type-safe dependency resolution

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-08
"""

import os
from pathlib import Path

from dependency_injector import containers, providers

from src.core.path_resolver import PathResolver
from src.core.app_config import get_app_config
from src.infrastructure.app_restart import QProcessAppRestarter
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.preferences import QSettingsUiPreferences
from src.ui.policy.scale import active_scale_factor, scale_locked

# Project root is three levels up from this file:
# src/infrastructure/container.py -> src/infrastructure -> src -> <project_root>
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ASSETS_DIR = _PROJECT_ROOT / "assets"

# Repositories
from src.infrastructure.repositories import (
    PatientRepository,
    TimelineRepository,
    SnapshotRepository,
    ProcessingMetadataRepository,
    StreamingRecordingRepository,
    AnnotationRepository,
    RecordingGroupRepository
)

# Services
from src.core.services import (
    PatientService,
    StatisticsService,
    StreamingService,
    AnnotationService,
    ComparisonService,
    SnapshotTimelineService
)
from src.core.services.upload_service import UploadService
from src.core.services.effect_size_calculator import EffectSizeCalculator
from src.core.services.splash_service import SplashService

# ViewModels
from src.ui.viewmodels import (
    AppViewModel,
    DataManagementViewModel,
    ShellViewModel,
    SplashViewModel,
    UiScaleViewModel,
)


class ApplicationContainer(containers.DeclarativeContainer):
    """
    Application-wide dependency injection container.

    This container manages the entire dependency graph for the application,
    ensuring that all components are properly wired together with their
    dependencies.

    Architecture:
        Infrastructure Layer → Repository Layer → Service Layer → ViewModel Layer

    Usage:
        # In main.py
        container = ApplicationContainer()
        app_viewmodel = container.app_viewmodel()

        # In tests
        container = ApplicationContainer()
        container.patient_repository.override(providers.Factory(MockPatientRepository))
        service = container.patient_service()  # Uses mocked repository
    """

    # ========================================================================
    # Configuration Layer
    # ========================================================================
    config = providers.Configuration()

    # Wire up existing AppConfig for preprocessing settings
    app_config = providers.Singleton(get_app_config)

    # Extract preprocessing setting from AppConfig
    enable_overvoltage_preprocessing = providers.Callable(
        lambda cfg: cfg.is_overvoltage_preprocessing_enabled(),
        cfg=app_config
    )

    # ========================================================================
    # Infrastructure Layer
    # Core infrastructure components (singletons)
    # ========================================================================
    path_resolver = providers.Singleton(PathResolver)

    db_adapter = providers.Singleton(SQLiteAdapter)

    # ========================================================================
    # Repository Layer
    # All repositories share same adapter + path_resolver
    # Using Factory provider so each request gets new instance
    # ========================================================================

    patient_repository = providers.Factory(
        PatientRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    timeline_repository = providers.Factory(
        TimelineRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    snapshot_repository = providers.Factory(
        SnapshotRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    processing_metadata_repository = providers.Factory(
        ProcessingMetadataRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    streaming_recording_repository = providers.Factory(
        StreamingRecordingRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    annotation_repository = providers.Factory(
        AnnotationRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    recording_group_repository = providers.Factory(
        RecordingGroupRepository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    # ========================================================================
    # Service Layer
    # All services auto-injected with repositories and infrastructure
    # Using Factory provider for flexibility
    # ========================================================================

    patient_service = providers.Factory(
        PatientService,
        repository=patient_repository,
        adapter=db_adapter,
        path_resolver=path_resolver
    )

    statistics_service = providers.Factory(
        StatisticsService,
        adapter=db_adapter,
        path_resolver=path_resolver,
        patient_repository=patient_repository
    )

    upload_service = providers.Factory(
        UploadService,
        adapter=db_adapter,
        path_resolver=path_resolver,
        timeline_repo=timeline_repository,
        snapshot_repo=snapshot_repository,
        processing_repo=processing_metadata_repository,
        patient_repo=patient_repository,
        enable_overvoltage_preprocessing=enable_overvoltage_preprocessing
    )

    streaming_service = providers.Factory(
        StreamingService,
        repository=streaming_recording_repository,
        path_resolver=path_resolver
    )

    annotation_service = providers.Factory(
        AnnotationService,
        repository=annotation_repository
    )

    comparison_service = providers.Factory(
        ComparisonService,
        group_repository=recording_group_repository,
        streaming_repository=streaming_recording_repository
    )

    effect_size_calculator = providers.Factory(
        EffectSizeCalculator
    )

    snapshot_timeline_service = providers.Factory(
        SnapshotTimelineService,
        snapshot_repository=snapshot_repository,
        patient_service=patient_service
    )

    splash_service = providers.Factory(
        SplashService,
        assets_dir=_ASSETS_DIR,
    )

    # ========================================================================
    # ViewModel Layer
    # All ViewModels auto-injected with services
    # Using Factory provider to support multiple instances if needed
    # ========================================================================

    app_viewmodel = providers.Factory(
        AppViewModel,
        patient_service=patient_service
    )

    data_management_viewmodel = providers.Factory(
        DataManagementViewModel,
        patient_service=patient_service,
        statistics_service=statistics_service,
        upload_service=upload_service,
        path_resolver=path_resolver
    )

    splash_viewmodel = providers.Factory(
        SplashViewModel,
        splash_service=splash_service,
    )

    # ========================================================================
    # Shell and interface size (plan §4.7)
    # Lazy singletons, one per container; one store serves both ViewModels
    # ========================================================================

    # The environment Qt started with. main() composes the interface size into
    # os.environ before the QApplication exists, so the live os.environ is
    # right for the app; a harness that starts Qt with another environment
    # overrides this provider with that mapping.
    startup_environment = providers.Object(os.environ)

    ui_preferences = providers.Singleton(QSettingsUiPreferences)

    app_restarter = providers.Singleton(QProcessAppRestarter)

    ui_scale_viewmodel = providers.Singleton(
        UiScaleViewModel,
        store=ui_preferences,
        restarter=app_restarter,
        active_factor=providers.Callable(active_scale_factor, startup_environment),
        locked=providers.Callable(scale_locked, startup_environment),
    )

    shell_viewmodel = providers.Singleton(
        ShellViewModel,
        store=ui_preferences,
    )
