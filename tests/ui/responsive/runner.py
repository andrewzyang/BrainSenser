"""Run the responsive matrix of one screen profile in a fresh Qt process.

Parent side, :func:`run_profile` / :func:`run_profiles`: one child process per
profile (several in parallel), each in its own sandbox — ``HOME``,
``BRAINSENSER_DATA_DIR`` and cwd in a throwaway folder, ``MPLCONFIGDIR`` in a
harness-owned font cache — with the profile's offscreen screen configuration.

Child side (``python -m tests.ui.responsive.runner``, :class:`_ProfileWalk`):
guards against opening real data, builds the real ``MainWindow`` the way
``main()`` does, opens it maximized, then walks every viewport × page — first
empty, then filled with the deterministic synthetic state of
:mod:`tests.ui._synthetic` — running the invariant detectors in each cell. The
window is built once and resized from cell to cell. The result (one JSON file)
lists every cell's violations plus the plot-export digests (I9), the history
probe (I7b) and the interface size the window ran at (active and chosen).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QRect, QSettings, Qt
from PySide6.QtGui import QColor, QFontInfo, QImage, QPainter
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QLabel,
                               QWidget)

from tests.ui.responsive import _safety
from tests.ui.responsive.profiles import (COMMON_SIZE_REACH_PX, COMMON_SIZES, FLOOR, LAUNCH, MOVED,
                                          PAGES, PROFILES, STATES, Screen, cell_invariants,
                                          parse_viewport)

NATIVE = "native"  # --platform cocoa: the real display, whatever it is

# matplotlib's font cache takes ~10 s to build; children share this one (never
# the user's ~/.matplotlib, whose matplotlibrc would leak into the plots).
MPL_CACHE = Path(tempfile.gettempdir()) / "brainsenser_responsive_mplconfig"

# Inherited settings that would distort the emulated display.
_SCALING_VARIABLES = ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI",
                      "QT_USE_PHYSICAL_DPI", "QT_ENABLE_HIGHDPI_SCALING",
                      "QT_SCALE_FACTOR_ROUNDING_POLICY")

# Plot exports (I9) are taken at the first and the last viewport — the farthest
# apart in time, so a timestamp in an export cannot hide — and after a move.
EXPORT_FORMATS = ("png", "pdf", "svg")
EXPORT_DPI = 100

# The history probe (I7b) watches the grouping panel on this page, arriving at
# each common size from a small and from a large window.
HISTORY_PAGE = "timeline_lfp_threshold"
HISTORY_FROM = ((600, 500), (3840, 2120))

SETTLE_TIMEOUT_S = 5
# Event passes the window's geometry must hold still for before a cell is measured.
SETTLE_STILL_PASSES = 2

# The child's preferences (EffectSizePreference and the UI-preferences adapter), in its sandbox.
SETTINGS_FILE = "settings.ini"


# ======================================================================= parent

def child_environment(sandbox: Path, qpa: str, repo: Path, extra=None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SCALING_VARIABLES}
    env.update({
        "HOME": str(sandbox / "home"), "MPLCONFIGDIR": str(MPL_CACHE),
        "BRAINSENSER_DATA_DIR": str(sandbox / "appdata"), "QT_QPA_PLATFORM": qpa,
        "PYTHONPATH": str(repo), "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM": "1",
    })
    env.update(extra or {})
    return env


def _warm_font_cache(sandbox: Path, repo: Path) -> None:
    """Build the shared matplotlib font cache once, before children race to."""
    if not list(MPL_CACHE.glob("fontlist-*.json")):
        MPL_CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-c", "import matplotlib.font_manager"],
                       env=child_environment(sandbox, "offscreen", repo), cwd=sandbox,
                       check=True, capture_output=True)


def run_profile(name: str, out: Path, *, repo: Path = _safety.REPO_ROOT,
                platform: str = "offscreen", label: str = "", sheets: bool = False,
                cell_png: bool = False, ladder: bool = False, env: dict = None,
                zoom_steps: dict = None, timeout: int = 900) -> dict:
    """Run one profile's child; its parsed result, or ``{"profile": ..., "error": ...}``.

    ``label`` distinguishes several runs of one profile (e.g. per interface
    size); ``env`` adds variables to the child's environment; ``zoom_steps``
    (display name → ladder step) is saved in the child's preferences first, as
    the interface size chosen for each display."""
    _safety.check_sandbox_location(out, repo)
    run_name = name + label
    sandbox = out / "sandbox" / run_name
    for folder in ("home", "appdata", "cwd"):
        (sandbox / folder).mkdir(parents=True, exist_ok=True)
    for folder in ("logs", "profiles"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    if zoom_steps:
        from src.infrastructure.preferences import QSettingsUiPreferences
        settings = str(sandbox / SETTINGS_FILE)
        QSettingsUiPreferences(lambda: QSettings(settings, QSettings.Format.IniFormat)
                               ).save_zoom_steps(zoom_steps)
    _warm_font_cache(sandbox, repo)
    if platform == "cocoa":
        qpa = "cocoa"
    else:
        qpa = f"offscreen:configfile={PROFILES[name].write_qpa_config(sandbox / 'screens.json')}"
    result_path = out / "profiles" / f"{run_name}.json"
    result_path.unlink(missing_ok=True)
    command = [sys.executable, "-m", "tests.ui.responsive.runner", "--profile", name,
               "--sandbox", str(sandbox), "--out", str(out), "--result", str(result_path),
               "--platform", platform]
    command += ["--sheets"] * sheets + ["--cell-png"] * cell_png + ["--ladder"] * ladder
    log = out / "logs" / f"{run_name}.log"
    started = time.monotonic()
    with open(log, "w") as handle:
        try:
            code = subprocess.run(command, env=child_environment(sandbox, qpa, repo, env),
                                  cwd=sandbox / "cwd", stdout=handle, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    if code == 0 and result_path.exists():
        result = json.loads(result_path.read_text())
        result["wall_s"] = round(time.monotonic() - started, 1)
        return result
    return {"profile": name, "error": f"child exited with {code}; log: {log}"}


def run_profiles(names, out: Path, *, jobs: int = None, **options) -> dict:
    """Run several profiles in parallel, one child each; ``{name: result}``."""
    names = list(names)
    with ThreadPoolExecutor(max_workers=jobs or min(len(names), os.cpu_count() or 4)) as pool:
        futures = {name: pool.submit(run_profile, name, out, **options) for name in names}
        return {name: future.result() for name, future in futures.items()}


# ======================================================================== child

class _ProfileWalk:
    """One profile's matrix, walked in this (child) process on the real window."""

    def __init__(self, args):
        self.args = args
        self.sandbox = Path(args.sandbox).resolve()
        _safety.check_child_environment(self.sandbox)
        _safety.install_open_guard()
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        self.app = QApplication([sys.argv[0]])
        from src.ui.app_bootstrap import build_presentation, configure_application
        configure_application(self.app)

        # EffectSizePreference and the UI-preferences adapter use QSettings(org, app):
        # the native preferences store.
        import src.domain.effect_size_preference as effect_size_preference
        import src.infrastructure.preferences.qsettings_ui_preferences as ui_preferences
        settings = str(self.sandbox / SETTINGS_FILE)
        effect_size_preference.QSettings = (
            lambda *_a, **_k: QSettings(settings, QSettings.Format.IniFormat))
        effect_size_preference.EffectSizePreference.reset_singleton()
        ui_preferences.native_settings = lambda: QSettings(settings, QSettings.Format.IniFormat)

        container = build_presentation().container
        resolver = container.path_resolver()
        self.resolved = {"path_resolver.base_dir": resolver.base_dir,
                         "global_db": resolver.get_global_db_path(),
                         "app_config": container.app_config().config_path,
                         "effect_size_settings": effect_size_preference.QSettings().fileName(),
                         "ui_preferences_settings": ui_preferences.native_settings().fileName()}
        for what, path in self.resolved.items():
            _safety.assert_inside(path, self.sandbox, what)

        import logging
        import main as app_main
        from src.ui.widgets.responsive_figure import ResponsiveFigureWidget
        from tests.ui.responsive import invariants
        self.inv, self.plot_type = invariants, ResponsiveFigureWidget
        logging.getLogger().setLevel(logging.WARNING)  # main configures INFO on import

        self.win = app_main.MainWindow(container=container)
        _safety.assert_inside(self.win.path_resolver.base_dir, self.sandbox, "window data dir")
        if args.platform == "cocoa":
            self.win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.screens = self._profile_screens()
        self.screen_changes = []
        self.win.winId()  # create the platform window so its screen changes can be observed
        self.win.windowHandle().screenChanged.connect(
            lambda screen: self.screen_changes.append(screen.name()))
        self.sheets = (_ContactSheets(Path(args.out), args.profile)
                       if args.sheets or args.cell_png else None)

    # ---------------------------------------------------------------- screens

    def _profile_screens(self) -> tuple:
        """The profile's screens, checked against what the platform emulates. Device
        px are compared, so an interface size (which shrinks logical px) passes."""
        app = self.app
        if self.args.platform == "cocoa":
            real = app.primaryScreen()
            size = real.availableGeometry().size()
            return (Screen(real.name(), (size.width(), size.height()),
                           real.devicePixelRatio(), 72, 28),)
        declared = PROFILES[self.args.profile].screens

        def device(width, height, dpr):
            return round(width * dpr), round(height * dpr)

        want = sorted((s.name, device(*s.available, s.dpr)) for s in declared)
        got = sorted((s.name(), device(s.availableGeometry().width(),
                                       s.availableGeometry().height(), s.devicePixelRatio()))
                     for s in app.screens())
        same = len(want) == len(got) and all(
            w[0] == g[0] and max(abs(a - b) for a, b in zip(w[1], g[1])) <= 2
            for w, g in zip(want, got))
        if not same or app.primaryScreen().name() != declared[0].name:
            raise RuntimeError(f"offscreen screens {got} (primary {app.primaryScreen().name()}) "
                               f"differ from the profile's {want}")
        return declared

    def viewports(self) -> list:
        """The profile's viewports; on the real display, the §3.2 ones (no move)."""
        if self.args.platform == "cocoa":
            return [v for v in PROFILES["mac_air15"].viewports() if v != MOVED]
        return list(PROFILES[self.args.profile].viewports())

    def qscreen(self, screen: Screen):
        return next(s for s in self.app.screens() if s.name() == screen.name)

    def title_bar(self, screen: Screen) -> int:
        """``screen``'s title bar in this process's logical px. The window manager
        draws it at the display's own scaling, so an interface size (Qt's
        ``QT_SCALE_FACTOR``, on top of that scaling) shrinks it like the screen:
        the 28-px macOS title bar is 14 logical px at 200 %."""
        return round(screen.title_bar * screen.dpr / self.qscreen(screen).devicePixelRatio())

    def client_area(self, screen: Screen) -> tuple:
        area = self.qscreen(screen).availableGeometry()
        return area.width(), area.height() - self.title_bar(screen)

    # ---------------------------------------------------------------- events

    def lay_out(self) -> None:
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self.app.processEvents()

    def settle(self) -> None:
        """Deliver pending resize and layout events until the window holds still,
        and wait until every visible plot shows its final frame (drawn at the
        canvas's size and context). A layout change reaches a page host one
        event pass per level of posted layout requests, so the geometry of every
        visible widget has to hold for ``SETTLE_STILL_PASSES`` passes."""
        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        last, still = None, 0
        while True:
            self.lay_out()
            geometry = [w.geometry().getRect() for w in self.win.findChildren(QWidget)
                        if w.isVisible()]
            plots_final = all(p.is_layout_settled()
                              for p in self.win.findChildren(self.plot_type) if p.isVisible())
            still = still + 1 if plots_final and geometry == last else 0
            if still == SETTLE_STILL_PASSES:
                return
            if time.monotonic() > deadline:
                raise RuntimeError(f"the window did not settle within {SETTLE_TIMEOUT_S} s")
            last = geometry
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.002)

    # ---------------------------------------------------------------- cells

    def place_for_launch(self, screen: Screen) -> None:
        """Put the window where main()'s show_at_launch() puts it on a first launch
        under a window manager (the pointer starts on the primary screen; the
        sandbox has no saved geometry): maximized, i.e.
        the client area below the title bar and never smaller than the window's
        minimum, or at its centred normal geometry. Offscreen maximizing ignores
        the title bar and the minimum, and an offscreen window re-applies its
        maximized device-px geometry on a later screen change, so the geometry is
        set directly."""
        from src.ui.shell.window_placement import launch_geometry
        area = self.qscreen(screen).availableGeometry()
        minimum = self.win.minimumSize()
        launch = launch_geometry(area, minimum)
        title_bar = self.title_bar(screen)
        self.win.showNormal()
        if launch.maximized:
            self.win.setGeometry(area.x(), area.y() + title_bar,
                                 max(minimum.width(), area.width()),
                                 max(minimum.height(), area.height() - title_bar))
        else:
            self.win.setGeometry(launch.normal)

    def enter(self, viewport: str) -> None:
        win = self.win
        if viewport == LAUNCH:
            self.place_for_launch(self.screens[0])
        elif viewport == MOVED:  # the launch-size window, dragged onto the second screen
            target = self.screens[1]
            win.showNormal()
            win.resize(*self.client_area(self.screens[0]))
            win.move(self.qscreen(target).availableGeometry().topLeft()
                     + QPoint(0, self.title_bar(target)))
        else:
            win.showNormal()
            win.resize(*parse_viewport(viewport))
        self.settle()

    def check_window(self, viewport: str) -> list:
        if viewport == LAUNCH:
            primary = self.screens[0]
            return self.inv.check_window_fits(self.win, self.qscreen(primary).availableGeometry(),
                                              self.title_bar(primary), FLOOR)
        if viewport == MOVED:
            target = self.screens[1]
            return self.inv.check_screen_change(self.win, self.qscreen(target),
                                                self.title_bar(target), FLOOR, self.screen_changes)
        return self.inv.check_window_size(self.win, parse_viewport(viewport))

    def measure(self, viewport: str, page: str, state: str) -> dict:
        inv, win = self.inv, self.win
        detectors = {"I1": inv.check_crushed, "I2": inv.check_containment,
                     "I4": inv.check_page_hscroll, "I5": inv.check_text, "I6": inv.check_plots}
        found = {k: detectors[k](win) if k in detectors else self.check_window(viewport)
                 for k in cell_invariants(viewport)}
        stack = win.main_layout.content_stack
        return {"viewport": viewport, "page": page, "state": state,
                "window": [win.width(), win.height()], "stack": [stack.width(), stack.height()],
                "widgets": len(win.findChildren(QWidget)),
                "facts": inv.observe_arrangement(win, win.main_layout.get_page(page)),
                "violations": {k: [asdict(v) for v in found[k]] for k in sorted(found)}}

    def export_digests(self, folder: Path) -> dict:
        folder.mkdir(parents=True, exist_ok=True)
        digests = {}
        for plot in self.win.findChildren(self.plot_type):
            for fmt in EXPORT_FORMATS:
                path = folder / f"{type(plot).__name__}.{fmt}"
                plot.render_export(str(path), EXPORT_DPI)
                digests[path.name] = hashlib.md5(path.read_bytes()).hexdigest()
                path.unlink()
        return digests

    def ladder_metrics(self) -> dict:
        """I8b inputs: device-px font size and height of every visible text control."""
        inv, win = self.inv, self.win
        dpr = win.devicePixelRatioF()
        metrics = {}
        for page in PAGES:
            win.main_layout.switch_page(page)
            for w in inv.considered_widgets(win):
                if isinstance(w, (QAbstractButton, QComboBox, QAbstractSpinBox, QLabel)):
                    metrics[f"{inv.widget_path(w)}[{inv.text_of(w)}]"] = (
                        QFontInfo(w.font()).pixelSize() * dpr, w.height() * dpr)
        return metrics

    def history(self) -> dict:
        """I7b: the class facts around each common size (±8 px), arriving from a small
        and from a large window."""
        win, reach = self.win, COMMON_SIZE_REACH_PX
        win.main_layout.switch_page(HISTORY_PAGE)
        page = win.main_layout.get_page(HISTORY_PAGE)
        observed = {}
        for width, height in COMMON_SIZES:
            seen = []
            for dw, dh in ((0, 0), (-reach, 0), (reach, 0), (0, -reach), (0, reach)):
                for start in HISTORY_FROM:
                    win.resize(*start)
                    self.lay_out()
                    win.resize(width + dw, height + dh)
                    self.lay_out()
                    facts = self.inv.observe_arrangement(win, page)
                    seen.append({k: facts.get(k) for k in ("panel", "sidebar_width")})
            observed[f"{width}x{height}"] = seen
        return observed

    def run(self) -> dict:
        from tests.ui._synthetic import populate_main_window
        result = {"profile": self.args.profile, "platform": self.app.platformName(),
                  "isolation": {k: str(v) for k, v in self.resolved.items()},
                  "screens": {s.name(): {"available": list(s.availableGeometry().getRect()),
                                         "dpr": s.devicePixelRatio(),
                                         "logical_dpi": s.logicalDotsPerInch()}
                              for s in self.app.screens()},
                  "cells": [], "exports": {}, "errors": []}
        started = time.monotonic()
        viewports = self.viewports()
        for state in STATES:
            if state == "populated":
                populate_main_window(self.win, Path(os.environ["BRAINSENSER_DATA_DIR"]),
                                     settle_ms=0)
            for viewport in viewports:
                if viewport == MOVED and state != "populated":
                    continue
                try:
                    self.enter(viewport)
                except Exception as exc:  # recorded so one failure doesn't hide the other cells
                    result["errors"].append(f"{viewport}/{state}: {exc!r}")
                    continue
                for page in PAGES:
                    try:
                        self.win.main_layout.switch_page(page)
                        self.settle()
                        cell = self.measure(viewport, page, state)
                    except Exception as exc:
                        result["errors"].append(f"{viewport}/{page}/{state}: {exc!r}")
                        continue
                    result["cells"].append(cell)
                    if self.sheets is not None:
                        self.sheets.add(self.win, cell, save_cell=self.args.cell_png)
                if state == "populated" and viewport in (viewports[1], viewports[-1], MOVED):
                    result["exports"][viewport] = self.export_digests(
                        self.sandbox / "exports" / viewport)
                if self.args.ladder and state == "populated" and viewport == LAUNCH:
                    result["ladder"] = self.ladder_metrics()
        result["history"] = self.history()
        state = self.win.ui_scale_viewmodel.state
        result["interface_size"] = {"active": state.active_percent, "chosen": state.chosen_percent}
        if self.sheets is not None:
            self.sheets.write()
        result["elapsed_s"] = round(time.monotonic() - started, 1)
        return result


