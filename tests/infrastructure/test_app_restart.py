"""QProcessAppRestarter: relaunch command, environment and order (plan §4.7, M4.1).

The app is never relaunched: the restarter gets a recording launcher and a
recording lifecycle. A running app quits first and starts the new instance only
once its event loop has ended (the windows have saved their state by then);
during start-up, before the event loop, it starts the new instance and exits,
or carries on when that fails. Only test_start_detached_passes_exactly_the_environment
starts a process, a throwaway interpreter that writes what it received into the
test's tmp dir. The real lifecycle's order (closeEvent, then aboutToQuit) is
checked end to end in tests/unit/test_main_shell_wiring.py.
"""

import json
import logging
import os
import sys
import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from src.domain.ui_preferences import AppRestarter
from src.infrastructure.app_restart import (
    QProcessAppRestarter, QtAppLifecycle, relaunch_command, start_detached,
)
from src.ui.policy.scale import QT_SCALE_FACTOR, SCALE_INJECTED

BUNDLE_EXECUTABLE = "/Applications/BrainSenser.app/Contents/MacOS/BrainSenser"


class Recorder:
    """Launcher and lifecycle in one: records what the restarter asks for."""

    def __init__(self, started=True, running=True):
        self.events = []
        self.after_quit = []
        self._started = started
        self._running = running

    def launch(self, program, arguments, environment, working_directory):
        self.events.append(("launch", program, list(arguments), dict(environment),
                            working_directory))
        return self._started

    # AppLifecycle
    def running(self):
        return self._running

    def quit_then(self, callback):
        self.events.append(("quit",))
        self.after_quit.append(callback)

    def exit(self):
        self.events.append(("exit",))

    def event_loop_ended(self):
        """What Qt does once the event loop has ended: aboutToQuit."""
        for callback in self.after_quit:
            callback()

    def restarter(self):
        return QProcessAppRestarter(launch=self.launch, lifecycle=self)


@pytest.fixture
def dev_process(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/python/bin/python3.13")
    monkeypatch.setattr(sys, "orig_argv", ["python", "-X", "dev", "main.py", "--verbose"])
    monkeypatch.setattr(sys, "argv", ["main.py", "--verbose"])


@pytest.fixture
def frozen_process(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", BUNDLE_EXECUTABLE)
    monkeypatch.setattr(sys, "orig_argv", [BUNDLE_EXECUTABLE, "--verbose"])
    monkeypatch.setattr(sys, "argv", [BUNDLE_EXECUTABLE, "--verbose"])


def test_restarter_implements_the_port():
    assert isinstance(QProcessAppRestarter(), AppRestarter)


def test_dev_relaunches_the_same_interpreter_and_command_line(dev_process):
    assert relaunch_command() == (
        "/opt/python/bin/python3.13", ["-X", "dev", "main.py", "--verbose"])


def test_frozen_relaunches_the_bundle_executable(frozen_process):
    assert relaunch_command() == (BUNDLE_EXECUTABLE, ["--verbose"])


# ------------------------------------------------------------------ a running app

def test_running_app_quits_first_and_starts_the_new_instance_after(dev_process, monkeypatch,
                                                                   tmp_path):
    monkeypatch.chdir(tmp_path)
    recorder = Recorder()
    recorder.restarter().restart()
    assert recorder.events == [("quit",)]  # nothing started while the windows still save

    recorder.event_loop_ended()

    quit_, launch = recorder.events
    assert launch[:3] == ("launch", "/opt/python/bin/python3.13",
                          ["-X", "dev", "main.py", "--verbose"])
    assert launch[4] == str(tmp_path)


def test_restart_carries_the_composed_environment(dev_process, monkeypatch):
    monkeypatch.setenv(QT_SCALE_FACTOR, "1.25")
    monkeypatch.setenv(SCALE_INJECTED, "1")
    recorder = Recorder()
    recorder.restarter().restart()
    recorder.event_loop_ended()
    environment = recorder.events[1][3]
    assert environment == dict(os.environ)
    assert (environment[QT_SCALE_FACTOR], environment[SCALE_INJECTED]) == ("1.25", "1")
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in environment


def test_frozen_restart_starts_an_independent_instance(frozen_process):
    recorder = Recorder()
    recorder.restarter().restart()
    recorder.event_loop_ended()
    _, program, arguments, environment, _ = recorder.events[1]
    assert (program, arguments) == (BUNDLE_EXECUTABLE, ["--verbose"])
    assert environment["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_restarting_twice_starts_one_instance(dev_process):
    recorder = Recorder()
    restarter = recorder.restarter()
    restarter.restart()
    restarter.restart()  # e.g. a second click while quitting
    recorder.event_loop_ended()
    assert [event[0] for event in recorder.events] == ["quit", "launch"]


def test_a_new_instance_that_fails_to_start_is_logged(dev_process, caplog):
    recorder = Recorder(started=False)
    recorder.restarter().restart()
    with caplog.at_level(logging.ERROR):
        recorder.event_loop_ended()
    assert [event[0] for event in recorder.events] == ["quit", "launch"]
    assert "Could not start a new instance" in caplog.text


# ------------------------------------------------------------------ during start-up

def test_before_the_event_loop_it_starts_the_new_instance_then_exits(dev_process):
    recorder = Recorder(running=False)
    recorder.restarter().restart()
    assert [event[0] for event in recorder.events] == ["launch", "exit"]


def test_before_the_event_loop_a_failed_start_carries_on(dev_process, caplog):
    recorder = Recorder(started=False, running=False)
    with caplog.at_level(logging.ERROR):
        recorder.restarter().restart()
    assert [event[0] for event in recorder.events] == ["launch"]
    assert "Could not start a new instance" in caplog.text


def test_qt_lifecycle_knows_whether_the_event_loop_runs(qapp):
    lifecycle = QtAppLifecycle()
    seen = []
    loop = QEventLoop()
    QTimer.singleShot(0, lambda: (seen.append(lifecycle.running()), loop.quit()))
    assert lifecycle.running() is False
    loop.exec()
    assert seen == [True]


def test_qt_lifecycle_exits_the_process():
    with pytest.raises(SystemExit) as exited:
        QtAppLifecycle().exit()
    assert exited.value.code == 0


# ------------------------------------------------------------------ the real launcher

def test_start_detached_passes_exactly_the_environment(tmp_path):
    out = tmp_path / "child.json"
    code = ("import json, os, sys; out = sys.argv[1]\n"
            "report = {'argv': sys.argv[1:], 'env': dict(os.environ), 'cwd': os.getcwd()}\n"
            "with open(out + '.tmp', 'w') as f:\n"
            "    json.dump(report, f)\n"
            "os.replace(out + '.tmp', out)")
    started = start_detached(sys.executable, ["-c", code, str(out), "--flag"],
                             {"BRAINSENSER_PROBE": "1"}, str(tmp_path))
    assert started
    deadline = time.monotonic() + 30
    while not out.exists():
        assert time.monotonic() < deadline, "the detached child did not report back"
        time.sleep(0.05)
    report = json.loads(out.read_text())
    assert report["argv"] == [str(out), "--flag"]
    assert report["env"].get("BRAINSENSER_PROBE") == "1"
    assert "HOME" not in report["env"] and "BRAINSENSER_DATA_DIR" not in report["env"]
    assert os.path.realpath(report["cwd"]) == os.path.realpath(tmp_path)
