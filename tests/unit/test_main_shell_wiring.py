"""MainWindow's shell wiring and the start-up lifecycle (plan §4.7 L0–L10, R2, R7).

``_connect_shell_signals`` runs on a bare MainWindow (``__new__`` +
``QMainWindow.__init__``, as in test_main_window_shutdown.py) holding the real
shell — Sidebar, TopBar, MainLayout with its ResponsiveContext — and the real
ViewModels over an in-memory store: each state is applied before anything is
emitted, the window class drives the sidebar through ShellViewModel, the footer
toggle and View ▸ Sidebar reach it, the title names the page, the display is
reported from the first show, the ViewModels outlive the window. The window
looks its launch screen up by name when it opens (a display unplugged during
the splash falls back). L0 composes the interface size into the environment
before the QApplication exists, from the DI container's store; the first frame
of a maximised launch already has the maximised size's classes, and Restart
Now starts the new instance only after the window saved its geometry and
screen (each in a fresh offscreen process).
"""

import base64
import inspect
import json
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from dependency_injector import providers
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, SIGNAL
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMainWindow, QToolButton, QWidget

import main
import src.infrastructure.container as container_module
import src.ui.app_bootstrap as app_bootstrap
from main import MainWindow
from src.infrastructure.preferences import InMemoryUiPreferences, QSettingsUiPreferences
from src.ui.app_bootstrap import compose_startup_environment
from src.ui.components import Sidebar, TopBar
from src.ui.layouts import MainLayout
from src.ui.policy.layout import classify_window
from src.ui.policy.scale import (
    QT_SCALE_FACTOR, SCALE_DISPLAY, SCALE_INJECTED, SCALE_RELAUNCH, UI_SCALE_KILL_SWITCH,
    ScreenMetrics,
)
from src.ui.viewmodels import ShellViewModel, UiScaleViewModel
from tests.ui.responsive import runner
from tests.ui.responsive.profiles import PROFILES

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGES = ("data_management", "timeline_lfp_threshold", "timeline_peri_event",
         "snapshots_canonical_bands", "snapshots_5hz_band")


class _Restarter:
    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1


def _recorder(*signals):
    received = []
    for signal in signals:
        signal.connect(received.append)
    return received


@pytest.fixture
def store():
    return InMemoryUiPreferences()


@pytest.fixture
def viewmodels(store):
    return ShellViewModel(store), UiScaleViewModel(store, _Restarter(), active_factor=1.0)


@pytest.fixture
def at_125(store):
    """ViewModels of a session started at the 125 % saved for the screen."""
    store.zoom_steps = {QGuiApplication.primaryScreen().name(): 3}
    return ShellViewModel(store), UiScaleViewModel(store, _Restarter(), active_factor=1.25)


def _bare_window(qtbot, viewmodels):
    """A MainWindow with the real shell and no pages' content, not wired yet."""
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    qtbot.addWidget(window)
    window.sidebar = Sidebar()
    window.top_bar = TopBar()
    window.main_layout = MainLayout(window.sidebar, window.top_bar)
    for page in PAGES:
        window.main_layout.add_page(page, QWidget())
    window.main_layout.switch_page("data_management")
    window.setCentralWidget(window.main_layout)
    window.shell_viewmodel, window.ui_scale_viewmodel = viewmodels
    window._presentation = SimpleNamespace(
        launch_screen_name=QGuiApplication.primaryScreen().name())
    return window


@pytest.fixture
def wired(qtbot, viewmodels):
    window = _bare_window(qtbot, viewmodels)
    window._connect_shell_signals()
    return window


# -------------------------------------------------------------- read, then connect

def test_saved_icons_preference_shows_the_rail_before_anything_emits(qtbot, store, viewmodels):
    store.sidebar_preference = "icons"
    viewmodels = (ShellViewModel(store), viewmodels[1])
    shell_vm, scale_vm = viewmodels
    emitted = _recorder(shell_vm.sidebar_mode_changed, shell_vm.sidebar_preference_changed,
                        scale_vm.state_changed)
    window = _bare_window(qtbot, viewmodels)

    window._connect_shell_signals()

    assert window.sidebar.mode == "icons"
    assert window.shell_actions.sidebar_actions["icons"].isChecked()
    assert emitted == []


