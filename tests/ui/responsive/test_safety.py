"""The harness's data-safety helpers. The open guard is exercised in a child
process on a throwaway folder, never on real data."""

import subprocess
import sys

import pytest

from tests.ui.responsive import _safety


def test_never_open_list_covers_real_data_settings_and_export_fixtures():
    paths = set(_safety.never_open_paths())
    home = _safety.real_home()
    assert {home / ".brainsense_data", home / "Library" / "Application Support" / "BrainSenser",
            home / "Library" / "Preferences" / "com.brainsense.iEEG-App.plist"} <= paths
    fixtures = {p.name for p in paths if p.parent == _safety.REPO_ROOT / "tests" / "fixtures"}
    # Every export fixture in this checkout (none in the public repository) is covered.
    present = {p.name for p in (_safety.REPO_ROOT / "tests" / "fixtures").glob("sample_brainsense_*.json")}
    assert present <= fixtures


def test_open_guard_refuses_protected_paths_in_a_child(tmp_path):
    protected, allowed = tmp_path / "protected", tmp_path / "allowed"
    protected.mkdir()
    allowed.mkdir()
    (protected / "data.json").write_text("{}")
    code = "\n".join([
        "import sqlite3, sys",
        f"sys.path.insert(0, {str(_safety.REPO_ROOT)!r})",
        "from tests.ui.responsive import _safety",
        f"_safety.install_open_guard([{str(protected)!r}])",
        f"open({str(allowed / 'ok.txt')!r}, 'w').close()",
        "for attempt in (lambda: open(sys.argv[1] + '/data.json'),",
        "                lambda: sqlite3.connect(sys.argv[1] + '/x.db'),",
        "                lambda: __import__('os').listdir(sys.argv[1])):",
        "    try:",
        "        attempt()",
        "    except PermissionError:",
        "        continue",
        "    sys.exit('not refused')",
    ])
    run = subprocess.run([sys.executable, "-c", code, str(protected)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr or run.stdout
    assert (allowed / "ok.txt").exists() and not (protected / "x.db").exists()


def test_outputs_must_stay_outside_the_checkout(tmp_path):
    with pytest.raises(AssertionError, match="inside the checkout"):
        _safety.check_sandbox_location(_safety.REPO_ROOT / "sweep_out")
    _safety.check_sandbox_location(tmp_path)


def test_assert_inside(tmp_path):
    _safety.assert_inside(tmp_path / "home", tmp_path, "HOME")
    with pytest.raises(AssertionError, match="isolation violated: HOME"):
        _safety.assert_inside(_safety.real_home(), tmp_path, "HOME")
