"""
Unit tests for global database schema.

Tests the global_schema module including:
- Schema SQL validity
- Table creation
- Index creation
- STRICT mode enforcement
- Foreign key constraints
- Data insertion and retrieval
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil

from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema.global_schema import (
    get_global_schema,
    get_table_names,
    get_index_names,
    TABLE_PATIENT_REGISTRY,
    TABLE_APP_SETTINGS,
    TABLE_MIGRATION_HISTORY,
    TABLE_AUDIT_LOG,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def db_path(temp_dir):
    """Create a path for a test database."""
    return temp_dir / "test_global.db"


@pytest.fixture
def adapter():
    """Create a SQLiteAdapter instance."""
    return SQLiteAdapter()


class TestGlobalSchemaSQL:
    """Test the global schema SQL generation."""

    def test_get_global_schema_returns_string(self):
        """Test that get_global_schema returns a string."""
        schema = get_global_schema()
        assert isinstance(schema, str)
        assert len(schema) > 0

    def test_schema_contains_all_tables(self):
        """Test that schema SQL contains all expected table definitions."""
        schema = get_global_schema()

        assert "CREATE TABLE IF NOT EXISTS patient_registry" in schema
        assert "CREATE TABLE IF NOT EXISTS app_settings" in schema
        assert "CREATE TABLE IF NOT EXISTS migration_history" in schema
        assert "CREATE TABLE IF NOT EXISTS audit_log" in schema

    def test_schema_contains_strict_mode(self):
        """Test that all tables use STRICT mode."""
        schema = get_global_schema()

        # Count STRICT keywords
        strict_count = schema.count(") STRICT;")
        assert strict_count == 4, "All 4 tables should use STRICT mode"

    def test_schema_contains_indexes(self):
        """Test that schema contains index definitions."""
        schema = get_global_schema()

        assert "CREATE INDEX IF NOT EXISTS idx_patient_active" in schema
        assert "CREATE INDEX IF NOT EXISTS idx_patient_name" in schema

    def test_get_table_names_returns_list(self):
        """Test that get_table_names returns a list."""
        tables = get_table_names()
        assert isinstance(tables, list)
        assert len(tables) == 4

    def test_get_index_names_returns_list(self):
        """Test that get_index_names returns a list."""
        indexes = get_index_names()
        assert isinstance(indexes, list)
        assert len(indexes) == 2


class TestGlobalSchemaCreation:
    """Test actual schema creation in database."""

    def test_schema_creates_all_tables(self, adapter, db_path):
        """Test that schema creates all 4 tables."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            tables = [row[0] for row in cursor.fetchall()]

        expected = get_table_names()
        assert set(tables) == set(expected)

    def test_schema_creates_indexes(self, adapter, db_path):
        """Test that schema creates all indexes."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='index' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            indexes = [row[0] for row in cursor.fetchall()]

        expected = get_index_names()
        for index_name in expected:
            assert index_name in indexes

    def test_schema_is_idempotent(self, adapter, db_path):
        """Test that schema can be applied multiple times."""
        schema = get_global_schema()

        # Apply schema twice
        adapter.initialize_schema(db_path, schema)
        adapter.initialize_schema(db_path, schema)

        # Verify tables still exist
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            count = cursor.fetchone()[0]

        assert count == 4


class TestPatientRegistryTable:
    """Test patient_registry table structure and constraints."""

    def test_patient_registry_structure(self, adapter, db_path):
        """Test that patient_registry has correct columns."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_PATIENT_REGISTRY})")
            columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'patient_id', 'patient_name', 'data_directory', 'database_path',
            'created_at', 'updated_at', 'is_active', 'metadata_json'
        }
        assert columns == expected_columns

    def test_patient_registry_insert_and_query(self, adapter, db_path):
        """Test inserting and querying patient data."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PATIENT_REGISTRY}
                (patient_id, patient_name, data_directory, database_path)
                VALUES ('PATIENT001', 'Test Patient', '/path/to/data', '/path/to/db.db')
            """)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT patient_id, patient_name FROM {TABLE_PATIENT_REGISTRY}
                WHERE patient_id = 'PATIENT001'
            """)
            result = cursor.fetchone()

        assert result['patient_id'] == 'PATIENT001'
        assert result['patient_name'] == 'Test Patient'

    def test_patient_registry_duplicate_id_rejected(self, adapter, db_path):
        """Test that duplicate patient_id is rejected."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PATIENT_REGISTRY}
                (patient_id, patient_name, data_directory, database_path)
                VALUES ('PATIENT001', 'Test Patient', '/path', '/db.db')
            """)

        # Try to insert duplicate
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_PATIENT_REGISTRY}
                    (patient_id, patient_name, data_directory, database_path)
                    VALUES ('PATIENT001', 'Another Patient', '/path2', '/db2.db')
                """)

    def test_patient_registry_soft_delete(self, adapter, db_path):
        """Test soft delete functionality with is_active flag."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        # Insert patient
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PATIENT_REGISTRY}
                (patient_id, patient_name, data_directory, database_path)
                VALUES ('PATIENT001', 'Test Patient', '/path', '/db.db')
            """)

        # Soft delete
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                UPDATE {TABLE_PATIENT_REGISTRY}
                SET is_active = 0
                WHERE patient_id = 'PATIENT001'
            """)

        # Verify still exists but is_active = 0
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT is_active FROM {TABLE_PATIENT_REGISTRY}
                WHERE patient_id = 'PATIENT001'
            """)
            result = cursor.fetchone()

        assert result['is_active'] == 0