def test_the_window_class_drives_the_sidebar(wired, qtbot):
    wired.resize(1000, 700)
    wired.show()
    qtbot.waitExposed(wired)
    assert wired.sidebar.mode == "icons"  # 1000 px: narrow

    wired.resize(1400, 800)
    qtbot.waitUntil(lambda: wired.sidebar.mode == "labels")
    assert wired.shell_viewmodel.sidebar_mode == "labels"


def test_footer_toggle_is_a_session_override(wired, store):
    toggle = next(b for b in wired.sidebar.findChildren(QToolButton, "sidebar_footer_button")
                  if b.toolTip() == "Collapse Sidebar")
    toggle.click()
    assert wired.sidebar.mode == "icons"
    assert store.sidebar_preference is None  # not saved


def test_view_sidebar_choice_is_saved(wired, store):
    wired.shell_actions.sidebar_actions["icons"].trigger()
    assert wired.sidebar.mode == "icons"
    assert store.sidebar_preference == "icons"


def test_title_names_the_page(wired):
    assert wired.windowTitle() == "BrainSenser — Data Management"
    wired.main_layout.switch_page("timeline_peri_event")
    assert wired.windowTitle() == "BrainSenser — Timeline: Peri-Event"


def test_aa_button_and_banner_are_in_the_shell(wired, qtbot):
    interface = next(b for b in wired.sidebar.findChildren(QToolButton, "sidebar_footer_button")
                     if b.accessibleName() == "Interface Size")
    banner = wired.shell_actions.banner
    assert interface.isVisibleTo(wired.sidebar) and interface.text() == "Aa"
    assert wired.main_layout.isAncestorOf(banner)
    wired.resize(1280, 769)
    wired.show()
    qtbot.waitExposed(wired)
    wired.ui_scale_viewmodel.zoom_in()
    assert interface.text() == "Aa 110 %"
    assert banner.isVisible()


def test_a_banner_due_at_start_up_is_placed_shown(qtbot, viewmodels):
    """A D2 offer known before the window exists shows in the layout, never as a window."""
    viewmodels[1].set_current_display(ScreenMetrics("uhd", 3840, 2160, 1.0))
    window = _bare_window(qtbot, viewmodels)
    window._connect_shell_signals()
    banner = window.shell_actions.banner
    assert not banner.isWindow() and window.main_layout.isAncestorOf(banner)
    assert banner.isVisibleTo(window)


# ------------------------------------------------------------------------ display

def test_display_is_reported_from_the_first_show(qtbot, at_125):
    window = _bare_window(qtbot, at_125)
    window._connect_shell_signals()
    context = window.main_layout.responsive_context
    assert window._screen_watcher is None
    assert window.ui_scale_viewmodel.state.display is None

    window.show()
    qtbot.waitExposed(window)

    assert window._screen_watcher is not None
    state = window.ui_scale_viewmodel.state
    assert state.display == window.screen().name()
    assert (state.chosen_percent, state.restart_required) == (125, False)
    assert context.density.scale == 1.25
    assert window.shell_actions.banner.isHidden()


def test_display_change_is_reported_and_reclassified(wired, qtbot, monkeypatch):
    wired.show()
    qtbot.waitExposed(wired)
    calls = []
    context = wired.main_layout.responsive_context
    monkeypatch.setattr(context, "reclassify_now", lambda: calls.append("reclassify"))

    wired._screen_watcher.display_changed.emit(ScreenMetrics("monitor", 2560, 1440, 1.0))

    assert wired.ui_scale_viewmodel.state.display == "monitor"
    assert calls == ["reclassify"]


def test_viewmodels_outlive_the_window(qtbot, viewmodels):
    window = _bare_window(qtbot, viewmodels)
    window._connect_shell_signals()
    window.show()
    qtbot.waitExposed(window)
    shell_vm, scale_vm = viewmodels
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    shell_vm.set_sidebar_preference("icons")  # nothing of the window may be called
    scale_vm.zoom_in()
    assert shell_vm.sidebar_mode == "icons"


# ------------------------------------------------------------- placement, shutdown

