"""
AppViewModel - Application-level ViewModel for global state.

This ViewModel manages app-level state that persists across page navigation:
- Current patient selection
- Patient list
- Patient CRUD operations

All pages in the app listen to this ViewModel's signals to stay synchronized
with the currently selected patient.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-01
"""

import logging
from typing import Optional, List
from PySide6.QtCore import QObject, Signal

from src.core.models import Patient
from src.core.services import PatientService

logger = logging.getLogger(__name__)


class AppViewModel(QObject):
    """
    Application-level ViewModel for global state.

    Manages app-wide state that multiple pages need access to:
    - Current patient selection (used by TopBar and all pages)
    - Patient list (for TopBar dropdown)
    - Patient CRUD operations

    Signals:
        patients_loaded: Emitted when patient list is loaded
        patient_selected: Emitted when a patient is selected
        patient_cleared: Emitted when patient selection is cleared
        patient_created: Emitted when a new patient is created
        patient_updated: Emitted when a patient is updated
        patient_deleted: Emitted when a patient is deleted
        error_occurred: Emitted when an error occurs
        success_message: Emitted when an operation succeeds

    Example:
        >>> app_vm = AppViewModel(patient_service)
        >>> app_vm.patient_selected.connect(data_page_vm.on_patient_selected)
        >>> app_vm.load_patients()
        >>> app_vm.select_patient("PATIENT001")
    """

    # Signals
    patients_loaded = Signal(list)          # List[Patient]
    patient_selected = Signal(object)       # Patient
    patient_cleared = Signal()              # No args
    patient_created = Signal(object)        # Patient
    patient_updated = Signal(object)        # Patient
    patient_deleted = Signal(str)           # patient_id
    error_occurred = Signal(str)            # Error message
    success_message = Signal(str)           # Success message

    def __init__(self, patient_service: PatientService):
        """
        Initialize AppViewModel.

        Args:
            patient_service: Service for patient operations
        """
        super().__init__()
        self.patient_service = patient_service
        self.logger = logging.getLogger(__name__)

        # Current state
        self._current_patient: Optional[Patient] = None
        self._patients: List[Patient] = []

        self.logger.info("AppViewModel initialized")

    @property
    def current_patient(self) -> Optional[Patient]:
        """Get the currently selected patient."""
        return self._current_patient

    @property
    def patients(self) -> List[Patient]:
        """Get the list of all patients."""
        return self._patients

    def load_patients(self) -> None:
        """
        Load all active patients.

        Emits:
            patients_loaded: With List[Patient]
            error_occurred: If loading fails
        """
        try:
            self.logger.info("Loading patients...")
            patients = self.patient_service.get_all_patients()
            self._patients = patients

            self.logger.info(f"Loaded {len(patients)} active patients")
            self.patients_loaded.emit(patients)

        except Exception as e:
            error_msg = f"Failed to load patients: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def select_patient(self, patient_id: str) -> None:
        """
        Select a patient by ID.

        Args:
            patient_id: Patient identifier

        Emits:
            patient_selected: With Patient object
            error_occurred: If patient not found or loading fails
        """
        try:
            self.logger.info(f"Selecting patient: {patient_id}")

            # Get patient details
            patient = self.patient_service.get_patient(patient_id)

            if not patient:
                error_msg = f"Patient not found: {patient_id}"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Update current patient
            self._current_patient = patient

            self.logger.info(f"Patient selected: {patient_id}")
            self.patient_selected.emit(patient)

        except Exception as e:
            error_msg = f"Failed to select patient {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def clear_patient_selection(self) -> None:
        """
        Clear the current patient selection.

        Emits:
            patient_cleared: No args
        """
        self.logger.info("Clearing patient selection")
        self._current_patient = None
        self.patient_cleared.emit()

    def create_patient(self, patient_name: str, metadata: Optional[dict] = None) -> None:
        """
        Create a new patient.

        Args:
            patient_name: Display name for the patient
            metadata: Optional metadata dictionary (e.g., {"notes": "..."})

        Emits:
            patient_created: With newly created Patient
            patients_loaded: With updated patient list
            success_message: On successful creation
            error_occurred: If creation fails
        """
        try:
            self.logger.info(f"Creating patient: {patient_name}")

            # Validate patient name
            if not patient_name or not patient_name.strip():
                error_msg = "Patient name cannot be empty"
                self.logger.warning(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Generate patient_id (use sanitized name)
            sanitized_name = patient_name.strip().upper().replace(" ", "_")
            patient_id = sanitized_name

            # Create patient via service
            patient = self.patient_service.create_patient(
                patient_id=patient_id,
                patient_name=patient_name.strip(),
                metadata=metadata
            )

            if not patient:
                error_msg = f"Failed to create patient: {patient_name}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Reload patient list
            self.load_patients()

            self.logger.info(f"Patient created successfully: {patient_id}")
            self.patient_created.emit(patient)
            self.success_message.emit(f"Patient '{patient_name}' created successfully")

            # Auto-select the new patient
            self.select_patient(patient_id)

        except Exception as e:
            error_msg = f"Failed to create patient '{patient_name}': {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def update_patient(
        self,
        patient_id: str,
        patient_name: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> None:
        """
        Update an existing patient.

        Args:
            patient_id: Patient identifier
            patient_name: Updated patient name (optional)
            metadata: Updated metadata dictionary (optional)

        Emits:
            patient_updated: With updated Patient
            patients_loaded: With updated patient list
            success_message: On successful update
            error_occurred: If update fails
        """
        try:
            self.logger.info(f"Updating patient: {patient_id}")

            # Update patient via service
            patient = self.patient_service.update_patient(
                patient_id=patient_id,
                patient_name=patient_name,
                metadata=metadata
            )

            if not patient:
                error_msg = f"Failed to update patient: {patient_id}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # Reload patient list
            self.load_patients()

            # If this is the current patient, update it
            if self._current_patient and self._current_patient.patient_id == patient_id:
                self._current_patient = patient
                self.patient_selected.emit(patient)

            self.logger.info(f"Patient updated successfully: {patient_id}")
            self.patient_updated.emit(patient)
            self.success_message.emit(f"Patient updated successfully")

        except Exception as e:
            error_msg = f"Failed to update patient {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)

    def delete_patient(self, patient_id: str) -> None:
        """
        Delete a patient (soft delete).

        Args:
            patient_id: Patient identifier

        Emits:
            patient_deleted: With patient_id
            patients_loaded: With updated patient list
            patient_cleared: If the deleted patient was currently selected
            success_message: On successful deletion
            error_occurred: If deletion fails
        """
        try:
            self.logger.info(f"Deleting patient: {patient_id}")

            # Delete patient via service
            success = self.patient_service.delete_patient(patient_id)

            if not success:
                error_msg = f"Failed to delete patient: {patient_id}"
                self.logger.error(error_msg)
                self.error_occurred.emit(error_msg)
                return

            # If this was the current patient, clear selection
            if self._current_patient and self._current_patient.patient_id == patient_id:
                self.clear_patient_selection()

            # Reload patient list
            self.load_patients()

            self.logger.info(f"Patient deleted successfully: {patient_id}")
            self.patient_deleted.emit(patient_id)
            self.success_message.emit(f"Patient {patient_id} deleted successfully")

        except Exception as e:
            error_msg = f"Failed to delete patient {patient_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit(error_msg)
