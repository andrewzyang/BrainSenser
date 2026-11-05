"""
Repository for patient_registry table operations.

This module provides CRUD operations for the Patient model, mapping to the
patient_registry table in the global database (app_metadata.db).

Features:
- Create new patients with validation
- Retrieve patients by ID or get all active patients
- Update patient information
- Soft delete (set is_active = 0)
- JSON metadata support

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from .base_repository import BaseRepository
from src.core.models import Patient


class PatientRepository(BaseRepository[Patient]):
    """
    Repository for Patient model / patient_registry table.

    Provides CRUD operations for patients with soft delete support.
    All operations use the global database (app_metadata.db).

    Example:
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> repo = PatientRepository(adapter, resolver)
        >>>
        >>> # Create patient
        >>> patient = repo.create(
        ...     patient_id="PATIENT001",
        ...     patient_name="John Doe",
        ...     data_directory=Path("/data/patients/PATIENT001"),
        ...     database_path=Path("/data/patients/PATIENT001/brainsense_data.db")
        ... )
        >>>
        >>> # Get patient
        >>> patient = repo.get_by_id("PATIENT001")
        >>>
        >>> # Get all active patients
        >>> patients = repo.get_all_active()
    """

    def _map_row_to_model(self, row: sqlite3.Row) -> Patient:
        """
        Convert database row to Patient model.

        Args:
            row: Database row with patient_registry columns

        Returns:
            Patient: Patient model instance
        """
        return Patient(
            patient_id=row['patient_id'],
            patient_name=row['patient_name'],
            data_directory=Path(row['data_directory']),
            database_path=Path(row['database_path']),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            is_active=bool(row['is_active']),
            metadata=json.loads(row['metadata_json']) if row['metadata_json'] else None
        )

    def create(
        self,
        patient_id: str,
        patient_name: str,
        data_directory: Path,
        database_path: Path,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Patient:
        """
        Create new patient in patient_registry.

        Args:
            patient_id: Unique patient identifier
            patient_name: Display name for patient
            data_directory: Path to patient's data folder
            database_path: Path to patient's brainsense_data.db
            metadata: Optional metadata dict (e.g., DOB, diagnosis)

        Returns:
            Patient: Newly created patient

        Raises:
            sqlite3.IntegrityError: If patient_id already exists
            ValueError: If patient_id is invalid
        """
        # Validate patient_id (a new patient: its folder name must work on every OS)
        if not self.path_resolver.validate_new_patient_id(patient_id):
            raise ValueError(f"Invalid patient ID: {patient_id}")

        db_path = self.path_resolver.get_global_db_path()

        query = """
            INSERT INTO patient_registry
            (patient_id, patient_name, data_directory, database_path,
             created_at, updated_at, is_active, metadata_json)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, ?)
        """

        metadata_json = json.dumps(metadata) if metadata else None

        try:
            with self.adapter.transaction(db_path) as conn:
                self._execute_query(conn, query, (
                    patient_id,
                    patient_name,
                    str(data_directory),
                    str(database_path),
                    metadata_json
                ))

            self.logger.info(f"Created patient: {patient_id}")

            # Fetch and return created patient
            return self.get_by_id(patient_id)

        except sqlite3.IntegrityError as e:
            self.logger.error(f"Failed to create patient {patient_id}: {e}")
            raise

    def get_by_id(self, patient_id: str) -> Optional[Patient]:
        """
        Get patient by ID.

        Args:
            patient_id: Patient identifier

        Returns:
            Optional[Patient]: Patient or None if not found
        """
        db_path = self.path_resolver.get_global_db_path()

        query = "SELECT * FROM patient_registry WHERE patient_id = ?"

        with self.adapter.get_connection(db_path) as conn:
            patient = self._fetch_one(conn, query, (patient_id,))

        if patient:
            self.logger.debug(f"Retrieved patient: {patient_id}")
        else:
            self.logger.debug(f"Patient not found: {patient_id}")

        return patient

    def get_all_active(self) -> list[Patient]:
        """
        Get all active patients.

        Returns only patients where is_active = 1, ordered by patient_name.

        Returns:
            list[Patient]: List of active patients (empty if none)
        """
        db_path = self.path_resolver.get_global_db_path()

        query = """
            SELECT * FROM patient_registry
            WHERE is_active = 1
            ORDER BY patient_name
        """

        with self.adapter.get_connection(db_path) as conn:
            patients = self._fetch_all(conn, query)

        self.logger.debug(f"Retrieved {len(patients)} active patients")
        return patients

    def get_all(self) -> list[Patient]:
        """
        Get all patients (including inactive).

        Returns all patients regardless of is_active status, ordered by patient_name.

        Returns:
            list[Patient]: List of all patients (empty if none)
        """
        db_path = self.path_resolver.get_global_db_path()

        query = """
            SELECT * FROM patient_registry
            ORDER BY patient_name
        """

        with self.adapter.get_connection(db_path) as conn:
            patients = self._fetch_all(conn, query)

        self.logger.debug(f"Retrieved {len(patients)} total patients")
        return patients

    def update(
        self,
        patient_id: str,
        patient_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Patient]:
        """
        Update patient information.

        Only updates provided fields. Always updates updated_at timestamp.

        Args:
            patient_id: Patient identifier
            patient_name: New patient name (if provided)
            metadata: New metadata dict (if provided)

        Returns:
            Optional[Patient]: Updated patient or None if not found

        Raises:
            ValueError: If no updates provided
        """
        if patient_name is None and metadata is None:
            raise ValueError("Must provide at least one field to update")

        db_path = self.path_resolver.get_global_db_path()

        # Build dynamic UPDATE query
        updates = []
        params = []

        if patient_name is not None:
            updates.append("patient_name = ?")
            params.append(patient_name)

        if metadata is not None:
            updates.append("metadata_json = ?")
            params.append(json.dumps(metadata))

        # Always update timestamp
        updates.append("updated_at = CURRENT_TIMESTAMP")

        # Add patient_id for WHERE clause
        params.append(patient_id)

        query = f"""
            UPDATE patient_registry
            SET {", ".join(updates)}
            WHERE patient_id = ?
        """

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, tuple(params))

            if rows_affected == 0:
                self.logger.warning(f"Patient not found for update: {patient_id}")
                return None

            self.logger.info(f"Updated patient: {patient_id}")

            # Fetch and return updated patient
            return self.get_by_id(patient_id)

        except sqlite3.Error as e:
            self.logger.error(f"Failed to update patient {patient_id}: {e}")
            raise

    def soft_delete(self, patient_id: str) -> bool:
        """
        Soft delete patient (set is_active = 0).

        Does not actually delete the patient record. Sets is_active to 0
        so the patient won't appear in get_all_active() queries.

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if patient was deleted, False if not found
        """
        db_path = self.path_resolver.get_global_db_path()

        query = """
            UPDATE patient_registry
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE patient_id = ?
        """

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (patient_id,))

            if rows_affected == 0:
                self.logger.warning(f"Patient not found for deletion: {patient_id}")
                return False

            self.logger.info(f"Soft deleted patient: {patient_id}")
            return True

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete patient {patient_id}: {e}")
            raise

    def delete(self, patient_id: str) -> bool:
        """
        Hard delete patient (permanently remove from database).

        Permanently removes the patient record from the patient_registry table.
        This does NOT delete the patient's data files - that must be handled
        by the service layer.

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if patient was deleted, False if not found
        """
        db_path = self.path_resolver.get_global_db_path()

        query = """
            DELETE FROM patient_registry
            WHERE patient_id = ?
        """

        try:
            with self.adapter.transaction(db_path) as conn:
                rows_affected = self._execute_query(conn, query, (patient_id,))

            if rows_affected == 0:
                self.logger.warning(f"Patient not found for deletion: {patient_id}")
                return False

            self.logger.info(f"Hard deleted patient: {patient_id}")
            return True

        except sqlite3.Error as e:
            self.logger.error(f"Failed to delete patient {patient_id}: {e}")
            raise

    def exists(self, patient_id: str) -> bool:
        """
        Check if patient exists.

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if patient exists (regardless of is_active status)
        """
        db_path = self.path_resolver.get_global_db_path()

        query = "SELECT COUNT(*) as count FROM patient_registry WHERE patient_id = ?"

        try:
            with self.adapter.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, (patient_id,))
                row = cursor.fetchone()
                count = row['count']

            exists = count > 0
            self.logger.debug(f"Patient {patient_id} exists: {exists}")
            return exists

        except sqlite3.Error as e:
            self.logger.error(f"Error checking if patient exists: {e}")
            raise
