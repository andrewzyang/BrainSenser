"""Restarting the application, so a new interface size takes effect.

QProcessAppRestarter implements the AppRestarter port: it starts a new,
independent instance of the app with this process's environment and quits this
one. The bootstrap composed that environment before QApplication existed
(``src.ui.policy.scale.compose_scale_env``), marker included, so the new
instance's bootstrap replaces the interface size with the saved one.

- Development: the same interpreter with the same command line, in the same
  working directory.
- Frozen (PyInstaller): the bundle's executable with its arguments, plus
  ``PYINSTALLER_RESET_ENVIRONMENT=1`` so its bootloader starts a new instance
  rather than a worker of this one, whose onefile files are deleted on exit.

Order: a running app quits first. Quitting closes the windows, which save
their state (window geometry and screen, which the new instance's start-up
reads); only once the event loop has ended (``aboutToQuit``) does the new
instance start. If it can't be started then, the error is logged and the app
is gone. Before the event loop runs (start-up) no window has state to save:
the new instance starts at once and this process exits, or, if it can't be
started, this one carries on.
"""

import logging
import os
import sys
from typing import Callable, Mapping, Optional, Protocol, Sequence

from PySide6.QtCore import QCoreApplication, QProcess, QProcessEnvironment, Qt, QThread

logger = logging.getLogger(__name__)

# launch(program, arguments, environment, working_directory) -> started
Launcher = Callable[[str, Sequence[str], Mapping[str, str], str], bool]


def start_detached(program: str, arguments: Sequence[str], environment: Mapping[str, str],
                   working_directory: str) -> bool:
    """Start ``program`` as an independent process with exactly ``environment``."""
    process_environment = QProcessEnvironment()
    for name, value in environment.items():
        process_environment.insert(name, value)
    process = QProcess()
    process.setProgram(program)
    process.setArguments(list(arguments))
    process.setWorkingDirectory(working_directory)
    process.setProcessEnvironment(process_environment)
    return process.startDetached()


def relaunch_command() -> tuple[str, list[str]]:
    """The program and arguments that start this application again."""
    if getattr(sys, "frozen", False):
        return sys.executable, sys.argv[1:]
    return sys.executable, sys.orig_argv[1:]


class AppLifecycle(Protocol):
    """The application's lifecycle, as far as restarting it goes."""

    def running(self) -> bool:
        """Whether the event loop runs (False during start-up)."""

    def quit_then(self, callback: Callable[[], None]) -> None:
        """Quit; ``callback`` runs once, after the event loop has ended."""

    def exit(self) -> None:
        """End the process; for start-up, before the event loop runs."""


class QtAppLifecycle:
    """The QCoreApplication's lifecycle."""

    def running(self) -> bool:
        return QThread.currentThread().loopLevel() > 0

    def quit_then(self, callback: Callable[[], None]) -> None:
        # aboutToQuit follows the windows' closeEvent, so their state is saved by then.
        app = QCoreApplication.instance()
        app.aboutToQuit.connect(callback, Qt.ConnectionType.SingleShotConnection)
        app.quit()

    def exit(self) -> None:
        sys.exit(0)


class QProcessAppRestarter:
    """Starts a new instance and quits this one, in that order only before the
    event loop runs. ``launch`` and ``lifecycle`` default to
    :func:`start_detached` and :class:`QtAppLifecycle`."""

    def __init__(self, launch: Optional[Launcher] = None,
                 lifecycle: Optional[AppLifecycle] = None) -> None:
        self._launch = launch or start_detached
        self._lifecycle = lifecycle or QtAppLifecycle()
        self._pending: Optional[tuple[str, list[str], dict[str, str], str]] = None

    def restart(self) -> None:
        if self._pending is not None:
            return  # already quitting; the new instance starts once that is done
        program, arguments = relaunch_command()
        environment = dict(os.environ)
        if getattr(sys, "frozen", False):
            environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        command = (program, arguments, environment, os.getcwd())
        if self._lifecycle.running():
            logger.info("Restarting: quitting first, then starting a new instance of %s", program)
            self._pending = command
            self._lifecycle.quit_then(self._start_pending)
        elif self._start(*command):
            self._lifecycle.exit()

    def _start_pending(self) -> None:
        command, self._pending = self._pending, None
        self._start(*command)

    def _start(self, program: str, arguments: list[str], environment: dict[str, str],
               working_directory: str) -> bool:
        if self._launch(program, arguments, environment, working_directory):
            logger.info("Restarting: started a new instance of %s", program)
            return True
        logger.error("Could not start a new instance of %s", program)
        return False
