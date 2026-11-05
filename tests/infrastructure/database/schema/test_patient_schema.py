"""
Unit tests for patient database schema.

Tests the patient_schema module including:
- Schema SQL validity
- Table creation
- Index creation
- STRICT mode enforcement
- Deduplication via data_hash UNIQUE constraints
- Data insertion and retrieval
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil
import json

from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.infrastructure.database.schema.patient_schema import (
    get_patient_schema,
    get_table_names,
    get_index_names,
    TABLE_TIMELINE_DATA,
    TABLE_SNAPSHOT_DATA,
    TABLE_PROCESSING_METADATA,
    TABLE_THERAPY_CHANGES,
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
    return temp_dir / "test_patient.db"


@pytest.fixture
def adapter():
    """Create a SQLiteAdapter instance."""
    return SQLiteAdapter()


class TestPatientSchemaSQL:
    """Test the patient schema SQL generation."""

    def test_get_patient_schema_returns_string(self):
        """Test that get_patient_schema returns a string."""
        schema = get_patient_schema()
        assert isinstance(schema, str)
        assert len(schema) > 0

    def test_schema_contains_all_tables(self):
        """Test that schema SQL contains all expected table definitions."""
        schema = get_patient_schema()

        assert "CREATE TABLE IF NOT EXISTS timeline_data" in schema
        assert "CREATE TABLE IF NOT EXISTS snapshot_data" in schema
        assert "CREATE TABLE IF NOT EXISTS processing_metadata" in schema
        assert "CREATE TABLE IF NOT EXISTS therapy_changes" in schema

    def test_schema_contains_strict_mode(self):
        """Test that all tables use STRICT mode."""
        schema = get_patient_schema()

        # Count STRICT keywords
        strict_count = schema.count(") STRICT;")
        assert strict_count == 4, "All 4 tables should use STRICT mode"

    def test_schema_contains_indexes(self):
        """Test that schema contains index definitions."""
        schema = get_patient_schema()

        # Timeline indexes
        assert "CREATE INDEX IF NOT EXISTS idx_timeline_timestamp" in schema
        assert "CREATE INDEX IF NOT EXISTS idx_timeline_hash" in schema

        # Snapshot indexes
        assert "CREATE INDEX IF NOT EXISTS idx_snapshot_timestamp" in schema
        assert "CREATE INDEX IF NOT EXISTS idx_snapshot_event" in schema

        # Processing indexes
        assert "CREATE INDEX IF NOT EXISTS idx_processing_patient" in schema

    def test_get_table_names_returns_list(self):
        """Test that get_table_names returns a list."""
        tables = get_table_names()
        assert isinstance(tables, list)
        assert len(tables) == 4

    def test_get_index_names_returns_list(self):
        """Test that get_index_names returns a list."""
        indexes = get_index_names()
        assert isinstance(indexes, list)
        assert len(indexes) == 14  # 5 + 4 + 4 + 1


class TestPatientSchemaCreation:
    """Test actual schema creation in database."""

    def test_schema_creates_all_tables(self, adapter, db_path):
        """Test that schema creates all 4 tables."""
        schema = get_patient_schema()
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
        schema = get_patient_schema()
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
        schema = get_patient_schema()

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


class TestTimelineDataTable:
    """Test timeline_data table structure and deduplication."""

    def test_timeline_data_structure(self, adapter, db_path):
        """Test that timeline_data has correct columns."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_TIMELINE_DATA})")
            columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'timestamp', 'unix_timestamp',
            'left_hemisphere', 'right_hemisphere',
            'left_amplitude', 'right_amplitude',
            'left_frequency', 'right_frequency',
            'left_pulse_width', 'right_pulse_width',
            'therapy_status',
            'is_outlier', 'outlier_reason', 'outlier_score',
            'preprocessing_applied', 'preprocessing_timestamp',
            'original_left_hemisphere', 'original_right_hemisphere',
            'source_file', 'session_id', 'segment_id', 'segment_type',
            'data_hash', 'inserted_at', 'updated_at'
        }
        assert columns == expected_columns

    def test_timeline_data_insert_and_query(self, adapter, db_path):
        """Test inserting and querying timeline data."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_TIMELINE_DATA}
                (timestamp, left_hemisphere, right_hemisphere, source_file, data_hash)
                VALUES ('2025-01-01T12:00:00', 100.5, 95.3, 'test.json', 'hash123')
            """)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT timestamp, left_hemisphere FROM {TABLE_TIMELINE_DATA}
                WHERE data_hash = 'hash123'
            """)
            result = cursor.fetchone()

        assert result['timestamp'] == '2025-01-01T12:00:00'
        assert result['left_hemisphere'] == 100.5

    def test_timeline_data_hash_uniqueness(self, adapter, db_path):
        """Test that duplicate data_hash is rejected."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_TIMELINE_DATA}
                (timestamp, source_file, data_hash)
                VALUES ('2025-01-01T12:00:00', 'test.json', 'hash123')
            """)

        # Try to insert duplicate hash
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_TIMELINE_DATA}
                    (timestamp, source_file, data_hash)
                    VALUES ('2025-01-01T12:01:00', 'test.json', 'hash123')
                """)

    def test_timeline_data_insert_or_ignore_deduplication(self, adapter, db_path):
        """Test INSERT OR IGNORE deduplication pattern."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        # Insert first record
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT OR IGNORE INTO {TABLE_TIMELINE_DATA}
                (timestamp, source_file, data_hash)
                VALUES ('2025-01-01T12:00:00', 'test.json', 'hash123')
            """)

        # Try to insert duplicate - should be ignored
        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT OR IGNORE INTO {TABLE_TIMELINE_DATA}
                (timestamp, source_file, data_hash)
                VALUES ('2025-01-01T12:01:00', 'test.json', 'hash123')
            """)

        # Verify only one record exists
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {TABLE_TIMELINE_DATA}")
            count = cursor.fetchone()[0]

        assert count == 1


class TestSnapshotDataTable:
    """Test snapshot_data table structure and deduplication."""

    def test_snapshot_data_structure(self, adapter, db_path):
        """Test that snapshot_data has correct columns."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_SNAPSHOT_DATA})")
            columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'timestamp', 'unix_timestamp',
            'event_type', 'event_subtype', 'event_name',
            'frequency_data', 'power_data', 'fft_output',
            'hemisphere', 'source_file', 'session_id',
            'duration_seconds', 'sampling_rate',
            'patient_event', 'patient_event_id', 'event_notes',
            'therapy_amplitude_left', 'therapy_amplitude_right', 'therapy_frequency',
            'data_hash', 'inserted_at', 'updated_at'
        }
        assert columns == expected_columns

    def test_snapshot_data_insert_with_json(self, adapter, db_path):
        """Test inserting snapshot data with JSON fields."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        freq_data = json.dumps([1.0, 2.0, 3.0, 4.0, 5.0])
        power_data = json.dumps([10.0, 20.0, 30.0, 40.0, 50.0])

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_SNAPSHOT_DATA}
                (timestamp, frequency_data, power_data, source_file, data_hash)
                VALUES ('2025-01-01T12:00:00', ?, ?, 'test.json', 'hash456')
            """, (freq_data, power_data))

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT frequency_data, power_data FROM {TABLE_SNAPSHOT_DATA}
                WHERE data_hash = 'hash456'
            """)
            result = cursor.fetchone()

        # Parse JSON back
        frequencies = json.loads(result['frequency_data'])
        powers = json.loads(result['power_data'])

        assert frequencies == [1.0, 2.0, 3.0, 4.0, 5.0]
        assert powers == [10.0, 20.0, 30.0, 40.0, 50.0]

    def test_snapshot_data_hash_uniqueness(self, adapter, db_path):
        """Test that duplicate data_hash is rejected."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        freq_data = json.dumps([1.0, 2.0])
        power_data = json.dumps([10.0, 20.0])

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_SNAPSHOT_DATA}
                (timestamp, frequency_data, power_data, source_file, data_hash)
                VALUES ('2025-01-01T12:00:00', ?, ?, 'test.json', 'hash456')
            """, (freq_data, power_data))

        # Try to insert duplicate hash
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_SNAPSHOT_DATA}
                    (timestamp, frequency_data, power_data, source_file, data_hash)
                    VALUES ('2025-01-01T12:01:00', ?, ?, 'test.json', 'hash456')
                """, (freq_data, power_data))


