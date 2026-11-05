"""
Unit tests for PathResolver.

Tests cover:
    - Path resolution correctness
    - Security validation (path traversal prevention)
    - Edge cases (None, empty, special characters)
    - Directory creation
    - Cross-platform compatibility

Author: iEEG BrainSense Development Team
Last Updated: 2025-09-30
"""

import pytest
from pathlib import Path
from src.core.path_resolver import PathResolver


class TestPathResolverInitialization:
    """Test PathResolver initialization."""

    def test_init_with_default_base_dir(self, monkeypatch, temp_dir):
        """Default base dir is ~/.brainsense_data in development (home redirected)."""
        monkeypatch.delenv("BRAINSENSER_DATA_DIR", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: temp_dir))
        resolver = PathResolver()

        expected_base = temp_dir / ".brainsense_data"
        assert resolver.base_dir == expected_base.resolve()

    def test_data_dir_env_override(self, monkeypatch, temp_dir):
        """BRAINSENSER_DATA_DIR overrides the default data root."""
        override = temp_dir / "override_root"
        monkeypatch.setenv("BRAINSENSER_DATA_DIR", str(override))
        resolver = PathResolver()

        assert resolver.base_dir == override.resolve()

    def test_init_with_custom_base_dir(self, temp_dir):
        """Test initialization with custom base directory."""
        custom_base = temp_dir / "custom_brainsense"
        resolver = PathResolver(base_dir=custom_base)

        assert resolver.base_dir == custom_base.resolve()

    def test_init_with_string_base_dir(self, temp_dir):
        """Test initialization with string path (should convert to Path)."""
        custom_base_str = str(temp_dir / "string_base")
        resolver = PathResolver(base_dir=custom_base_str)

        assert isinstance(resolver.base_dir, Path)
        assert resolver.base_dir == Path(custom_base_str).resolve()

    def test_init_creates_base_directories(self, temp_dir):
        """Test that initialization creates required directories."""
        custom_base = temp_dir / "new_base"
        resolver = PathResolver(base_dir=custom_base)

        # Check base directory created
        assert custom_base.exists()
        assert custom_base.is_dir()

        # Check subdirectories created
        assert (custom_base / "patients").exists()
        assert (custom_base / "backups").exists()

    def test_init_with_invalid_base_dir_type(self):
        """Test initialization with invalid base_dir type raises ValueError."""
        with pytest.raises(ValueError, match="base_dir must be a Path object"):
            PathResolver(base_dir=12345)


class TestPatientIDValidation:
    """Test patient ID validation (security-critical)."""

    @pytest.mark.security
    def test_validate_patient_id_valid_simple(self):
        """Test validation accepts simple valid patient ID."""
        assert PathResolver.validate_patient_id("TEST_001") is True

    @pytest.mark.security
    def test_validate_patient_id_valid_complex(self):
        """Test validation accepts complex but valid patient ID."""
        valid_ids = [
            "PATIENT_20250930_001",
            "TEST-001",
            "A1B2C3",
            "Patient_Sarah_Johnson_001",
            "TEST.001",  # Dots are OK (not ..)
        ]
        for patient_id in valid_ids:
            assert PathResolver.validate_patient_id(patient_id) is True, \
                f"Should accept valid ID: {patient_id}"

    @pytest.mark.security
    def test_validate_patient_id_rejects_path_traversal_double_dot(self):
        """Test validation rejects .. (parent directory traversal)."""
        malicious_ids = [
            "..",
            "../etc/passwd",
            "TEST/../001",
            "..\\windows\\system32",
            "TEST..001",  # Even embedded
        ]
        for patient_id in malicious_ids:
            assert PathResolver.validate_patient_id(patient_id) is False, \
                f"Should reject malicious ID: {patient_id}"

    @pytest.mark.security
    def test_validate_patient_id_rejects_forward_slash(self):
        """Test validation rejects / (directory separator)."""
        assert PathResolver.validate_patient_id("TEST/001") is False
        assert PathResolver.validate_patient_id("/etc/passwd") is False

    @pytest.mark.security
    def test_validate_patient_id_rejects_backslash(self):
        """Test validation rejects \\ (Windows directory separator)."""
        assert PathResolver.validate_patient_id("TEST\\001") is False
        assert PathResolver.validate_patient_id("C:\\Users\\Test") is False

    @pytest.mark.security
    def test_validate_patient_id_rejects_null_byte(self):
        """Test validation rejects null byte (can terminate strings)."""
        assert PathResolver.validate_patient_id("TEST\0001") is False

    @pytest.mark.security
    def test_validate_patient_id_rejects_newline(self):
        """Test validation rejects newline characters."""
        assert PathResolver.validate_patient_id("TEST\n001") is False
        assert PathResolver.validate_patient_id("TEST\r001") is False

    @pytest.mark.security
    def test_validate_patient_id_rejects_tab(self):
        """Test validation rejects tab characters."""
        assert PathResolver.validate_patient_id("TEST\t001") is False

    def test_validate_patient_id_rejects_none(self):
        """Test validation rejects None."""
        assert PathResolver.validate_patient_id(None) is False

    def test_validate_patient_id_rejects_empty_string(self):
        """Test validation rejects empty string."""
        assert PathResolver.validate_patient_id("") is False

    def test_validate_patient_id_rejects_too_long(self):
        """Test validation rejects patient IDs that are too long (>255 chars)."""
        long_id = "A" * 256
        assert PathResolver.validate_patient_id(long_id) is False

    def test_validate_patient_id_accepts_max_length(self):
        """Test validation accepts patient IDs at max length (255 chars)."""
        max_id = "A" * 255
        assert PathResolver.validate_patient_id(max_id) is True

    def test_validate_patient_id_rejects_non_string(self):
        """Test validation rejects non-string types."""
        assert PathResolver.validate_patient_id(12345) is False
        assert PathResolver.validate_patient_id(['TEST', '001']) is False


