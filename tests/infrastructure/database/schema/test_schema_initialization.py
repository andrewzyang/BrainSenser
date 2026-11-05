"""
Integration tests for schema initialization.

Tests the schema initialization functions that coordinate between:
- PathResolver (for getting database paths)
- SQLiteAdapter (for executing SQL)
- Schema modules (for getting SQL scripts)

Tests both global and patient database initialization.
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema import (
    initialize_global_database,
    initialize_patient_database,
    verify_schema,
    get_global_table_names,
    get_patient_table_names,
    TABLE_PATIENT_REGISTRY,
    TABLE_TIMELINE_DATA,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def path_resolver(temp_dir):
    """Create a PathResolver with temporary base directory."""
    return PathResolver(base_dir=temp_dir)


@pytest.fixture
def adapter():
    """Create a SQLiteAdapter instance."""
    return SQLiteAdapter()


class TestInitializeGlobalDatabase:
    """Test global database initialization."""

    def test_initialize_global_database_success(self, adapter, path_resolver):
        """Test successful global database initialization."""
        result = initialize_global_database(adapter, path_resolver)
        assert result is True

        # Verify database exists
        db_path = path_resolver.get_global_db_path()
        assert db_path.exists()

    def test_initialize_global_database_creates_all_tables(self, adapter, path_resolver):
        """Test that all expected tables are created."""
        initialize_global_database(adapter, path_resolver)

        db_path = path_resolver.get_global_db_path()
        expected_tables = get_global_table_names()

        # Verify all tables exist
        assert verify_schema(adapter, db_path, expected_tables)

    def test_initialize_global_database_is_idempotent(self, adapter, path_resolver):
        """Test that initialization can be called multiple times safely."""
        # Initialize twice
        result1 = initialize_global_database(adapter, path_resolver)
        result2 = initialize_global_database(adapter, path_resolver)

        assert result1 is True
        assert result2 is True

        # Verify tables still exist
        db_path = path_resolver.get_global_db_path()
        expected_tables = get_global_table_names()
        assert verify_schema(adapter, db_path, expected_tables)

    def test_initialize_global_database_creates_migration_entry(self, adapter, path_resolver):
        """Test that initial migration is recorded."""
        initialize_global_database(adapter, path_resolver)

        db_path = path_resolver.get_global_db_path()
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM migration_history
                WHERE migration_name = 'initial_schema'
            """)
            count = cursor.fetchone()[0]

        assert count >= 1

    def test_initialize_global_database_enables_foreign_keys(self, adapter, path_resolver):
        """Test that foreign keys are enabled after initialization."""
        initialize_global_database(adapter, path_resolver)

        db_path = path_resolver.get_global_db_path()
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys")
            result = cursor.fetchone()[0]

        assert result == 1


class TestInitializePatientDatabase:
    """Test patient database initialization."""

    def test_initialize_patient_database_success(self, adapter, path_resolver):
        """Test successful patient database initialization."""
        patient_id = "TEST_PATIENT_001"
        result = initialize_patient_database(adapter, path_resolver, patient_id)
        assert result is True

        # Verify database exists
        db_path = path_resolver.get_patient_db_path(patient_id)
        assert db_path.exists()

    def test_initialize_patient_database_creates_all_tables(self, adapter, path_resolver):
        """Test that all expected tables are created."""
        patient_id = "TEST_PATIENT_001"
        initialize_patient_database(adapter, path_resolver, patient_id)

        db_path = path_resolver.get_patient_db_path(patient_id)
        expected_tables = get_patient_table_names()

        # Verify all tables exist
        assert verify_schema(adapter, db_path, expected_tables)

    def test_initialize_patient_database_creates_directory(self, adapter, path_resolver):
        """Test that patient directory is created."""
        patient_id = "TEST_PATIENT_001"
        patient_dir = path_resolver.get_patient_directory(patient_id)

        # Directory shouldn't exist yet
        if patient_dir.exists():
            shutil.rmtree(patient_dir)

        initialize_patient_database(adapter, path_resolver, patient_id)

        # Directory should now exist
        assert patient_dir.exists()
        assert patient_dir.is_dir()

    def test_initialize_patient_database_is_idempotent(self, adapter, path_resolver):
        """Test that initialization can be called multiple times safely."""
        patient_id = "TEST_PATIENT_001"

        # Initialize twice
        result1 = initialize_patient_database(adapter, path_resolver, patient_id)
        result2 = initialize_patient_database(adapter, path_resolver, patient_id)

        assert result1 is True
        assert result2 is True

        # Verify tables still exist
        db_path = path_resolver.get_patient_db_path(patient_id)
        expected_tables = get_patient_table_names()
        assert verify_schema(adapter, db_path, expected_tables)

    def test_initialize_patient_database_invalid_id_raises(self, adapter, path_resolver):
        """Test that invalid patient ID raises ValueError."""
        invalid_ids = ["../etc/passwd", "patient/id", "patient\nid", ""]

        for invalid_id in invalid_ids:
            with pytest.raises(ValueError):
                initialize_patient_database(adapter, path_resolver, invalid_id)

    def test_initialize_patient_database_multiple_patients(self, adapter, path_resolver):
        """Test initializing databases for multiple patients."""
        patient_ids = ["PATIENT_A", "PATIENT_B", "PATIENT_C"]

        for patient_id in patient_ids:
            result = initialize_patient_database(adapter, path_resolver, patient_id)
            assert result is True

        # Verify all databases exist and have correct tables
        for patient_id in patient_ids:
            db_path = path_resolver.get_patient_db_path(patient_id)
            assert db_path.exists()
            expected_tables = get_patient_table_names()
            assert verify_schema(adapter, db_path, expected_tables)


