"""
Base repository providing common database operations.

This module defines the abstract BaseRepository class that all concrete
repositories should extend. It provides common patterns for:
- Fetching single records
- Fetching multiple records
- Executing queries
- Mapping database rows to model instances

All repositories use the Repository pattern to separate database logic
from business logic and provide type-safe model instances.

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional
import sqlite3
import logging

from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter
from src.core.path_resolver import PathResolver

# Generic type variable for model type
T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """
    Abstract base repository with common database operations.

    All repositories should extend this class and implement
    _map_row_to_model() to convert database rows to models.

    The repository uses Generic[T] for type safety, where T is the
    model type (Patient, UploadedFile, PatientStatistics, etc.).

    Attributes:
        adapter: SQLiteAdapter for database operations
        path_resolver: PathResolver for database paths
        logger: Logger instance for this repository

    Example:
        >>> class MyRepository(BaseRepository[MyModel]):
        ...     def _map_row_to_model(self, row: sqlite3.Row) -> MyModel:
        ...         return MyModel(id=row['id'], name=row['name'])
        ...
        ...     def get_by_id(self, id: int) -> Optional[MyModel]:
        ...         query = "SELECT * FROM my_table WHERE id = ?"
        ...         with self.adapter.get_connection(db_path) as conn:
        ...             return self._fetch_one(conn, query, (id,))
    """

    def __init__(self, adapter: SQLiteAdapter, path_resolver: PathResolver):
        """
        Initialize base repository.

        Args:
            adapter: SQLiteAdapter for database operations
            path_resolver: PathResolver for database paths
        """
        self.adapter = adapter
        self.path_resolver = path_resolver
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def _map_row_to_model(self, row: sqlite3.Row) -> T:
        """
        Convert database row to model instance.

        This method must be implemented by all concrete repositories
        to map database rows to their specific model type.

        Args:
            row: Database row from sqlite3.Row

        Returns:
            T: Model instance of type T

        Example:
            >>> def _map_row_to_model(self, row: sqlite3.Row) -> Patient:
            ...     return Patient(
            ...         patient_id=row['patient_id'],
            ...         patient_name=row['patient_name'],
            ...         ...
            ...     )
        """

    def _fetch_one(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> Optional[T]:
        """
        Fetch single record and map to model.

        Executes query and returns the first result mapped to a model instance.
        Returns None if no record is found.

        Args:
            conn: Database connection
            query: SQL query with ? placeholders
            params: Query parameters tuple

        Returns:
            Optional[T]: Model instance or None if not found

        Raises:
            sqlite3.Error: If database query fails

        Example:
            >>> query = "SELECT * FROM patients WHERE patient_id = ?"
            >>> patient = self._fetch_one(conn, query, ("PATIENT001",))
        """
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()

            if row is None:
                self.logger.debug(f"No record found for query: {query[:50]}...")
                return None

            model = self._map_row_to_model(row)
            self.logger.debug(f"Fetched one record: {type(model).__name__}")
            return model

        except sqlite3.Error as e:
            self.logger.error(f"Database error in _fetch_one: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in _fetch_one: {e}")
            raise

    def _fetch_all(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[T]:
        """
        Fetch all records and map to models.

        Executes query and returns all results mapped to model instances.
        Returns empty list if no records are found.

        Args:
            conn: Database connection
            query: SQL query with ? placeholders
            params: Query parameters tuple

        Returns:
            list[T]: List of model instances (empty if no records)

        Raises:
            sqlite3.Error: If database query fails

        Example:
            >>> query = "SELECT * FROM patients WHERE is_active = ?"
            >>> patients = self._fetch_all(conn, query, (1,))
        """
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            models = [self._map_row_to_model(row) for row in rows]
            self.logger.debug(f"Fetched {len(models)} records")
            return models

        except sqlite3.Error as e:
            self.logger.error(f"Database error in _fetch_all: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in _fetch_all: {e}")
            raise

    def _execute_query(self, conn: sqlite3.Connection, query: str, params: tuple = ()) -> int:
        """
        Execute query and return affected row count.

        Executes INSERT, UPDATE, or DELETE query and returns the number
        of rows affected. Does not commit - use within transaction context.

        Args:
            conn: Database connection
            query: SQL query with ? placeholders
            params: Query parameters tuple

        Returns:
            int: Number of affected rows

        Raises:
            sqlite3.Error: If database query fails

        Example:
            >>> query = "UPDATE patients SET is_active = 0 WHERE patient_id = ?"
            >>> rows_affected = self._execute_query(conn, query, ("PATIENT001",))
        """
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row_count = cursor.rowcount

            self.logger.debug(f"Executed query affecting {row_count} rows")
            return row_count

        except sqlite3.Error as e:
            self.logger.error(f"Database error in _execute_query: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in _execute_query: {e}")
            raise