class TestProcessingMetadataTable:
    """Test processing_metadata table and constraints."""

    def test_processing_metadata_structure(self, adapter, db_path):
        """Test that processing_metadata has correct columns."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_PROCESSING_METADATA})")
            columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'patient_id', 'file_name', 'file_path', 'file_hash', 'file_size_bytes',
            'timeline_count', 'timeline_original_count',
            'snapshot_count', 'snapshot_original_count',
            'duplicates_skipped', 'outliers_detected',
            'processing_time_seconds', 'extractor_version', 'processing_settings',
            'errors_encountered', 'error_details', 'processed_at'
        }
        assert columns == expected_columns

    def test_processing_metadata_insert(self, adapter, db_path):
        """Test inserting processing metadata."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PROCESSING_METADATA}
                (patient_id, file_name, file_path, file_hash, file_size_bytes,
                 timeline_count, timeline_original_count)
                VALUES ('PATIENT001', 'data.json', '/path/to/data.json', 'filehash123',
                        1024, 100, 120)
            """)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT patient_id, file_name, timeline_count, timeline_original_count
                FROM {TABLE_PROCESSING_METADATA}
                WHERE file_hash = 'filehash123'
            """)
            result = cursor.fetchone()

        assert result['patient_id'] == 'PATIENT001'
        assert result['timeline_count'] == 100
        assert result['timeline_original_count'] == 120

    def test_processing_metadata_file_hash_uniqueness(self, adapter, db_path):
        """Test that duplicate file_hash is rejected."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PROCESSING_METADATA}
                (patient_id, file_name, file_path, file_hash)
                VALUES ('PATIENT001', 'data.json', '/path/to/data.json', 'filehash123')
            """)

        # Try to insert duplicate file_hash
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_PROCESSING_METADATA}
                    (patient_id, file_name, file_path, file_hash)
                    VALUES ('PATIENT001', 'data2.json', '/path/to/data2.json', 'filehash123')
                """)

    def test_processing_metadata_patient_file_uniqueness(self, adapter, db_path):
        """Test that (patient_id, file_name) combination is unique."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_PROCESSING_METADATA}
                (patient_id, file_name, file_path, file_hash)
                VALUES ('PATIENT001', 'data.json', '/path/to/data.json', 'hash1')
            """)

        # Try to insert same patient_id + file_name
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_PROCESSING_METADATA}
                    (patient_id, file_name, file_path, file_hash)
                    VALUES ('PATIENT001', 'data.json', '/different/path/data.json', 'hash2')
                """)


