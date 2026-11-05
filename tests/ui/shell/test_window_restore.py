"""Saved window geometry and the launch screen (plan M3.7; shell:SH-04 restore matrix).

The pure choice of the launch screen, then the restore matrix: a window placed
and saved under one display setup is restored under another through the same
path as MainWindow.show_at_launch — ShellViewModel's memento (only if its screen
is still connected), launch_screen(), apply_initial_geometry(). Whatever
changed, the window opens fully on its launch screen: restored where Qt can put
it back there, else placed as on first launch. Each setup runs in a fresh
offscreen process (window frames on); synthetic windows only, no settings.

| case | saved on                     | relaunched with                                | expected            |
|------|------------------------------|------------------------------------------------|---------------------|
| T1   | external monitor             | the laptop alone (monitor unplugged)           | first-launch, laptop |
| T2   | laptop                       | the monitor alone (lid closed)                 | first-launch, monitor |
| T3   | laptop at 100 %              | laptop at 150 % (Qt refuses the memento)       | first-launch        |
| T4   | monitor right of the laptop  | monitor now left of it                         | restored, moved onto it |
| T5   | monitor, maximised           | the same displays                              | restored maximised  |
| T6   | laptop at 150 %              | laptop at 100 % (Qt refuses the memento)       | first-launch        |
| T7   | laptop                       | the same displays (control)                    | restored exactly    |
| T8   | monitor (second display)     | a third display now second (index mismatch)    | restored, moved onto it |

A memento that does restore but would leave the window off its launch screen
falls back to the first-launch placement too (tested in-process: Qt keeps the
window on the screen it is given before restoring, so no display setup above
gets there).
"""

import base64
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow

from src.ui.shell.window_placement import apply_initial_geometry, launch_geometry, pick_launch_screen
from tests.ui.responsive import runner
from tests.ui.responsive.profiles import Profile, Screen

REPO_ROOT = Path(__file__).resolve().parents[3]

LAPTOP = Screen("a_laptop", (1440, 850), 1.0, 72, 28)
MONITOR = Screen("b_monitor", (1920, 1050), 1.0, 72, 28, x=1440)
SETUPS = {p.name: p for p in (
    Profile("two", "laptop + monitor on its right", (LAPTOP, MONITOR)),
    Profile("laptop_only", "the laptop alone", (LAPTOP,)),
    Profile("monitor_only", "the monitor alone", (Screen("b_monitor", (1920, 1050), 1.0, 72, 28),)),
    # The same 1440×850 panel at 150 %
    Profile("laptop_150", "the laptop at 150 %", (Screen("a_laptop", (960, 567), 1.5, 96, 30),)),
    Profile("swapped", "the monitor moved left of the laptop",
            (Screen("a_laptop", (1440, 850), 1.0, 72, 28, x=1920),
             Screen("b_monitor", (1920, 1050), 1.0, 72, 28))),
    Profile("reordered", "a TV is now the second display, the monitor the third",
            (LAPTOP, Screen("c_tv", (1920, 1050), 1.0, 72, 28, x=1440),
             Screen("b_monitor", (1920, 1050), 1.0, 72, 28, x=3360))),
)}

# case: (setup saved under, screen, normal geometry or None = left maximised, setup restored under)
CASES = {
    "T1": ("two", "b_monitor", [1700, 150, 900, 600], "laptop_only"),
    "T2": ("two", "a_laptop", [100, 80, 900, 600], "monitor_only"),
    "T3": ("laptop_only", "a_laptop", [100, 80, 900, 600], "laptop_150"),
    "T4": ("two", "b_monitor", [2400, 150, 900, 600], "swapped"),
    "T5": ("two", "b_monitor", None, "two"),
    "T6": ("laptop_150", "a_laptop", [60, 60, 700, 450], "laptop_only"),
    "T7": ("two", "a_laptop", [100, 80, 900, 600], "two"),
    "T8": ("two", "b_monitor", [1700, 150, 900, 600], "reordered"),
}


# ------------------------------------------------------------------------ pure

