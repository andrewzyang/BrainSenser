"""
Global database schema for app_metadata.db.

This module defines the schema for the application-level database that stores
patient registry, application settings, migration history, and audit logs.

The global database is the SINGLE SOURCE OF TRUTH for patient metadata.
Per-patient databases contain only recording data and reference patients
via foreign keys.

Tables:
    - patient_registry: Core patient information (SINGLE SOURCE OF TRUTH)
    - app_settings: Application configuration
    - migration_history: Database migration tracking
    - audit_log: Action tracking for compliance and debugging

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import logging

logger = logging.getLogger(__name__)

# Table name constants
TABLE_PATIENT_REGISTRY = "patient_registry"
TABLE_APP_SETTINGS = "app_settings"
TABLE_MIGRATION_HISTORY = "migration_history"
TABLE_AUDIT_LOG = "audit_log"

# Index name constants
INDEX_PATIENT_ACTIVE = "idx_patient_active"
INDEX_PATIENT_NAME = "idx_patient_name"


def get_global_schema() -> str:
    """
    Get the complete SQL schema for the global metadata database.

    This schema creates the application-level database structure including:
    - Patient registry (single source of truth for patient data)
    - Application settings
    - Migration tracking
    - Audit logging

    All tables use STRICT mode for type safety. The schema is idempotent
    (can be run multiple times safely) using IF NOT EXISTS clauses.

    Returns:
        str: Complete SQL script to create all tables and indexes

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> db_path = resolver.get_global_db_path()
        >>> adapter.initialize_schema(db_path, get_global_schema())
    """
    return """
-- ============================================================================
-- GLOBAL METADATA DATABASE SCHEMA
-- ============================================================================
-- Purpose: Application-level data storage
-- Location: ~/.brainsense_data/app_metadata.db
-- Version: 1.0
-- Last Updated: 2025-09-30
-- ============================================================================

-- ============================================================================
-- TABLE: patient_registry
-- ============================================================================
-- SINGLE SOURCE OF TRUTH for patient information
--
-- This table stores all patient metadata. Per-patient databases should NOT
-- duplicate this information - they only store recording data and reference
-- patients via foreign keys.
--
-- Soft delete pattern: is_active flag allows "deleting" patients without
-- losing audit trail or breaking foreign key constraints.
-- ============================================================================

CREATE TABLE IF NOT EXISTS patient_registry (
    -- Primary identification
    patient_id TEXT PRIMARY KEY,
    patient_name TEXT NOT NULL,

    -- File system paths
    data_directory TEXT NOT NULL,        -- Path to patient's data folder
    database_path TEXT NOT NULL,         -- Path to patient's brainsense_data.db

    -- Timestamps
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

    -- Soft delete flag
    is_active INTEGER DEFAULT 1,         -- 1 = active, 0 = deleted (boolean)

    -- Extensibility
    metadata_json TEXT                   -- JSON for future fields (DOB, diagnosis, etc.)
) STRICT;

-- Index for filtering active patients (most common query)
CREATE INDEX IF NOT EXISTS idx_patient_active
    ON patient_registry(is_active);

-- Index for searching by name
CREATE INDEX IF NOT EXISTS idx_patient_name
    ON patient_registry(patient_name);


-- ============================================================================
-- TABLE: app_settings
-- ============================================================================
-- Application configuration storage
--
-- Key-value store for application settings. The setting_type field enables
-- type-safe deserialization. Complex settings can be stored as JSON.
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_settings (
    -- Primary key
    setting_key TEXT PRIMARY KEY,

    -- Value and type
    setting_value TEXT NOT NULL,
    setting_type TEXT DEFAULT 'string',  -- 'string', 'int', 'bool', 'json'

    -- Documentation
    description TEXT,

    -- Tracking
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;


-- ============================================================================
-- TABLE: migration_history
-- ============================================================================
-- Database migration tracking
--
-- Tracks which migrations have been applied to which databases. This enables
-- safe schema evolution over time.
--
-- database_target values:
--   - 'global': Migrations for app_metadata.db
--   - 'patient': Migrations for brainsense_data.db
--   - 'streaming': Migrations for streaming_data.db (future)
-- ============================================================================

CREATE TABLE IF NOT EXISTS migration_history (
    -- Primary key
    migration_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Migration identification
    migration_name TEXT NOT NULL UNIQUE,
    migration_version INTEGER NOT NULL,

    -- Target database type
    database_target TEXT NOT NULL,       -- 'global', 'patient', or 'streaming'

    -- Tracking
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;


-- ============================================================================
-- TABLE: audit_log
-- ============================================================================
-- Action audit log for compliance and debugging
--
-- Logs all significant actions related to patients:
--   - Patient creation/deletion
--   - File uploads
--   - Data exports
--   - Settings changes
--
-- The details_json field can store action-specific metadata.
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    -- Primary key
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- When and what
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    action_type TEXT NOT NULL,          -- e.g., 'create_patient', 'upload_file'

    -- Who and where
    patient_id TEXT,                    -- NULL for non-patient actions
    user_id TEXT DEFAULT 'system',      -- Future: actual user tracking

    -- Additional details
    details_json TEXT,                  -- JSON with action-specific data

    -- Foreign key to patient (optional - some actions aren't patient-specific)
    FOREIGN KEY (patient_id) REFERENCES patient_registry(patient_id)
) STRICT;

-- ============================================================================
-- SCHEMA VERSION TRACKING
-- ============================================================================
-- Insert initial schema version into migration_history
-- This ensures we can track schema evolution over time
-- ============================================================================

INSERT OR IGNORE INTO migration_history (migration_name, migration_version, database_target)
VALUES ('initial_schema', 1, 'global');

"""


def get_table_names() -> list[str]:
    """
    Get list of all table names in the global schema.

    Returns:
        list[str]: List of table names

    Example:
        >>> tables = get_table_names()
        >>> assert TABLE_PATIENT_REGISTRY in tables
    """
    return [
        TABLE_PATIENT_REGISTRY,
        TABLE_APP_SETTINGS,
        TABLE_MIGRATION_HISTORY,
        TABLE_AUDIT_LOG,
    ]


def get_index_names() -> list[str]:
    """
    Get list of all index names in the global schema.

    Returns:
        list[str]: List of index names

    Example:
        >>> indexes = get_index_names()
        >>> assert INDEX_PATIENT_ACTIVE in indexes
    """
    return [
        INDEX_PATIENT_ACTIVE,
        INDEX_PATIENT_NAME,
    ]
