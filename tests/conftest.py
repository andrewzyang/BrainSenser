"""
Pytest configuration and shared fixtures for iEEG BrainSense Analysis App.

This file is automatically loaded by pytest and provides fixtures available
to all test modules.
"""

import os

# Force headless Qt rendering so PySide6 widgets work without a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Generator

# Never let a test open the user's real data root (~/.brainsense_data or
# ~/Library/Application Support/BrainSenser): every default PathResolver /
# AppConfig in the session resolves to this throwaway directory instead.
os.environ["BRAINSENSER_DATA_DIR"] = tempfile.mkdtemp(prefix="brainsenser_test_data_")


def _install_session_preferences_fallback() -> None:
    """Point EffectSizePreference's QSettings at a session INI from import time on.

    Module- and session-scoped fixtures run before the per-test autouse fixture
    below, so without this a fixture that builds a MainWindow would still reach
    the native preferences plist. The per-test fixture narrows it further.
    """
    from PySide6.QtCore import QSettings
    import src.domain.effect_size_preference as effect_size_preference

    session_ini = Path(os.environ["BRAINSENSER_DATA_DIR"]) / "qsettings_session.ini"

    def _session_settings(*_args, **_kwargs):
        return QSettings(str(session_ini), QSettings.Format.IniFormat)

    effect_size_preference.QSettings = _session_settings


_install_session_preferences_fallback()


@pytest.fixture(autouse=True)
def _isolate_user_preferences(tmp_path_factory, monkeypatch):
    """Route EffectSizePreference's QSettings to a per-test INI file.

    ``QSettings(org, app)`` always uses the native format (the real macOS
    preferences plist), so the symbol itself is patched; the singleton is reset
    on both sides so no test sees another test's preference.
    """
    from PySide6.QtCore import QSettings
    import src.domain.effect_size_preference as effect_size_preference

    ini_path = tmp_path_factory.mktemp("qsettings") / "iEEG-App.ini"

    def _isolated_settings(*_args, **_kwargs):
        return QSettings(str(ini_path), QSettings.Format.IniFormat)

    monkeypatch.setattr(effect_size_preference, "QSettings", _isolated_settings)
    effect_size_preference.EffectSizePreference.reset_singleton()
    yield
    effect_size_preference.EffectSizePreference.reset_singleton()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """
    Provide a temporary directory for tests.

    The directory is automatically cleaned up after the test completes.

    Yields:
        Path: Temporary directory path

    Example:
        def test_something(temp_dir):
            test_file = temp_dir / "test.txt"
            test_file.write_text("test data")
            assert test_file.exists()
    """
    temp_path = Path(tempfile.mkdtemp())
    try:
        yield temp_path
    finally:
        # Cleanup
        if temp_path.exists():
            shutil.rmtree(temp_path)


@pytest.fixture
def temp_base_dir(temp_dir) -> Path:
    """
    Provide a temporary base directory for PathResolver tests.

    Args:
        temp_dir: Temporary directory fixture

    Returns:
        Path: Base directory for app data

    Example:
        def test_path_resolver(temp_base_dir):
            resolver = PathResolver(base_dir=temp_base_dir)
            assert resolver.base_dir == temp_base_dir
    """
    base = temp_dir / ".brainsense_data_test"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def sample_patient_id() -> str:
    """
    Provide a valid sample patient ID for testing.

    Returns:
        str: Sample patient ID
    """
    return "TEST_20250930_001"


# Markers for test categorization
def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, isolated)"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests (slower)"
    )
    config.addinivalue_line(
        "markers", "database: Tests involving database operations"
    )
    config.addinivalue_line(
        "markers", "security: Security-related tests"
    )
    config.addinivalue_line(
        "markers", "slow: Tests that take >1 second"
    )


# Known-failures gate (tests/_plugins/known_failures.py). Loaded here rather than
# through addopts, so it stays active when a run overrides addopts.
pytest_plugins = ["tests._plugins.known_failures"]

# The throwaway data root set at the top of this file, captured at import.
_SESSION_DATA_DIR = Path(os.environ["BRAINSENSER_DATA_DIR"])


@pytest.fixture(scope="session")
def session_data_dir() -> Path:
    """The data root every default PathResolver / AppConfig resolves to."""
    return _SESSION_DATA_DIR


# Real user state that no test may change. stat() only: never open or list these.
_PROTECTED_PATHS = (
    Path.home() / "Library" / "Preferences" / "com.brainsense.iEEG-App.plist",
    Path.home() / ".brainsense_data",
    Path.home() / "Library" / "Application Support" / "BrainSenser",
)
_PROTECTED_AT_START = pytest.StashKey[dict]()
_PROTECTED_CHANGED = pytest.StashKey[list]()


def _stat_protected_paths() -> dict:
    """(mtime_ns, size) of each protected path, or None if it does not exist."""
    stats = {}
    for path in _PROTECTED_PATHS:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            stats[path] = None
        else:
            stats[path] = (st.st_mtime_ns, st.st_size)
    return stats


def pytest_sessionstart(session):
    session.config.stash[_PROTECTED_AT_START] = _stat_protected_paths()


def pytest_sessionfinish(session):
    """Fail the session if any protected path changed while it ran."""
    before = session.config.stash[_PROTECTED_AT_START]
    changed = [str(path) for path, stat in _stat_protected_paths().items() if stat != before[path]]
    if changed:
        session.config.stash[_PROTECTED_CHANGED] = changed
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter):
    changed = terminalreporter.config.stash.get(_PROTECTED_CHANGED, [])
    if changed:
        terminalreporter.write_sep(
            "=", "real user data changed during the test run", red=True, bold=True
        )
        for path in changed:
            terminalreporter.write_line(f"changed: {path}", red=True)
        terminalreporter.write_line(
            "A test reached the real data root or preferences plist "
            "(or BrainSenser itself ran meanwhile); the session fails."
        )


# The UI-preferences adapter (src/infrastructure/preferences) defaults to the
# same native store as EffectSizePreference, so it is redirected the same way:
# a session INI from import time on, narrowed to a per-test INI.

def _install_session_ui_preferences_fallback() -> None:
    """Point the UI-preferences adapter's default store at a session INI file."""
    from PySide6.QtCore import QSettings
    import src.infrastructure.preferences.qsettings_ui_preferences as qsettings_ui_preferences

    session_ini = Path(os.environ["BRAINSENSER_DATA_DIR"]) / "ui_preferences_session.ini"
    qsettings_ui_preferences.native_settings = (
        lambda: QSettings(str(session_ini), QSettings.Format.IniFormat))


_install_session_ui_preferences_fallback()


@pytest.fixture(autouse=True)
def _isolate_ui_preferences(tmp_path_factory, monkeypatch):
    """Route the UI-preferences adapter's default (native) store to a per-test INI file."""
    from PySide6.QtCore import QSettings
    import src.infrastructure.preferences.qsettings_ui_preferences as qsettings_ui_preferences

    ini_path = tmp_path_factory.mktemp("ui_preferences") / "iEEG-App.ini"
    monkeypatch.setattr(qsettings_ui_preferences, "native_settings",
                        lambda: QSettings(str(ini_path), QSettings.Format.IniFormat))
