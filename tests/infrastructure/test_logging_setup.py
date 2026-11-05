"""
Tests for ``src.infrastructure.logging_setup``: the rotating log file under
``<data dir>/logs`` that error dialogs point to.

Every test points ``BRAINSENSER_DATA_DIR`` at its own temporary folder and
removes the handler it installed, so nothing reaches the session's root logger
or a real data directory.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.infrastructure import logging_setup
from src.infrastructure.logging_setup import (
    LOG_FILE_NAME,
    active_log_file,
    configure_logging,
    log_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("BRAINSENSER_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _remove_log_handler():
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == logging_setup._HANDLER_NAME:
            root.removeHandler(handler)
            handler.close()


def test_log_directory_is_under_the_data_dir(data_dir):
    assert log_directory() == data_dir / "logs"


def test_configure_logging_writes_records_to_the_log_file(data_dir):
    path = configure_logging()

    assert path == data_dir / "logs" / LOG_FILE_NAME
    assert active_log_file() == path
    logging.getLogger("tests.logging_setup").warning("written to the log file")
    text = path.read_text(encoding="utf-8")
    assert "WARNING" in text and "written to the log file" in text


def test_configure_logging_is_idempotent(data_dir):
    first = configure_logging()
    second = configure_logging()

    assert first == second
    names = [h.get_name() for h in logging.getLogger().handlers]
    assert names.count(logging_setup._HANDLER_NAME) == 1


def test_the_log_file_rotates(data_dir, monkeypatch):
    monkeypatch.setattr(logging_setup, "_MAX_BYTES", 200)
    path = configure_logging()
    log = logging.getLogger("tests.logging_setup")
    for i in range(20):
        log.warning("record %d with enough text to fill the small file", i)

    assert path.with_name(LOG_FILE_NAME + ".1").exists()
    assert path.stat().st_size <= 200


def test_an_unwritable_folder_disables_the_file_log(data_dir):
    (data_dir / "logs").write_text("a file where the folder should be")

    assert configure_logging() is None
    assert active_log_file() is None


def test_import_configures_nothing(tmp_path):
    """Only configure_logging() (called from main()) creates the log."""
    env = {**os.environ, "BRAINSENSER_DATA_DIR": str(tmp_path), "PYTHONPATH": str(REPO_ROOT)}
    probe = "import src.infrastructure.logging_setup as s; print(s.active_log_file())"
    result = subprocess.run([sys.executable, "-c", probe], env=env, cwd=tmp_path,
                            capture_output=True, text=True, check=True)

    assert result.stdout.strip() == "None"
    assert not (tmp_path / "logs").exists()
