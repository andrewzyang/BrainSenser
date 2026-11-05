"""
Patient model representing a patient from patient_registry table.

This module defines the Patient dataclass that maps directly to the
patient_registry table in the global database (app_metadata.db).

The Patient model is immutable (frozen=True) to ensure data integrity
and thread safety throughout the application.

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class Patient:
    """
    Immutable patient model matching patient_registry table.

    Maps to: app_metadata.db → patient_registry

    This model represents core patient information and provides
    a type-safe interface for working with patient data. All patient
    metadata is stored here as the SINGLE SOURCE OF TRUTH.

    Attributes:
        patient_id: Unique patient identifier (PRIMARY KEY)
        patient_name: Display name for patient
        data_directory: Path to patient's data folder
        database_path: Path to patient's brainsense_data.db
        created_at: Timestamp of patient creation
        updated_at: Timestamp of last update
        is_active: Soft delete flag (True = active, False = deleted)
        metadata: Optional JSON metadata for extensibility (DOB, diagnosis, etc.)

    Example:
        >>> from pathlib import Path
        >>> from datetime import datetime
        >>>
        >>> patient = Patient(
        ...     patient_id="PATIENT001",
        ...     patient_name="John Doe",
        ...     data_directory=Path("/data/patients/PATIENT001"),
        ...     database_path=Path("/data/patients/PATIENT001/brainsense_data.db"),
        ...     created_at=datetime.now(),
        ...     updated_at=datetime.now(),
        ...     is_active=True,
        ...     metadata={"diagnosis": "Parkinson's Disease"}
        ... )
        >>> print(patient.display_name)
        'John Doe'
        >>> str(patient)
        'Patient(PATIENT001: John Doe)'
    """
    patient_id: str
    patient_name: str
    data_directory: Path
    database_path: Path
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    metadata: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        """
        String representation for debugging.

        Returns:
            str: Format "Patient({patient_id}: {patient_name})"
        """
        return f"Patient({self.patient_id}: {self.patient_name})"

    @property
    def display_name(self) -> str:
        """
        Name shown in UI dropdowns and displays.

        Returns:
            str: The patient's display name (patient_name field)
        """
        return self.patient_name
