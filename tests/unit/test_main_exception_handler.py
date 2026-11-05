"""
Tests for main._install_exception_handler.

Verifies the global exception hook correctly:
  - Installs itself on sys.excepthook
  - Delegates KeyboardInterrupt and SystemExit to sys.__excepthook__
  - Logs regular exceptions with full traceback via logging.critical
  - Shows a QMessageBox only when a QApplication is running
  - Does not crash if logging or the dialog itself raises
"""

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

import main


@pytest.fixture(autouse=True)
def restore_excepthook():
    """Restore sys.excepthook after every test."""
    original = sys.excepthook
    yield
    sys.excepthook = original


def _trigger(exc):
    """Call the currently-installed sys.excepthook with a real exc_info tuple."""
    try:
        raise exc
    except type(exc):
        sys.excepthook(*sys.exc_info())


class TestInstall:
    def test_install_replaces_sys_excepthook(self):
        original = sys.excepthook
        main._install_exception_handler()
        assert sys.excepthook is not original
        assert callable(sys.excepthook)


class TestPassThroughSignals:
    def test_keyboardinterrupt_delegates_to_system_excepthook(self):
        main._install_exception_handler()
        with patch.object(sys, "__excepthook__") as mock_orig:
            _trigger(KeyboardInterrupt("user hit ctrl+c"))
            assert mock_orig.called
            args = mock_orig.call_args[0]
            assert args[0] is KeyboardInterrupt

    def test_systemexit_delegates_to_system_excepthook(self):
        main._install_exception_handler()
        with patch.object(sys, "__excepthook__") as mock_orig:
            _trigger(SystemExit(1))
            assert mock_orig.called
            args = mock_orig.call_args[0]
            assert args[0] is SystemExit

    def test_keyboardinterrupt_does_not_log(self, caplog):
        main._install_exception_handler()
        with patch.object(sys, "__excepthook__"):
            with caplog.at_level(logging.CRITICAL):
                _trigger(KeyboardInterrupt())
        assert "Uncaught exception" not in caplog.text


class TestRegularException:
    def test_regular_exception_is_logged_at_critical(self, caplog):
        main._install_exception_handler()
        with patch.object(main.QApplication, "instance", return_value=None):
            with caplog.at_level(logging.CRITICAL):
                _trigger(ValueError("synthetic"))
        assert "Uncaught exception" in caplog.text

    def test_regular_exception_logs_full_traceback(self, caplog):
        main._install_exception_handler()
        with patch.object(main.QApplication, "instance", return_value=None):
            with caplog.at_level(logging.CRITICAL):
                _trigger(RuntimeError("traceback should appear"))
        # caplog.text contains the formatted traceback when exc_info is passed
        assert "RuntimeError" in caplog.text
        assert "traceback should appear" in caplog.text

    def test_does_not_delegate_to_system_excepthook_for_regular_exception(self):
        main._install_exception_handler()
        with patch.object(main.QApplication, "instance", return_value=None):
            with patch.object(sys, "__excepthook__") as mock_orig:
                _trigger(ValueError("regular"))
                assert not mock_orig.called


class TestDialogGating:
    def test_dialog_shown_when_qapplication_exists(self):
        main._install_exception_handler()
        fake_app = MagicMock()
        with patch.object(main.QApplication, "instance", return_value=fake_app):
            with patch.object(main.QMessageBox, "critical") as mock_crit:
                _trigger(ValueError("show dialog"))
                assert mock_crit.called
                dialog_text = mock_crit.call_args[0][2]
                assert "ValueError" in dialog_text
                assert "show dialog" in dialog_text

    def test_dialog_skipped_when_no_qapplication(self):
        main._install_exception_handler()
        with patch.object(main.QApplication, "instance", return_value=None):
            with patch.object(main.QMessageBox, "critical") as mock_crit:
                _trigger(ValueError("no app"))
                assert not mock_crit.called


class TestDefensiveErrorHandling:
    def test_does_not_crash_if_logging_fails(self):
        main._install_exception_handler()
        with patch.object(main.QApplication, "instance", return_value=None):
            with patch("main.logging.critical", side_effect=OSError("disk full")):
                # Must not raise
                _trigger(ValueError("logging broken"))

    def test_does_not_crash_if_dialog_fails(self):
        main._install_exception_handler()
        fake_app = MagicMock()
        with patch.object(main.QApplication, "instance", return_value=fake_app):
            with patch.object(
                main.QMessageBox, "critical", side_effect=RuntimeError("no display")
            ):
                # Must not raise
                _trigger(ValueError("dialog broken"))

    def test_does_not_crash_if_both_fail(self):
        main._install_exception_handler()
        fake_app = MagicMock()
        with patch.object(main.QApplication, "instance", return_value=fake_app):
            with patch("main.logging.critical", side_effect=OSError("log down")):
                with patch.object(
                    main.QMessageBox, "critical", side_effect=RuntimeError("dlg down")
                ):
                    # Must not raise
                    _trigger(ValueError("both broken"))
