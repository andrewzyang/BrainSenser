"""
Unit tests for SQLiteAdapter.

Tests the database adapter layer with in-memory databases to ensure:
- Connection context managers work correctly
- Transaction context managers work correctly
- PRAGMA settings are applied
- Error handling works as expected
- Schema initialization works
"""

import pytest
import sqlite3
from pathlib import Path
import tempfile
import shutil

from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    # Cleanup after test
    shutil.rmtree(temp_path)


@pytest.fixture
def db_path(temp_dir):
    """Create a path for a test database."""
    return temp_dir / "test.db"


@pytest.fixture
def adapter():
    """Create a SQLiteAdapter instance."""
    return SQLiteAdapter()


class TestSQLiteAdapterConnection:
    """Test connection context manager."""

    def test_get_connection_creates_directory(self, adapter, temp_dir):
        """Test that get_connection creates parent directory if needed."""
        db_path = temp_dir / "subdir" / "test.db"
        assert not db_path.parent.exists()

        with adapter.get_connection(db_path) as conn:
            assert conn is not None

        assert db_path.parent.exists()

    def test_get_connection_enables_row_factory(self, adapter, db_path):
        """Test that connections have row_factory enabled."""
        with adapter.get_connection(db_path) as conn:
            assert conn.row_factory == sqlite3.Row

    def test_get_connection_closes_on_exit(self, adapter, db_path):
        """Test that connection is closed after context exit."""
        with adapter.get_connection(db_path) as conn:
            test_conn = conn
            # Connection should be open inside context
            cursor = conn.cursor()
            cursor.execute("SELECT 1")

        # Connection should be closed after context
        with pytest.raises(sqlite3.ProgrammingError):
            test_conn.cursor()

    def test_get_connection_read_operations(self, adapter, db_path):
        """Test that read operations work correctly."""
        # First, create a table and insert data using transaction
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO users (name) VALUES ('Alice')")

        # Now read using get_connection
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM users WHERE id = 1")
            result = cursor.fetchone()
            assert result['name'] == 'Alice'

    def test_get_connection_applies_pragmas(self, adapter, db_path):
        """Test that PRAGMA settings are applied."""
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()

            # Check journal_mode
            cursor.execute("PRAGMA journal_mode")
            result = cursor.fetchone()
            assert result[0] == 'wal'

            # Check foreign_keys
            cursor.execute("PRAGMA foreign_keys")
            result = cursor.fetchone()
            assert result[0] == 1


class TestSQLiteAdapterTransaction:
    """Test transaction context manager."""

    def test_transaction_commits_on_success(self, adapter, db_path):
        """Test that transaction commits when no exception occurs."""
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO users (name) VALUES ('Bob')")

        # Verify data persisted
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            assert count == 1

    def test_transaction_rolls_back_on_exception(self, adapter, db_path):
        """Test that transaction rolls back when exception occurs."""
        # First, create table
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")

        # Now try a transaction that will fail
        try:
            with adapter.transaction(db_path) as conn:
                conn.execute("INSERT INTO users (name) VALUES ('Charlie')")
                # Force an error
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify data was NOT persisted
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            assert count == 0

    def test_transaction_closes_on_exit(self, adapter, db_path):
        """Test that connection is closed after transaction context exit."""
        with adapter.transaction(db_path) as conn:
            test_conn = conn
            conn.execute("CREATE TABLE test (id INTEGER)")

        # Connection should be closed
        with pytest.raises(sqlite3.ProgrammingError):
            test_conn.cursor()

    def test_transaction_enforces_foreign_keys(self, adapter, db_path):
        """Test that foreign key constraints are enforced."""
        with adapter.transaction(db_path) as conn:
            conn.execute("""
                CREATE TABLE parent (
                    id INTEGER PRIMARY KEY
                )
            """)
            conn.execute("""
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER,
                    FOREIGN KEY (parent_id) REFERENCES parent(id)
                )
            """)

        # Try to insert child with non-existent parent
        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")

    def test_transaction_multiple_operations(self, adapter, db_path):
        """Test that multiple operations in a transaction work correctly."""
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance REAL)")
            conn.execute("INSERT INTO accounts (id, balance) VALUES (1, 100.0)")
            conn.execute("INSERT INTO accounts (id, balance) VALUES (2, 50.0)")
            conn.execute("UPDATE accounts SET balance = balance - 10 WHERE id = 1")
            conn.execute("UPDATE accounts SET balance = balance + 10 WHERE id = 2")

        # Verify all operations persisted
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM accounts WHERE id = 1")
            assert cursor.fetchone()[0] == 90.0
            cursor.execute("SELECT balance FROM accounts WHERE id = 2")
            assert cursor.fetchone()[0] == 60.0