class TestAppSettingsTable:
    """Test app_settings table."""

    def test_app_settings_insert_and_query(self, adapter, db_path):
        """Test inserting and querying settings."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_APP_SETTINGS}
                (setting_key, setting_value, setting_type)
                VALUES ('theme', 'dark', 'string')
            """)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT setting_value, setting_type FROM {TABLE_APP_SETTINGS}
                WHERE setting_key = 'theme'
            """)
            result = cursor.fetchone()

        assert result['setting_value'] == 'dark'
        assert result['setting_type'] == 'string'


class TestMigrationHistoryTable:
    """Test migration_history table."""

    def test_migration_history_initial_entry(self, adapter, db_path):
        """Test that initial schema migration is recorded."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT migration_name, database_target FROM {TABLE_MIGRATION_HISTORY}
                WHERE migration_name = 'initial_schema'
            """)
            result = cursor.fetchone()

        assert result is not None
        assert result['migration_name'] == 'initial_schema'
        assert result['database_target'] == 'global'


class TestAuditLogTable:
    """Test audit_log table and foreign key constraint."""

    def test_audit_log_insert(self, adapter, db_path):
        """Test inserting audit log entries."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        # Insert patient first
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PATIENT_REGISTRY}
                (patient_id, patient_name, data_directory, database_path)
                VALUES ('PATIENT001', 'Test', '/path', '/db.db')
            """)

        # Insert audit log
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_AUDIT_LOG}
                (action_type, patient_id, details_json)
                VALUES ('create_patient', 'PATIENT001', '{{"source": "test"}}')
            """)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT action_type, patient_id FROM {TABLE_AUDIT_LOG}
            """)
            result = cursor.fetchone()

        assert result['action_type'] == 'create_patient'
        assert result['patient_id'] == 'PATIENT001'

    def test_audit_log_foreign_key_constraint(self, adapter, db_path):
        """Test that foreign key to patient_registry is enforced."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        # Try to insert audit log with non-existent patient
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_AUDIT_LOG}
                    (action_type, patient_id)
                    VALUES ('test_action', 'NONEXISTENT')
                """)


class TestStrictMode:
    """Test STRICT mode enforcement."""

    def test_strict_mode_rejects_wrong_types(self, adapter, db_path):
        """Test that STRICT mode rejects values of wrong type."""
        schema = get_global_schema()
        adapter.initialize_schema(db_path, schema)

        # Try to insert text into is_active (should be boolean/integer)
        # Note: SQLite STRICT mode should catch this
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_PATIENT_REGISTRY}
                    (patient_id, patient_name, data_directory, database_path, is_active)
                    VALUES ('PATIENT001', 'Test', '/path', '/db.db', 'invalid_boolean')
                """)
