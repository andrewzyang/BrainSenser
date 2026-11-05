"""
Tests for MainWindow.closeEvent.

Verifies the shutdown sequence correctly:
  - Hands the window geometry to ShellViewModel first; a failing save
    stops nothing, and a window without one skips it
  - Waits bounded-time for QThreadPool workers to finish
  - Skips the wait when no workers are active
  - Closes all 4 child pages
  - Continues when one page's close() raises
  - Tolerates missing page attributes (partial initialization)
  - Calls event.accept() and delegates to QMainWindow.closeEvent

Tests run against real MainWindow instances created via __new__ +
QMainWindow.__init__ to avoid booting the full DI container, database, and
UI stack. This exercises the actual closeEvent (including the super() call)
without any refactoring of main.py.

QCloseEvent instances are real (PySide6 C++ bindings reject MagicMock here).
A TrackingCloseEvent subclass captures call ordering.
"""

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMainWindow
from PySide6.QtGui import QCloseEvent

import main
from main import MainWindow


@pytest.fixture
def shell_window(qtbot):
    """
    Real MainWindow instance with only the Qt base class initialized.

    Created via __new__ + QMainWindow.__init__ so MainWindow.__init__ is
    skipped entirely (no DI container, no DB, no UI). This gives us a live
    QMainWindow with a real C++ backing object that super().closeEvent()
    can dispatch to, while leaving page attributes unset so each test can
    configure them explicitly.
    """
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    qtbot.addWidget(window)
    return window


class TrackingCloseEvent(QCloseEvent):
    """QCloseEvent subclass that records calls for ordering checks."""

    def __init__(self, call_log):
        super().__init__()
        self._call_log = call_log

    def accept(self):
        self._call_log.append("accept")
        super().accept()


def _attach_pages(window):
    """Give the shell window 4 mock pages."""
    window.data_management_page = MagicMock()
    window.snapshots_psd_page = MagicMock()
    window.snapshots_5hz_band_page = MagicMock()


class TestThreadPoolWait:
    def test_waits_when_workers_active(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            pool = mock_pool_cls.globalInstance.return_value
            pool.activeThreadCount.return_value = 2
            pool.waitForDone.return_value = True

            shell_window.closeEvent(event)

            pool.waitForDone.assert_called_once_with(3000)

    def test_skips_wait_when_no_workers(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            pool = mock_pool_cls.globalInstance.return_value
            pool.activeThreadCount.return_value = 0

            shell_window.closeEvent(event)

            pool.waitForDone.assert_not_called()

    def test_continues_when_wait_times_out(self, shell_window, caplog):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            pool = mock_pool_cls.globalInstance.return_value
            pool.activeThreadCount.return_value = 3
            pool.waitForDone.return_value = False  # timeout

            shell_window.closeEvent(event)  # must not raise

            shell_window.data_management_page.close.assert_called_once()
            assert "did not finish" in caplog.text.lower()

    def test_tolerates_threadpool_exception(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            mock_pool_cls.globalInstance.side_effect = RuntimeError("pool broken")

            shell_window.closeEvent(event)  # must not raise

            shell_window.data_management_page.close.assert_called_once()


class TestPageClosing:
    def test_closes_all_four_pages(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)

        shell_window.data_management_page.close.assert_called_once()
        shell_window.snapshots_psd_page.close.assert_called_once()
        shell_window.snapshots_5hz_band_page.close.assert_called_once()

    def test_continues_when_one_page_raises(self, shell_window):
        _attach_pages(shell_window)
        shell_window.snapshots_psd_page.close.side_effect = RuntimeError("boom")
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)  # must not propagate

        shell_window.data_management_page.close.assert_called_once()
        shell_window.snapshots_5hz_band_page.close.assert_called_once()

    def test_tolerates_missing_page_attributes(self, shell_window):
        """Partial initialization: page attrs were never set."""
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)  # must not raise

    def test_tolerates_none_page_attributes(self, shell_window):
        shell_window.data_management_page = None
        shell_window.snapshots_psd_page = None
        shell_window.snapshots_5hz_band_page = None
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)  # must not raise

    def test_logs_page_close_failures(self, shell_window, caplog):
        _attach_pages(shell_window)
        shell_window.snapshots_psd_page.close.side_effect = RuntimeError("close fail")
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)

        assert "snapshots_psd_page" in caplog.text


class TestEventHandling:
    def test_event_is_accepted(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)

        assert event.isAccepted()

    def test_event_accepted_even_when_threadpool_raises(self, shell_window):
        _attach_pages(shell_window)
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            mock_pool_cls.globalInstance.side_effect = RuntimeError("boom")
            shell_window.closeEvent(event)

        assert event.isAccepted()

    def test_event_accepted_even_when_page_close_raises(self, shell_window):
        _attach_pages(shell_window)
        shell_window.snapshots_5hz_band_page.close.side_effect = RuntimeError("boom")
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)

        assert event.isAccepted()


class TestOrdering:
    def test_threadpool_wait_happens_before_page_close(self, shell_window):
        _attach_pages(shell_window)
        call_order = []

        def record_wait(*args, **kwargs):
            call_order.append("wait")
            return True

        shell_window.data_management_page.close.side_effect = (
            lambda: call_order.append("close")
        )
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            pool = mock_pool_cls.globalInstance.return_value
            pool.activeThreadCount.return_value = 1
            pool.waitForDone.side_effect = record_wait

            shell_window.closeEvent(event)

        assert call_order == ["wait", "close"]

    def test_cleanup_happens_before_event_accept(self, shell_window):
        """event.accept() should come after page cleanup is done."""
        _attach_pages(shell_window)
        call_order = []

        shell_window.data_management_page.close.side_effect = (
            lambda: call_order.append("close")
        )
        event = TrackingCloseEvent(call_order)

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)

        assert "close" in call_order
        assert "accept" in call_order
        assert call_order.index("close") < call_order.index("accept")


class TestWindowGeometry:
    """The window geometry is handed to ShellViewModel first (plan M3.7)."""

    def test_geometry_saved_once_before_the_threadpool_wait(self, shell_window):
        _attach_pages(shell_window)
        call_order = []
        shell_window.shell_viewmodel = MagicMock()
        shell_window.shell_viewmodel.remember_window_geometry.side_effect = (
            lambda blob, screen_name: call_order.append(("save", type(blob), type(screen_name))))
        event = QCloseEvent()

        with patch("main.QThreadPool") as mock_pool_cls:
            pool = mock_pool_cls.globalInstance.return_value
            pool.activeThreadCount.return_value = 1
            pool.waitForDone.side_effect = lambda *args: call_order.append("wait") or True

            shell_window.closeEvent(event)

        assert call_order == [("save", bytes, str), "wait"]
        blob, screen_name = shell_window.shell_viewmodel.remember_window_geometry.call_args.args
        assert blob and screen_name == shell_window.screen().name()

    def test_save_failure_does_not_block_the_shutdown(self, shell_window, caplog):
        _attach_pages(shell_window)
        shell_window.shell_viewmodel = MagicMock()
        shell_window.shell_viewmodel.remember_window_geometry.side_effect = RuntimeError("disk full")
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)  # must not raise

        assert event.isAccepted()
        shell_window.data_management_page.close.assert_called_once()
        assert "window geometry" in caplog.text

    def test_bare_window_has_nothing_to_save(self, shell_window):
        assert shell_window.shell_viewmodel is None  # the class default
        event = QCloseEvent()

        with patch("main.QThreadPool"):
            shell_window.closeEvent(event)  # must not raise

        assert event.isAccepted()
