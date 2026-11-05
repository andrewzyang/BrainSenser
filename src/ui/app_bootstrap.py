"""Startup seam shared by ``main()`` and the UI test harness (plan §4.7 lifecycle).

``compose_startup_environment`` (L0) runs before the ``QApplication`` exists: Qt
reads the interface size (``QT_SCALE_FACTOR``) once, when the application is
constructed. It reads the saved sizes from the store it is given: ``main()``
builds the (lazy) DI container first and passes its preferences store.
``configure_application`` (L1) gives a fresh ``QApplication`` the app-wide look
(light appearance, system font, greyscale dialog icons, metadata, window icon,
global stylesheet).
``build_presentation`` (L2–L5) builds the objects the main window is made from:
the DI container, the shell and interface-size ViewModels and the name of the
launch screen; when that screen needs another interface size than L0 composed
(the window's last display is gone), it relaunches the app once instead.
``main()`` and the harness call these same functions, so tests always see the
app exactly as it starts.
"""

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, MutableMapping, Optional, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from src.ui.app_style import apply_app_stylesheet
from src.ui.asset_paths import asset_path
from src.ui.policy.scale import (
    SCALE_DISPLAY, SCALE_RELAUNCH, ZoomState, compose_scale_env, relaunch_scale_env,
)
from src.ui.policy.tokens import TYPE_PX, TypeRole
from src.ui.shell.screen_watcher import read_screen_metrics
from src.ui.shell.window_placement import launch_screen

if TYPE_CHECKING:
    from src.infrastructure.container import ApplicationContainer
    from src.ui.viewmodels import ShellViewModel, UiScaleViewModel

logger = logging.getLogger(__name__)

APP_ICON_PATH = asset_path("brainsenser_app_icon.png")


@dataclass(frozen=True)
class Presentation:
    """Everything the main window is built from."""

    container: "ApplicationContainer"
    shell_viewmodel: "ShellViewModel"
    ui_scale_viewmodel: "UiScaleViewModel"
    # The screen the splash and the main window open on, by name: each looks it
    # up as it opens (launch_screen), since a display can be unplugged meanwhile.
    launch_screen_name: str


class StartupPreferences(Protocol):
    """What L0 reads: the saved interface sizes and the window's last screen."""

    def load_zoom_steps(self) -> dict[str, int]: ...

    def load_last_screen(self) -> Optional[str]: ...


def compose_startup_environment(store: StartupPreferences,
                                environ: MutableMapping[str, str] = os.environ) -> None:
    """L0, before the ``QApplication`` exists: put the interface size saved in
    ``store`` for the display the window was last on into ``environ`` as
    ``QT_SCALE_FACTOR``.

    ``compose_scale_env`` decides: Qt scaling the user or IT set is left alone,
    ``BRAINSENSER_UI_SCALE=1`` turns the interface size off, and the app's own
    factor from before a restart is replaced. After a relaunch for the display
    the app opened on (:func:`build_presentation`), that display's size is
    composed instead. Unreadable preferences start the app at 100 %.
    """
    try:
        steps, last_screen = store.load_zoom_steps(), store.load_last_screen()
    except Exception:
        logger.exception("Could not read the interface size; starting at 100 %")
        steps, last_screen = {}, None
    launch_display = environ.get(SCALE_RELAUNCH, last_screen)
    _replace_environment(environ, compose_scale_env(steps, environ, launch_display=launch_display))


def configure_application(app: QApplication) -> None:
    """Apply the app-wide look and metadata to a freshly created ``QApplication``.

    Call it before any window exists, so the first widget is already polished
    with the light appearance and the app font.
    """
    # Always the light appearance (D20): the sidebar and top bar paint no
    # background of their own and the stylesheet sets dark text, so a dark
    # system appearance would show through them (shell:SH-11).
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    # The system UI font at the body size. The stylesheet names no family, so
    # every widget gets this one; text measured with the app font now matches
    # the `* { font-size }` rule.
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPixelSize(TYPE_PX[TypeRole.BODY])
    app.setFont(font)

    # Greyscale the standard dialog severity icons (the red/blue QMessageBox
    # glyphs) to match the app's manuscript palette. QSS cannot recolour
    # standard icons, so we wrap the application style. See GreyscaleProxyStyle.
    from src.ui.greyscale_proxy_style import install_greyscale_dialog_icons
    install_greyscale_dialog_icons(app)

    app.setApplicationName("iEEG BrainSense")
    app.setOrganizationName("iEEG BrainSense Development Team")
    app.setApplicationVersion("1.0.0")  # also VERSION in packaging/brainsenser.spec

    # Dock / taskbar icon. On macOS, QGuiApplication.setWindowIcon also sets
    # the icon shown in the Dock for the running process.
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    else:
        logger.warning(f"App icon not found: {APP_ICON_PATH}")

    apply_app_stylesheet(app)


def build_presentation(container: Optional["ApplicationContainer"] = None) -> Presentation:
    """Build the presentation objects; a fresh DI container unless one is given.

    The container is shared with the splash ViewModel and the main window so
    PathResolver/SQLiteAdapter singletons stay consistent across both. The
    shell ViewModel restores its preferences (emitting nothing), the launch
    screen is picked from them, and the interface-size ViewModel learns that
    display before anything listens to it. If L0 composed the interface size
    for another display and this one needs another size, the app relaunches
    once, before any window exists (:func:`relaunch_scale_env`). Needs the
    ``QApplication``.
    """
    if container is None:
        from src.infrastructure.container import ApplicationContainer
        container = ApplicationContainer()
    shell_viewmodel = container.shell_viewmodel()
    screen = launch_screen(shell_viewmodel.last_screen_name)
    ui_scale_viewmodel = container.ui_scale_viewmodel()
    ui_scale_viewmodel.set_current_display(read_screen_metrics(screen))
    _relaunch_for_the_launch_display(container, ui_scale_viewmodel.state)
    return Presentation(container=container, shell_viewmodel=shell_viewmodel,
                        ui_scale_viewmodel=ui_scale_viewmodel, launch_screen_name=screen.name())


def _relaunch_for_the_launch_display(container: "ApplicationContainer", state: ZoomState) -> None:
    """Relaunch once, through the container's restarter, if the launch display
    (``state``) needs another interface size than L0 composed. Returns when no
    relaunch is needed, or when the new instance could not be started; with no
    event loop running yet, the restarter otherwise ends this process."""
    environ = container.startup_environment()
    relaunch = relaunch_scale_env(environ, state)
    environ.pop(SCALE_RELAUNCH, None)  # handled: a later restart composes afresh
    if relaunch is None:
        return
    logger.info("Opening on %r, not on %r: restarting once at its interface size, %s",
                state.display, environ.get(SCALE_DISPLAY), state.label)
    started_with = dict(environ)
    _replace_environment(environ, relaunch)
    container.app_restarter().restart()
    _replace_environment(environ, started_with)  # not restarted: carry on at this size


def _replace_environment(environ: MutableMapping[str, str], values: Mapping[str, str]) -> None:
    """Make ``environ`` equal to ``values``, in place (``os.environ`` stays the
    process environment)."""
    for name in set(environ) - set(values):
        del environ[name]
    environ.update(values)
