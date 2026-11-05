"""Run the real BrainSenser main window in a fresh, isolated Qt process.

Display settings such as ``QT_SCALE_FACTOR`` or an emulated screen only take
effect before a ``QApplication`` exists, so each display profile gets its own
interpreter. :class:`AppProcess` starts one: the child isolates itself, starts
the application the way ``main()`` does, calls a ``"module:function"`` target
with a JSON payload and hands the target's JSON-serialisable result back. The
targets build their window with :func:`open_main_window` and friends.

Isolation (no real user state, no patient data):

* ``BRAINSENSER_DATA_DIR``, ``HOME`` and ``MPLCONFIGDIR`` point into the child's
  work dir, and no Qt, BrainSenser, matplotlib or locale variable of the parent
  (nor ``SOURCE_DATE_EPOCH``) leaks in;
* ``EffectSizePreference`` and the UI-preferences adapter use a throwaway INI
  file, as in the root conftest (the native macOS plist ignores ``HOME``);
* ``QMessageBox`` calls are recorded in :data:`MESSAGES`, never shown, so an
  unexpected dialog cannot block the child;
* content comes only from :mod:`tests.ui._synthetic`.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]

# In the order MainWindow adds them; every page but the first has Save Plot and Copy Table.
PAGES = ("data_management", "timeline_lfp_threshold", "timeline_peri_event",
         "snapshots_canonical_bands", "snapshots_5hz_band")
ANALYSIS_PAGES = PAGES[1:]

# Child only: [kind, title, text] of every QMessageBox call.
MESSAGES: list = []

# Parent variables that would change how the child renders or where it writes.
# Without LANG/LC_* the child formats dates as the app does when started from Finder.
_PARENT_ONLY = ("QT_", "BRAINSENSER_", "MPL", "MATPLOTLIBRC", "SOURCE_DATE_EPOCH",
                "LANG", "LC_")


@dataclass(frozen=True)
class DisplayProfile:
    """How the child's offscreen platform emulates a display.

    ``screen`` is an offscreen-plugin ``configfile`` screen (device px plus
    ``logicalDpi``/``logicalBaseDpi``); None keeps Qt's default 800×800 screen
    at 96 dpi. ``app_font`` stands in for the platform theme's default font,
    which offscreen lacks (it falls back to 9-pt "Sans Serif").
    """

    name: str
    scale_factor: Optional[float] = None
    screen: Optional[dict] = None
    app_font: Optional[tuple[str, int]] = None


# The user's MacBook Air 15" at its current setting: 1280×797 logical px
# available, DPR 2. The platform reports the DPR (logicalDpi / logicalBaseDpi =
# 144 / 72) as cocoa does, fonts resolve at 72 dpi (1 pt = 1 px), and cocoa's
# default application font is the 13-pt system font.
MAC_AIR15_RETINA = DisplayProfile(
    name="mac_air15_retina",
    screen={"name": "Built-in Retina Display", "x": 0, "y": 0, "width": 2560,
            "height": 1594, "logicalDpi": 144, "logicalBaseDpi": 72},
    app_font=(".AppleSystemUIFont", 13),
)


def qt_scale_profile(factor: float) -> DisplayProfile:
    """Qt's default offscreen screen under ``QT_SCALE_FACTOR=factor``."""
    return DisplayProfile(name=f"qt_scale_factor_{factor:g}", scale_factor=factor)