class TestTherapyChangesTable:
    """Test therapy_changes table."""

    def test_therapy_changes_structure(self, adapter, db_path):
        """Test that therapy_changes has correct columns."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({TABLE_THERAPY_CHANGES})")
            columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'timestamp', 'change_type', 'previous_settings', 'new_settings',
            'hemisphere_affected', 'source_file', 'data_hash', 'inserted_at'
        }
        assert columns == expected_columns

    def test_therapy_changes_insert(self, adapter, db_path):
        """Test inserting therapy change data."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        prev_settings = json.dumps({'amplitude': 2.0})
        new_settings = json.dumps({'amplitude': 2.5})

        with adapter.transaction(db_path) as conn:
            conn.execute(f"""
                INSERT INTO {TABLE_THERAPY_CHANGES}
                (timestamp, change_type, previous_settings, new_settings, hemisphere_affected)
                VALUES ('2025-01-01T12:00:00', 'amplitude', ?, ?, 'LEFT')
            """, (prev_settings, new_settings))

        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT change_type, hemisphere_affected FROM {TABLE_THERAPY_CHANGES}
            """)
            result = cursor.fetchone()

        assert result['change_type'] == 'amplitude'
        assert result['hemisphere_affected'] == 'LEFT'


class TestStrictMode:
    """Test STRICT mode enforcement."""

    def test_strict_mode_rejects_wrong_types(self, adapter, db_path):
        """Test that STRICT mode rejects values of wrong type."""
        schema = get_patient_schema()
        adapter.initialize_schema(db_path, schema)

        # Try to insert text into numeric field
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute(f"""
                    INSERT INTO {TABLE_TIMELINE_DATA}
                    (timestamp, left_hemisphere, source_file, data_hash)
                    VALUES ('2025-01-01T12:00:00', 'invalid_number', 'test.json', 'hash')
                """)