class TestVerifySchema:
    """Test schema verification function."""

    def test_verify_schema_returns_true_for_complete_schema(self, adapter, path_resolver):
        """Test that verify_schema returns True when all tables exist."""
        initialize_global_database(adapter, path_resolver)

        db_path = path_resolver.get_global_db_path()
        expected_tables = get_global_table_names()

        assert verify_schema(adapter, db_path, expected_tables) is True

    def test_verify_schema_returns_false_for_incomplete_schema(self, adapter, temp_dir):
        """Test that verify_schema returns False when tables are missing."""
        db_path = temp_dir / "incomplete.db"

        # Create empty database
        with adapter.get_connection(db_path) as conn:
            pass

        expected_tables = get_global_table_names()
        assert verify_schema(adapter, db_path, expected_tables) is False

    def test_verify_schema_returns_false_for_nonexistent_db(self, adapter, temp_dir):
        """Test that verify_schema handles nonexistent database."""
        db_path = temp_dir / "nonexistent.db"
        expected_tables = ["table1", "table2"]

        result = verify_schema(adapter, db_path, expected_tables)
        assert result is False

    def test_verify_schema_empty_table_list(self, adapter, temp_dir):
        """Test verify_schema with empty table list."""
        db_path = temp_dir / "empty.db"

        # Create empty database
        with adapter.get_connection(db_path) as conn:
            pass

        # Verify with empty list should return True
        assert verify_schema(adapter, db_path, []) is True


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""

    def test_complete_database_setup_workflow(self, adapter, path_resolver):
        """Test complete workflow: initialize global DB, then patient DB."""
        # Step 1: Initialize global database
        global_success = initialize_global_database(adapter, path_resolver)
        assert global_success is True

        # Step 2: Initialize patient database
        patient_id = "PATIENT_001"
        patient_success = initialize_patient_database(adapter, path_resolver, patient_id)
        assert patient_success is True

        # Step 3: Verify both databases are accessible
        global_db_path = path_resolver.get_global_db_path()
        patient_db_path = path_resolver.get_patient_db_path(patient_id)

        assert adapter.verify_connection(global_db_path)
        assert adapter.verify_connection(patient_db_path)

    def test_patient_data_references_global_patient(self, adapter, path_resolver):
        """Test that patient database can reference global patient registry."""
        # Initialize both databases
        initialize_global_database(adapter, path_resolver)
        patient_id = "PATIENT_001"
        initialize_patient_database(adapter, path_resolver, patient_id)

        # Insert patient into global registry
        global_db_path = path_resolver.get_global_db_path()
        with adapter.transaction(global_db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PATIENT_REGISTRY}
                (patient_id, patient_name, data_directory, database_path)
                VALUES (?, 'Test Patient', '/path', '/path/db.db')
            """, (patient_id,))

        # Insert processing metadata in patient database
        patient_db_path = path_resolver.get_patient_db_path(patient_id)
        with adapter.transaction(patient_db_path) as conn:
            conn.execute("""
                INSERT INTO processing_metadata
                (patient_id, file_name, file_path, file_hash)
                VALUES (?, 'test.json', '/path/test.json', 'hash123')
            """, (patient_id,))

        # Verify data was inserted
        with adapter.get_connection(patient_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT patient_id FROM processing_metadata
            """)
            result = cursor.fetchone()

        assert result['patient_id'] == patient_id

    def test_multiple_patients_independent_databases(self, adapter, path_resolver):
        """Test that multiple patients have independent databases."""
        # Initialize global database
        initialize_global_database(adapter, path_resolver)

        # Initialize multiple patient databases
        patients = ["PATIENT_A", "PATIENT_B", "PATIENT_C"]
        for patient_id in patients:
            initialize_patient_database(adapter, path_resolver, patient_id)

        # Insert different data into each patient database
        for i, patient_id in enumerate(patients):
            patient_db_path = path_resolver.get_patient_db_path(patient_id)
            with adapter.transaction(patient_db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_TIMELINE_DATA}
                    (timestamp, source_file, data_hash)
                    VALUES ('2025-01-0{i+1}T12:00:00', 'test.json', 'hash_{i}')
                """)

        # Verify each database has only its own data
        for i, patient_id in enumerate(patients):
            patient_db_path = path_resolver.get_patient_db_path(patient_id)
            with adapter.get_connection(patient_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {TABLE_TIMELINE_DATA}")
                count = cursor.fetchone()[0]

            assert count == 1  # Each database should have only one record


class TestErrorHandling:
    """Test error handling in initialization functions."""

    def test_initialize_patient_database_validates_patient_id(self, adapter, path_resolver):
        """Test that patient ID validation works."""
        with pytest.raises(ValueError, match="Invalid patient ID"):
            initialize_patient_database(adapter, path_resolver, "../etc/passwd")

    def test_initialize_global_database_logs_errors(self, adapter, path_resolver, caplog):
        """Test that errors are logged appropriately."""
        import logging

        with caplog.at_level(logging.INFO):
            initialize_global_database(adapter, path_resolver)

        # Check that success message was logged
        assert any("Successfully initialized global database" in record.message
                   for record in caplog.records)
