"""
Per-patient database schema for brainsense_data.db.

This module defines the schema for patient-specific databases that store
all recording data for a single patient. Each patient has their own isolated
database containing timeline data, snapshots, and processing metadata.

The schema implements hash-based deduplication to prevent storing duplicate
recordings across multiple file uploads.

Tables:
    - timeline_data: BrainSense time-domain recordings (LFP, therapy settings)
    - snapshot_data: LFP frequency snapshots (power spectral density)
    - processing_metadata: File upload tracking and statistics
    - therapy_changes: Therapy adjustment tracking

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import logging

logger = logging.getLogger(__name__)

# Table name constants
TABLE_TIMELINE_DATA = "timeline_data"
TABLE_SNAPSHOT_DATA = "snapshot_data"
TABLE_PROCESSING_METADATA = "processing_metadata"
TABLE_THERAPY_CHANGES = "therapy_changes"
TABLE_INDEFINITE_STREAMING = "indefinite_streaming"
TABLE_DEFINITE_STREAMING = "definite_streaming"
TABLE_STREAMING_RECORDINGS = "streaming_recordings"
TABLE_ANNOTATIONS = "annotations"
TABLE_RECORDING_GROUPS = "recording_groups"

# Index name constants
INDEX_TIMELINE_TIMESTAMP = "idx_timeline_timestamp"
INDEX_TIMELINE_UNIX = "idx_timeline_unix"
INDEX_TIMELINE_HASH = "idx_timeline_hash"
INDEX_TIMELINE_SOURCE = "idx_timeline_source"
INDEX_TIMELINE_OUTLIER = "idx_timeline_outlier"

INDEX_SNAPSHOT_TIMESTAMP = "idx_snapshot_timestamp"
INDEX_SNAPSHOT_EVENT = "idx_snapshot_event"
INDEX_SNAPSHOT_PATIENT_EVENT = "idx_snapshot_patient_event"
INDEX_SNAPSHOT_SOURCE = "idx_snapshot_source"

INDEX_PROCESSING_PATIENT = "idx_processing_patient"
INDEX_PROCESSING_FILE_HASH = "idx_processing_file_hash"
INDEX_PROCESSING_DATE = "idx_processing_date"
INDEX_PROCESSING_PATIENT_FILE = "idx_processing_patient_file"

INDEX_THERAPY_TIMESTAMP = "idx_therapy_timestamp"

INDEX_STREAMING_PATIENT = "idx_streaming_patient"
INDEX_STREAMING_DATE = "idx_streaming_date"
INDEX_STREAMING_TRIMMED = "idx_streaming_trimmed"

INDEX_ANNOTATION_RECORDING = "idx_annotation_recording"
INDEX_ANNOTATION_TIMESTAMP = "idx_annotation_timestamp"
INDEX_ANNOTATION_TYPE = "idx_annotation_type"

INDEX_GROUP_PATIENT = "idx_group_patient"
INDEX_GROUP_CRITERIA = "idx_group_criteria"


def get_patient_schema() -> str:
    """
    Get the complete SQL schema for a patient-specific database.

    This schema creates the per-patient database structure including:
    - Timeline data (BrainSense time-domain recordings)
    - Snapshot data (LFP frequency snapshots)
    - Processing metadata (file upload tracking)
    - Therapy changes (therapy adjustment tracking)

    All tables use STRICT mode for type safety and include UNIQUE constraints
    on data_hash fields for automatic deduplication via INSERT OR IGNORE.

    The schema is idempotent (can be run multiple times safely) using
    IF NOT EXISTS clauses.

    Returns:
        str: Complete SQL script to create all tables and indexes

    Example:
        >>> from src.infrastructure.database.adapters import SQLiteAdapter
        >>> from src.core.path_resolver import PathResolver
        >>>
        >>> adapter = SQLiteAdapter()
        >>> resolver = PathResolver()
        >>> db_path = resolver.get_patient_db_path("PATIENT001")
        >>> adapter.initialize_schema(db_path, get_patient_schema())
    """
    return """
-- ============================================================================
-- PER-PATIENT DATABASE SCHEMA
-- ============================================================================
-- Purpose: Recording data storage for ONE patient
-- Location: ~/.brainsense_data/patients/{patient_id}/brainsense_data.db
-- Version: 1.0
-- Last Updated: 2025-09-30
-- ============================================================================

