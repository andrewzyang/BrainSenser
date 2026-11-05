"""
PathResolver - Centralized path resolution for all database and data files.

This is the SINGLE SOURCE OF TRUTH for all file paths in the application.
All file operations must use PathResolver to prevent path traversal attacks
and ensure consistent directory structure.

Security Considerations:
    - Validates patient IDs to prevent path traversal (../, ./, etc.)
    - Uses Path objects for OS-independent path handling
    - Creates directories with appropriate permissions
    - Logs all directory operations for auditing

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Directory names for the app's writable data root.
APP_DATA_DIR_NAME = ".brainsense_data"          # development + non-macOS frozen
MACOS_APP_SUPPORT_NAME = "BrainSenser"          # ~/Library/Application Support/<name>
WINDOWS_APP_DATA_NAME = "BrainSenser"           # %LOCALAPPDATA%\<name>


def _is_frozen() -> bool:
    """True when running inside a PyInstaller-frozen bundle (sets frozen + _MEIPASS)."""
    import sys
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def default_app_data_dir() -> Path:
    """Writable root for ALL app-generated data (databases, config, backups, uploads).

    SINGLE SOURCE OF TRUTH shared by PathResolver and AppConfig. This must live
    OUTSIDE the application bundle: a frozen .app is read-only when launched from
    a mounted .dmg or a protected /Applications, so writing inside
    ``Contents/Resources`` raises ``OSError(30, 'Read-only file system')``.

    - Frozen on macOS:  ~/Library/Application Support/BrainSenser
    - Frozen on Windows:  %LOCALAPPDATA%\\BrainSenser
    - Development / other frozen:  ~/.brainsense_data
    - ``BRAINSENSER_DATA_DIR`` (set and non-empty) overrides all of these, so
      tests, UI sweeps and demo sessions never open real patient data.
    """
    import os
    import sys
    override = os.environ.get("BRAINSENSER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if _is_frozen() and sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / MACOS_APP_SUPPORT_NAME
    if _is_frozen() and sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / WINDOWS_APP_DATA_NAME
    return Path.home() / APP_DATA_DIR_NAME


class PathResolver:
    """
    Resolves all file paths for databases, patient data, and backups.

    This class ensures consistent directory structure across the application
    and provides security validation for all path operations.

    Directory Structure:
        ~/.brainsense_data/
        ├── app_metadata.db              # Global database
        ├── patients/
        │   └── {patient_id}/
        │       ├── brainsense_data.db   # All patient data (including streaming)
        │       └── raw_uploads/         # Original files
        └── backups/
            └── {timestamp}/             # Backup snapshots

    Usage:
        >>> resolver = PathResolver()
        >>> global_db = resolver.get_global_db_path()
        >>> patient_db = resolver.get_patient_db_path("PATIENT001")

    Args:
        base_dir: Base directory for all app data.
                 Defaults to ~/.brainsense_data

    Attributes:
        base_dir: Path to base directory for all app data

    Example:
        >>> resolver = PathResolver()
        >>> resolver.validate_patient_id("TEST_001")
        True
        >>> resolver.validate_patient_id("../etc/passwd")
        False
    """

    # Class constants for directory/file names
    GLOBAL_DB_NAME = "app_metadata.db"
    PATIENT_DATA_DB_NAME = "brainsense_data.db"
    STREAMING_DATA_DB_NAME = "streaming_data.db"
    PATIENTS_DIR_NAME = "patients"
    BACKUPS_DIR_NAME = "backups"
    RAW_UPLOADS_DIR_NAME = "raw_uploads"

    # Security: Forbidden characters in patient IDs
    FORBIDDEN_CHARS = ['..', '/', '\\', '\0', '\n', '\r', '\t']
    # What Windows also forbids in a folder name. Checked only when a patient is
    # created (validate_new_patient_id), so patients made earlier stay readable.
    NON_PORTABLE_CHARS = ['<', '>', ':', '"', '|', '?', '*']
    WINDOWS_RESERVED_NAMES = frozenset(
        ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)]
        + [f"LPT{i}" for i in range(1, 10)])

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize path resolver.

        Args:
            base_dir: Base directory for all app data.
                     Defaults to ~/.brainsense_data (development)
                     or app bundle location (packaged app)
                     Can be overridden for testing purposes.

        Raises:
            ValueError: If base_dir is not a valid path
        """
        if base_dir is None:
            base_dir = self._get_default_base_dir()

        # Convert to Path if string provided
        if isinstance(base_dir, str):
            base_dir = Path(base_dir)

        if not isinstance(base_dir, Path):
            raise ValueError(f"base_dir must be a Path object, got {type(base_dir)}")

        self.base_dir = base_dir.resolve()  # Resolve to absolute path
        self._ensure_directories()

        logger.info(f"PathResolver initialized with base_dir: {self.base_dir}")

    def _get_default_base_dir(self) -> Path:
        """
        Get default base directory for app data.

        Returns portable app bundle location when frozen (packaged),
        or home directory location during development.

        Returns:
            Path: Default base directory
        """
        import sys
        import os

        # Debug logging
        logger.info(f"=== Path Resolution Debug ===")
        logger.info(f"sys.frozen = {getattr(sys, 'frozen', False)}")
        logger.info(f"sys.executable = {sys.executable}")
        logger.info(f"sys.platform = {sys.platform}")
        logger.info(f"__file__ exists = {hasattr(sys.modules[__name__], '__file__')}")
        logger.info(f"MEIPASS = {getattr(sys, '_MEIPASS', 'Not set')}")

        # Delegate to the shared resolver so PathResolver and AppConfig agree.
        # IMPORTANT: a frozen .app is read-only when run from a mounted .dmg or a
        # protected /Applications, so writable data must NOT live inside the bundle
        # (that raised OSError 30 on '.../Contents/Resources/.brainsense_data').
        base_dir = default_app_data_dir()
        logger.info(f"Resolved writable app data dir: {base_dir}")
        return base_dir

    def _ensure_directories(self) -> None:
        """
        Create base directory structure if it doesn't exist.

        Creates:
            - Base directory
            - Patients directory
            - Backups directory

        Raises:
            OSError: If directory creation fails
        """
        directories = [
            self.base_dir,
            self.base_dir / self.PATIENTS_DIR_NAME,
            self.base_dir / self.BACKUPS_DIR_NAME,
        ]

        for directory in directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured directory exists: {directory}")
            except Exception as e:
                logger.error(f"Failed to create directory {directory}: {e}")
                raise

    # ========== Global Database ==========

    def get_global_db_path(self) -> Path:
        """
        Get path to global metadata database.

        This database contains:
            - patient_registry: All patient metadata
            - app_settings: Application configuration
            - migration_history: Database version tracking

        Returns:
            Path: Absolute path to global database
                 (~/.brainsense_data/app_metadata.db)

        Example:
            >>> resolver = PathResolver()
            >>> db_path = resolver.get_global_db_path()
            >>> print(db_path)
            /Users/user/.brainsense_data/app_metadata.db
        """
        return self.base_dir / self.GLOBAL_DB_NAME

    # ========== Patient Directories ==========

    def get_patient_directory(self, patient_id: str) -> Path:
        """
        Get path to patient's data directory.

        Args:
            patient_id: Patient identifier (must be validated)

        Returns:
            Path: Absolute path to patient directory
                 (~/.brainsense_data/patients/{patient_id}/)

        Raises:
            ValueError: If patient_id is invalid

        Example:
            >>> resolver = PathResolver()
            >>> patient_dir = resolver.get_patient_directory("TEST_001")
            >>> print(patient_dir)
            /Users/user/.brainsense_data/patients/TEST_001
        """
        if not self.validate_patient_id(patient_id):
            raise ValueError(f"Invalid patient_id: {patient_id}")

        return self.base_dir / self.PATIENTS_DIR_NAME / patient_id

    def get_patient_db_path(self, patient_id: str) -> Path:
        """
        Get path to patient's main database.

        This database contains:
            - timeline_data: LFP time-series data
            - snapshot_data: Frequency snapshots
            - processing_metadata: Upload history

        Args:
            patient_id: Patient identifier

        Returns:
            Path: Absolute path to patient database
                 (~/.brainsense_data/patients/{patient_id}/brainsense_data.db)

        Raises:
            ValueError: If patient_id is invalid

        Example:
            >>> resolver = PathResolver()
            >>> db_path = resolver.get_patient_db_path("TEST_001")
            >>> print(db_path)
            /Users/user/.brainsense_data/patients/TEST_001/brainsense_data.db
        """
        return self.get_patient_directory(patient_id) / self.PATIENT_DATA_DB_NAME

    def get_streaming_db_path(self, patient_id: str) -> Path:
        """
        Get path to patient's streaming database.

        Maintains backwards compatibility with legacy components that expect a
        dedicated streaming database file separate from the main patient DB.
        Current implementations store streaming tables alongside other patient
        data, but callers may still rely on this path for migrations or
        on-disk checks.

        Args:
            patient_id: Patient identifier

        Returns:
            Path: Absolute path to streaming database
                 (~/.brainsense_data/patients/{patient_id}/streaming_data.db)

        Raises:
            ValueError: If patient_id is invalid
        """
        return self.get_patient_directory(patient_id) / self.STREAMING_DATA_DB_NAME

    def get_patient_uploads_directory(self, patient_id: str) -> Path:
        """
        Get path to directory for storing original uploaded files.

        Original files are kept for:
            - Reprocessing with updated algorithms
            - Verification of data integrity
            - Backup/archival purposes

        Args:
            patient_id: Patient identifier

        Returns:
            Path: Absolute path to uploads directory
                 (~/.brainsense_data/patients/{patient_id}/raw_uploads/)
                 Directory is created if it doesn't exist.

        Raises:
            ValueError: If patient_id is invalid
            OSError: If directory creation fails

        Example:
            >>> resolver = PathResolver()
            >>> uploads_dir = resolver.get_patient_uploads_directory("TEST_001")
            >>> uploads_dir.exists()
            True
        """
        upload_dir = self.get_patient_directory(patient_id) / self.RAW_UPLOADS_DIR_NAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir

    # ========== Backups ==========

    def get_backup_directory(self, timestamp: Optional[str] = None) -> Path:
        """
        Get path to backup directory.

        Args:
            timestamp: Optional timestamp string (e.g., "2025-09-30_143022")
                      If None, returns base backup directory

        Returns:
            Path: Absolute path to backup directory
                 If timestamp provided: ~/.brainsense_data/backups/{timestamp}/
                 If no timestamp: ~/.brainsense_data/backups/

        Example:
            >>> resolver = PathResolver()
            >>> backup_dir = resolver.get_backup_directory("2025-09-30_143022")
            >>> print(backup_dir)
            /Users/user/.brainsense_data/backups/2025-09-30_143022
        """
        if timestamp:
            return self.base_dir / self.BACKUPS_DIR_NAME / timestamp
        return self.base_dir / self.BACKUPS_DIR_NAME

    def get_global_db_backup_path(self, timestamp: str) -> Path:
        """
        Get path for global database backup.

        Args:
            timestamp: Timestamp string for backup (e.g., "2025-09-30_143022")

        Returns:
            Path: Absolute path to backup file
                 Directory is created if it doesn't exist.

        Raises:
            OSError: If directory creation fails

        Example:
            >>> resolver = PathResolver()
            >>> backup_path = resolver.get_global_db_backup_path("2025-09-30_143022")
        """
        backup_dir = self.get_backup_directory(timestamp)
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir / self.GLOBAL_DB_NAME

    def get_patient_db_backup_path(self, patient_id: str, timestamp: str) -> Path:
        """
        Get path for patient database backup.

        Args:
            patient_id: Patient identifier
            timestamp: Timestamp string for backup

        Returns:
            Path: Absolute path to backup file
                 (~/.brainsense_data/backups/{timestamp}/{patient_id}_brainsense_data.db)
                 Directory is created if it doesn't exist.

        Raises:
            ValueError: If patient_id is invalid
            OSError: If directory creation fails

        Example:
            >>> resolver = PathResolver()
            >>> backup_path = resolver.get_patient_db_backup_path(
            ...     "TEST_001", "2025-09-30_143022"
            ... )
        """
        if not self.validate_patient_id(patient_id):
            raise ValueError(f"Invalid patient_id: {patient_id}")

        backup_dir = self.get_backup_directory(timestamp)
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir / f"{patient_id}_{self.PATIENT_DATA_DB_NAME}"

    # ========== Validation ==========

    @staticmethod
    def validate_patient_id(patient_id: str) -> bool:
        """
        Validate patient ID doesn't contain path traversal characters.

        Security-critical method that prevents path traversal attacks.
        Patient IDs must be safe strings without special characters.

        Args:
            patient_id: Patient identifier to validate

        Returns:
            bool: True if valid, False otherwise

        Validation Rules:
            - Must not be None or empty
            - Must not contain: ..  /  \\  null  newline  carriage return  tab
            - Must be reasonable length (1-255 characters)

        Example:
            >>> PathResolver.validate_patient_id("TEST_001")
            True
            >>> PathResolver.validate_patient_id("../etc/passwd")
            False
            >>> PathResolver.validate_patient_id("TEST/../001")
            False
        """
        # Check for None or empty
        if not patient_id or not isinstance(patient_id, str):
            logger.warning(f"Invalid patient_id: None or empty")
            return False

        # Check for forbidden characters
        if any(char in patient_id for char in PathResolver.FORBIDDEN_CHARS):
            logger.warning(f"Invalid patient_id contains forbidden characters: {patient_id}")
            return False

        # Check length (reasonable bounds)
        if len(patient_id) < 1 or len(patient_id) > 255:
            logger.warning(f"Invalid patient_id length: {len(patient_id)}")
            return False

        return True

    @staticmethod
    def validate_new_patient_id(patient_id: str) -> bool:
        """
        validate_patient_id, plus the rules that keep a new patient's folder
        name valid on every OS, so data moves between macOS and Windows.

        Extra rules: none of  < > : " | ? *, not a Windows reserved name
        (CON, PRN, AUX, NUL, COM1-9, LPT1-9, with or without an extension), and
        no trailing dot or space.

        Example:
            >>> PathResolver.validate_new_patient_id("TEST_001")
            True
            >>> PathResolver.validate_new_patient_id("pilot: week 1")
            False
            >>> PathResolver.validate_new_patient_id("NUL")
            False
        """
        if not PathResolver.validate_patient_id(patient_id):
            return False
        if any(char in patient_id for char in PathResolver.NON_PORTABLE_CHARS):
            logger.warning(f"Patient ID has a character Windows can't use in folder names: {patient_id}")
            return False
        if patient_id.split(".")[0].strip().upper() in PathResolver.WINDOWS_RESERVED_NAMES:
            logger.warning(f"Patient ID is a name Windows reserves: {patient_id}")
            return False
        if patient_id[-1] in ". ":
            logger.warning(f"Patient ID ends with a dot or space: {patient_id!r}")
            return False
        return True

    def create_patient_directory(self, patient_id: str) -> bool:
        """
        Create directory structure for a new patient.

        Creates:
            - Patient directory
            - Raw uploads subdirectory

        Args:
            patient_id: Patient identifier

        Returns:
            bool: True if successful, False otherwise

        Raises:
            ValueError: If patient_id is invalid

        Example:
            >>> resolver = PathResolver()
            >>> success = resolver.create_patient_directory("TEST_001")
            >>> success
            True
        """
        if not self.validate_patient_id(patient_id):
            logger.error(f"Invalid patient ID: {patient_id}")
            raise ValueError(f"Invalid patient_id: {patient_id}")

        try:
            # Create patient directory
            patient_dir = self.get_patient_directory(patient_id)
            patient_dir.mkdir(parents=True, exist_ok=True)

            # Create subdirectories
            self.get_patient_uploads_directory(patient_id)

            logger.info(f"Created patient directory: {patient_dir}")
            return True

        except Exception as e:
            logger.error(f"Failed to create patient directory: {e}")
            return False

    # ========== Utility ==========

    def get_database_info(self) -> Dict[str, Any]:
        """
        Get information about all databases.

        Returns:
            dict: Information about database locations and sizes
                  {
                      'base_directory': str,
                      'global_database': {
                          'path': str,
                          'exists': bool,
                          'size_mb': float
                      },
                      'patient_databases': List[{
                          'patient_id': str,
                          'path': str,
                          'size_mb': float
                      }]
                  }

        Example:
            >>> resolver = PathResolver()
            >>> info = resolver.get_database_info()
            >>> print(info['global_database']['exists'])
            True
        """
        global_db = self.get_global_db_path()

        info = {
            'base_directory': str(self.base_dir),
            'global_database': {
                'path': str(global_db),
                'exists': global_db.exists(),
                'size_mb': global_db.stat().st_size / (1024 * 1024) if global_db.exists() else 0
            },
            'patient_databases': []
        }

        # Scan for patient databases
        patients_dir = self.base_dir / self.PATIENTS_DIR_NAME
        if patients_dir.exists():
            for patient_dir in patients_dir.iterdir():
                if patient_dir.is_dir():
                    db_path = patient_dir / self.PATIENT_DATA_DB_NAME
                    if db_path.exists():
                        info['patient_databases'].append({
                            'patient_id': patient_dir.name,
                            'path': str(db_path),
                            'size_mb': db_path.stat().st_size / (1024 * 1024)
                        })

        return info