class TestSQLiteAdapterSchema:
    """Test schema initialization."""

    def test_initialize_schema_creates_tables(self, adapter, db_path):
        """Test that initialize_schema creates tables correctly."""
        schema_sql = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                title TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """

        adapter.initialize_schema(db_path, schema_sql)

        # Verify tables exist
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN ('users', 'posts')
            """)
            tables = [row[0] for row in cursor.fetchall()]
            assert 'users' in tables
            assert 'posts' in tables

    def test_initialize_schema_idempotent(self, adapter, db_path):
        """Test that initialize_schema can be called multiple times."""
        schema_sql = "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY);"

        # Call twice
        adapter.initialize_schema(db_path, schema_sql)
        adapter.initialize_schema(db_path, schema_sql)

        # Should not raise error
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            # Should have exactly one 'users' table
            assert len([t for t in tables if t[0] == 'users']) == 1


class TestSQLiteAdapterUtilities:
    """Test utility methods."""

    def test_verify_connection_success(self, adapter, db_path):
        """Test verify_connection returns True for valid database."""
        # Create database
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE test (id INTEGER)")

        assert adapter.verify_connection(db_path) is True

    def test_verify_connection_failure(self, adapter, temp_dir):
        """Test verify_connection returns False for invalid path."""
        # A regular file where the parent folder should be: unusable on every OS
        blocker = temp_dir / "not_a_folder"
        blocker.write_text("")
        invalid_path = blocker / "test.db"
        assert adapter.verify_connection(invalid_path) is False

    def test_get_pragma_value(self, adapter, db_path):
        """Test getting PRAGMA values."""
        # Create database first
        with adapter.get_connection(db_path) as conn:
            pass

        # Get journal_mode
        journal_mode = adapter.get_pragma_value(db_path, "journal_mode")
        assert journal_mode.lower() == "wal"

        # Get foreign_keys
        foreign_keys = adapter.get_pragma_value(db_path, "foreign_keys")
        assert foreign_keys == "1"

    def test_get_pragma_value_invalid_pragma(self, adapter, db_path):
        """Test get_pragma_value with invalid PRAGMA name."""
        # Create database first
        with adapter.get_connection(db_path) as conn:
            pass

        # Should return empty string for invalid PRAGMA
        result = adapter.get_pragma_value(db_path, "invalid_pragma_name")
        assert result == ""


class TestSQLiteAdapterConcurrency:
    """Test concurrent access scenarios."""

    def test_concurrent_reads(self, adapter, db_path):
        """Test that multiple concurrent reads work correctly."""
        # Setup test data
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, value INTEGER)")
            conn.execute("INSERT INTO data (value) VALUES (1), (2), (3)")

        # Simulate concurrent reads
        results = []
        for _ in range(3):
            with adapter.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM data")
                results.append(cursor.fetchone()[0])

        assert all(r == 3 for r in results)

    def test_wal_mode_enabled(self, adapter, db_path):
        """Test that WAL mode is enabled for better concurrency."""
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            assert mode.lower() == 'wal'


class TestSQLiteAdapterErrorHandling:
    """Test error handling scenarios."""

    def test_connection_error_propagates(self, adapter):
        """Test that connection errors are propagated correctly."""
        # Use a completely invalid path
        invalid_path = Path("")

        with pytest.raises(Exception):
            with adapter.get_connection(invalid_path) as conn:
                pass

    def test_transaction_error_propagates(self, adapter, db_path):
        """Test that errors in transactions are propagated."""
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")

        with pytest.raises(sqlite3.OperationalError):
            with adapter.transaction(db_path) as conn:
                # Try to select from non-existent table
                conn.execute("SELECT * FROM nonexistent_table")

    def test_integrity_error_propagates(self, adapter, db_path):
        """Test that integrity errors are propagated."""
        with adapter.transaction(db_path) as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO test (id) VALUES (1)")

        with pytest.raises(sqlite3.IntegrityError):
            with adapter.transaction(db_path) as conn:
                # Try to insert duplicate primary key
                conn.execute("INSERT INTO test (id) VALUES (1)")