def test_show_at_launch_reopens_the_window_where_it_was(qtbot, store, viewmodels):
    first = _bare_window(qtbot, viewmodels)
    first._connect_shell_signals()
    first.setGeometry(QRect(40, 50, 700, 560))
    first.show()
    qtbot.waitExposed(first)
    first._remember_window_geometry()
    assert store.window_geometry and store.last_screen == first.screen().name()

    again = _bare_window(qtbot, (ShellViewModel(store), viewmodels[1]))
    again._connect_shell_signals()
    again.show_at_launch()
    qtbot.waitExposed(again)
    assert again.geometry() == QRect(40, 50, 700, 560)


def test_first_launch_without_saved_geometry(wired, qtbot):
    wired.show_at_launch()
    qtbot.waitExposed(wired)
    qtbot.waitUntil(wired.isMaximized)  # the session's screen is narrower than 2600 px


def test_a_launch_display_unplugged_during_the_splash_falls_back(qtbot, store, viewmodels):
    """The presentation names the screen picked before the splash; the window
    looks it up as it opens. Stand-in for an unplugged display (offscreen screens
    cannot be removed at run time): a name no screen has any more, with the
    window's memento saved on it. The window opens on the primary screen as on
    first launch, and nothing raises."""
    store.window_geometry, store.last_screen = b"saved on the unplugged display", "Sidecar"
    window = _bare_window(qtbot, (ShellViewModel(store), viewmodels[1]))
    window._presentation = SimpleNamespace(launch_screen_name="Sidecar")
    window._connect_shell_signals()

    window.show_at_launch()

    qtbot.waitExposed(window)
    assert window.screen() is QGuiApplication.primaryScreen()
    qtbot.waitUntil(window.isMaximized)


def test_the_presentation_holds_the_launch_screen_by_name():
    """No QScreen crosses the splash: one deleted with its display would crash."""
    fields = {f.name: f.type for f in app_bootstrap.Presentation.__dataclass_fields__.values()}
    assert fields["launch_screen_name"] is str
    assert "QScreen" not in json.dumps({name: str(kind) for name, kind in fields.items()})


def test_quitting_saves_the_geometry_again(qtbot, viewmodels, store):
    app = QApplication.instance()
    before = app.receivers(SIGNAL("aboutToQuit()"))
    window = _bare_window(qtbot, viewmodels)
    window._connect_shell_signals()
    assert app.receivers(SIGNAL("aboutToQuit()")) == before + 1
    window._remember_window_geometry()
    assert store.window_geometry


def test_shell_wiring_stays_out_of_connect_signals():
    """_connect_signals runs on bare windows in other tests (plan R11)."""
    source = inspect.getsource(MainWindow._connect_signals)
    assert "shell" not in source and "ui_scale" not in source


# --------------------------------------------------------------------------- L0

@pytest.fixture
def saved_size():
    """The adapter's (per-test INI) store with 125 % saved for the last-used display."""
    preferences = QSettingsUiPreferences()
    preferences.save_zoom_steps({"air15": 3})
    preferences.save_window_geometry(b"memento", "air15")
    return preferences


def test_l0_applies_the_size_saved_for_the_last_display(saved_size):
    environ = {"PATH": "/usr/bin"}
    compose_startup_environment(saved_size, environ)
    assert environ == {"PATH": "/usr/bin", QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1",
                       SCALE_DISPLAY: "air15"}


