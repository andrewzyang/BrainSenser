"""Screen profiles and window viewports of the responsive matrix (plan §3.1–§3.2).

A profile is one emulated display setup, run in its own Qt process through the
offscreen QPA's ``configfile`` (``offscreen:configfile=<json>``). Display scaling
is emulated the way Windows and macOS report it, through ``logicalDpi`` over
``logicalBaseDpi`` (DPR = logicalDpi / base; base 72 on macOS, where 1 pt is
1 px, and 96 on Windows, where 1 pt is 4/3 px). The JSON ``dpr`` key is not
applied to windows, so it is never used (``09_verification.md`` §3.5).

The offscreen platform has no menu bar, Dock or taskbar, so each screen is
declared at its *available* logical size and the title bar is modelled
separately: a maximized window's client area is ``available − title_bar``.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# D3: the window must shrink to 600×500 (clamped to the screen); every viewport is ≥ it.
FLOOR = (600, 500)

# Window client sizes (logical px) of plan §3.2, smallest first.
VIEWPORTS = (
    (600, 500), (800, 500), (640, 830), (756, 860), (1024, 560), (1093, 546),
    (1280, 640), (1280, 727), (1280, 769), (1440, 822), (960, 1010), (1512, 932),
    (1920, 1040), (1280, 1370), (1080, 1850), (2560, 1400), (3840, 2120),
)

# Common maximized client sizes of plan §3.1 and the grouping-panel arrangement
# the contract assigns to each. Classes are computed without history and every
# boundary stays ≥ 25 px away, so within ±8 px of these sizes nothing may change.
COMMON_SIZES = {
    (1093, 546): "ROW",       # Windows 1366×768 @ 125 %
    (1280, 640): "ROW",       # Windows 1920×1080 @ 150 %
    (1366, 697): "ROW",       # 1366×768 @ 100 %
    (1024, 600): "ROW",       # macOS Larger Text 13-inch
    (1280, 769): "ROW",       # the user's Mac, Dock hidden
    (1280, 706): "ROW",       # the user's Mac, Dock shown
    (1164, 699): "ROW",       # the user's Mac at 110 %
    (1024, 615): "ROW",       # the user's Mac at 125 %
    (1512, 982): "ROW",       # MacBook Pro 14-inch full screen
    (960, 1010): "STACKED",   # half of a 1080p screen
    (640, 830): "STACKED",    # macOS Split View tile
    (1080, 1850): "STACKED",  # portrait 1080×1920
}
COMMON_SIZE_REACH_PX = 8

PAGES = ("data_management", "timeline_lfp_threshold", "timeline_peri_event",
         "snapshots_canonical_bands", "snapshots_5hz_band")
STATES = ("empty", "populated")

# Pseudo-viewports: "launch" is the window as main() opens it (show_at_launch:
# maximised, or centred on very wide screens; the pointer starts on the primary
# screen); "moved" is the same window after it moves to the
# profile's second screen (mixed-DPI profiles only, populated state only).
LAUNCH = "launch"
MOVED = "moved"


@dataclass(frozen=True)
class Screen:
    """One emulated display, declared at its available logical size."""

    name: str
    available: tuple[int, int]  # logical px left for windows (menu bar, Dock, taskbar removed)
    dpr: float                  # display scaling: 1.25 = Windows 125 %, 2.0 = Retina
    base_dpi: int               # 72 macOS, 96 Windows
    title_bar: int              # maximized window frame above the client area (logical px)
    x: int = 0                  # logical left edge (offscreen keeps native origins unscaled)

    def qpa_entry(self) -> dict:
        width, height = self.available
        return {"name": self.name, "x": self.x, "y": 0,
                "width": round(width * self.dpr), "height": round(height * self.dpr),
                "logicalDpi": self.base_dpi * self.dpr, "logicalBaseDpi": self.base_dpi}


@dataclass(frozen=True)
class Profile:
    """A display setup; ``screens[0]`` is primary (the window launches on it).

    The offscreen platform makes the screen whose name sorts first primary, so
    the primary screen's name must sort first."""

    name: str
    description: str
    screens: tuple[Screen, ...]

    def __post_init__(self):
        if min(s.name for s in self.screens) != self.screens[0].name:
            raise ValueError(f"{self.name}: the primary screen's name must sort first")

    @property
    def primary(self) -> Screen:
        return self.screens[0]

    def viewports(self) -> tuple[str, ...]:
        """Cell viewport ids: launch, every §3.2 viewport, then moved (two screens only)."""
        ids = (LAUNCH,) + tuple(viewport_id(size) for size in VIEWPORTS)
        return ids + ((MOVED,) if len(self.screens) > 1 else ())

    def states(self, viewport: str) -> tuple[str, ...]:
        return ("populated",) if viewport == MOVED else STATES

    def write_qpa_config(self, path: Path) -> Path:
        """Write the offscreen configfile (``offscreen:configfile=<path>``)."""
        config = {"synchronousWindowSystemEvents": False, "windowFrameMargins": False,
                  "screens": [s.qpa_entry() for s in self.screens]}
        path.write_text(json.dumps(config, indent=1))
        return path


