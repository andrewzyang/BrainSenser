"""main()'s launch flow (plan M1.4, D19; shell SH-16).

The splash plays on the launch screen; when it ends (here: a click skips it)
the main window is built later, from the event loop, never inside the splash's
input handler; the splash stays up until the window is shown and closes even
when building the window fails, so no error dialog can open behind it; the
initial data loads only after the window is shown. Reduce motion or a missing
video skips the splash.

main() runs for real, with stand-ins only for what needs a fresh process (the
QApplication and its look) or real data (the container and the main window);
the splash is the real SplashView over a stand-in ViewModel. The splash looks
the launch screen up by the name the presentation gives.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

import main
import src.infrastructure.container as container_module
import src.ui.app_bootstrap as app_bootstrap
from src.infrastructure.preferences import InMemoryUiPreferences
from src.ui.views.splash import splash_view
from src.ui.views.splash.splash_view import SplashView


class _SplashViewModel(QObject):
    """Stand-in for SplashViewModel: no media; ``skip()`` ends the splash."""

    closed = Signal()
    player = None

    def __init__(self, video_available: bool):
        super().__init__()
        self._video_available = video_available
        self.prepared = self.playing = False

    def prepare(self) -> bool:
        self.prepared = True
        return self._video_available

    def start_playback(self) -> None:
        self.playing = True

    def skip(self) -> None:
        self.closed.emit()


def _visible_splash():
    return next((w for w in QApplication.topLevelWidgets()
                 if isinstance(w, SplashView) and w.isVisible()), None)


@pytest.fixture
def launch(qtbot, monkeypatch):
    """``launch(scenario, ...)`` runs main() and returns (viewmodel, events); the
    scenario, called with both, stands in for the event loop."""
    events = []
    windows = []

    class _MainWindow(QMainWindow):
        fails = False

        def __init__(self, presentation):
            events.append(("built", _visible_splash() is not None))
            if self.fails:
                raise RuntimeError("the database could not be opened")
            super().__init__()
            windows.append(self)

        def show_at_launch(self):
            self.show()

        def showEvent(self, event):
            events.append(("shown", _visible_splash() is not None))
            super().showEvent(event)

        def _load_initial_data(self):
            events.append(("loaded", self.isVisible()))

    def run(scenario, *, video_available=True, reduce_motion=False, window_fails=False):
        viewmodel = _SplashViewModel(video_available)

        class _Application:
            """main()'s QApplication: the session's own; exec() runs the scenario."""

            setHighDpiScaleFactorRoundingPolicy = staticmethod(lambda policy: None)

            def __init__(self, argv):
                pass

            def exec(self):
                scenario(viewmodel, events)
                return 0

        _MainWindow.fails = window_fails
        # L0 runs for real, on an empty store and an environment of its own
        environment = {}
        container = SimpleNamespace(splash_viewmodel=lambda: viewmodel,
                                    ui_preferences=InMemoryUiPreferences,
                                    startup_environment=lambda: environment)
        monkeypatch.setattr(main, "_install_exception_handler", lambda: None)
        monkeypatch.setattr(main, "QApplication", _Application)
        monkeypatch.setattr(main, "MainWindow", _MainWindow)
        monkeypatch.setattr(container_module, "ApplicationContainer", lambda: container)
        monkeypatch.setattr(app_bootstrap, "configure_application", lambda app: None)
        monkeypatch.setattr(
            app_bootstrap, "build_presentation",
            lambda built: SimpleNamespace(
                container=built, launch_screen_name=QApplication.primaryScreen().name()))
        monkeypatch.setattr(splash_view, "motion_reduced", lambda: reduce_motion)
        with pytest.raises(SystemExit) as exited:
            main.main()
        assert exited.value.code == 0
        return viewmodel, events

    yield run
    for window in windows:
        window.close()
        window.deleteLater()


def test_skipping_the_splash_launches_the_window_from_the_event_loop(launch, qtbot):
    def scenario(viewmodel, events):
        splash = _visible_splash()
        qtbot.addWidget(splash)
        assert splash.screen() is QApplication.primaryScreen()  # the launch screen here
        QTest.mouseClick(splash, Qt.MouseButton.LeftButton)
        events.append(("click handled", None))
        qtbot.waitUntil(lambda: ("loaded", True) in events)
        assert not splash.isVisible()

    viewmodel, events = launch(scenario)
    assert viewmodel.playing
    # Built after the click handler returned, while the splash still covered the
    # screen; the splash closed once the window was shown; data loaded after that.
    assert events == [("click handled", None), ("built", True), ("shown", True), ("loaded", True)]


def test_the_splash_closes_when_building_the_window_fails(launch, qtbot):
    def scenario(viewmodel, events):
        splash = _visible_splash()
        qtbot.addWidget(splash)
        with qtbot.captureExceptions() as exceptions:
            viewmodel.skip()
            qtbot.waitUntil(lambda: not splash.isVisible())
            qtbot.waitUntil(lambda: bool(exceptions))
        assert [type(e[1]) for e in exceptions] == [RuntimeError]
        assert events == [("built", True)]  # never shown, nothing loaded

    launch(scenario, window_fails=True)


@pytest.mark.parametrize("reduce_motion, video_available", [(True, True), (False, False)])
def test_no_splash_under_reduce_motion_or_without_the_video(launch, qtbot, reduce_motion,
                                                            video_available):
    def scenario(viewmodel, events):
        qtbot.waitUntil(lambda: ("loaded", True) in events)
        assert events == [("built", False), ("shown", False), ("loaded", True)]

    viewmodel, _events = launch(scenario, reduce_motion=reduce_motion,
                                video_available=video_available)
    assert viewmodel.prepared == (not reduce_motion)  # no media player under Reduce motion
    assert not viewmodel.playing


def test_main_window_construction_leaves_loading_to_the_launch(qtbot, monkeypatch):
    """The real window: no data is loaded while it is built (a load error's dialog
    would have no visible window), and it gets the D3 floor."""
    from src.ui.app_bootstrap import build_presentation
    from src.ui.viewmodels.app_viewmodel import AppViewModel

    loads = []
    monkeypatch.setattr(AppViewModel, "load_patients", lambda self: loads.append(self))
    window = main.MainWindow(container=build_presentation().container)
    qtbot.addWidget(window)
    assert loads == []
    assert window.minimumSize() == QSize(600, 500)
    window._load_initial_data()
    assert loads == [window.app_viewmodel]