@pytest.mark.parametrize("environ, expected", [
    ({QT_SCALE_FACTOR: "2"}, {QT_SCALE_FACTOR: "2"}),            # the user's or IT's: kept
    ({UI_SCALE_KILL_SWITCH: "1"}, {UI_SCALE_KILL_SWITCH: "1"}),  # the kill switch: nothing added
    ({QT_SCALE_FACTOR: "1.5", SCALE_INJECTED: "1",               # the app's own, across a restart
      SCALE_DISPLAY: "elsewhere"},
     {QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1", SCALE_DISPLAY: "air15"}),
])
def test_l0_respects_the_environment(saved_size, environ, expected):
    compose_startup_environment(saved_size, environ)
    assert environ == expected


def test_l0_drops_its_own_factor_once_the_size_is_back_at_100(saved_size):
    saved_size.save_zoom_steps({"air15": 1})
    environ = {QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1"}
    compose_startup_environment(saved_size, environ)
    assert environ == {SCALE_DISPLAY: "air15"}


def test_l0_reads_the_store_it_is_given():
    """Not the native store: an override (here in memory, the INI left empty) reaches L0."""
    store = InMemoryUiPreferences()
    store.zoom_steps, store.last_screen = {"air15": 4}, "air15"
    environ = {}
    compose_startup_environment(store, environ)
    assert environ == {QT_SCALE_FACTOR: "1.5", SCALE_INJECTED: "1", SCALE_DISPLAY: "air15"}


def test_l0_composes_for_the_display_a_relaunch_names(saved_size):
    """build_presentation relaunched for the laptop: not the saved last screen's size."""
    saved_size.save_zoom_steps({"air15": 3, "laptop": 2})
    environ = {QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1", SCALE_DISPLAY: "air15",
               SCALE_RELAUNCH: "laptop"}
    compose_startup_environment(saved_size, environ)
    assert environ == {QT_SCALE_FACTOR: "1.1", SCALE_INJECTED: "1", SCALE_DISPLAY: "laptop",
                       SCALE_RELAUNCH: "laptop"}


def test_l0_unreadable_preferences_start_at_100(monkeypatch, caplog):
    def broken(_self):
        raise OSError("settings unreadable")

    monkeypatch.setattr(QSettingsUiPreferences, "load_zoom_steps", broken)
    environ = {}
    with caplog.at_level(logging.ERROR):
        compose_startup_environment(QSettingsUiPreferences(), environ)
    assert environ == {} and "interface size" in caplog.text


def test_main_composes_the_environment_from_the_container_before_the_application(monkeypatch):
    """L0 reads the container's store, so a test's or the harness's override reaches it."""
    order = []
    store = InMemoryUiPreferences()
    environment = {}
    container = container_module.ApplicationContainer()
    container.ui_preferences.override(providers.Object(store))
    container.startup_environment.override(providers.Object(environment))

    class _Started(Exception):
        pass

    class _Application:
        setHighDpiScaleFactorRoundingPolicy = staticmethod(lambda policy: None)

        def __init__(self, argv):
            order.append("QApplication")
            raise _Started  # enough: the environment Qt starts with is composed

    monkeypatch.setattr(main, "_install_exception_handler", lambda: None)
    monkeypatch.setattr(main, "QApplication", _Application)
    monkeypatch.setattr(container_module, "ApplicationContainer", lambda: container)
    monkeypatch.setattr(app_bootstrap, "compose_startup_environment",
                        lambda store, environ: order.append(("L0", store, environ)))
    with pytest.raises(_Started):
        main.main()
    assert len(order) == 2 and order[1] == "QApplication"
    assert order[0][0] == "L0" and order[0][1] is store and order[0][2] is environment


# ---------------------------------------------- first frame, maximised launch (subprocess)

@pytest.mark.qt_subprocess
def test_the_first_frame_has_the_maximised_sizes_classes(tmp_path):
    """On the user's Mac (1280×797 available) the window opens maximised from a
    1021-px normal geometry: narrow, then wide. Its first frame already shows the
    labelled sidebar of the wide class."""
    for folder in ("home", "appdata", "cwd"):
        (tmp_path / folder).mkdir()
    qpa = f"offscreen:configfile={PROFILES['mac_air15'].write_qpa_config(tmp_path / 's.json')}"
    code = f"import sys; from {__name__} import _first_frame_child; _first_frame_child(sys.argv[1])"
    result = tmp_path / "result.json"
    done = subprocess.run([sys.executable, "-c", code, str(result)], cwd=tmp_path / "cwd",
                          env=runner.child_environment(tmp_path, qpa, REPO_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and result.exists(), done.stdout[-3000:] + done.stderr[-3000:]
    first = json.loads(result.read_text())
    assert first["normal_width"] < 1120 <= first["width"]
    assert (first["sidebar"], first["class"]) == ("labels", classify_window(first["width"]).value)


class _Bot:
    """Enough of qtbot for _bare_window, in a child process."""

    @staticmethod
    def addWidget(_widget):
        pass


def _first_frame_child(result_path: str) -> None:
    app = QApplication([])
    store = InMemoryUiPreferences()
    viewmodels = (ShellViewModel(store), UiScaleViewModel(store, _Restarter(), active_factor=1.0))
    window = _bare_window(_Bot, viewmodels)
    window._connect_shell_signals()
    first = {}

    class _FirstExpose(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.Expose and not first:
                first.update(width=window.main_layout.width(), sidebar=window.sidebar.mode,
                             normal_width=window.normalGeometry().width(),
                             **{"class": window.main_layout.responsive_context.width_class.value})
            return False

    window.winId()
    spy = _FirstExpose()
    window.windowHandle().installEventFilter(spy)
    window.show_at_launch()
    for _ in range(20):
        app.processEvents()
    Path(result_path).write_text(json.dumps(first))


# ------------------------------------------------- Restart Now saves first (subprocess)

@pytest.mark.qt_subprocess
def test_restart_now_starts_the_new_instance_after_the_window_saved_its_state(tmp_path):
    """Restart Now from the "Aa" menu, with the real restarter (its launcher only
    records) and the real event loop: the app quits, the window closes and saves
    its geometry and screen, and only then is the new instance started — which
    reads those, not the stale ones of an older session."""
    for folder in ("home", "appdata", "cwd"):
        (tmp_path / folder).mkdir()
    code = f"import sys; from {__name__} import _restart_child; _restart_child(sys.argv[1])"
    result = tmp_path / "result.json"
    done = subprocess.run([sys.executable, "-c", code, str(result)], cwd=tmp_path / "cwd",
                          env=runner.child_environment(tmp_path, "offscreen", REPO_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and result.exists(), done.stdout[-3000:] + done.stderr[-3000:]
    outcome = json.loads(result.read_text())
    expected = outcome["expected"]
    assert len(outcome["launches"]) == 1, outcome
    launch = outcome["launches"][0]
    assert launch["window_visible"] is False  # closed (and saved) before the start
    assert (launch["screen"], launch["geometry"], launch["zoom_steps"]) == (
        expected["screen"], expected["geometry"], expected["zoom_steps"])


def _restart_child(result_path: str) -> None:
    from PySide6.QtCore import QSettings, QTimer

    import src.domain.effect_size_preference as effect_size_preference
    import src.infrastructure.preferences.qsettings_ui_preferences as ui_preferences
    from src.infrastructure.app_restart import QProcessAppRestarter

    # Every settings store of this process in the sandbox's INI file
    ini = str(Path(result_path).with_name("settings.ini"))
    effect_size_preference.QSettings = lambda *_a, **_k: QSettings(ini, QSettings.Format.IniFormat)
    effect_size_preference.EffectSizePreference.reset_singleton()
    ui_preferences.native_settings = lambda: QSettings(ini, QSettings.Format.IniFormat)

    def stored():
        return QSettingsUiPreferences(lambda: QSettings(ini, QSettings.Format.IniFormat))

    app = QApplication([])
    store = stored()
    store.save_window_geometry(b"stale", "a display unplugged since")  # an older session's
    launches, expected = [], {}

    def launch(program, arguments, environment, working_directory):
        fresh = stored()  # what the new instance's start-up would read
        launches.append({"window_visible": window.isVisible(), "screen": fresh.load_last_screen(),
                         "geometry": base64.b64encode(fresh.load_window_geometry() or b"").decode(),
                         "zoom_steps": fresh.load_zoom_steps()})
        return True

    scale_vm = UiScaleViewModel(store, QProcessAppRestarter(launch=launch), active_factor=1.0)
    window = _bare_window(_Bot, (ShellViewModel(store), scale_vm))
    window._connect_shell_signals()
    window.show_at_launch()

    def restart_now():
        window.showNormal()
        window.setGeometry(QRect(30, 40, 720, 540))
        app.processEvents()
        scale_vm.zoom_in()
        expected.update(screen=window.screen().name(), zoom_steps=store.load_zoom_steps(),
                        geometry=base64.b64encode(bytes(window.saveGeometry())).decode())
        window.shell_actions.restart_action.trigger()

    QTimer.singleShot(100, restart_now)
    QTimer.singleShot(10_000, app.quit)  # never hang
    app.exec()
    Path(result_path).write_text(json.dumps({"launches": launches, "expected": expected}))
