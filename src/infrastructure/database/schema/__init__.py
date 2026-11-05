"""
Database schema initialization and management.

This module provides high-level functions for initializing and verifying
database schemas. It coordinates between the PathResolver (for getting
database paths), SQLiteAdapter (for executing SQL), and schema definitions
(for getting SQL scripts).

Functions:
    - initialize_global_database: Create global metadata database
    - initialize_patient_database: Create per-patient database
    - verify_schema: Verify that all expected tables exist

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import logging
from pathlib import Path
from typing import List

from src.core.path_resolver import PathResolver
from src.infrastructure.database.adapters.sqlite_adapter import SQLiteAdapter

from .global_schema import (
    get_global_schema,
    get_table_names as get_global_table_names,
    get_index_names as get_global_index_names,
    TABLE_PATIENT_REGISTRY,
    TABLE_APP_SETTINGS,
    TABLE_MIGRATION_HISTORY,
    TABLE_AUDIT_LOG,
)

from .patient_schema import (
    get_patient_schema,
    get_table_names as get_patient_table_names,
    get_index_names as get_patient_index_names,
    TABLE_TIMELINE_DATA,
    TABLE_SNAPSHOT_DATA,
    TABLE_PROCESSING_METADATA,
    TABLE_THERAPY_CHANGES,
    TABLE_INDEFINITE_STREAMING,
    TABLE_DEFINITE_STREAMING,
)

# Streaming tables are now part of patient_schema

logger = logging.getLogger(__name__)


def initialize_global_database(
    adapter: SQLiteAdapter,
    path_resolver: PathResolver
) -> bool:
    """
    Initialize the global metadata database.

    Creates app_metadata.db with all required tables:
    - patient_registry
    - app_settings
    - migration_history
    - audit_log

    The function is idempotent - it can be safely called multiple times.
    Existing tables will not be modified.

    Args:
        adapter: SQLiteAdapter instance for database operations
        path_resolver: PathResolver instance for getting database path

    Returns:
        bool: True if initialization succeeded, False otherwise

    Example:
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> success = initialize_global_database(adapter, resolver)
        >>> assert success
    """
    try:
        # Get database path
        db_path = path_resolver.get_global_db_path()
        logger.info(f"Initializing global database: {db_path}")

        # Get schema SQL
        schema_sql = get_global_schema()

        # Initialize schema
        adapter.initialize_schema(db_path, schema_sql)

        # Verify initialization
        expected_tables = get_global_table_names()
        if not verify_schema(adapter, db_path, expected_tables):
            logger.error("Global database verification failed")
            return False

        logger.info(f"Successfully initialized global database with {len(expected_tables)} tables")
        return True

    except Exception as e:
        logger.error(f"Failed to initialize global database: {e}", exc_info=True)
        return False


def initialize_patient_database(
    adapter: SQLiteAdapter,
    path_resolver: PathResolver,
    patient_id: str
) -> bool:
    """
    Initialize a patient-specific database.

    Creates brainsense_data.db for the specified patient with all required tables:
    - timeline_data
    - snapshot_data
    - processing_metadata
    - therapy_changes

    The function is idempotent - it can be safely called multiple times.
    Existing tables will not be modified.

    Args:
        adapter: SQLiteAdapter instance for database operations
        path_resolver: PathResolver instance for getting database path
        patient_id: Patient identifier (must be valid)

    Returns:
        bool: True if initialization succeeded, False otherwise

    Raises:
        ValueError: If patient_id is invalid

    Example:
        >>> from src.core.path_resolver import PathResolver
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> success = initialize_patient_database(adapter, resolver, "PATIENT001")
        >>> assert success
    """
    try:
        # Validate patient ID
        if not PathResolver.validate_patient_id(patient_id):
            raise ValueError(f"Invalid patient ID: {patient_id}")

        # Ensure patient directory exists
        if not path_resolver.create_patient_directory(patient_id):
            logger.error(f"Failed to create patient directory for {patient_id}")
            return False

        # Get database path
        db_path = path_resolver.get_patient_db_path(patient_id)
        logger.info(f"Initializing patient database: {db_path}")

        # Get schema SQL
        schema_sql = get_patient_schema()

        # Initialize schema
        adapter.initialize_schema(db_path, schema_sql)

        # Verify initialization
        expected_tables = get_patient_table_names()
        if not verify_schema(adapter, db_path, expected_tables):
            logger.error(f"Patient database verification failed for {patient_id}")
            return False

        logger.info(f"Successfully initialized patient database for {patient_id} with {len(expected_tables)} tables (including streaming)")
        return True

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to initialize patient database for {patient_id}: {e}", exc_info=True)
        return False


def verify_schema(
    adapter: SQLiteAdapter,
    db_path: Path,
    expected_tables: List[str]
) -> bool:
    """
    Verify that a database has all expected tables.

    Queries sqlite_master to check that all expected tables exist.
    Does NOT verify table structure - only checks that tables exist.

    Args:
        adapter: SQLiteAdapter instance for database operations
        db_path: Path to database file
        expected_tables: List of table names that should exist

    Returns:
        bool: True if all expected tables exist, False otherwise

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from pathlib import Path
        >>>
        >>> adapter = SQLiteAdapter()
        >>> db_path = Path("/tmp/test.db")
        >>> expected = ["table1", "table2"]
        >>> exists = verify_schema(adapter, db_path, expected)
    """
    try:
        with adapter.get_connection(db_path) as conn:
            cursor = conn.cursor()

            # Query sqlite_master for all table names
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)

            actual_tables = {row[0] for row in cursor.fetchall()}

            # Check that all expected tables exist
            expected_set = set(expected_tables)
            missing_tables = expected_set - actual_tables

            if missing_tables:
                logger.error(f"Missing tables in {db_path}: {missing_tables}")
                return False

            logger.debug(f"Schema verification passed for {db_path}: {len(actual_tables)} tables found")
            return True

    except Exception as e:
        logger.error(f"Schema verification failed for {db_path}: {e}")
        return False


# Export public API
__all__ = [
    # Initialization functions
    'initialize_global_database',
    'initialize_patient_database',
    'verify_schema',

    # Schema getter functions
    'get_global_schema',
    'get_patient_schema',
    'get_global_table_names',
    'get_patient_table_names',
    'get_global_index_names',
    'get_patient_index_names',

    # Global table name constants
    'TABLE_PATIENT_REGISTRY',
    'TABLE_APP_SETTINGS',
    'TABLE_MIGRATION_HISTORY',
    'TABLE_AUDIT_LOG',

    # Patient table name constants (including streaming)
    'TABLE_TIMELINE_DATA',
    'TABLE_SNAPSHOT_DATA',
    'TABLE_PROCESSING_METADATA',
    'TABLE_THERAPY_CHANGES',
    'TABLE_INDEFINITE_STREAMING',
    'TABLE_DEFINITE_STREAMING',
]
