"""
Guards for the root test isolation in tests/conftest.py (plan M0.2).

Every test must resolve the app data root to the session's throwaway directory
and keep preferences in a per-test INI file: never ~/.brainsense_data,
~/Library/Application Support/BrainSenser or the native QSettings plist.
"""

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

import src.domain.effect_size_preference as effect_size_preference
from src.core.path_resolver import default_app_data_dir
from src.domain.models import EffectSizeType

REAL_DATA_ROOTS = (
    Path.home() / ".brainsense_data",
    Path.home() / "Library" / "Application Support" / "BrainSenser",
)


def test_session_data_dir_is_a_throwaway_temp_dir(session_data_dir):
    data_dir = session_data_dir.resolve()

    assert data_dir.is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert data_dir.name.startswith("brainsenser_test_data_")
    for root in REAL_DATA_ROOTS:
        assert not data_dir.is_relative_to(root.resolve())


def test_default_app_data_dir_is_the_session_temp_dir(session_data_dir):
    assert default_app_data_dir().resolve() == session_data_dir.resolve()


def test_container_path_resolver_uses_the_session_temp_dir(session_data_dir):
    from src.infrastructure.container import ApplicationContainer

    resolver = ApplicationContainer().path_resolver()

    assert resolver.base_dir == session_data_dir.resolve()
    assert resolver.get_global_db_path().is_relative_to(session_data_dir.resolve())


@pytest.mark.parametrize("attempt", ["first", "second"])
def test_effect_size_preference_persists_to_a_per_test_ini(attempt, tmp_path_factory):
    settings = effect_size_preference.QSettings(
        effect_size_preference.ORGANIZATION_NAME, effect_size_preference.APPLICATION_NAME
    )
    assert settings.format() == QSettings.Format.IniFormat
    ini_path = Path(settings.fileName())
    assert ini_path.resolve().is_relative_to(tmp_path_factory.getbasetemp().resolve())

    preference = effect_size_preference.EffectSizePreference()
    # Each test gets a fresh INI: whichever attempt runs second would otherwise
    # load the value the other one saved.
    assert preference.get_effect_size() == effect_size_preference.DEFAULT_EFFECT_SIZE
    preference.set_effect_size(EffectSizeType.COHENS_D)

    saved = QSettings(str(ini_path), QSettings.Format.IniFormat)
    assert saved.value(effect_size_preference.SETTINGS_KEY) == EffectSizeType.COHENS_D.value