class TestNewPatientIDValidation:
    """New patients get folder names that work on macOS and Windows alike."""

    def test_accepts_ordinary_ids(self):
        for patient_id in ("TEST_001", "Pt 1", "pilot-week.2", "Ünïcode"):
            assert PathResolver.validate_new_patient_id(patient_id) is True, patient_id

    def test_rejects_windows_forbidden_characters(self):
        for char in '<>:"|?*':
            assert PathResolver.validate_new_patient_id(f"pilot{char}1") is False, char

    def test_rejects_windows_reserved_names(self):
        for patient_id in ("CON", "nul", "Com1", "LPT9", "aux.txt"):
            assert PathResolver.validate_new_patient_id(patient_id) is False, patient_id
        assert PathResolver.validate_new_patient_id("CONSOLE") is True

    def test_rejects_trailing_dot_or_space(self):
        assert PathResolver.validate_new_patient_id("pilot.") is False
        assert PathResolver.validate_new_patient_id("pilot ") is False

    def test_keeps_the_basic_rules(self):
        assert PathResolver.validate_new_patient_id("../etc") is False
        assert PathResolver.validate_new_patient_id("") is False

    def test_existing_ids_stay_readable(self):
        """Reading a patient made before these rules still validates."""
        assert PathResolver.validate_patient_id("pilot: week 1") is True


class TestFrozenDataDir:
    """Where a frozen (PyInstaller) app keeps its data on each OS."""

    @pytest.fixture
    def frozen(self, monkeypatch, temp_dir):
        import sys
        monkeypatch.delenv("BRAINSENSER_DATA_DIR", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(temp_dir), raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: temp_dir))
        return monkeypatch

    def test_windows_uses_localappdata(self, frozen, temp_dir):
        import sys
        from src.core.path_resolver import default_app_data_dir
        frozen.setattr(sys, "platform", "win32")
        frozen.setenv("LOCALAPPDATA", str(temp_dir / "Local"))
        assert default_app_data_dir() == temp_dir / "Local" / "BrainSenser"

    def test_windows_without_localappdata_falls_back_under_home(self, frozen, temp_dir):
        import sys
        from src.core.path_resolver import default_app_data_dir
        frozen.setattr(sys, "platform", "win32")
        frozen.delenv("LOCALAPPDATA", raising=False)
        assert default_app_data_dir() == temp_dir / "AppData" / "Local" / "BrainSenser"

    def test_macos_uses_application_support(self, frozen, temp_dir):
        import sys
        from src.core.path_resolver import default_app_data_dir
        frozen.setattr(sys, "platform", "darwin")
        assert default_app_data_dir() == temp_dir / "Library" / "Application Support" / "BrainSenser"


