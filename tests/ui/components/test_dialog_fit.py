"""
Tests for ``src.ui.components.dialog_fit``: message boxes that fit their screen
(long text moves under "Show Details…"), the 90 % screen cap, the exception
hook's report, and the dialogs that use them (MainWindow._show_error /
_show_success, the five views' ``_on_error``, the ML progress dialog).

No dialog is ever run modally: ``QMessageBox.exec`` is replaced by a recorder.
The "fits a 576-px screen" check runs in a fresh offscreen process that
emulates Windows 1366×768 at 125 % (1093×576 logical px).
"""

import logging
import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout, QWidget

import main
from src.infrastructure import logging_setup
from src.ui.components.dialog_fit import (
    ELLIPSIS,
    SCREEN_SHARE,
    clamp_to_screen,
    message_box,
    screen_limit,
    show_message,
)
from src.ui.components.ml_progress_dialog import MlProgressDialog
from src.ui.policy.tokens import Dim
from src.ui.views.data_management.data_management_page import DataManagementPage
from src.ui.views.snapshots_5hz_band.snapshots_5hz_band_view import Snapshots5HzBandView
from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView
from src.ui.views.timeline_lfp_threshold.timeline_lfp_threshold_view import (
    TimelineLfpThresholdView,
)
from src.ui.views.timeline_peri_event.timeline_peri_event_view import TimelinePeriEventView
from tests.ui.scaling._app_process import AppProcess, DisplayProfile

FORTY_LINES = "\n".join(f"Line {i}: file Report_{i:04d}.json was skipped (duplicate)."
                        for i in range(1, 41))

# Windows 1366×768 at 125 %: 1093×576 logical px.
WIN125 = DisplayProfile(
    name="win125",
    screen={"name": "1366x768@125", "x": 0, "y": 0, "width": 1366, "height": 720,
            "logicalDpi": 120, "logicalBaseDpi": 96},
)


def _shown_title(title: str) -> str:
    """What ``windowTitle()`` reads back: QMessageBox drops titles on macOS."""
    return "" if sys.platform == "darwin" else title


