"""QSettingsUiPreferences / InMemoryUiPreferences: the UI preference stores (plan §4.7, R8).

Every store here is an IniFormat file in the test's tmp dir; no test constructs
the native store (the root conftest redirects the adapter's default to a
per-test INI, which test_default_store_is_a_per_test_ini guards).
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import src.domain.effect_size_preference as effect_size_preference
import src.infrastructure.preferences.qsettings_ui_preferences as qsettings_ui_preferences
from src.domain.ui_preferences import ShellPreferenceStore, ZoomPreferenceStore
from src.infrastructure.preferences import InMemoryUiPreferences, QSettingsUiPreferences
from src.infrastructure.preferences.qsettings_ui_preferences import (
    GEOMETRY_KEY, SCREEN_KEY, SIDEBAR_KEY, SUGGESTION_DISMISSED_KEY, ZOOM_STEPS_KEY,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = b"\x01\xd9\xd0\xcb\x00\x03\x00\x00\xff"


@pytest.fixture
def ini_path(tmp_path) -> Path:
    return tmp_path / "iEEG-App.ini"


@pytest.fixture
def prefs(ini_path) -> QSettingsUiPreferences:
    return QSettingsUiPreferences(lambda: QSettings(str(ini_path), QSettings.Format.IniFormat))


def raw(ini_path: Path) -> QSettings:
    return QSettings(str(ini_path), QSettings.Format.IniFormat)


# ------------------------------------------------------------------ scope

def test_scope_is_the_effect_size_preference_scope():
    assert (qsettings_ui_preferences.ORGANIZATION_NAME,
            qsettings_ui_preferences.APPLICATION_NAME) == (
        effect_size_preference.ORGANIZATION_NAME, effect_size_preference.APPLICATION_NAME)


def test_native_settings_opens_that_scope(monkeypatch):
    # A fresh copy of the module: the root conftest has redirected native_settings
    # in the imported one. QSettings is replaced, so no store is opened.
    spec = importlib.util.spec_from_file_location("fresh_qsettings_ui_preferences",
                                                  qsettings_ui_preferences.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    opened = []
    monkeypatch.setattr(fresh, "QSettings", lambda *args: opened.append(args))
    fresh.native_settings()
    assert opened == [(effect_size_preference.ORGANIZATION_NAME,
                       effect_size_preference.APPLICATION_NAME)]


def test_default_store_is_a_per_test_ini(tmp_path_factory):
    settings = qsettings_ui_preferences.native_settings()
    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()).resolve().is_relative_to(
        tmp_path_factory.getbasetemp().resolve())

    QSettingsUiPreferences().save_sidebar_preference("icons")
    assert raw(Path(settings.fileName())).value(SIDEBAR_KEY) == "icons"


@pytest.mark.parametrize("attempt", ["first", "second"])
def test_default_store_starts_empty_in_every_test(attempt):
    store = QSettingsUiPreferences()
    assert store.load_zoom_steps() == {} and store.load_sidebar_preference() is None
    store.save_zoom_steps({"Built-in Retina Display": 3})


# ------------------------------------------------------------------ round trips

def test_values_round_trip_under_ui_v1_keys(prefs, ini_path):
    prefs.save_zoom_steps({"Built-in Retina Display": 3, "Écran;=\\ (2)": 0})
    prefs.save_dismissed_suggestions(frozenset({"LG UltraFine", "a,b"}))
    prefs.save_sidebar_preference("icons")
    prefs.save_window_geometry(GEOMETRY, "DELL U2720Q")

    assert sorted(raw(ini_path).allKeys()) == sorted(
        [ZOOM_STEPS_KEY, SUGGESTION_DISMISSED_KEY, SIDEBAR_KEY, GEOMETRY_KEY, SCREEN_KEY])
    assert all(key.startswith("ui/v1/") for key in raw(ini_path).allKeys())
    again = QSettingsUiPreferences(lambda: raw(ini_path))
    assert again.load_zoom_steps() == {"Built-in Retina Display": 3, "Écran;=\\ (2)": 0}
    assert again.load_dismissed_suggestions() == {"LG UltraFine", "a,b"}
    assert again.load_sidebar_preference() == "icons"
    assert again.load_window_geometry() == GEOMETRY
    assert again.load_last_screen() == "DELL U2720Q"


def test_empty_store_loads_defaults(prefs):
    assert prefs.load_zoom_steps() == {}
    assert prefs.load_dismissed_suggestions() == frozenset()
    assert prefs.load_sidebar_preference() is None
    assert prefs.load_window_geometry() is None
    assert prefs.load_last_screen() is None


def test_geometry_is_stored_as_a_byte_array_not_a_pickle(prefs, ini_path):
    prefs.save_window_geometry(GEOMETRY, "DELL U2720Q")
    text = ini_path.read_text(encoding="latin-1")
    assert "@ByteArray(" in text and "PyObjectWrapper" not in text


def test_read_and_written_by_a_process_without_qapplication(prefs, ini_path):
    """L0: the bootstrap reads the store before QApplication exists (and in a new process)."""
    prefs.save_zoom_steps({"air15": 3})
    prefs.save_window_geometry(GEOMETRY, "air15")
    code = (
        "import json, sys\n"
        "from PySide6.QtCore import QCoreApplication, QSettings\n"
        "from src.infrastructure.preferences import QSettingsUiPreferences\n"
        "assert QCoreApplication.instance() is None\n"
        "store = QSettingsUiPreferences(\n"
        "    lambda: QSettings(sys.argv[1], QSettings.Format.IniFormat))\n"
        "steps, screen = store.load_zoom_steps(), store.load_last_screen()\n"
        "store.save_sidebar_preference('labels')\n"
        "assert QCoreApplication.instance() is None\n"
        "print(json.dumps([steps, screen]))\n"
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", code, str(ini_path)], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [{"air15": 3}, "air15"]
    assert QSettingsUiPreferences(lambda: raw(ini_path)).load_sidebar_preference() == "labels"


# ------------------------------------------------------------------ corrupt values

@pytest.mark.parametrize("stored, steps", [
    ("not json", {}),
    ("[1, 2]", {}),
    ('{"A": "3", "B": 2, "C": true, "D": null, "E": 1.5}', {"B": 2}),
    ("", {}),
])
def test_corrupt_zoom_steps_are_ignored(prefs, ini_path, stored, steps):
    settings = raw(ini_path)
    settings.setValue(ZOOM_STEPS_KEY, stored)
    settings.sync()
    assert prefs.load_zoom_steps() == steps


@pytest.mark.parametrize("stored, displays", [
    ("not json", frozenset()),
    ('{"a": 1}', frozenset()),
    ('["a", 3, null]', frozenset({"a"})),
])
def test_corrupt_dismissed_suggestions_are_ignored(prefs, ini_path, stored, displays):
    settings = raw(ini_path)
    settings.setValue(SUGGESTION_DISMISSED_KEY, stored)
    settings.sync()
    assert prefs.load_dismissed_suggestions() == displays


def test_hand_edited_ini_values_are_ignored(prefs, ini_path, caplog):
    # Unquoted commas make QSettings read a string list; @ByteArray is not a string.
    ini_path.write_text(
        "[ui]\n"
        'v1\\zoom_steps={"A": 1, "B": 2}\n'
        "v1\\suggestion_dismissed=a, b\n"
        "v1\\sidebar=@ByteArray(icons)\n"
        "v1\\geometry=plain text\n"
        "v1\\screen=one, two\n",
        encoding="utf-8")
    assert prefs.load_zoom_steps() == {}
    assert prefs.load_dismissed_suggestions() == frozenset()
    assert prefs.load_sidebar_preference() is None
    assert prefs.load_window_geometry() is None
    assert prefs.load_last_screen() is None
    assert "Ignoring unreadable" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="chmod can't make a folder read-only on Windows")
def test_write_failure_is_logged_not_raised(tmp_path, caplog):
    locked_dir = tmp_path / "read-only"
    locked_dir.mkdir()
    locked_dir.chmod(0o500)
    try:
        store = QSettingsUiPreferences(
            lambda: QSettings(str(locked_dir / "iEEG-App.ini"), QSettings.Format.IniFormat))
        store.save_sidebar_preference("icons")
    finally:
        locked_dir.chmod(0o700)
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    assert "Could not save ui/v1/sidebar" in caplog.text


# ------------------------------------------------------------------ ports

@pytest.mark.parametrize("store_type", [QSettingsUiPreferences, InMemoryUiPreferences])
def test_adapters_implement_both_store_ports(store_type):
    store = store_type()
    assert isinstance(store, ZoomPreferenceStore) and isinstance(store, ShellPreferenceStore)


def test_in_memory_store_round_trips_and_hands_out_copies():
    store = InMemoryUiPreferences()
    steps = {"a": 3}
    store.save_zoom_steps(steps)
    steps["b"] = 4
    loaded = store.load_zoom_steps()
    loaded["c"] = 5
    assert store.load_zoom_steps() == {"a": 3}
    store.save_dismissed_suggestions({"x"})
    store.save_sidebar_preference("icons")
    store.save_window_geometry(GEOMETRY, "DELL U2720Q")
    assert store.load_dismissed_suggestions() == frozenset({"x"})
    assert store.load_sidebar_preference() == "icons"
    assert (store.load_window_geometry(), store.load_last_screen()) == (GEOMETRY, "DELL U2720Q")