@pytest.mark.parametrize("screens, last, pointer, expected", [
    (["a", "b"], "b", "a", "b"),          # the last-used screen, by name
    (["a"], "b", "a", "a"),               # it is gone: the pointer's
    (["a", "b"], None, "b", "b"),         # never saved: the pointer's
    (["a", "b"], "c", None, "a"),         # neither: the primary
    (["a", "b"], None, None, "a"),
    (["", "b"], "", "b", ""),             # an unnamed screen is still a name
])
def test_pick_launch_screen(screens, last, pointer, expected):
    assert pick_launch_screen(screens, last, pointer, primary="a" if "a" in screens else "") \
        == expected


# ------------------------------------------------- apply_initial_geometry, in-process

@pytest.fixture
def placed(qtbot):
    """A fresh window and the session's (offscreen) screen."""
    window = QMainWindow()
    qtbot.addWidget(window)
    screen = QGuiApplication.primaryScreen()
    return window, screen, launch_geometry(screen.availableGeometry(), window.minimumSize())


def _first_launch(window, launch) -> bool:
    maximized = bool(window.windowState() & Qt.WindowState.WindowMaximized)
    return window.geometry() == launch.normal and maximized == launch.maximized


def test_no_memento_places_it_as_on_first_launch(placed):
    window, screen, launch = placed
    assert apply_initial_geometry(window, screen, None) is False
    assert _first_launch(window, launch)


def test_a_memento_qt_refuses_falls_back(placed):
    window, screen, launch = placed
    assert apply_initial_geometry(window, screen, b"not a saveGeometry() memento") is False
    assert _first_launch(window, launch)


def test_a_restore_that_lands_off_the_screen_falls_back(placed, monkeypatch):
    window, screen, launch = placed

    def restore_elsewhere(self, _memento):
        self.setGeometry(QRect(5000, 5000, 640, 480))  # e.g. onto a display that is gone
        self.setWindowState(Qt.WindowState.WindowMaximized)
        return True

    monkeypatch.setattr(QMainWindow, "restoreGeometry", restore_elsewhere)
    assert apply_initial_geometry(window, screen, b"memento") is False
    assert _first_launch(window, launch)


def test_a_memento_from_this_screen_is_restored(placed, qtbot):
    window, screen, _launch = placed
    previous = QMainWindow()
    qtbot.addWidget(previous)
    previous.setGeometry(QRect(60, 70, 640, 520))
    memento = bytes(previous.saveGeometry())
    assert apply_initial_geometry(window, screen, memento) is True
    assert window.geometry() == QRect(60, 70, 640, 520)


# ------------------------------------------------------------------ the matrix

def _run(tmp_path: Path, label: str, setup: str, spec: dict) -> dict:
    sandbox = tmp_path / label
    for folder in ("home", "appdata", "cwd"):
        (sandbox / folder).mkdir(parents=True)
    config = json.loads(SETUPS[setup].write_qpa_config(sandbox / "screens.json").read_text())
    config["windowFrameMargins"] = True
    (sandbox / "screens.json").write_text(json.dumps(config))
    (sandbox / "spec.json").write_text(json.dumps(spec))
    code = f"import sys; from {__name__} import _child; _child(sys.argv[1])"
    done = subprocess.run([sys.executable, "-c", code, str(sandbox / "spec.json")],
                          cwd=sandbox / "cwd", capture_output=True, text=True, timeout=120,
                          env=runner.child_environment(
                              sandbox, f"offscreen:configfile={sandbox / 'screens.json'}",
                              REPO_ROOT))
    result = sandbox / "result.json"
    assert done.returncode == 0 and result.exists(), done.stdout[-3000:] + done.stderr[-3000:]
    return json.loads(result.read_text())


def _case(tmp_path: Path, case: str) -> dict:
    saved_under, screen, normal, restored_under = CASES[case]
    saved = _run(tmp_path, f"{case}_save", saved_under,
                 {"mode": "save", "screen": screen, "normal": normal})
    restored = _run(tmp_path, f"{case}_restore", restored_under,
                    {"mode": "restore", "blob": saved["blob"], "screen": saved["screen"]})
    return {"saved": saved, "restored": restored}