@pytest.fixture
def shown_boxes(monkeypatch):
    """Every QMessageBox that would run modally, in order (exec returns at once)."""
    boxes = []

    def record(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", record)
    return boxes


def _host(qtbot) -> QWidget:
    host = QWidget()
    qtbot.addWidget(host)
    return host


# --------------------------------------------------------------- message_box

def test_short_text_is_shown_as_is(qtbot):
    host = _host(qtbot)
    box = message_box(host, QMessageBox.Icon.Critical, "Error", "Patient not found.")

    assert box.text() == "Patient not found."
    assert box.detailedText() == ""
    assert box.textFormat() == Qt.TextFormat.PlainText


def test_long_text_moves_under_show_details(qtbot):
    host = _host(qtbot)
    box = message_box(host, QMessageBox.Icon.Critical, "Error", FORTY_LINES)

    summary = box.text()
    assert summary.endswith("\n" + ELLIPSIS)
    assert FORTY_LINES.startswith(summary[:-len(ELLIPSIS)])
    assert summary.count("\n") < FORTY_LINES.count("\n")
    assert box.detailedText() == FORTY_LINES


def test_one_overlong_paragraph_is_cut_short(qtbot):
    text = "word " * 3000
    host = _host(qtbot)

    box = message_box(host, QMessageBox.Icon.Critical, "Error", text)

    assert box.text().endswith(ELLIPSIS)
    assert len(box.text()) < len(text) // 2
    assert box.detailedText() == text


def test_details_follow_the_overflow(qtbot):
    host = _host(qtbot)

    short = message_box(host, QMessageBox.Icon.Critical, "Error", "Failed.", details="trace")
    long = message_box(host, QMessageBox.Icon.Critical, "Error", FORTY_LINES, details="trace")

    assert (short.text(), short.detailedText()) == ("Failed.", "trace")
    assert long.detailedText() == FORTY_LINES + "\n\ntrace"


def test_show_message_runs_the_fitted_box(qtbot, shown_boxes):
    host = _host(qtbot)

    result = show_message(host, QMessageBox.Icon.Information, "Success", FORTY_LINES)

    assert result == QMessageBox.StandardButton.Ok
    (box,) = shown_boxes
    assert (box.parent(), box.windowTitle(), box.icon()) == (
        host, _shown_title("Success"), QMessageBox.Icon.Information)
    assert box.detailedText() == FORTY_LINES


# ---------------------------------------------------------- the 90 % screen cap

class _Sized(QWidget):
    def __init__(self, hint: QSize):
        super().__init__()
        self._hint = hint

    def sizeHint(self) -> QSize:
        return self._hint


def _dialog(qtbot, content_hint: QSize) -> QDialog:
    dialog = QDialog()
    QVBoxLayout(dialog).addWidget(_Sized(content_hint))
    qtbot.addWidget(dialog)
    return dialog


def test_screen_limit_is_90_percent_of_the_available_size(qtbot):
    host = _host(qtbot)
    available = host.screen().availableGeometry().size()

    assert screen_limit(host) == QSize(round(available.width() * SCREEN_SHARE),
                                       round(available.height() * SCREEN_SHARE))


def test_clamp_to_screen_caps_a_huge_dialog(qtbot):
    dialog = _dialog(qtbot, QSize(9000, 9000))

    clamp_to_screen(dialog)

    assert dialog.size() == screen_limit(dialog)


def test_clamp_to_screen_keeps_a_small_dialog_at_its_size_hint(qtbot):
    dialog = _dialog(qtbot, QSize(200, 100))

    clamp_to_screen(dialog)

    assert dialog.size() == dialog.sizeHint()


def test_progress_dialog_width_follows_its_step_font(qtbot):
    dialog = MlProgressDialog()
    qtbot.addWidget(dialog)

    dialog.start("Permutation 10/1000")
    assert dialog.width() == Dim.DIALOG_W  # 30 em of the 12-px step font

    dialog.reset()
    dialog._step_label.setStyleSheet("font-size: 16px;")
    dialog.start("Permutation 10/1000")
    assert dialog.width() == 480


def test_progress_dialog_stays_within_90_percent_of_the_screen(qtbot):
    dialog = MlProgressDialog()
    qtbot.addWidget(dialog)
    dialog._step_label.setStyleSheet("font-size: 60px;")

    dialog.start("Permutation 10/1000")

    assert dialog.width() == screen_limit(dialog).width()


# ------------------------------------------------- dialogs that use show_message

def _error_host(qtbot) -> QWidget:
    host = _host(qtbot)
    host.grouping_panel = MagicMock()
    host.progress_dialog = MagicMock()
    return host


@pytest.mark.parametrize("on_error, title", [
    (TimelineLfpThresholdView._on_error, "Analysis Error"),
    (TimelinePeriEventView._on_error, "Analysis Error"),
    (SnapshotsPsdView._on_error, "Analysis Error"),
    (Snapshots5HzBandView._on_error, "Analysis Error"),
    (DataManagementPage._on_error, "Error"),
], ids=["lfp_threshold", "peri_event", "psd", "5hz_band", "data_management"])
def test_views_on_error_fit_long_messages(qtbot, shown_boxes, on_error, title):
    host = _error_host(qtbot)

    on_error(host, FORTY_LINES)

    (box,) = shown_boxes
    assert (box.parent(), box.windowTitle(), box.icon()) == (
        host, _shown_title(title), QMessageBox.Icon.Critical)
    assert box.detailedText() == FORTY_LINES


@pytest.mark.parametrize("method, title, icon", [
    (main.MainWindow._show_error, "Error", QMessageBox.Icon.Critical),
    (main.MainWindow._show_success, "Success", QMessageBox.Icon.Information),
], ids=["error", "success"])
def test_main_window_messages_fit_long_text(qtbot, shown_boxes, method, title, icon):
    host = _host(qtbot)

    method(host, FORTY_LINES)

    (box,) = shown_boxes
    assert (box.parent(), box.windowTitle(), box.icon()) == (host, _shown_title(title), icon)
    assert box.detailedText() == FORTY_LINES


# ------------------------------------------------------------- exception hook

@pytest.fixture
def exception_hook():
    original = sys.excepthook
    main._install_exception_handler()
    yield
    sys.excepthook = original


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAINSENSER_DATA_DIR", str(tmp_path))
    path = logging_setup.configure_logging()
    yield path
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == logging_setup._HANDLER_NAME:
            root.removeHandler(handler)
            handler.close()


def _raise_uncaught(exc):
    try:
        raise exc
    except type(exc):
        sys.excepthook(*sys.exc_info())


def test_exception_hook_reports_over_the_active_window(qtbot, monkeypatch, exception_hook,
                                                       log_file):
    window = _host(qtbot)
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: window))
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(opened.append))
    boxes = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: boxes.append(box) or 0)
    # The user presses "Open Log Folder" (the box is never run, so nothing is clicked).
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: next(
        b for b in box.buttons() if b.text() == "Open Log Folder"))

    _raise_uncaught(ValueError("synthetic failure"))

    (box,) = boxes
    assert box.parent() is window
    assert box.windowTitle() == _shown_title("Unexpected Error")
    assert box.text().startswith("An unexpected error occurred (ValueError).")
    assert "synthetic failure" in box.text()
    assert "written to the log" in box.text()
    assert "Traceback (most recent call last)" in box.detailedText()
    assert "ValueError: synthetic failure" in box.detailedText()
    assert opened == [QUrl.fromLocalFile(str(log_file.parent))]
    assert "synthetic failure" in log_file.read_text(encoding="utf-8")