# Available areas and title bars follow plan §2.1/§3.1 where it names them (e.g.
# Windows 1366×768 @ 125 %: 1093×576 available, 1093×546 client); otherwise the
# Windows 11 taskbar takes 48 px and the macOS menu bar 31 (37 with a notch).
PROFILES = {p.name: p for p in (
    Profile("win125", "Windows 1366×768 @ 125 %",
            (Screen("1366x768@125", (1093, 576), 1.25, 96, 30),)),
    Profile("win150", "Windows 1920×1080 @ 150 %, the most common laptop default",
            (Screen("1920x1080@150", (1280, 672), 1.5, 96, 32),)),
    Profile("win175", "Windows 2560×1440 @ 175 % (14-inch QHD laptop)",
            (Screen("2560x1440@175", (1463, 775), 1.75, 96, 32),)),
    Profile("win200", "Windows 2880×1920 @ 200 % (Surface Pro)",
            (Screen("2880x1920@200", (1440, 912), 2.0, 96, 32),)),
    Profile("mac_air15", "MacBook Air 15-inch at 1280×828, Dock hidden: the user's screen",
            (Screen("air15", (1280, 797), 2.0, 72, 28),)),
    Profile("mac_larger_text", "MacBook Air 13-inch at 'Larger Text' (1024×665)",
            (Screen("air13_larger_text", (1024, 628), 2.0, 72, 28),)),
    Profile("mixed", "Retina laptop (primary) beside a 1x external display",
            (Screen("laptop_retina", (1440, 850), 2.0, 72, 28),
             Screen("monitor_1x", (1920, 1050), 1.0, 72, 28, x=1440))),
)}


def viewport_id(size: tuple[int, int]) -> str:
    return f"{size[0]}x{size[1]}"


def parse_viewport(viewport: str) -> Optional[tuple[int, int]]:
    """The size a viewport id names; None for the launch/moved pseudo-viewports."""
    if viewport in (LAUNCH, MOVED):
        return None
    width, height = viewport.split("x")
    return int(width), int(height)


def cell_invariants(viewport: str) -> tuple[str, ...]:
    """The invariants a cell measures: I3 (window size or launch fit) everywhere
    except after a screen move, which measures I10 instead."""
    return ("I1", "I2", "I10" if viewport == MOVED else "I3", "I4", "I5", "I6")


def cell_id(profile: str, viewport: str, page: str, state: str) -> str:
    return f"{profile}/{viewport}/{page}/{state}"


def all_cells() -> list[tuple[str, str, str, str]]:
    """Every (profile, viewport, page, state) cell, in run order."""
    cells = []
    for profile in PROFILES.values():
        for viewport in profile.viewports():
            for state in profile.states(viewport):
                cells.extend((profile.name, viewport, page, state) for page in PAGES)
    return cells