-- ============================================================================
-- TABLE: timeline_data
-- ============================================================================
-- BrainSense time-domain recordings
--
-- Stores continuous LFP recordings with associated therapy settings.
-- Uses data_hash UNIQUE constraint for automatic deduplication.
--
-- Deduplication strategy:
--   - data_hash = SHA256(timestamp + LFP values + therapy settings)
--   - UNIQUE constraint prevents duplicates
--   - Use INSERT OR IGNORE for automatic duplicate prevention
--
-- Quality control:
--   - is_outlier flag for BRAVO-style outlier detection
--   - preprocessing_applied tracks any signal preprocessing
-- ============================================================================

CREATE TABLE IF NOT EXISTS timeline_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timing
    timestamp TEXT NOT NULL,
    unix_timestamp REAL,

    -- LFP Data (microvolts)
    left_hemisphere REAL,
    right_hemisphere REAL,

    -- Therapy Settings
    left_amplitude REAL,
    right_amplitude REAL,
    left_frequency REAL,
    right_frequency REAL,
    left_pulse_width REAL,
    right_pulse_width REAL,
    therapy_status TEXT,

    -- Quality Indicators (BRAVO approach)
    is_outlier INTEGER DEFAULT 0,        -- boolean: 0 = not outlier, 1 = outlier
    outlier_reason TEXT,
    outlier_score REAL,

    -- Preprocessing Tracking
    preprocessing_applied TEXT DEFAULT NULL,        -- JSON: {method: 'OvER', threshold: X}
    preprocessing_timestamp TEXT DEFAULT NULL,
    original_left_hemisphere REAL DEFAULT NULL,
    original_right_hemisphere REAL DEFAULT NULL,

    -- Metadata
    source_file TEXT NOT NULL,           -- Which uploaded file this came from
    session_id TEXT,
    segment_id TEXT,
    segment_type TEXT,

    -- Deduplication
    data_hash TEXT UNIQUE NOT NULL,      -- SHA256 of core physiological data

    -- Timestamps
    inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_timeline_timestamp ON timeline_data(timestamp);
CREATE INDEX IF NOT EXISTS idx_timeline_unix ON timeline_data(unix_timestamp);
CREATE INDEX IF NOT EXISTS idx_timeline_hash ON timeline_data(data_hash);
CREATE INDEX IF NOT EXISTS idx_timeline_source ON timeline_data(source_file);
CREATE INDEX IF NOT EXISTS idx_timeline_outlier ON timeline_data(is_outlier);


-- ============================================================================
-- TABLE: snapshot_data
-- ============================================================================
-- LFP frequency snapshots (power spectral density)
--
-- Stores frequency-domain snapshots of LFP data, typically 30-second windows.
-- Uses data_hash UNIQUE constraint for automatic deduplication.
--
-- Deduplication strategy:
--   - data_hash = SHA256(timestamp + frequency_data + power_data + event info)
--   - UNIQUE constraint prevents duplicates
--   - Use INSERT OR IGNORE for automatic duplicate prevention
--
-- Data storage:
--   - frequency_data, power_data, fft_output stored as JSON TEXT
--   - Enables flexible frequency bin sizes
-- ============================================================================

CREATE TABLE IF NOT EXISTS snapshot_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timing
    timestamp TEXT NOT NULL,
    unix_timestamp REAL,

    -- Event Information
    event_type TEXT,
    event_subtype TEXT,
    event_name TEXT,

    -- Frequency Data (Stored as JSON)
    frequency_data TEXT NOT NULL,        -- JSON array of frequency bins
    power_data TEXT NOT NULL,            -- JSON array of power values
    fft_output TEXT,                     -- JSON with FFT results

    -- Hemisphere
    hemisphere TEXT,                     -- LEFT, RIGHT, or BOTH

    -- Metadata
    source_file TEXT NOT NULL,
    session_id TEXT,
    duration_seconds REAL DEFAULT 30.0,
    sampling_rate REAL,

    -- Patient Events
    patient_event INTEGER DEFAULT 0,     -- boolean: 0 = system event, 1 = patient event
    patient_event_id TEXT,
    event_notes TEXT,

    -- Therapy State at Snapshot Time
    therapy_amplitude_left REAL,
    therapy_amplitude_right REAL,
    therapy_frequency REAL,

    -- Deduplication
    data_hash TEXT UNIQUE NOT NULL,

    -- Timestamps
    inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_snapshot_timestamp ON snapshot_data(timestamp);
