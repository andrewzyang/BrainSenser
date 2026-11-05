"""
DataManagementViewModel for coordinating Data Management page.

This ViewModel implements the MVVM pattern, separating UI logic from business
logic. It coordinates between the Data Management page UI and the service layer,
managing state and emitting signals for UI updates.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import logging
from typing import Optional
from PySide6.QtCore import QObject, Signal

from pathlib import Path
from src.core.models import Patient
from src.core.services import PatientService, StatisticsService
from src.core.services.upload_service import UploadService
from src.core.path_resolver import PathResolver

logger = logging.getLogger(__name__)


class DataManagementViewModel(QObject):
    """
    ViewModel for Data Management page.

    Responsibilities:
    - Coordinate between UI and services
    - Manage page state (current patient, statistics)
    - Emit signals for UI updates
    - Handle user actions (create, update, delete, select)

    Signals:
        patients_loaded: Emitted when patient list is loaded
        patient_selected: Emitted when a patient is selected
        patient_cleared: Emitted when patient selection is cleared
        statistics_updated: Emitted when statistics are recalculated
        upload_history_updated: Emitted when upload history changes
        data_uploaded: Emitted when new data is uploaded (sends patient_id)
        error_occurred: Emitted when an error occurs
        success_message: Emitted when an operation succeeds

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.infrastructure.repositories import PatientRepository
        >>> from src.core.services import PatientService, StatisticsService
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> patient_repo = PatientRepository(adapter, resolver)
        >>> patient_service = PatientService(patient_repo, adapter, resolver)
        >>> stats_service = StatisticsService(adapter, resolver, patient_repo)
        >>>
        >>> viewmodel = DataManagementViewModel(
        ...     patient_service, stats_service, resolver
        ... )
        >>>
        >>> # Connect signals to UI
        >>> viewmodel.patients_loaded.connect(ui.populate_dropdown)
        >>> viewmodel.patient_selected.connect(ui.show_patient_overview)
        >>> viewmodel.statistics_updated.connect(ui.update_statistics_cards)
        >>>
        >>> # Load patients
        >>> viewmodel.load_patients()
    """

    # Signals for UI updates
    patients_loaded = Signal(list)          # List[Patient]
    patient_selected = Signal(object)       # Patient
    patient_cleared = Signal()              # No args
    statistics_updated = Signal(object)     # PatientStatistics
    upload_history_updated = Signal(list)   # List[UploadedFile]
    metadata_updated = Signal(dict)         # Patient metadata dictionary
    data_uploaded = Signal(str)             # Patient ID (emitted when new data is uploaded)
    error_occurred = Signal(str)            # Error message
    success_message = Signal(str)           # Success message

    def __init__(
        self,
        patient_service: PatientService,
        statistics_service: StatisticsService,
        upload_service: UploadService,
        path_resolver: PathResolver
    ):
        """
        Initialize DataManagementViewModel.

        Args:
            patient_service: Service for patient operations
            statistics_service: Service for statistics calculations
            upload_service: Service for file upload operations
            path_resolver: PathResolver for file system operations
        """
        super().__init__()

        # Services
        self.patient_service = patient_service
        self.statistics_service = statistics_service
        self.upload_service = upload_service
        self.path_resolver = path_resolver

        # Current state
        self._current_patient: Optional[Patient] = None

        self.logger = logging.getLogger(__name__)
        self.logger.info("DataManagementViewModel initialized")

    @property
    def current_patient(self) -> Optional[Patient]:
        """Get currently selected patient."""
        return self._current_patient

    def load_patients(self) -> None:
        """
        Load all active patients from the database.

        Emits:
            patients_loaded: With list of active patients
            error_occurred: If loading fails

        Example:
            >>> viewmodel.load_patients()
            # Signal emitted: patients_loaded with List[Patient]
        """
        try:
            self.logger.info("Loading patients...")
            patients = self.patient_service.get_all_active_patients()
            self.logger.info(f"Loaded {len(patients)} active patients")

            self.patients_loaded.emit(patients)

        except Exception as e:
            error_msg = f"Failed to load patients: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def select_patient(self, patient_id: str) -> None:
        """
        Select a patient and load their data.

        This will:
        1. Retrieve patient from service
        2. Set as current patient
        3. Emit patient_selected signal
        4. Load and emit patient statistics

        Args:
            patient_id: Patient identifier

        Emits:
            patient_selected: With Patient object
            statistics_updated: With PatientStatistics object
            error_occurred: If patient not found or loading fails

        Example:
            >>> viewmodel.select_patient("PATIENT001")
            # Signals emitted:
            # - patient_selected with Patient object
            # - statistics_updated with PatientStatistics object
        """
        try:
            self.logger.info(f"Selecting patient: {patient_id}")

            # Get patient from service
            patient = self.patient_service.get_patient(patient_id)

            if not patient:
                error_msg = f"Patient not found: {patient_id}"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Update current state
            self._current_patient = patient
            self.logger.info(f"Patient selected: {patient.patient_name}")

            # Emit patient selected signal
            self.patient_selected.emit(patient)

            # Emit metadata signal (from patient.metadata field)
            metadata = patient.metadata or {}
            self.metadata_updated.emit(metadata)

            # Load statistics for this patient
            self._load_patient_statistics(patient_id)

            # Load upload history for this patient
            self._load_upload_history(patient_id)

        except Exception as e:
            error_msg = f"Failed to select patient {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def clear_patient_selection(self) -> None:
        """
        Clear the current patient selection.

        Emits:
            patient_cleared: No arguments

        Example:
            >>> viewmodel.clear_patient_selection()
            # Signal emitted: patient_cleared
        """
        self.logger.info("Clearing patient selection")
        self._current_patient = None
        self.patient_cleared.emit()

    def create_patient(self, patient_name: str, metadata: Optional[dict] = None) -> None:
        """
        Create a new patient.

        This will:
        1. Validate patient name
        2. Generate patient_id via service
        3. Create patient via service
        4. Auto-select the new patient
        5. Reload patient list

        Args:
            patient_name: Name for the new patient
            metadata: Optional metadata dictionary

        Emits:
            success_message: On successful creation
            patients_loaded: After creating patient (refreshes dropdown)
            patient_selected: Auto-selects the new patient
            error_occurred: If creation fails

        Example:
            >>> viewmodel.create_patient("John Doe")
            # Signals emitted:
            # - success_message: "Patient created successfully"
            # - patients_loaded: Refreshed list
            # - patient_selected: New patient auto-selected
        """
        try:
            self.logger.info(f"Creating patient: {patient_name}")

            # Validate patient name
            if not patient_name or not patient_name.strip():
                error_msg = "Patient name cannot be empty"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Generate patient_id via service (business logic)
            patient_id = self.patient_service.generate_patient_id(patient_name)

            # Create patient via service
            patient = self.patient_service.create_patient(
                patient_id=patient_id,
                patient_name=patient_name.strip(),
                metadata=metadata
            )

            self.logger.info(f"Patient created: {patient.patient_id}")
            self.success_message.emit(f"Patient created: {patient_name}")

            # Reload patients to refresh dropdown
            self.load_patients()

            # Auto-select the new patient
            self.select_patient(patient.patient_id)

        except Exception as e:
            error_msg = f"Failed to create patient: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def update_patient(self, patient_id: str, patient_name: str, metadata: Optional[dict] = None) -> None:
        """
        Update an existing patient.

        Args:
            patient_id: Patient identifier
            patient_name: New patient name
            metadata: New metadata dictionary

        Emits:
            success_message: On successful update
            patients_loaded: After updating (refreshes dropdown)
            patient_selected: Re-selects updated patient
            error_occurred: If update fails

        Example:
            >>> viewmodel.update_patient("PATIENT001", "Jane Doe")
            # Signals emitted:
            # - success_message: "Patient updated successfully"
            # - patients_loaded: Refreshed list
            # - patient_selected: Updated patient re-selected
        """
        try:
            self.logger.info(f"Updating patient: {patient_id}")

            # Validate patient name
            if not patient_name or not patient_name.strip():
                error_msg = "Patient name cannot be empty"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Update via service
            updated_patient = self.patient_service.update_patient(
                patient_id=patient_id,
                patient_name=patient_name.strip(),
                metadata=metadata
            )

            if not updated_patient:
                error_msg = f"Patient not found: {patient_id}"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            self.logger.info(f"Patient updated: {patient_id}")
            self.success_message.emit(f"Patient updated: {patient_name}")

            # Reload patients to refresh dropdown
            self.load_patients()

            # Re-select the updated patient
            self.select_patient(patient_id)

        except Exception as e:
            error_msg = f"Failed to update patient: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def delete_patient(self, patient_id: str) -> None:
        """
        Soft delete a patient.

        This sets is_active = False but preserves all data.

        Args:
            patient_id: Patient identifier

        Emits:
            success_message: On successful deletion
            patients_loaded: After deleting (refreshes dropdown)
            patient_cleared: Clears current selection
            error_occurred: If deletion fails

        Example:
            >>> viewmodel.delete_patient("PATIENT001")
            # Signals emitted:
            # - success_message: "Patient deleted successfully"
            # - patients_loaded: Refreshed list
            # - patient_cleared: Selection cleared
        """
        try:
            self.logger.info(f"Deleting patient: {patient_id}")

            # Delete via service (soft delete)
            success = self.patient_service.delete_patient(patient_id)

            if not success:
                error_msg = f"Patient not found: {patient_id}"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            self.logger.info(f"Patient deleted: {patient_id}")
            self.success_message.emit("Patient deleted successfully")

            # Clear selection if this was the selected patient
            if self._current_patient and self._current_patient.patient_id == patient_id:
                self.clear_patient_selection()

            # Reload patients to refresh dropdown
            self.load_patients()

        except Exception as e:
            error_msg = f"Failed to delete patient: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def refresh_statistics(self) -> None:
        """
        Refresh statistics for the currently selected patient.

        Emits:
            statistics_updated: With refreshed PatientStatistics
            error_occurred: If no patient selected or refresh fails

        Example:
            >>> viewmodel.select_patient("PATIENT001")
            >>> # ... later ...
            >>> viewmodel.refresh_statistics()
            # Signal emitted: statistics_updated with fresh data
        """
        if not self._current_patient:
            error_msg = "No patient selected"
            self.logger.warning(error_msg)
            self.error_occurred.emit(error_msg)
            return

        self._load_patient_statistics(self._current_patient.patient_id)

    def _load_patient_statistics(self, patient_id: str) -> None:
        """
        Load statistics for a specific patient (internal helper).

        Args:
            patient_id: Patient identifier

        Emits:
            statistics_updated: With PatientStatistics object
            error_occurred: If loading fails
        """
        try:
            self.logger.debug(f"Loading statistics for patient: {patient_id}")

            stats = self.statistics_service.get_patient_statistics(patient_id)

            if not stats:
                self.logger.warning(f"No statistics found for patient: {patient_id}")
                # Create empty statistics
                from datetime import datetime
                from src.core.models import PatientStatistics
                stats = PatientStatistics(
                    patient_id=patient_id,
                    snapshots_original=0,
                    snapshots_deduplicated=0,
                    timeline_original=0,
                    timeline_deduplicated=0,
                    total_files_uploaded=0,
                    total_duplicates_skipped=0,
                    last_upload_date=None,
                    last_calculated=datetime.now()
                )

            self.logger.debug(
                f"Statistics loaded for {patient_id}: "
                f"{stats.total_files_uploaded} files, "
                f"{stats.snapshots_deduplicated} snapshots"
            )

            self.statistics_updated.emit(stats)

        except Exception as e:
            error_msg = f"Failed to load statistics for {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def upload_path(self, path: Path) -> None:
        """
        Route an upload to the correct handler based on the path type.

        The View hands over the user's selected path (from the file-or-directory
        picker) without deciding how to upload it; this ViewModel owns that
        routing decision.

        Args:
            path: A JSON file or a directory of JSON files

        Emits:
            error_occurred: If the path does not exist
            (otherwise delegates to upload_file() / upload_directory())

        Example:
            >>> viewmodel.upload_path(Path("/data/session_01.json"))   # single file
            >>> viewmodel.upload_path(Path("/data/recordings"))        # whole directory
        """
        if path.is_dir():
            self.upload_directory(path)
        elif path.is_file():
            self.upload_file(path)
        else:
            error_msg = f"Path not found: {path}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)

    def upload_file(self, file_path: Path) -> None:
        """
        Upload a single BrainSense JSON file.

        Delegates the actual upload to UploadService.upload_file(); the ViewModel
        validates inputs, presents the result, and refreshes page state.

        Args:
            file_path: Path to a BrainSense JSON file

        Emits:
            success_message: On successful upload (with a per-data-type breakdown),
                or when the file was already uploaded (a benign skip)
            error_occurred: If no patient is selected, the path is invalid, or the
                upload fails

        Example:
            >>> viewmodel.upload_file(Path("/data/session_01.json"))
        """
        if not self._current_patient:
            error_msg = "No patient selected. Please select a patient first."
            self.logger.warning(error_msg)
            self.error_occurred.emit(error_msg)
            return

        # Validate the file (basic checks before the service call)
        if not file_path.exists() or not file_path.is_file():
            error_msg = f"Invalid file: {file_path}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
            return

        if file_path.suffix.lower() != ".json":
            error_msg = (
                f"Unsupported File Type\n\n"
                f"{file_path.name}\n\n"
                f"Please select a BrainSense JSON (.json) file."
            )
            self.logger.warning(error_msg)
            self.error_occurred.emit(error_msg)
            return

        try:
            self.logger.info(
                f"Starting file upload from {file_path} "
                f"for patient {self._current_patient.patient_id}"
            )

            # ✅ MVVM COMPLIANT: Delegate entirely to service layer
            result = self.upload_service.upload_file(
                patient_id=self._current_patient.patient_id,
                file_path=file_path,
                progress_callback=None  # Could add progress tracking if needed
            )

            if not result.success:
                # A previously-uploaded file is a benign skip, not an error.
                if result.is_duplicate:
                    info_msg = (
                        f"Already Uploaded\n\n"
                        f"{file_path.name} was uploaded previously and was skipped."
                    )
                    self.logger.info(f"Duplicate file skipped: {file_path.name}")
                    self.success_message.emit(info_msg)
                    return

                self.logger.error(f"File upload failed: {result.message}")
                self.error_occurred.emit(result.message)
                return

            # Build detailed success message (same per-type breakdown as batch upload)
            success_parts = [
                f"Upload Complete!\n",
                f"Successfully uploaded {file_path.name}\n"
            ]

            if result.timeline_inserted > 0 or result.timeline_duplicates > 0:
                original = result.timeline_inserted + result.timeline_duplicates
                success_parts.append(
                    f"Timeline: {result.timeline_inserted:,} records "
                    f"({original:,} original, {result.timeline_duplicates:,} duplicates skipped)"
                )

            if result.snapshot_inserted > 0 or result.snapshot_duplicates > 0:
                original = result.snapshot_inserted + result.snapshot_duplicates
                success_parts.append(
                    f"Snapshots: {result.snapshot_inserted:,} records "
                    f"({original:,} original, {result.snapshot_duplicates:,} duplicates skipped)"
                )

            if result.indefinite_streaming_inserted > 0 or result.indefinite_streaming_duplicates > 0:
                original = result.indefinite_streaming_inserted + result.indefinite_streaming_duplicates
                success_parts.append(
                    f"Indefinite Streaming: {result.indefinite_streaming_inserted:,} records "
                    f"({original:,} original, {result.indefinite_streaming_duplicates:,} duplicates skipped)"
                )

            if result.definite_streaming_inserted > 0 or result.definite_streaming_duplicates > 0:
                original = result.definite_streaming_inserted + result.definite_streaming_duplicates
                success_parts.append(
                    f"Definite Streaming: {result.definite_streaming_inserted:,} records "
                    f"({original:,} original, {result.definite_streaming_duplicates:,} duplicates skipped)"
                )

            success_msg = "\n".join(success_parts)

            self.logger.info(f"File upload complete: {file_path.name}")
            self.success_message.emit(success_msg)

            # Refresh page state (shared with upload_directory)
            self._refresh_after_upload()

        except FileNotFoundError:
            error_msg = f"File not found: {file_path}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
        except Exception as e:
            error_msg = (
                f"Unexpected Error During Upload\n\n"
                f"An error occurred while uploading:\n{file_path}\n\n"
                f"Error: {str(e)}\n\n"
                f"Please check the application logs for more details."
            )
            self.logger.error(
                f"Failed file upload from {file_path}: {str(e)}",
                exc_info=True
            )
            self.error_occurred.emit(error_msg)

    def upload_directory(self, directory_path: Path) -> None:
        """
        Upload all JSON files from a directory recursively.

        Delegates all file discovery and upload logic to UploadService.
        ViewModel only handles result presentation and signal emission.

        Args:
            directory_path: Path to directory containing JSON files

        Emits:
            success_message: On successful upload(s) with statistics
            error_occurred: If upload fails or directory invalid

        Example:
            >>> viewmodel.upload_directory(Path("/data/patient_recordings"))
            # Service discovers and uploads all .json files, ViewModel presents results
        """
        if not self._current_patient:
            error_msg = "No patient selected. Please select a patient first."
            self.logger.warning(error_msg)
            self.error_occurred.emit(error_msg)
            return

        try:
            # Validate directory (basic check before service call)
            if not directory_path.exists() or not directory_path.is_dir():
                error_msg = f"Invalid directory: {directory_path}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return

            self.logger.info(
                f"Starting directory upload from {directory_path} "
                f"for patient {self._current_patient.patient_id}"
            )

            # ✅ MVVM COMPLIANT: Delegate entirely to service layer
            result = self.upload_service.upload_directory(
                patient_id=self._current_patient.patient_id,
                directory_path=directory_path,
                progress_callback=None  # Could add progress tracking if needed
            )

            # Handle results based on success/failure
            if result.total_files == 0:
                error_msg = (
                    f"No JSON Files Found\n\n"
                    f"Directory: {directory_path}\n\n"
                    f"Please select a directory containing BrainSense JSON files."
                )
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Nothing was uploaded. Distinguish "everything was already uploaded"
            # (a benign skip) from genuine upload failures.
            if result.successful_uploads == 0:
                if result.failed_uploads == 0 and result.skipped_duplicates > 0:
                    info_msg = (
                        f"Already Uploaded\n\n"
                        f"All {result.total_files} file(s) in this directory were "
                        f"uploaded previously and were skipped as duplicates.\n\n"
                        f"Nothing new to add."
                    )
                    self.logger.info(
                        f"Directory upload skipped: all {result.total_files} files "
                        f"already uploaded for {self._current_patient.patient_id}"
                    )
                    self.success_message.emit(info_msg)
                    return

                error_msg = (
                    f"Batch Upload Failed\n\n"
                    f"All {result.total_files} files failed to upload.\n\n"
                    f"Please check the application logs for details."
                )
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Build detailed success message
            success_parts = [
                f"Batch Upload Complete!\n",
                f"Successfully uploaded {result.successful_uploads} of {result.total_files} files\n"
            ]

            # Add breakdown by data type (same pattern as single file upload)
            if result.total_timeline_inserted > 0 or result.total_timeline_duplicates > 0:
                original = result.total_timeline_inserted + result.total_timeline_duplicates
                success_parts.append(
                    f"Timeline: {result.total_timeline_inserted:,} records "
                    f"({original:,} original, {result.total_timeline_duplicates:,} duplicates skipped)"
                )

            if result.total_snapshot_inserted > 0 or result.total_snapshot_duplicates > 0:
                original = result.total_snapshot_inserted + result.total_snapshot_duplicates
                success_parts.append(
                    f"Snapshots: {result.total_snapshot_inserted:,} records "
                    f"({original:,} original, {result.total_snapshot_duplicates:,} duplicates skipped)"
                )

            if result.total_indefinite_streaming_inserted > 0 or result.total_indefinite_streaming_duplicates > 0:
                original = result.total_indefinite_streaming_inserted + result.total_indefinite_streaming_duplicates
                success_parts.append(
                    f"Indefinite Streaming: {result.total_indefinite_streaming_inserted:,} records "
                    f"({original:,} original, {result.total_indefinite_streaming_duplicates:,} duplicates skipped)"
                )

            if result.total_definite_streaming_inserted > 0 or result.total_definite_streaming_duplicates > 0:
                original = result.total_definite_streaming_inserted + result.total_definite_streaming_duplicates
                success_parts.append(
                    f"Definite Streaming: {result.total_definite_streaming_inserted:,} records "
                    f"({original:,} original, {result.total_definite_streaming_duplicates:,} duplicates skipped)"
                )

            success_msg = "\n".join(success_parts)

            # Add a notes section for failures and/or skipped duplicate files.
            if result.has_errors or result.skipped_duplicates > 0:
                note_parts = ["\n\nNotes:"]
                if result.failed_uploads > 0:
                    note_parts.append(f"  • Failed uploads: {result.failed_uploads}")
                if result.skipped_duplicates > 0:
                    note_parts.append(
                        f"  • Already uploaded (skipped): {result.skipped_duplicates}"
                    )
                success_msg += "\n".join(note_parts) + "\n"

            self.logger.info(
                f"Batch upload complete: {result.successful_uploads}/{result.total_files} successful"
            )
            self.success_message.emit(success_msg)

            # Refresh page state (shared with upload_file)
            self._refresh_after_upload()

        except FileNotFoundError:
            error_msg = f"Directory not found: {directory_path}"
            self.logger.error(error_msg)
            self.error_occurred.emit(error_msg)
        except Exception as e:
            error_msg = (
                f"Unexpected Error During Batch Upload\n\n"
                f"An error occurred while uploading files from:\n{directory_path}\n\n"
                f"Error: {str(e)}\n\n"
                f"Please check the application logs for more details."
            )
            self.logger.error(
                f"Failed batch upload from {directory_path}: {str(e)}",
                exc_info=True
            )
            self.error_occurred.emit(error_msg)

    def _refresh_after_upload(self) -> None:
        """
        Refresh page state after a successful upload (file or directory).

        Re-fetches the current patient, re-emits selection/metadata, refreshes
        statistics and upload history, and notifies other pages via data_uploaded.
        Shared by upload_file() and upload_directory() so both paths refresh
        identically.

        Emits:
            patient_selected: With the refreshed Patient
            metadata_updated: With the refreshed patient metadata
            statistics_updated: Via refresh_statistics()
            upload_history_updated: Via _load_upload_history()
            data_uploaded: With the patient ID (notifies other pages)
        """
        if not self._current_patient:
            return

        patient_id = self._current_patient.patient_id

        # Refresh patient metadata so views get the latest details
        refreshed_patient = self.patient_service.get_patient(patient_id)
        if refreshed_patient:
            self._current_patient = refreshed_patient
            self.patient_selected.emit(refreshed_patient)
            self.metadata_updated.emit(refreshed_patient.metadata or {})
        else:
            self.logger.warning(
                "Patient no longer available after upload: %s",
                patient_id
            )

        # Refresh statistics and upload history
        self.refresh_statistics()
        self._load_upload_history(patient_id)

        # Emit data_uploaded signal to notify other pages
        self.data_uploaded.emit(patient_id)

    def _load_upload_history(self, patient_id: str) -> None:
        """
        Load upload history for a specific patient (internal helper).

        Args:
            patient_id: Patient identifier

        Emits:
            upload_history_updated: With List[UploadedFile]
            error_occurred: If loading fails
        """
        try:
            self.logger.debug(f"Loading upload history for patient: {patient_id}")

            uploads = self.upload_service.get_upload_history(patient_id)

            self.logger.debug(f"Upload history loaded for {patient_id}: {len(uploads)} files")

            self.upload_history_updated.emit(uploads)

        except Exception as e:
            error_msg = f"Failed to load upload history for {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)