def test_exception_hook_without_a_log_file_offers_no_folder(qtbot, monkeypatch,
                                                            exception_hook, shown_boxes):
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))

    _raise_uncaught(RuntimeError("synthetic failure"))

    (box,) = shown_boxes
    assert "Open Log Folder" not in [b.text() for b in box.buttons()]
    assert "written to the log" not in box.text()
    assert "RuntimeError: synthetic failure" in box.detailedText()


# ----------------------------------------------- a 40-line message, 576-px screen

@pytest.mark.qt_subprocess
def test_forty_lines_fit_a_576_px_screen(tmp_path):
    # This folder is no package, so pytest imports this file as a top-level
    # module; the child imports it by its dotted path (a namespace package).
    result = AppProcess("tests.ui.components.test_dialog_fit:measure_forty_line_box", None,
                        WIN125, tmp_path).result()

    assert result["available_height"] == 576
    limit = SCREEN_SHARE * result["available_height"]
    assert result["collapsed_height"] <= limit
    assert result["expanded_height"] <= limit  # with "Show Details…" open
    assert result["details"] == FORTY_LINES


def measure_forty_line_box(_payload) -> dict:
    """Child side: show the box non-modally, measure it, then open its details."""
    box = message_box(None, QMessageBox.Icon.Critical, "Error", FORTY_LINES)
    box.show()
    QApplication.processEvents()
    collapsed = box.frameGeometry().height()
    next(b for b in box.buttons() if b.text().startswith("Show Details")).click()
    QApplication.processEvents()
    return {"available_height": box.screen().availableGeometry().height(),
            "collapsed_height": collapsed,
            "expanded_height": box.frameGeometry().height(),
            "details": box.detailedText()}


# ------------------------------- the application's screen outlives fitted dialogs

@pytest.mark.qt_subprocess
def test_dialogs_freed_by_the_cycle_collector_leave_the_screen_alive(tmp_path):
    # Looked up with QWidget.screen(), the screen's wrapper became a child of each
    # dialog in turn; freeing two such pages through the cycle collector deleted
    # the application's QScreen, and hiding the next window segfaulted.
    result = AppProcess("tests.ui.components.test_dialog_fit:free_pages_with_fitted_dialogs",
                        None, DisplayProfile(name="default_screen"), tmp_path).result()

    assert result == {"screens": 1, "probe_hidden": True}


def free_pages_with_fitted_dialogs(_payload) -> dict:
    """Child side: two pages fit a progress dialog and a message box to the screen,
    then only the cycle collector can free them; hiding a window reads the screen."""
    import gc

    def page() -> QWidget:
        host = QWidget()
        host.progress_dialog = MlProgressDialog(host)
        host.progress_dialog.start("PSD curves")
        host.box = message_box(host, QMessageBox.Icon.Information, "Saved", "Done.")
        host.cycle = host
        return host

    gc.disable()  # one collection, below
    pages = [page(), page()]
    del pages
    gc.collect()
    gc.enable()
    probe = QWidget()
    probe.show()
    probe.hide()  # the offscreen platform reads the cursor position on the primary screen
    return {"screens": len(QApplication.screens()), "probe_hidden": not probe.isVisible()}