class AppProcess:
    """A child interpreter running ``target(payload)`` under ``profile``.

    The child starts immediately, so several can run at once; :meth:`result`
    waits for one and raises with the tail of its log if it failed.
    """

    def __init__(self, target: str, payload: Any, profile: DisplayProfile, workdir: Path):
        self._label = f"{target} [{profile.name}]"
        self._result_path = workdir / "result.json"
        self._log_path = workdir / "child.log"
        spec_path = workdir / "spec.json"
        spec_path.write_text(json.dumps({"target": target, "payload": payload,
                                         "app_font": profile.app_font,
                                         "result": str(self._result_path)}))
        self._log = open(self._log_path, "w")
        self._process = subprocess.Popen(
            [sys.executable, "-c", f"import sys, {__name__} as m; m._child_main(sys.argv[1])",
             str(spec_path)],
            env=_child_env(profile, workdir), cwd=workdir,
            stdout=self._log, stderr=subprocess.STDOUT,
        )

    def result(self, timeout: float = 300) -> Any:
        try:
            status = self._process.wait(timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
            status = f"killed after {timeout:.0f} s"
        finally:
            self._log.close()
        if status != 0 or not self._result_path.exists():
            log_tail = self._log_path.read_text()[-6000:]
            raise AssertionError(f"{self._label} failed (exit {status}):\n{log_tail}")
        return json.loads(self._result_path.read_text())


def _child_env(profile: DisplayProfile, workdir: Path) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith(_PARENT_ONLY)}
    platform = "offscreen"
    if profile.screen is not None:
        config = workdir / "screen.json"
        config.write_text(json.dumps({"windowFrameMargins": False, "screens": [profile.screen]}))
        platform = f"offscreen:configfile={config}"
    if profile.scale_factor is not None:
        env["QT_SCALE_FACTOR"] = str(profile.scale_factor)
    for name in ("data", "home", "mplconfig"):
        (workdir / name).mkdir()
    _seed_font_cache(workdir / "mplconfig")
    env.update(
        QT_QPA_PLATFORM=platform,
        BRAINSENSER_DATA_DIR=str(workdir / "data"),
        HOME=str(workdir / "home"),
        MPLCONFIGDIR=str(workdir / "mplconfig"),
        PYTHONPATH=str(REPO_ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
    )
    return env


def _seed_font_cache(config_dir: Path) -> None:
    """Copy this process's matplotlib font list so the child skips the ~10-s rebuild."""
    import matplotlib

    for font_list in Path(matplotlib.get_cachedir()).glob("fontlist-v*.json"):
        shutil.copy2(font_list, config_dir)


# ---------------------------------------------------------------------------
# Child side
# ---------------------------------------------------------------------------

def open_main_window(width: int, height: int):
    """Build the real main window the way ``main()`` does, show it and settle."""
    import main
    from src.ui.app_bootstrap import build_presentation

    presentation = build_presentation()
    data_dir = Path(os.environ["BRAINSENSER_DATA_DIR"]).resolve()
    if presentation.container.path_resolver().base_dir != data_dir:
        raise RuntimeError("the container does not resolve to the throwaway data dir")
    win = main.MainWindow(container=presentation.container)
    win.resize(width, height)
    win.show()
    wait_settled(win)
    return win


def populate(win) -> None:
    """Fill every page with the deterministic synthetic results."""
    from tests.ui._synthetic import populate_main_window

    populate_main_window(win, Path(os.environ["BRAINSENSER_DATA_DIR"]), settle_ms=0)
    wait_settled(win)


def accept_synthetic_results(win) -> None:
    """Let Save Plot and Copy Table act on the synthetic results.

    The synthetic state is written straight into the widgets, but the two
    Snapshots views gate both actions on their ViewModel's own results.
    """
    for view in (win.snapshots_psd_page, win.snapshots_5hz_band_page):
        view.viewmodel.has_analysis_results = lambda: True


def show_page(win, page: str) -> None:
    win.main_layout.switch_page(page)
    wait_settled(win)


def wait_settled(win, timeout_s: float = 30.0) -> None:
    """Process events until layouts are applied and every plot shows its final frame.

    Settled must hold on two consecutive passes, so work posted by the first
    pass (layout requests, a newly shown page's resize) is seen.
    """
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication

    from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    settled_passes = 0
    while settled_passes < 2:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if all(plot.is_layout_settled() for plot in win.findChildren(ResponsiveFigureWidget)):
            settled_passes += 1
            continue
        settled_passes = 0
        if time.monotonic() > deadline:
            raise TimeoutError(f"plots did not settle within {timeout_s:.0f} s")
        time.sleep(0.005)


def _isolate_preferences(ini_path: Path) -> None:
    from PySide6.QtCore import QSettings

    import src.domain.effect_size_preference as effect_size_preference
    import src.infrastructure.preferences.qsettings_ui_preferences as ui_preferences

    effect_size_preference.QSettings = (
        lambda *_args, **_kwargs: QSettings(str(ini_path), QSettings.Format.IniFormat))
    effect_size_preference.EffectSizePreference.reset_singleton()
    ui_preferences.native_settings = lambda: QSettings(str(ini_path), QSettings.Format.IniFormat)


def _record_message_boxes() -> None:
    from PySide6.QtWidgets import QMessageBox

    def recorder(kind, answer):
        def record(_parent, title, text, *_args, **_kwargs):
            MESSAGES.append([kind, title, text])
            return answer
        return staticmethod(record)

    ok, no = QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.No
    for kind, answer in (("information", ok), ("warning", ok), ("critical", ok), ("question", no)):
        setattr(QMessageBox, kind, recorder(kind, answer))

    # Boxes built by src.ui.components.dialog_fit are shown with exec().
    def record_exec(box):
        MESSAGES.append(["exec", box.windowTitle(), box.text()])
        return ok
    QMessageBox.exec = record_exec


def _child_main(spec_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text())
    _isolate_preferences(Path(spec_path).parent / "iEEG-App.ini")
    _record_message_boxes()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from src.ui.app_bootstrap import configure_application

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    if spec["app_font"]:
        # configure_application sizes the platform's system font; stand in the
        # platform theme's one (offscreen has no theme fonts).
        theme_font = QFont(*spec["app_font"])
        QFontDatabase.systemFont = staticmethod(lambda _which: QFont(theme_font))
        app.setFont(theme_font)
    configure_application(app)

    module, function = spec["target"].split(":")
    result = getattr(importlib.import_module(module), function)(spec["payload"])
    Path(spec["result"]).write_text(json.dumps(result))