class TestGlobalDatabasePaths:
    """Test global database path resolution."""

    def test_get_global_db_path(self, temp_base_dir):
        """Test getting global database path."""
        resolver = PathResolver(base_dir=temp_base_dir)

        global_db = resolver.get_global_db_path()
        expected = (temp_base_dir / "app_metadata.db").resolve()

        assert global_db == expected
        assert global_db.parent == temp_base_dir.resolve()


class TestPatientDirectoryPaths:
    """Test patient directory path resolution."""

    def test_get_patient_directory_valid_id(self, temp_base_dir, sample_patient_id):
        """Test getting patient directory with valid ID."""
        resolver = PathResolver(base_dir=temp_base_dir)

        patient_dir = resolver.get_patient_directory(sample_patient_id)
        expected = (temp_base_dir / "patients" / sample_patient_id).resolve()

        assert patient_dir == expected

    def test_get_patient_directory_invalid_id_raises(self, temp_base_dir):
        """Test getting patient directory with invalid ID raises ValueError."""
        resolver = PathResolver(base_dir=temp_base_dir)

        with pytest.raises(ValueError, match="Invalid patient_id"):
            resolver.get_patient_directory("../etc/passwd")

    def test_get_patient_db_path(self, temp_base_dir, sample_patient_id):
        """Test getting patient database path."""
        resolver = PathResolver(base_dir=temp_base_dir)

        patient_db = resolver.get_patient_db_path(sample_patient_id)
        expected = (temp_base_dir / "patients" / sample_patient_id / "brainsense_data.db").resolve()

        assert patient_db == expected

    def test_get_streaming_db_path(self, temp_base_dir, sample_patient_id):
        """Test getting streaming database path."""
        resolver = PathResolver(base_dir=temp_base_dir)

        streaming_db = resolver.get_streaming_db_path(sample_patient_id)
        expected = (temp_base_dir / "patients" / sample_patient_id / "streaming_data.db").resolve()

        assert streaming_db == expected

    def test_get_patient_uploads_directory_creates_dir(self, temp_base_dir, sample_patient_id):
        """Test getting uploads directory creates it if it doesn't exist."""
        resolver = PathResolver(base_dir=temp_base_dir)

        # First, create patient directory
        resolver.create_patient_directory(sample_patient_id)

        # Get uploads directory (should be created automatically)
        uploads_dir = resolver.get_patient_uploads_directory(sample_patient_id)

        expected = (temp_base_dir / "patients" / sample_patient_id / "raw_uploads").resolve()
        assert uploads_dir == expected
        assert uploads_dir.exists()
        assert uploads_dir.is_dir()


class TestBackupPaths:
    """Test backup directory path resolution."""

    def test_get_backup_directory_without_timestamp(self, temp_base_dir):
        """Test getting base backup directory (no timestamp)."""
        resolver = PathResolver(base_dir=temp_base_dir)

        backup_dir = resolver.get_backup_directory()
        expected = (temp_base_dir / "backups").resolve()

        assert backup_dir == expected

    def test_get_backup_directory_with_timestamp(self, temp_base_dir):
        """Test getting backup directory with timestamp."""
        resolver = PathResolver(base_dir=temp_base_dir)
        timestamp = "2025-09-30_143022"

        backup_dir = resolver.get_backup_directory(timestamp)
        expected = (temp_base_dir / "backups" / timestamp).resolve()

        assert backup_dir == expected

    def test_get_global_db_backup_path_creates_dir(self, temp_base_dir):
        """Test getting global DB backup path creates directory."""
        resolver = PathResolver(base_dir=temp_base_dir)
        timestamp = "2025-09-30_143022"

        backup_path = resolver.get_global_db_backup_path(timestamp)

        expected = (temp_base_dir / "backups" / timestamp / "app_metadata.db").resolve()
        assert backup_path == expected
        assert backup_path.parent.exists()  # Directory created

    def test_get_patient_db_backup_path(self, temp_base_dir, sample_patient_id):
        """Test getting patient DB backup path."""
        resolver = PathResolver(base_dir=temp_base_dir)
        timestamp = "2025-09-30_143022"

        backup_path = resolver.get_patient_db_backup_path(sample_patient_id, timestamp)

        expected = (temp_base_dir / "backups" / timestamp / f"{sample_patient_id}_brainsense_data.db").resolve()
        assert backup_path == expected
        assert backup_path.parent.exists()


