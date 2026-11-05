"""ScreenWatcher: display changes of a window, debounced (plan §4.7; I10).

A display change is a change of the window's screen, or of its DPR or logical
size; a burst of them is reported once, 250 ms after the last, never while a
mouse button is down, and metrics equal to the last reported ones never. The
logic runs on the session's offscreen screen with the metrics stood in; a real
move between two emulated screens runs in a fresh offscreen process.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.policy.scale import ScreenMetrics
from src.ui.shell import screen_watcher
from src.ui.shell.screen_watcher import DEBOUNCE_MS, ScreenWatcher, read_screen_metrics
from tests.ui.responsive import runner
from tests.ui.responsive.profiles import PROFILES

REPO_ROOT = Path(__file__).resolve().parents[3]

LAPTOP = ScreenMetrics("laptop", 1440, 900, 2.0)
MONITOR = ScreenMetrics("monitor", 1920, 1080, 1.0)


@pytest.fixture
def window(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@pytest.fixture
def metrics(monkeypatch):
    """What read_screen_metrics reports; set ``metrics.now`` to change the display."""
    class _Display:
        now = LAPTOP

    monkeypatch.setattr(screen_watcher, "read_screen_metrics", lambda _screen: _Display.now)
    return _Display


@pytest.fixture
def watcher(window, metrics):
    return ScreenWatcher(window.windowHandle(), window)


def test_reads_the_screen_as_qt_reports_it(window):
    screen = window.screen()
    assert read_screen_metrics(screen) == ScreenMetrics(
        screen.name(), screen.geometry().width(), screen.geometry().height(),
        screen.devicePixelRatio())


def test_starts_with_the_current_display_and_reports_nothing(watcher, qtbot):
    assert watcher.metrics == LAPTOP
    with qtbot.assertNotEmitted(watcher.display_changed, wait=DEBOUNCE_MS + 100):
        pass


def test_a_burst_is_reported_once_after_the_last_signal(watcher, metrics, qtbot):
    reported = []
    watcher.display_changed.connect(reported.append)
    metrics.now = MONITOR
    for _ in range(5):
        watcher._schedule()
        qtbot.wait(DEBOUNCE_MS // 5)
    assert reported == []  # each signal restarted the wait
    qtbot.waitUntil(lambda: reported == [MONITOR], timeout=DEBOUNCE_MS * 4)
    assert watcher.metrics == MONITOR


def test_unchanged_metrics_are_not_reported(watcher, qtbot):
    watcher._schedule()
    with qtbot.assertNotEmitted(watcher.display_changed, wait=DEBOUNCE_MS + 100):
        pass


def test_held_while_a_mouse_button_is_down(watcher, metrics, qtbot, monkeypatch):
    buttons = [Qt.MouseButton.LeftButton]
    monkeypatch.setattr(QGuiApplication, "mouseButtons", staticmethod(lambda: buttons[0]))
    metrics.now = MONITOR
    watcher._schedule()
    with qtbot.assertNotEmitted(watcher.display_changed, wait=DEBOUNCE_MS * 2 + 100):
        pass
    buttons[0] = Qt.MouseButton.NoButton  # dropped
    with qtbot.waitSignal(watcher.display_changed, timeout=DEBOUNCE_MS * 4) as blocker:
        pass
    assert blocker.args == [MONITOR]


def test_screen_geometry_and_dpr_changes_are_watched(window, watcher, metrics, qtbot):
    resized = ScreenMetrics(LAPTOP.name, 1280, 800, 2.0)    # the display's resolution changed
    rescaled = ScreenMetrics(LAPTOP.name, 1280, 800, 1.0)   # then its scaling
    metrics.now = resized
    with qtbot.waitSignal(watcher.display_changed, timeout=DEBOUNCE_MS * 4) as first:
        window.screen().geometryChanged.emit(window.screen().geometry())
    metrics.now = rescaled
    with qtbot.waitSignal(watcher.display_changed, timeout=DEBOUNCE_MS * 4) as second:
        QApplication.sendEvent(window.windowHandle(), QEvent(QEvent.Type.DevicePixelRatioChange))
    assert (first.args, second.args) == ([resized], [rescaled])


def test_available_area_is_not_a_display_change(window, watcher, qtbot):
    """The Dock or taskbar appearing changes the available area only."""
    window.screen().availableGeometryChanged.emit(window.screen().availableGeometry())
    assert not watcher._timer.isActive()


def test_holds_no_viewmodel():
    source = Path(screen_watcher.__file__).read_text(encoding="utf-8")
    assert "src.ui.viewmodels" not in source and "src.infrastructure" not in source


# ------------------------------------------------- a real move, in a fresh process

@pytest.mark.qt_subprocess
def test_moving_to_another_screen_is_reported_once(tmp_path):
    profile = PROFILES["mixed"]
    for folder in ("home", "appdata", "cwd"):
        (tmp_path / folder).mkdir()
    qpa = f"offscreen:configfile={profile.write_qpa_config(tmp_path / 'screens.json')}"
    result = tmp_path / "result.json"
    code = f"import sys; from {__name__} import _child; _child(sys.argv[1])"
    done = subprocess.run([sys.executable, "-c", code, str(result)], cwd=tmp_path / "cwd",
                          env=runner.child_environment(tmp_path, qpa, REPO_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and result.exists(), done.stdout[-3000:] + done.stderr[-3000:]
    out = json.loads(result.read_text())
    monitor = next(s for s in profile.screens if s.name == "monitor_1x")
    assert out["start"]["name"] == profile.primary.name
    assert out["reported"] == [["monitor_1x", monitor.available[0], out["monitor_height"], 1.0]]


def _child(result_path: str) -> None:
    import time

    from PySide6.QtCore import QEventLoop, QPoint

    app = QApplication([])
    window = QWidget()
    window.resize(QSize(400, 300))
    window.show()
    app.processEvents()
    watcher = ScreenWatcher(window.windowHandle())
    reported = []
    watcher.display_changed.connect(
        lambda m: reported.append([m.name, m.logical_w, m.logical_h, m.dpr]))

    def settle(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)

    # Dragged onto the monitor, back and onto it again, within the debounce
    laptop, monitor = (next(s for s in app.screens() if s.name() == name)
                       for name in ("laptop_retina", "monitor_1x"))
    for screen in (monitor, laptop, monitor):
        window.move(screen.availableGeometry().topLeft() + QPoint(40, 40))
        settle(0.03)
    settle(3 * DEBOUNCE_MS / 1000)
    Path(result_path).write_text(json.dumps({
        "start": {"name": app.primaryScreen().name()},
        "monitor_height": monitor.geometry().height(),
        "reported": reported,
    }))
