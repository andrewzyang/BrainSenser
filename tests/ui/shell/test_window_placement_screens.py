"""Window placement and the splash on emulated screens (plan §3.1, D3; I3, I10).

Screens exist only before a QApplication does, so every screen layout runs in a
fresh offscreen Qt process (``window frame margins`` on, so a frame exists, except
on the one profile that shows the floor without a reported frame): every
responsive screen profile, a 4K and an ultrawide display, a screen smaller than
the floor, two-screen layouts, the user's screen at a 200 % interface size, and a
Wayland session (only the platform name says so; there the window is sized, never
positioned). The window is a stand-in whose layout minimum (1040×669, the real
window's floor before M1) is larger than the floor, so the explicit floor has to
win. Synthetic widgets only; no data, no settings.
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.ui.responsive import runner
from tests.ui.responsive.profiles import PROFILES, Profile, Screen

pytestmark = [pytest.mark.qt_subprocess]

REPO_ROOT = Path(__file__).resolve().parents[3]

EXTRA_PROFILES = {p.name: p for p in (
    Profile("uhd100", "4K at 100 %", (Screen("uhd", (3840, 2120), 1.0, 72, 28),)),
    Profile("ultrawide", "3440×1440", (Screen("ultrawide", (3440, 1400), 1.0, 96, 32),)),
    Profile("tiny", "smaller than the floor", (Screen("tiny", (640, 480), 1.0, 96, 30),)),
    # Equal DPRs, so the offscreen pointer position round-trips between the screens.
    Profile("pointer", "pointer on the second of two screens",
            (Screen("a_left", (1440, 850), 1.0, 72, 28),
             Screen("b_right", (1920, 1050), 1.0, 72, 28, x=1440))),
    Profile("small_second", "a large laptop beside a short display",
            (Screen("a_laptop", (1440, 850), 2.0, 72, 28),
             Screen("b_short", (1024, 460), 1.0, 72, 28, x=1440))),
    Profile("wayland", "a Wayland session, 4K", (Screen("uhd", (3840, 2120), 1.0, 96, 32),)),
    # The user's 1280×797 screen at 200 %, as Qt then reports it (DPR 4).
    Profile("air15_200", "the user's Mac at a 200 % interface size",
            (Screen("air15", (640, 399), 4.0, 72, 14),)),
)}
ALL_PROFILES = {**PROFILES, **EXTRA_PROFILES}
# Child modes by profile: "pointer" moves the pointer (which starts on the primary
# screen) to the last screen; "wayland" reports the Wayland platform.
CHILD_MODES = {"pointer": "pointer", "wayland": "wayland"}
# Profiles whose platform reports no window frame (as for the responsive harness).
NO_FRAME = {"air15_200"}
FRAMED = [name for name in ALL_PROFILES if name not in NO_FRAME]


def _run_child(profile: Profile, tmp_path: Path) -> dict:
    sandbox = tmp_path / profile.name
    for folder in ("home", "appdata", "cwd"):
        (sandbox / folder).mkdir(parents=True)
    config = json.loads(profile.write_qpa_config(sandbox / "screens.json").read_text())
    config["windowFrameMargins"] = profile.name not in NO_FRAME
    (sandbox / "screens.json").write_text(json.dumps(config))
    qpa = f"offscreen:configfile={sandbox / 'screens.json'}"
    result = sandbox / "result.json"
    code = f"import sys; from {__name__} import _child; _child(sys.argv[1], sys.argv[2])"
    mode = CHILD_MODES.get(profile.name, "")
    done = subprocess.run([sys.executable, "-c", code, str(result), mode], cwd=sandbox / "cwd",
                          env=runner.child_environment(sandbox, qpa, REPO_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and result.exists(), done.stdout[-4000:] + done.stderr[-4000:]
    return json.loads(result.read_text())


@pytest.fixture(scope="module")
def placements(tmp_path_factory) -> dict:
    tmp_path = tmp_path_factory.mktemp("placement")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(_run_child, profile, tmp_path)
                   for name, profile in ALL_PROFILES.items()}
        return {name: future.result() for name, future in futures.items()}


def _rect(values):
    x, y, w, h = values
    return x, y, x + w, y + h


def _inside(inner, outer, tolerance: int = 1) -> bool:
    """Within 1 px: fractional DPRs round the emulated device geometry."""
    ix0, iy0, ix1, iy1 = _rect(inner)
    ox0, oy0, ox1, oy1 = _rect(outer)
    return (ox0 - tolerance <= ix0 and oy0 - tolerance <= iy0
            and ix1 <= ox1 + tolerance and iy1 <= oy1 + tolerance)


@pytest.mark.parametrize("name", FRAMED)
def test_window_opens_on_the_launch_screen_within_its_floor(placements, name):
    launch = placements[name]["launch"]
    available, frame = launch["available"], launch["frame_extent"]
    floor = [min(600, available[2] - frame[0]), min(500, available[3] - frame[1])]
    assert launch["minimum"] == floor
    assert launch["screen"] == launch["launch_screen"]
    assert _inside(launch["frame_geometry"], available)
    width, height = available[2], available[3]
    assert launch["maximized"] == (width < 2600 and width <= 2 * height)
    assert _inside(launch["normal"], available)


def test_wide_screens_get_a_centred_window(placements):
    for name in ("uhd100", "ultrawide"):
        launch = placements[name]["launch"]
        assert not launch["maximized"]
        assert launch["geometry"] == launch["normal"]
        assert launch["positioned"]


def test_on_wayland_the_window_is_sized_not_positioned(placements):
    wayland, x11 = placements["wayland"]["launch"], placements["uhd100"]["launch"]
    assert not wayland["positioned"]
    assert wayland["geometry"][2:] == x11["normal"][2:]


def test_floor_clamps_to_a_screen_smaller_than_600x500(placements):
    launch = placements["tiny"]["launch"]
    assert launch["minimum"] == [600, 480 - launch["frame_extent"][1]]


@pytest.mark.parametrize("name", ALL_PROFILES)
def test_floor_before_the_first_show_leaves_room_for_a_title_bar(placements, name):
    """Placed before its first show the window has no frame yet; the style's
    title-bar height stands in for it, so even the first geometry fits the screen
    with a title bar. The first show then applies the real frame (above)."""
    launch = placements[name]["launch"]
    width, height = launch["available"][2:]
    assert launch["minimum_before_show"] == [min(600, width),
                                             min(500, height - launch["title_bar_estimate"])]


def test_floor_keeps_the_title_bar_estimate_where_no_frame_is_reported(placements):
    """I3 at 200 % on the user's Mac (640×399 logical px): where the platform reports
    no frame at all (offscreen, as in the responsive harness), the estimate stays
    after the show, so the window still fits below a title bar."""
    launch = placements["air15_200"]["launch"]
    assert launch["frame_extent"] == [0, 0]
    assert launch["minimum"] == [600, 399 - launch["title_bar_estimate"]]


def test_launch_screen_is_the_screen_under_the_pointer(placements):
    assert placements["pointer"]["launch"]["launch_screen"] == "b_right"
    assert placements["pointer"]["pointer_off_screen"] == "a_left"  # falls back to the primary


def test_floor_follows_the_window_to_another_screen(placements):
    """I10: moved to a display too short for 500 px, the floor shrinks to fit it."""
    moved = placements["small_second"]["moved"]
    assert moved["screen"] == "b_short"
    assert moved["minimum"] == [600, 460 - moved["frame_extent"][1]]


def test_floor_is_reapplied_when_the_available_area_changes(placements):
    assert placements["mac_air15"]["after_area_change"] == [600, 500]


def test_splash_covers_the_launch_screen(placements):
    for name in ("pointer", "mixed"):
        splash = placements[name]["splash"]
        assert splash["screen"] == placements[name]["launch"]["launch_screen"]
        assert splash["geometry"] == splash["screen_geometry"]


# ---------------------------------------------------------------- child side

def _child(result_path: str, mode: str) -> None:
    from PySide6.QtCore import QObject, QPoint, Qt, Signal
    from PySide6.QtGui import QCursor, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMainWindow, QStyle, QWidget

    from src.ui.shell.window_placement import (apply_initial_geometry, keep_window_floor,
                                               launch_screen)
    from src.ui.views.splash.splash_view import SplashView

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    screens = app.screens()
    out = {}

    def settle():
        for _ in range(5):
            app.processEvents()

    def rect(r):
        return [r.x(), r.y(), r.width(), r.height()]

    def facts(window):
        frame = window.frameGeometry()
        return {"screen": window.screen().name(), "minimum": list(window.minimumSize().toTuple()),
                "geometry": rect(window.geometry()), "frame_geometry": rect(frame),
                "frame_extent": [frame.width() - window.width(), frame.height() - window.height()],
                "maximized": window.isMaximized(),
                "available": rect(window.screen().availableGeometry())}

    if mode == "pointer":
        QCursor.setPos(screens[-1].geometry().center())
    if mode == "wayland":
        QGuiApplication.platformName = staticmethod(lambda: "wayland")
    target = launch_screen()
    window = QMainWindow()
    content = QWidget()
    content.setMinimumSize(1040, 669)
    window.setCentralWidget(content)
    keep_window_floor(window)
    apply_initial_geometry(window, target, None)  # no saved geometry: as on first launch
    minimum_before_show = list(window.minimumSize().toTuple())
    window.show()
    settle()
    out["launch"] = {**facts(window), "launch_screen": target.name(),
                     "normal": rect(window.normalGeometry()),
                     "positioned": window.testAttribute(Qt.WidgetAttribute.WA_Moved),
                     "minimum_before_show": minimum_before_show,
                     "title_bar_estimate": window.style().pixelMetric(
                         QStyle.PixelMetric.PM_TitleBarHeight, None, window)}

    QCursor.setPos(QPoint(-10000, -10000))
    out["pointer_off_screen"] = launch_screen().name()

    window.setMinimumSize(100, 100)
    window.screen().availableGeometryChanged.emit(window.screen().availableGeometry())
    out["after_area_change"] = list(window.minimumSize().toTuple())

    if len(screens) > 1:
        class _SplashViewModel(QObject):
            closed = Signal()
            player = None

        splash = SplashView(_SplashViewModel(), target)
        splash.show()
        settle()
        out["splash"] = {"screen": splash.screen().name(), "geometry": rect(splash.geometry()),
                         "screen_geometry": rect(target.geometry())}
        splash.close()

        other = next(s for s in screens if s is not window.screen())
        window.showNormal()
        settle()
        area = other.availableGeometry()
        window.setGeometry(area.x() + 10, area.y() + 40, 640, 400)
        settle()
        out["moved"] = facts(window)
    Path(result_path).write_text(json.dumps(out))
