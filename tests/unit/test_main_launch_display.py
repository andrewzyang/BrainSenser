"""The display the app opens on, at start-up (adversarial review: the undocked laptop).

L0 composes the interface size of the display the window was last on before Qt
knows which displays are connected, and records that display. build_presentation
compares the display the app actually opens on: when it is another one that
needs another size (the last one was unplugged), the app relaunches once,
through the container's restarter, before any splash or window exists; the
relaunched start-up composes for that display and never relaunches again. When
the new instance can't be started, the app carries on.

Nothing relaunches for real: in-process tests inject a recording restarter; the
two-process scenario runs the real QProcessAppRestarter with a launcher that only
records, on emulated offscreen screens, every store in its sandbox.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dependency_injector import providers
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from src.infrastructure.container import ApplicationContainer
from src.infrastructure.preferences import InMemoryUiPreferences
from src.ui.app_bootstrap import build_presentation
from src.ui.policy.scale import (
    QT_SCALE_FACTOR, SCALE_DISPLAY, SCALE_INJECTED, SCALE_RELAUNCH, ZOOM_LADDER, ZoomNotice,
    compose_scale_env,
)
from tests.ui.responsive import runner

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = "DELL U2720Q"


class _Restarter:
    """Records the environment a relaunch would start with. Like the real one
    before the event loop, it ends start-up (``exits``), or returns as when the
    new instance could not be started."""

    def __init__(self, environ, exits):
        self._environ = environ
        self._exits = exits
        self.started_with = []

    def restart(self):
        self.started_with.append(dict(self._environ))
        if self._exits:
            raise SystemExit(0)


@pytest.fixture
def start(qapp):
    """``start(environ, steps, exits=False)`` -> (container, restarter): the
    environment L0 left, the sizes saved per display, the window last saved on
    the external display."""
    def build(environ, steps, exits=False):
        store = InMemoryUiPreferences()
        store.zoom_steps = dict(steps)
        store.window_geometry, store.last_screen = b"memento", EXTERNAL
        restarter = _Restarter(environ, exits)
        container = ApplicationContainer()
        container.ui_preferences.override(providers.Object(store))
        container.startup_environment.override(providers.Object(environ))
        container.app_restarter.override(providers.Object(restarter))
        return container, restarter
    return build


def _primary() -> str:
    return QGuiApplication.primaryScreen().name()


def _l0(steps, display) -> dict:
    """The environment L0 composes for ``display``."""
    return compose_scale_env(steps, {}, launch_display=display)


def test_undocked_display_relaunches_once_and_carries_on_if_that_fails(start):
    steps = {EXTERNAL: ZOOM_LADDER.index(125)}
    environ = _l0(steps, EXTERNAL)  # last session on the external display, now gone
    composed = dict(environ)
    container, restarter = start(environ, steps)

    presentation = build_presentation(container)

    assert restarter.started_with == [{SCALE_DISPLAY: _primary(), SCALE_RELAUNCH: _primary()}]
    assert environ == composed  # restored: a later Restart Now composes afresh
    state = presentation.ui_scale_viewmodel.state
    assert presentation.launch_screen_name == _primary()
    # carried on at 125 %: no banner, Restart Now in the "Aa" menu
    assert (state.active_percent, state.chosen_percent, state.restart_required, state.notice) == (
        125, 100, True, ZoomNotice.NONE)


def test_a_started_relaunch_ends_start_up_before_any_window(start):
    steps = {EXTERNAL: ZOOM_LADDER.index(150), _primary(): ZOOM_LADDER.index(110)}
    environ = _l0(steps, EXTERNAL)
    container, restarter = start(environ, steps, exits=True)
    windows = set(QApplication.topLevelWidgets())

    with pytest.raises(SystemExit):
        build_presentation(container)

    assert restarter.started_with == [{QT_SCALE_FACTOR: "1.1", SCALE_INJECTED: "1",
                                       SCALE_DISPLAY: _primary(), SCALE_RELAUNCH: _primary()}]
    assert set(QApplication.topLevelWidgets()) == windows


@pytest.mark.parametrize("environ, steps", [
    # composed for the display it opens on
    (_l0({"": 3}, ""), {"": 3}),
    # another display, the same size
    (_l0({EXTERNAL: 3}, EXTERNAL), {EXTERNAL: 3, "": 3}),
    # L0 did not run (tests, the harness): nothing to compare with
    ({}, {"": 3}),
    # Qt scaling set by the user or IT
    ({QT_SCALE_FACTOR: "1.25", SCALE_DISPLAY: EXTERNAL}, {}),
])
def test_no_relaunch(start, environ, steps, qapp):
    assert _primary() == ""  # the session's offscreen screen, which the cases name
    container, restarter = start(environ, steps)
    build_presentation(container)
    assert restarter.started_with == []


def test_the_relaunched_start_up_never_relaunches_again(start):
    """Even if the display it opens on changed once more, and the marker is used up."""
    steps = {EXTERNAL: 3, "Sidecar": 2}
    environ = {**_l0(steps, "Sidecar"), SCALE_RELAUNCH: "Sidecar"}
    container, restarter = start(environ, steps)
    build_presentation(container)
    assert restarter.started_with == [] and SCALE_RELAUNCH not in environ


# ------------------------------------------------------- two processes, real Qt and restarter

LAPTOP = "laptop_retina"
EXTERNAL_1X = "monitor_1x"


@pytest.mark.qt_subprocess
def test_undocked_laptop_two_processes(tmp_path):
    """Last session: the window on the 1x external display, set to 125 %. Now only
    the laptop is connected. The first process starts at 125 % (L0 cannot know),
    sees the laptop and asks the real restarter for one relaunch, which starts
    it (recorded) and exits before any window. The relaunched process, started
    with that environment, runs the laptop at its own 100 % and relaunches no more."""
    config = tmp_path / "screens.json"
    config.write_text(json.dumps({
        "synchronousWindowSystemEvents": False, "windowFrameMargins": False,
        "screens": [{"name": LAPTOP, "x": 0, "y": 0, "width": 2880, "height": 1800,
                     "logicalDpi": 144, "logicalBaseDpi": 72}]}))
    settings = tmp_path / "settings.ini"

    first = _run(tmp_path, "first", config, settings, {})
    assert first["returncode"] == 0, first["log"]
    assert first["dpr"] == 2.5  # the laptop at the external display's 125 %
    assert first["built"] is False  # ended at the relaunch: no splash, no window
    launch = first["launch"]
    scale = {k: v for k, v in launch["environment"].items() if k.startswith(
        ("BRAINSENSER_SCALE", "QT_SCALE"))}
    assert scale == {SCALE_DISPLAY: LAPTOP, SCALE_RELAUNCH: LAPTOP}

    second = _run(tmp_path, "second", config, settings, scale)
    assert second["returncode"] == 0, second["log"]
    assert (second["dpr"], second["built"], second["launch"]) == (2.0, True, None)
    assert second["state"] == {"display": LAPTOP, "active": 100, "chosen": 100,
                               "restart_required": False, "notice": "none"}
    assert second["relaunch_marker_left"] is False


def _run(tmp_path, label, config, settings, scale_environment) -> dict:
    sandbox = tmp_path / label
    for folder in ("home", "appdata", "cwd"):
        (sandbox / folder).mkdir(parents=True)
    env = {k: v for k, v in runner.child_environment(sandbox, f"offscreen:configfile={config}",
                                                     REPO_ROOT).items()
           if not k.startswith("BRAINSENSER_SCALE")}
    env.update(scale_environment)
    result = sandbox / "result.json"
    code = (f"import sys; from {__name__} import _start_up_child; "
            "_start_up_child(sys.argv[1], sys.argv[2])")
    done = subprocess.run([sys.executable, "-c", code, str(result), str(settings)],
                          cwd=sandbox / "cwd", env=env, capture_output=True, text=True, timeout=120)
    outcome = json.loads(result.read_text()) if result.exists() else {}
    return {"returncode": done.returncode, "log": done.stdout[-3000:] + done.stderr[-3000:],
            "built": outcome.get("built", False), "launch": outcome.get("launch"),
            **{k: v for k, v in outcome.items() if k not in ("built", "launch")}}


def _start_up_child(result_path: str, settings_path: str) -> None:
    """main()'s start-up, L0 to build_presentation, with the real restarter whose
    launcher only records; every settings store in the sandbox's INI file."""
    from PySide6.QtCore import QSettings, Qt

    import src.domain.effect_size_preference as effect_size_preference
    import src.infrastructure.preferences.qsettings_ui_preferences as ui_preferences
    from src.infrastructure.app_restart import QProcessAppRestarter
    from src.infrastructure.preferences import QSettingsUiPreferences
    from src.ui.app_bootstrap import compose_startup_environment

    def settings():
        return QSettings(settings_path, QSettings.Format.IniFormat)

    effect_size_preference.QSettings = lambda *_a, **_k: settings()
    effect_size_preference.EffectSizePreference.reset_singleton()
    ui_preferences.native_settings = settings
    store = QSettingsUiPreferences(settings)
    if not Path(settings_path).exists():  # the last session's
        store.save_zoom_steps({EXTERNAL_1X: ZOOM_LADDER.index(125)})
        store.save_window_geometry(b"saved on the external display", EXTERNAL_1X)

    outcome = {"built": False}

    def write():
        Path(result_path).write_text(json.dumps(outcome))

    def launch(program, arguments, environment, working_directory):
        outcome["launch"] = {"environment": dict(environment)}
        write()  # the restarter exits next
        return True

    container = ApplicationContainer()
    container.ui_preferences.override(providers.Object(store))
    container.app_restarter.override(providers.Object(QProcessAppRestarter(launch=launch)))

    compose_startup_environment(container.ui_preferences(), container.startup_environment())
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    outcome["dpr"] = app.primaryScreen().devicePixelRatio()
    write()

    presentation = build_presentation(container)

    state = presentation.ui_scale_viewmodel.state
    outcome.update(built=True, state={
        "display": state.display, "active": state.active_percent, "chosen": state.chosen_percent,
        "restart_required": state.restart_required, "notice": state.notice.value},
        relaunch_marker_left=SCALE_RELAUNCH in os.environ)
    write()
