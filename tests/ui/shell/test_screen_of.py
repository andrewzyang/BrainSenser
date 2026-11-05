"""screen_of: the screen Qt reports, looked up so PySide cannot delete it.

``QWidget.screen()`` and ``QWindow.screen()`` make the application's QScreen a
child of the caller's wrapper; when the cycle collector frees a window that the
(older) screen wrapper had moved to, it can clear that wrapper first, and
Shiboken then deletes the QScreen (``src/ui/utils/screens.py``). The window
lifecycle runs in a fresh offscreen process, so a regression kills only that.
"""

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from src.ui.utils.screens import screen_of
from tests.ui.scaling._app_process import AppProcess, DisplayProfile


def test_screen_of_is_the_screen_qt_reports(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    handle = window.windowHandle()

    assert screen_of(window) is window.screen()
    assert screen_of(handle) is handle.screen()


@pytest.mark.qt_subprocess
def test_windows_freed_by_the_cycle_collector_leave_the_screen_alive(tmp_path):
    # A module fixture's close(), deleteLater() and processEvents() leave its
    # window alive, so the next window's lookups take over the screen wrapper;
    # when the cycle collector then freed that window, the QScreen went with it
    # and hiding the next window segfaulted.
    result = AppProcess("tests.ui.shell.test_screen_of:collect_a_window_after_a_fixture",
                        None, DisplayProfile(name="default_screen"), tmp_path).result()

    assert result == {"screen_deleted": False, "screens": 1}


def collect_a_window_after_a_fixture(_payload) -> dict:
    """Child side: two windows wired as MainWindow is (floor, floor keeper, screen
    watcher), the first torn down as a module fixture is, the second left to the
    cycle collector; then a window is shown and hidden, which reads the screen."""
    import gc

    from PySide6.QtGui import QGuiApplication

    from src.ui.shell.screen_watcher import ScreenWatcher
    from src.ui.shell.window_placement import keep_window_floor

    deleted = []
    screen = QGuiApplication.primaryScreen()
    screen.destroyed.connect(lambda *_: deleted.append(True))
    del screen  # a reference held here would keep the collector off the wrapper

    def window() -> QMainWindow:
        win = QMainWindow()
        keep_window_floor(win)
        win.show()  # the floor keeper looks the screen up at the first show
        QApplication.processEvents()
        win.watcher = ScreenWatcher(win.windowHandle(), win)
        win.cycle = win  # only the cycle collector frees it
        return win

    gc.disable()  # one collection, below
    first = window()
    first.close()
    first.deleteLater()
    QApplication.processEvents()  # runs no deleteLater() outside an event loop
    del first
    second = window()
    del second
    gc.collect()
    gc.enable()
    probe = QWidget()
    probe.show()
    probe.hide()
    return {"screen_deleted": bool(deleted), "screens": len(QApplication.screens())}
