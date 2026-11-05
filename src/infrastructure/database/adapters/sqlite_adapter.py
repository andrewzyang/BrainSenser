"""
SQLite database adapter with context managers for connections and transactions.

This module provides the database adapter layer for the iEEG BrainSense Analysis App.
It uses raw SQLite without any ORM, following a simplified design that relies on
SQLite's WAL mode for concurrency.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
import logging
from typing import Generator

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """
    SQLite database adapter with context managers for connections and transactions.

    Simplified design:
    - No connection pooling (SQLite + WAL handles concurrency)
    - Context managers ensure cleanup
    - PRAGMA settings for performance and safety

    Usage:
        # For read operations:
        adapter = SQLiteAdapter()
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ...")
            result = cursor.fetchall()

        # For write operations (transactions):
        with adapter.transaction(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT ...")
            cursor.execute("UPDATE ...")
        # Auto-commits here if no exception
    """

    def __init__(self):
        """Initialize the SQLite adapter with default PRAGMA settings."""
        self._pragma_settings = {
            'journal_mode': 'WAL',         # Write-Ahead Logging for concurrency
            'synchronous': 'NORMAL',       # Fast but safe
            'cache_size': -64000,          # 64MB cache
            'temp_store': 'MEMORY',        # Temp tables in RAM
            'foreign_keys': 'ON',          # Enforce FK constraints
            'busy_timeout': 5000,          # 5s timeout on locks
        }

    @contextmanager
    def get_connection(self, db_path: Path) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection for READ operations.

        Context manager automatically closes connection on exit.

        Args:
            db_path: Path to the SQLite database file

        Yields:
            sqlite3.Connection: Database connection with row_factory set to sqlite3.Row

        Raises:
            sqlite3.OperationalError: If connection cannot be established
            Exception: For other unexpected errors

        Usage:
            with adapter.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ...")
                result = cursor.fetchall()
        """
        conn = None
        try:
            # Ensure database file's directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)

            # Connect
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row  # Enable column access by name

            # Apply PRAGMA settings
            self._apply_pragma_settings(conn)

            yield conn

        except sqlite3.OperationalError as e:
            logger.error(f"Database connection error for {db_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected database error for {db_path}: {e}")
            raise
        finally:
            if conn:
                conn.close()

    @contextmanager
    def transaction(self, db_path: Path) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a transactional database connection for WRITE operations.

        Context manager automatically:
        - Begins transaction
        - Commits on success
        - Rolls back on exception
        - Closes connection

        Args:
            db_path: Path to the SQLite database file

        Yields:
            sqlite3.Connection: Database connection with transaction started

        Raises:
            Exception: Any exception from the transaction block (after rollback)

        Usage:
            with adapter.transaction(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT ...")
                cursor.execute("UPDATE ...")
            # Auto-commits here if no exception
        """
        conn = None
        try:
            # Ensure database file's directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)

            # Connect
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row

            # Apply PRAGMA settings
            self._apply_pragma_settings(conn)

            # Begin transaction
            conn.execute("BEGIN")

            yield conn

            # Commit if no exception
            conn.commit()
            logger.debug(f"Transaction committed: {db_path}")

        except Exception as e:
            if conn:
                conn.rollback()
                logger.warning(f"Transaction rolled back: {db_path} - {e}")
            raise
        finally:
            if conn:
                conn.close()

    def _apply_pragma_settings(self, conn: sqlite3.Connection) -> None:
        """
        Apply performance and safety PRAGMA settings to a connection.

        Args:
            conn: Database connection to configure

        Note:
            Failures to set individual PRAGMAs are logged as warnings but don't
            prevent the connection from being used.
        """
        for pragma, value in self._pragma_settings.items():
            try:
                if isinstance(value, str):
                    conn.execute(f"PRAGMA {pragma}={value}")
                else:
                    conn.execute(f"PRAGMA {pragma}={value}")
            except sqlite3.Error as e:
                logger.warning(f"Failed to set PRAGMA {pragma}={value}: {e}")

    def initialize_schema(self, db_path: Path, schema_sql: str) -> None:
        """
        Initialize database schema.

        Args:
            db_path: Path to database file
            schema_sql: SQL script with CREATE TABLE statements

        Raises:
            Exception: If schema initialization fails

        Note:
            Uses get_connection() instead of transaction() because executescript()
            automatically handles transactions internally (issues COMMIT/BEGIN).

        Usage:
            adapter = SQLiteAdapter()
            schema = "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY);"
            adapter.initialize_schema(db_path, schema)
        """
        with self.get_connection(db_path) as conn:
            conn.executescript(schema_sql)
            logger.info(f"Initialized schema: {db_path}")

    def verify_connection(self, db_path: Path) -> bool:
        """
        Verify that a database connection can be established.

        Args:
            db_path: Path to database file to test

        Returns:
            bool: True if connection successful, False otherwise

        Usage:
            if adapter.verify_connection(db_path):
                print("Database accessible")
        """
        try:
            with self.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Connection verification failed for {db_path}: {e}")
            return False

    def get_pragma_value(self, db_path: Path, pragma_name: str) -> str:
        """
        Get the value of a PRAGMA setting.

        Args:
            db_path: Path to database file
            pragma_name: Name of the PRAGMA to query

        Returns:
            str: Value of the PRAGMA setting, or empty string if query fails

        Usage:
            journal_mode = adapter.get_pragma_value(db_path, "journal_mode")
        """
        try:
            with self.get_connection(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA {pragma_name}")
                result = cursor.fetchone()
                return str(result[0]) if result else ""
        except Exception as e:
            logger.error(f"Failed to get PRAGMA {pragma_name} for {db_path}: {e}")
            return ""