class TestPatientDirectoryCreation:
    """Test patient directory creation."""

    def test_create_patient_directory_success(self, temp_base_dir, sample_patient_id):
        """Test creating patient directory successfully."""
        resolver = PathResolver(base_dir=temp_base_dir)

        success = resolver.create_patient_directory(sample_patient_id)

        assert success is True

        # Verify directory structure
        patient_dir = temp_base_dir / "patients" / sample_patient_id
        assert patient_dir.exists()
        assert patient_dir.is_dir()

        # Verify uploads subdirectory created
        uploads_dir = patient_dir / "raw_uploads"
        assert uploads_dir.exists()
        assert uploads_dir.is_dir()

    def test_create_patient_directory_invalid_id_raises(self, temp_base_dir):
        """Test creating directory with invalid ID raises ValueError."""
        resolver = PathResolver(base_dir=temp_base_dir)

        with pytest.raises(ValueError, match="Invalid patient_id"):
            resolver.create_patient_directory("../malicious")

    def test_create_patient_directory_idempotent(self, temp_base_dir, sample_patient_id):
        """Test creating directory twice is idempotent (doesn't fail)."""
        resolver = PathResolver(base_dir=temp_base_dir)

        # Create once
        success1 = resolver.create_patient_directory(sample_patient_id)
        assert success1 is True

        # Create again (should not fail)
        success2 = resolver.create_patient_directory(sample_patient_id)
        assert success2 is True


class TestDatabaseInfo:
    """Test database information retrieval."""

    def test_get_database_info_empty_system(self, temp_base_dir):
        """Test getting database info when no databases exist."""
        resolver = PathResolver(base_dir=temp_base_dir)

        info = resolver.get_database_info()

        assert 'base_directory' in info
        # Compare resolved paths since macOS may have /var -> /private/var symlink
        assert Path(info['base_directory']).resolve() == temp_base_dir.resolve()

        assert 'global_database' in info
        assert info['global_database']['exists'] is False
        assert info['global_database']['size_mb'] == 0

        assert 'patient_databases' in info
        assert len(info['patient_databases']) == 0

    def test_get_database_info_with_global_db(self, temp_base_dir):
        """Test getting database info when global DB exists."""
        resolver = PathResolver(base_dir=temp_base_dir)

        # Create fake global database
        global_db = resolver.get_global_db_path()
        global_db.write_text("fake database content")

        info = resolver.get_database_info()

        assert info['global_database']['exists'] is True
        assert info['global_database']['size_mb'] > 0

    def test_get_database_info_with_patient_dbs(self, temp_base_dir):
        """Test getting database info when patient DBs exist."""
        resolver = PathResolver(base_dir=temp_base_dir)

        # Create patient directories and databases
        patient_ids = ["TEST_001", "TEST_002"]
        for patient_id in patient_ids:
            resolver.create_patient_directory(patient_id)
            patient_db = resolver.get_patient_db_path(patient_id)
            patient_db.write_text("fake patient database")

        info = resolver.get_database_info()

        assert len(info['patient_databases']) == 2

        # Verify patient database info
        for patient_db_info in info['patient_databases']:
            assert 'patient_id' in patient_db_info
            assert 'path' in patient_db_info
            assert 'size_mb' in patient_db_info
            assert patient_db_info['patient_id'] in patient_ids
            assert patient_db_info['size_mb'] > 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_patient_id_with_spaces(self, temp_base_dir):
        """Test patient ID with spaces (should be allowed)."""
        resolver = PathResolver(base_dir=temp_base_dir)
        patient_id = "TEST PATIENT 001"

        # Spaces are allowed
        assert resolver.validate_patient_id(patient_id) is True

        # Should be able to create directory
        success = resolver.create_patient_directory(patient_id)
        assert success is True

    def test_patient_id_unicode_characters(self, temp_base_dir):
        """Test patient ID with unicode characters (should be allowed)."""
        resolver = PathResolver(base_dir=temp_base_dir)
        patient_id = "患者_001"  # Chinese characters

        # Unicode should be allowed
        assert resolver.validate_patient_id(patient_id) is True

    def test_multiple_resolvers_same_base_dir(self, temp_base_dir):
        """Test multiple PathResolver instances with same base_dir."""
        resolver1 = PathResolver(base_dir=temp_base_dir)
        resolver2 = PathResolver(base_dir=temp_base_dir)

        # Both should work independently
        assert resolver1.base_dir == resolver2.base_dir
        assert resolver1.get_global_db_path() == resolver2.get_global_db_path()