@pytest.fixture(scope="module")
def matrix(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("restore")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {case: pool.submit(_case, tmp_path, case) for case in CASES}
        return {case: future.result() for case, future in futures.items()}


def _inside(inner, outer, tolerance: int = 1) -> bool:
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return (ox - tolerance <= ix and oy - tolerance <= iy
            and ix + iw <= ox + ow + tolerance and iy + ih <= oy + oh + tolerance)


@pytest.mark.qt_subprocess
@pytest.mark.parametrize("case", sorted(CASES))
def test_window_opens_fully_on_its_launch_screen(matrix, case):
    restored = matrix[case]["restored"]
    assert restored["screen"] == restored["launch_screen"]
    assert _inside(restored["frame_geometry"], restored["available"])


@pytest.mark.qt_subprocess
@pytest.mark.parametrize("case, launch_screen, memento", [
    ("T1", "a_laptop", False), ("T2", "b_monitor", False), ("T3", "a_laptop", True),
    ("T4", "b_monitor", True), ("T5", "b_monitor", True), ("T6", "a_laptop", True),
    ("T7", "a_laptop", True), ("T8", "b_monitor", True),
])
def test_launch_screen_and_memento(matrix, case, launch_screen, memento):
    """The saved screen is used while connected; its memento only then."""
    restored = matrix[case]["restored"]
    assert (restored["launch_screen"], restored["had_memento"]) == (launch_screen, memento)


@pytest.mark.qt_subprocess
@pytest.mark.parametrize("case", ["T1", "T2", "T3", "T6"])
def test_first_launch_placement_when_the_memento_does_not_fit(matrix, case):
    restored = matrix[case]["restored"]
    assert not restored["restored"]
    assert restored["maximized"]  # these screens are narrower than 2600 px


@pytest.mark.qt_subprocess
@pytest.mark.parametrize("case", ["T4", "T8"])
def test_rearranged_displays_restore_onto_the_same_monitor(matrix, case):
    """Qt moves the saved geometry onto the monitor at its new place."""
    restored = matrix[case]["restored"]
    assert restored["restored"] and not restored["maximized"]
    assert restored["geometry"][2:] == matrix[case]["saved"]["geometry"][2:]


@pytest.mark.qt_subprocess
def test_maximised_window_reopens_maximised(matrix):
    saved, restored = matrix["T5"]["saved"], matrix["T5"]["restored"]
    assert saved["maximized"] and restored["maximized"] and restored["restored"]
    # and un-maximises to the geometry it had before
    assert restored["normal"] == saved["normal"]


@pytest.mark.qt_subprocess
def test_unchanged_displays_restore_exactly(matrix):
    saved, restored = matrix["T7"]["saved"], matrix["T7"]["restored"]
    assert restored["restored"] and not restored["maximized"]
    assert restored["frame_geometry"] == saved["frame_geometry"]


# ---------------------------------------------------------------- child side

def _child(spec_path: str) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

    from src.infrastructure.preferences import InMemoryUiPreferences
    from src.ui.shell.window_placement import (apply_initial_geometry, keep_window_floor,
                                               launch_screen)
    from src.ui.viewmodels.shell_viewmodel import ShellViewModel

    spec = json.loads(Path(spec_path).read_text())
    app = QApplication([])

    def settle():
        for _ in range(5):
            app.processEvents()

    def rect(r):
        return [r.x(), r.y(), r.width(), r.height()]

    window = QMainWindow()
    window.setCentralWidget(QWidget())
    keep_window_floor(window)
    out = {}
    if spec["mode"] == "save":
        screen = next(s for s in app.screens() if s.name() == spec["screen"])
        apply_initial_geometry(window, screen, None)
        window.show()
        settle()
        if spec["normal"]:
            window.showNormal()
            window.setGeometry(QRect(*spec["normal"]))
            settle()
        out["blob"] = base64.b64encode(bytes(window.saveGeometry())).decode()
    else:
        store = InMemoryUiPreferences()
        store.window_geometry = base64.b64decode(spec["blob"])
        store.last_screen = spec["screen"]
        shell_vm = ShellViewModel(store)
        screen = launch_screen(shell_vm.last_screen_name)
        memento = shell_vm.saved_window_geometry([s.name() for s in app.screens()])
        restored = apply_initial_geometry(window, screen, memento)
        window.show()
        settle()
        out.update(launch_screen=screen.name(), had_memento=memento is not None,
                   restored=restored)
    out.update(screen=window.screen().name(), geometry=rect(window.geometry()),
               frame_geometry=rect(window.frameGeometry()), normal=rect(window.normalGeometry()),
               maximized=window.isMaximized(),
               available=rect(window.screen().availableGeometry()))
    Path(spec_path).with_name("result.json").write_text(json.dumps(out))