CREATE INDEX IF NOT EXISTS idx_snapshot_event ON snapshot_data(event_type);
CREATE INDEX IF NOT EXISTS idx_snapshot_patient_event ON snapshot_data(patient_event);
CREATE INDEX IF NOT EXISTS idx_snapshot_source ON snapshot_data(source_file);


-- ============================================================================
-- TABLE: processing_metadata
-- ============================================================================
-- File upload tracking and statistics
--
-- Tracks each file uploaded for this patient:
--   - Original counts (before deduplication)
--   - Final counts (after deduplication)
--   - Processing time and errors
--
-- Foreign key constraint:
--   - patient_id references global patient_registry
--   - Maintains referential integrity across databases
--
-- Uniqueness constraints:
--   - file_hash: Prevents uploading same file twice
--   - (patient_id, file_name): Prevents uploading same filename twice
-- ============================================================================

CREATE TABLE IF NOT EXISTS processing_metadata (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Patient reference (foreign key to global DB)
    patient_id TEXT NOT NULL,            -- Links to patient_registry.patient_id

    -- File information
    file_name TEXT NOT NULL,             -- Original filename
    file_path TEXT NOT NULL,             -- Full path to stored file
    file_hash TEXT UNIQUE NOT NULL,      -- SHA256 of file for deduplication
    file_size_bytes INTEGER,

    -- Processing Results (for statistics calculation)
    timeline_count INTEGER DEFAULT 0,           -- Records inserted into timeline_data
    timeline_original_count INTEGER DEFAULT 0,  -- Before deduplication
    snapshot_count INTEGER DEFAULT 0,           -- Records inserted into snapshot_data
    snapshot_original_count INTEGER DEFAULT 0,  -- Before deduplication
    indefinite_streaming_count INTEGER DEFAULT 0,           -- Records inserted into streaming DB
    indefinite_streaming_original_count INTEGER DEFAULT 0,  -- Before deduplication
    definite_streaming_count INTEGER DEFAULT 0,             -- Records inserted into streaming DB
    definite_streaming_original_count INTEGER DEFAULT 0,    -- Before deduplication
    duplicates_skipped INTEGER DEFAULT 0,       -- Total duplicates across all types
    outliers_detected INTEGER DEFAULT 0,

    -- Processing Details
    processing_time_seconds REAL,
    extractor_version TEXT,
    processing_settings TEXT,            -- JSON with settings used

    -- Error Tracking
    errors_encountered INTEGER DEFAULT 0,
    error_details TEXT,

    -- Timestamps
    processed_at TEXT DEFAULT CURRENT_TIMESTAMP

    -- Note: patient_id references patient_registry.patient_id in global DB
    -- Foreign key constraint cannot be enforced across database files
    -- Application logic must ensure referential integrity
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_processing_patient ON processing_metadata(patient_id);
CREATE INDEX IF NOT EXISTS idx_processing_file_hash ON processing_metadata(file_hash);
CREATE INDEX IF NOT EXISTS idx_processing_date ON processing_metadata(processed_at);

-- Unique constraint: One patient cannot upload same file twice
CREATE UNIQUE INDEX IF NOT EXISTS idx_processing_patient_file
    ON processing_metadata(patient_id, file_name);


-- ============================================================================
-- TABLE: therapy_changes
-- ============================================================================
-- Therapy adjustment tracking
--
-- Tracks changes to therapy settings over time:
--   - Amplitude adjustments
--   - Frequency adjustments
--   - Pulse width adjustments
--
-- Optional data_hash for deduplication (may be NULL if not needed)
-- ============================================================================

CREATE TABLE IF NOT EXISTS therapy_changes (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timing
    timestamp TEXT NOT NULL,

    -- Change information
    change_type TEXT,                    -- 'amplitude', 'frequency', 'pulse_width'
    previous_settings TEXT,              -- JSON with previous values
    new_settings TEXT,                   -- JSON with new values
    hemisphere_affected TEXT,            -- 'LEFT', 'RIGHT', 'BOTH'

    -- Source
    source_file TEXT,

    -- Deduplication (optional - may be NULL)
    data_hash TEXT UNIQUE,

    -- Timestamps
    inserted_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;

-- Index for chronological queries
CREATE INDEX IF NOT EXISTS idx_therapy_timestamp ON therapy_changes(timestamp);


-- ============================================================================
-- TABLE: indefinite_streaming
-- ============================================================================
-- Continuous streaming waveform data (IndefiniteStreaming)
--
-- Stores long-duration continuous LFP waveforms captured during indefinite
-- streaming sessions. Each record contains:
-- - Waveform data (thousands of samples stored as JSON array)
-- - Timing information (start time, sample rate, ticks)
-- - Channel and gain information
-- - Packet metadata for reconstruction
--
-- Deduplication strategy:
--   - data_hash = SHA256(timestamp + channel + waveform_data)
--   - UNIQUE constraint prevents duplicates
--   - Use INSERT OR IGNORE for automatic duplicate prevention
-- ============================================================================

CREATE TABLE IF NOT EXISTS indefinite_streaming (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timing
    timestamp TEXT NOT NULL,                 -- FirstPacketDateTime (ISO format)
    unix_timestamp REAL,                     -- Unix epoch timestamp

    -- Channel information
    channel TEXT NOT NULL,                   -- ZERO_THREE_LEFT, ONE_TWO_RIGHT, etc
    hemisphere TEXT,                         -- LEFT, RIGHT (derived from channel)

    -- Waveform data (large JSON array)
    waveform_data TEXT NOT NULL,             -- JSON array of voltage samples
    sample_count INTEGER NOT NULL,           -- Number of samples in waveform
    sample_rate INTEGER NOT NULL,            -- SampleRateInHz (typically 250)
    duration_seconds REAL,                   -- Calculated duration

    -- Signal processing
    gain INTEGER,                            -- Gain value for amplitude conversion

    -- Packet reconstruction metadata
    global_sequences TEXT,                   -- Comma-separated packet sequences
    global_packet_sizes TEXT,                -- Comma-separated packet sizes
    ticks_in_mses TEXT,                      -- Comma-separated timing ticks
    pass_info TEXT,                          -- Pass field from JSON

    -- Metadata
    source_file TEXT NOT NULL,               -- Which uploaded file this came from
    session_id TEXT,                         -- Session identifier

    -- Deduplication
    data_hash TEXT UNIQUE NOT NULL,          -- SHA256 of timestamp+channel+waveform

    -- Timestamps
    inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_indefinite_timestamp ON indefinite_streaming(timestamp);
CREATE INDEX IF NOT EXISTS idx_indefinite_channel ON indefinite_streaming(channel);
CREATE INDEX IF NOT EXISTS idx_indefinite_hash ON indefinite_streaming(data_hash);
CREATE INDEX IF NOT EXISTS idx_indefinite_source ON indefinite_streaming(source_file);


-- ============================================================================
-- TABLE: definite_streaming
-- ============================================================================
-- Definite/triggered streaming waveform data (future use)
--
-- Similar to indefinite_streaming but for triggered/event-based streaming.
-- This table is prepared for future use when DefiniteStreaming data is available.
-- ============================================================================

CREATE TABLE IF NOT EXISTS definite_streaming (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timing
    timestamp TEXT NOT NULL,
    unix_timestamp REAL,

    -- Channel information
    channel TEXT NOT NULL,
    hemisphere TEXT,

    -- Waveform data
    waveform_data TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    sample_rate INTEGER NOT NULL,
    duration_seconds REAL,

    -- Signal processing
    gain INTEGER,

    -- Trigger information (specific to definite streaming)
    trigger_type TEXT,                       -- Type of trigger that started recording
    trigger_timestamp TEXT,                  -- When trigger occurred

    -- Packet metadata
    global_sequences TEXT,
    global_packet_sizes TEXT,
    ticks_in_mses TEXT,
    pass_info TEXT,

    -- Metadata
    source_file TEXT NOT NULL,
    session_id TEXT,

    -- Deduplication
    data_hash TEXT UNIQUE NOT NULL,

    -- Timestamps
    inserted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_definite_timestamp ON definite_streaming(timestamp);
CREATE INDEX IF NOT EXISTS idx_definite_channel ON definite_streaming(channel);
CREATE INDEX IF NOT EXISTS idx_definite_hash ON definite_streaming(data_hash);
CREATE INDEX IF NOT EXISTS idx_definite_source ON definite_streaming(source_file);


-- ============================================================================
-- TABLE: streaming_recordings
-- ============================================================================
-- Complete streaming recording files (original or trimmed)
--
-- Represents complete streaming recording files for streaming data management.
-- Tracks original and trimmed recordings with processing metadata.
--
-- Key features:
--   - Tracks complete recording files (not individual waveform segments)
--   - Maintains relationship between original and trimmed recordings
--   - Stores processing steps applied (filters, etc.)
--   - Flexible metadata for recording context
-- ============================================================================

CREATE TABLE IF NOT EXISTS streaming_recordings (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Patient reference
    patient_id TEXT NOT NULL,

    -- File information
    file_path TEXT NOT NULL,                 -- Absolute path to recording file
    original_file_path TEXT,                 -- Path to original if trimmed

    -- Recording timing
    recording_date TEXT NOT NULL,            -- When recording was made (ISO format)
    duration_seconds REAL NOT NULL,          -- Total duration
    start_time TEXT,                         -- Start within original (for trimmed)
    end_time TEXT,                           -- End within original (for trimmed)

    -- Recording type
    is_trimmed INTEGER NOT NULL DEFAULT 0,   -- 0 = original, 1 = trimmed

    -- File metadata
    file_size_bytes INTEGER NOT NULL,
    sampling_rate REAL NOT NULL,
    channel_count INTEGER NOT NULL,
    channel_labels TEXT NOT NULL,            -- JSON array of channel names

    -- Additional metadata
    metadata TEXT NOT NULL,                  -- JSON object (time_of_day, med_state, etc.)
    processing_applied TEXT NOT NULL,        -- JSON array of processing steps

    -- File integrity validation
    file_checksum TEXT,                      -- SHA-256 hash of file contents

    -- Database timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL

    -- Note: patient_id references global DB patient_registry.patient_id
    -- Foreign key constraint not enforced as it's in a different database
    -- Application logic must ensure referential integrity
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_streaming_patient ON streaming_recordings(patient_id);
CREATE INDEX IF NOT EXISTS idx_streaming_date ON streaming_recordings(recording_date);
CREATE INDEX IF NOT EXISTS idx_streaming_trimmed ON streaming_recordings(is_trimmed);


-- ============================================================================
-- TABLE: annotations
-- ============================================================================
-- Clinical annotations for streaming recordings
--
-- Stores clinical event annotations (symptoms, medications, activities) at
-- specific timestamps within streaming recordings.
--
-- Annotation types:
--   - symptom: Clinical symptoms (tremor, dyskinesia, etc.)
--   - medication: Medication administration events
--   - activity: Patient activities
--   - other: Custom annotations
--
-- Metadata flexibility:
--   - Symptom: severity, body_part, frequency, etc.
--   - Medication: dose, route, medication_name, etc.
--   - Activity: activity_type, duration, etc.
-- ============================================================================

CREATE TABLE IF NOT EXISTS annotations (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Recording reference
    recording_id TEXT NOT NULL,

    -- Timing
    timestamp_seconds REAL NOT NULL,         -- Time within recording (seconds from start)

    -- Event classification
    annotation_type TEXT NOT NULL,           -- 'symptom', 'medication', 'activity', 'other'
    label TEXT NOT NULL,                     -- Short label (e.g., "Tremor onset")

    -- Event details
    description TEXT,                        -- Optional detailed description
    severity INTEGER,                        -- Optional 1-10 scale for symptoms

    -- Additional metadata
    metadata TEXT NOT NULL,                  -- JSON object for flexible event data

    -- Database timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    -- Foreign key (cascade delete when recording is deleted)
    FOREIGN KEY (recording_id) REFERENCES streaming_recordings(id) ON DELETE CASCADE
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_annotation_recording ON annotations(recording_id);
CREATE INDEX IF NOT EXISTS idx_annotation_timestamp ON annotations(recording_id, timestamp_seconds);
CREATE INDEX IF NOT EXISTS idx_annotation_type ON annotations(annotation_type);


-- ============================================================================
-- TABLE: recording_groups
-- ============================================================================
-- Recording groups for multi-recording comparison analysis
--
-- Stores groups of streaming recordings for the Streaming Spectrum.
-- Enables comparison of multiple recordings with statistical analysis.
--
-- Group types:
--   - manual: User-created groups
--   - time_of_day: Auto-grouped by recording time
--   - medication_state: Auto-grouped by medication state
--   - custom: Auto-grouped by custom criteria
--
-- Features:
--   - recording_ids: JSON array of streaming_recording IDs
--   - custom_criteria: JSON object with custom grouping rules
--   - color: Hex color code for visualization
-- ============================================================================

CREATE TABLE IF NOT EXISTS recording_groups (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Patient reference
    patient_id TEXT NOT NULL,

    -- Group metadata
    name TEXT NOT NULL,
    description TEXT,

    -- Group composition
    recording_ids TEXT NOT NULL,                 -- JSON array of recording IDs

    -- Grouping information
    grouping_criteria TEXT NOT NULL,             -- 'manual', 'time_of_day', 'medication_state', 'custom'
    custom_criteria TEXT,                        -- JSON object for custom grouping rules

    -- Visualization
    color TEXT NOT NULL DEFAULT '#3498db',       -- Hex color code

    -- Database timestamps
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL

    -- Note: patient_id references global DB patient_registry.patient_id
    -- Foreign key constraint not enforced as it's in a different database
    -- Application logic must ensure referential integrity
) STRICT;

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_group_patient ON recording_groups(patient_id);
CREATE INDEX IF NOT EXISTS idx_group_criteria ON recording_groups(grouping_criteria);

"""


def get_table_names() -> list[str]:
    """
    Get list of all table names in the patient schema.

    Returns:
        list[str]: List of table names

    Example:
        >>> tables = get_table_names()
        >>> assert TABLE_TIMELINE_DATA in tables
    """
    return [
        TABLE_TIMELINE_DATA,
        TABLE_SNAPSHOT_DATA,
        TABLE_PROCESSING_METADATA,
        TABLE_THERAPY_CHANGES,
        TABLE_INDEFINITE_STREAMING,
        TABLE_DEFINITE_STREAMING,
        TABLE_STREAMING_RECORDINGS,
        TABLE_ANNOTATIONS,
        TABLE_RECORDING_GROUPS,
    ]


def get_index_names() -> list[str]:
    """
    Get list of all index names in the patient schema.

    Returns:
        list[str]: List of index names

    Example:
        >>> indexes = get_index_names()
        >>> assert INDEX_TIMELINE_TIMESTAMP in indexes
    """
    return [
        INDEX_TIMELINE_TIMESTAMP,
        INDEX_TIMELINE_UNIX,
        INDEX_TIMELINE_HASH,
        INDEX_TIMELINE_SOURCE,
        INDEX_TIMELINE_OUTLIER,
        INDEX_SNAPSHOT_TIMESTAMP,
        INDEX_SNAPSHOT_EVENT,
        INDEX_SNAPSHOT_PATIENT_EVENT,
        INDEX_SNAPSHOT_SOURCE,
        INDEX_PROCESSING_PATIENT,
        INDEX_PROCESSING_FILE_HASH,
        INDEX_PROCESSING_DATE,
        INDEX_PROCESSING_PATIENT_FILE,
        INDEX_THERAPY_TIMESTAMP,
        INDEX_STREAMING_PATIENT,
        INDEX_STREAMING_DATE,
        INDEX_STREAMING_TRIMMED,
        INDEX_ANNOTATION_RECORDING,
        INDEX_ANNOTATION_TIMESTAMP,
        INDEX_ANNOTATION_TYPE,
        INDEX_GROUP_PATIENT,
        INDEX_GROUP_CRITERIA,
    ]
