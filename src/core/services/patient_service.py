"""
Patient service for orchestrating patient lifecycle operations.

This service provides high-level business logic for patient management,
orchestrating operations across repositories, database adapters, and the
file system. It ensures that patient creation is atomic (all-or-nothing).

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import logging
import shutil
from typing import Optional, Dict, Any, List, Tuple

from src.core.path_resolver import PathResolver
from src.core.models import Patient
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema import initialize_patient_database
from src.infrastructure.repositories.patient_repository import PatientRepository

from .exceptions import (
    PatientAlreadyExistsError,
    InvalidPatientIDError,
    DatabaseInitializationError,
)

logger = logging.getLogger(__name__)


class PatientService:
    """
    Service for patient lifecycle management.

    Orchestrates patient creation, retrieval, updates, and deletion
    across repositories, database initialization, and directory structure.

    The create_patient method ensures atomic operations:
    - Validates patient ID
    - Checks for duplicates
    - Creates directory structure
    - Initializes patient database
    - Registers in patient_registry

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = PatientRepository(adapter, resolver)
        >>> service = PatientService(repo, adapter, resolver)
        >>>
        >>> # Create new patient
        >>> patient = service.create_patient(
        ...     patient_id="PATIENT001",
        ...     patient_name="John Doe",
        ...     metadata={"diagnosis": "Parkinson's"}
        ... )
        >>>
        >>> # Get patient
        >>> patient = service.get_patient("PATIENT001")
        >>>
        >>> # Get all active patients
        >>> patients = service.get_all_active_patients()
    """

    def __init__(
        self,
        repository: PatientRepository,
        adapter: SQLiteAdapter,
        path_resolver: PathResolver
    ):
        """
        Initialize PatientService.

        Args:
            repository: PatientRepository for database operations
            adapter: SQLiteAdapter for database connections
            path_resolver: PathResolver for path management
        """
        self.repository = repository
        self.adapter = adapter
        self.path_resolver = path_resolver
        self.logger = logging.getLogger(__name__)

    def create_patient(
        self,
        patient_id: str,
        patient_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Patient:
        """
        Create new patient with full orchestration.

        This method performs atomic patient creation:
        1. Validates patient_id format
        2. Checks for duplicates
        3. Creates patient directory structure
        4. Initializes patient database with schema
        5. Registers patient in patient_registry
        6. Returns Patient model

        If any step fails, the operation is rolled back where possible.

        Args:
            patient_id: Unique patient identifier
            patient_name: Display name for patient
            metadata: Optional metadata dict (e.g., {"diagnosis": "PD"})

        Returns:
            Patient: Newly created patient

        Raises:
            InvalidPatientIDError: If patient_id format is invalid
            PatientAlreadyExistsError: If patient_id already exists
            DatabaseInitializationError: If database initialization fails
        """
        self.logger.info(f"Creating patient: {patient_id} ({patient_name})")

        # Step 1: Validate patient ID (a new patient: its folder name must work on every OS)
        if not PathResolver.validate_new_patient_id(patient_id):
            self.logger.error(f"Invalid patient ID format: {patient_id}")
            raise InvalidPatientIDError(f"Invalid patient ID: {patient_id}")

        # Step 2: Check for duplicates
        if self.repository.exists(patient_id):
            self.logger.error(f"Patient already exists: {patient_id}")
            raise PatientAlreadyExistsError(f"Patient already exists: {patient_id}")

        # Step 3: Create directory structure
        if not self.path_resolver.create_patient_directory(patient_id):
            self.logger.error(f"Failed to create patient directory: {patient_id}")
            raise DatabaseInitializationError(
                f"Failed to create patient directory: {patient_id}"
            )

        try:
            # Step 4: Initialize patient database with schema
            success = initialize_patient_database(
                self.adapter,
                self.path_resolver,
                patient_id
            )

            if not success:
                self.logger.error(f"Failed to initialize patient database: {patient_id}")
                raise DatabaseInitializationError(
                    f"Failed to initialize patient database: {patient_id}"
                )

            # Step 5: Register patient in patient_registry
            data_directory = self.path_resolver.get_patient_directory(patient_id)
            database_path = self.path_resolver.get_patient_db_path(patient_id)

            patient = self.repository.create(
                patient_id=patient_id,
                patient_name=patient_name,
                data_directory=data_directory,
                database_path=database_path,
                metadata=metadata
            )

            self.logger.info(f"Successfully created patient: {patient_id}")
            return patient

        except Exception as e:
            # Log error and re-raise
            self.logger.error(
                f"Failed to create patient {patient_id}: {e}",
                exc_info=True
            )
            raise

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        """
        Get patient by ID.

        Args:
            patient_id: Patient identifier

        Returns:
            Optional[Patient]: Patient or None if not found
        """
        self.logger.debug(f"Retrieving patient: {patient_id}")
        return self.repository.get_by_id(patient_id)

    def get_all_active_patients(self) -> List[Patient]:
        """
        Get all active patients.

        Returns only patients where is_active = True.

        Returns:
            List[Patient]: List of active patients (empty if none)
        """
        self.logger.debug("Retrieving all active patients")
        return self.repository.get_all_active()

    def get_all_patients(self) -> List[Patient]:
        """
        Get all patients (including inactive).

        Returns all patients regardless of is_active status.

        Returns:
            List[Patient]: List of all patients (empty if none)
        """
        self.logger.debug("Retrieving all patients")
        return self.repository.get_all()

    def update_patient(
        self,
        patient_id: str,
        patient_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Patient]:
        """
        Update patient information.

        Updates only the provided fields.

        Args:
            patient_id: Patient identifier
            patient_name: New patient name (if provided)
            metadata: New metadata dict (if provided)

        Returns:
            Optional[Patient]: Updated patient or None if not found

        Raises:
            ValueError: If no updates provided
        """
        self.logger.info(f"Updating patient: {patient_id}")

        if patient_name is None and metadata is None:
            raise ValueError("Must provide at least one field to update")

        updated_patient = self.repository.update(
            patient_id=patient_id,
            patient_name=patient_name,
            metadata=metadata
        )

        if updated_patient:
            self.logger.info(f"Successfully updated patient: {patient_id}")
        else:
            self.logger.warning(f"Patient not found for update: {patient_id}")

        return updated_patient

    def delete_patient_permanently(self, patient_id: str) -> Tuple[bool, Optional[str]]:
        """
        Permanently delete patient from database and filesystem.

        This performs a two-phase deletion:
        1. Delete from database (transactional, atomic)
        2. Delete patient directory (best-effort)

        Strategy: Database is source of truth. If database deletion succeeds
        but filesystem fails, the patient is still logically deleted (files
        are orphaned but can be manually cleaned up).

        Args:
            patient_id: Patient identifier

        Returns:
            Tuple of (success, error_message):
            - (True, None): Complete success
            - (True, warning): Database deleted, filesystem failed (partial)
            - (False, error): Database deletion failed (nothing deleted)
        """
        self.logger.info(f"Permanently deleting patient: {patient_id}")

        # Phase 1: Delete from database (atomic, transactional)
        try:
            deleted = self.repository.delete(patient_id)
            if not deleted:
                self.logger.warning(f"Patient not found: {patient_id}")
                return False, f"Patient {patient_id} not found"
        except Exception as e:
            self.logger.error(f"Database deletion failed for {patient_id}: {e}")
            return False, f"Database error: {str(e)}"

        # Phase 2: Delete patient directory (best-effort)
        patient_dir = self.path_resolver.get_patient_directory(patient_id)

        if patient_dir.exists():
            try:
                shutil.rmtree(patient_dir)
                self.logger.info(f"Deleted patient directory: {patient_dir}")
            except PermissionError as e:
                # Database deleted but filesystem failed - partial success
                warning = f"Files remain at {patient_dir} (permission denied)"
                self.logger.warning(f"Filesystem cleanup failed for {patient_id}: {e}")
                return True, warning
            except Exception as e:
                # Database deleted but filesystem failed - partial success
                warning = f"Files may remain at {patient_dir}"
                self.logger.warning(f"Filesystem cleanup failed for {patient_id}: {e}")
                return True, warning
        else:
            self.logger.info(f"Patient directory not found (already removed): {patient_dir}")

        self.logger.info(f"Successfully deleted patient {patient_id}")
        return True, None

    def delete_patient(self, patient_id: str) -> bool:
        """
        Permanently delete patient (removes from database and filesystem).

        For soft delete behavior, use repository.soft_delete() directly.

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if patient was deleted, False if not found

        Raises:
            Exception: If deletion fails (caller should handle)
        """
        success, error = self.delete_patient_permanently(patient_id)

        if not success:
            self.logger.error(f"Failed to delete patient {patient_id}: {error}")
            return False

        if error:
            # Partial success - log warning but return True
            self.logger.warning(f"Partial deletion for {patient_id}: {error}")

        return True

    def patient_exists(self, patient_id: str) -> bool:
        """
        Check if patient exists.

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if patient exists (regardless of is_active status)
        """
        return self.repository.exists(patient_id)

    def get_patient_count(self, active_only: bool = True) -> int:
        """
        Get count of patients.

        Args:
            active_only: If True, count only active patients.
                        If False, count all patients.

        Returns:
            int: Number of patients
        """
        if active_only:
            patients = self.repository.get_all_active()
        else:
            patients = self.repository.get_all()

        count = len(patients)
        self.logger.debug(f"Patient count (active_only={active_only}): {count}")
        return count

    def generate_patient_id(self, patient_name: str) -> str:
        """
        Generate unique patient ID from patient name.

        Creates a unique identifier using sanitized patient name and timestamp.
        Format: SANITIZEDNAME_TIMESTAMP

        ID Generation Rules:
        - Name sanitization:
          - Strip leading/trailing whitespace
          - Convert to uppercase
          - Replace spaces with underscores
          - Truncate to 20 characters
        - Timestamp: YYYYMMDDHHmmSS format for uniqueness

        Args:
            patient_name: Display name for the patient

        Returns:
            str: Generated patient ID

        Example:
            >>> service.generate_patient_id("John Doe")
            'JOHN_DOE_20251015143022'

            >>> service.generate_patient_id("  alice jones  ")
            'ALICE_JONES_20251015143022'

            >>> service.generate_patient_id("Very Long Patient Name That Exceeds Limit")
            'VERY_LONG_PATIENT__20251015143022'
        """
        from datetime import datetime

        # Sanitize patient name for ID
        # Rules: uppercase, spaces→underscores, max 20 chars
        sanitized_name = patient_name.strip().upper().replace(" ", "_")[:20]

        # Generate timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

        # Combine into patient ID
        return f"{sanitized_name}_{timestamp}"