class _ContactSheets:
    """One sheet per page and state with every viewport's screenshot as a captioned
    tile (failing invariants in red); optionally each cell's screenshot too."""

    TILE_HEIGHT = 240
    SHEET_WIDTH = 2400
    CAPTION_HEIGHT = 22
    GAP = 12

    def __init__(self, out: Path, profile: str):
        self._out, self._profile = out, profile
        self._tiles = {}

    def add(self, win, cell: dict, save_cell: bool) -> None:
        smooth = Qt.TransformationMode.SmoothTransformation
        image = win.grab().toImage()
        image.setDevicePixelRatio(1)
        failing = [k for k, v in cell["violations"].items() if v]
        caption = f"{cell['viewport']}  {' '.join(failing) or 'OK'}"
        self._tiles.setdefault((cell["page"], cell["state"]), []).append(
            (image.scaledToHeight(self.TILE_HEIGHT, smooth), caption, bool(failing)))
        if save_cell:
            folder = self._out / "cells" / self._profile
            folder.mkdir(parents=True, exist_ok=True)
            logical = image.scaledToWidth(min(1600, win.width()), smooth)
            logical.save(str(folder / f"{cell['viewport']}__{cell['page']}__{cell['state']}.png"))

    def write(self) -> None:
        folder = self._out / "sheets"
        folder.mkdir(parents=True, exist_ok=True)
        row_height = self.TILE_HEIGHT + self.CAPTION_HEIGHT + self.GAP
        for (page, state), tiles in self._tiles.items():
            rows, row, x = [], [], 0
            for tile in tiles:
                if row and x + tile[0].width() > self.SHEET_WIDTH:
                    rows.append(row)
                    row, x = [], 0
                row.append(tile)
                x += tile[0].width() + self.GAP
            rows.append(row)
            width = max(sum(t[0].width() + self.GAP for t in r) for r in rows) + self.GAP
            sheet = QImage(width, len(rows) * row_height + self.GAP, QImage.Format.Format_RGB32)
            sheet.fill(QColor("#d8d8d8"))
            painter = QPainter(sheet)
            for r, tiles_in_row in enumerate(rows):
                x, y = self.GAP, self.GAP + r * row_height
                for image, caption, failing in tiles_in_row:
                    painter.drawImage(x, y, image)
                    painter.setPen(QColor("#b00020" if failing else "#1b5e20"))
                    painter.drawText(QRect(x, y + self.TILE_HEIGHT, image.width(),
                                           self.CAPTION_HEIGHT),
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     caption)
                    x += image.width() + self.GAP
            painter.end()
            sheet.save(str(folder / f"{self._profile}__{page}__{state}.png"))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True)
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--platform", choices=("offscreen", "cocoa"), default="offscreen")
    parser.add_argument("--sheets", action="store_true", help="write contact sheets")
    parser.add_argument("--cell-png", action="store_true", help="also save every cell's screenshot")
    parser.add_argument("--ladder", action="store_true", help="record the I8b font/height metrics")
    args = parser.parse_args(argv)
    result = _ProfileWalk(args).run()
    Path(args.result).write_text(json.dumps(result, indent=1))
    sys.stdout.flush()
    os._exit(0)  # skip Qt/matplotlib teardown; everything is written


if __name__ == "__main__":
    main()
