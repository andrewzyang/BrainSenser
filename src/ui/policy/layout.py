"""Layout classes: the few global layout decisions, as pure data.

Pure Python (no Qt). Geometry becomes a class only in the View layer
(``ResponsiveContext``); ViewModels receive the classified facts (plan R4).
Everything else is intrinsic: decided by its own container and content.

| Class        | Measured on          | Rule (logical px)                                      |
|--------------|----------------------|--------------------------------------------------------|
| WidthClass   | window client width  | NARROW (icon rail) < rail_below <= WIDE (labels)       |
| HeightClass  | content-stack height | COMPACT < compact_below <= REGULAR                     |
| Arrangement  | content-stack size   | STACKED if narrower than the ROW minimum, or narrower  |
|              |                      | than stacked_max_width with aspect < stacked_enter;    |
|              |                      | leave STACKED at aspect > stacked_leave                |

Classes are computed without history on discrete events (first show,
maximise/restore, screen or interface-size change), so common maximised sizes
always land in the same class; the hysteresis bands apply only while the user
drags the window edge (:func:`classify_window`, :func:`classify_content` and
:func:`choose_arrangement` with ``dragging=True`` and the previous class). Keep
every boundary >= 25 px from the common maximised sizes in plan §3.1: more
than the ±8 px around them plus a band. Tests import BOUNDARIES and never
hard-code the numbers.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WidthClass(str, Enum):
    NARROW = "narrow"   # sidebar collapses to the icon rail
    WIDE = "wide"       # labelled sidebar


class HeightClass(str, Enum):
    COMPACT = "compact"
    REGULAR = "regular"


class Arrangement(str, Enum):
    ROW = "row"           # setup sections and table side by side (today)
    STACKED = "stacked"   # setup sections on top, full-width table below


@dataclass(frozen=True)
class Boundaries:
    rail_below: int = 1120
    rail_hysteresis: int = 16
    compact_below: int = 620
    compact_hysteresis: int = 12
    stacked_max_width: int = 1400
    stacked_enter_aspect: float = 1.25
    stacked_leave_aspect: float = 1.35
    stacked_hysteresis: int = 16   # the width band of STACKED's two width rules


BOUNDARIES = Boundaries()


@dataclass(frozen=True)
class Density:
    """What a page is commanded with (DensityAware.apply_density)."""

    width: WidthClass
    height: HeightClass
    arrangement: Arrangement
    scale: float = 1.0   # active interface-size factor of the window's display


def _below(value: float, boundary: float, band: float, was_below: Optional[bool],
           dragging: bool) -> bool:
    """``value < boundary``; while dragging, the side ``value`` was on holds
    within ``band`` of the boundary."""
    if dragging and was_below is not None:
        boundary += band if was_below else -band
    return value < boundary


def classify_window(width: int, prev: Optional[WidthClass] = None, *,
                    dragging: bool = False) -> WidthClass:
    """The window's width class from its client width."""
    narrow = _below(width, BOUNDARIES.rail_below, BOUNDARIES.rail_hysteresis,
                    None if prev is None else prev is WidthClass.NARROW, dragging)
    return WidthClass.NARROW if narrow else WidthClass.WIDE


def classify_content(height: int, prev: Optional[HeightClass] = None, *,
                     dragging: bool = False) -> HeightClass:
    """The pages' height class (their density) from the content-stack height."""
    compact = _below(height, BOUNDARIES.compact_below, BOUNDARIES.compact_hysteresis,
                     None if prev is None else prev is HeightClass.COMPACT, dragging)
    return HeightClass.COMPACT if compact else HeightClass.REGULAR


def choose_arrangement(width: int, height: int, row_min_width: int,
                       prev: Optional[Arrangement] = None, *,
                       dragging: bool = False) -> Arrangement:
    """The grouping panels' arrangement for a ``width`` × ``height`` content stack.

    STACKED when the stack is narrower than ``row_min_width``, the narrowest
    content width the ROW arrangement fits, or narrower than stacked_max_width
    with an aspect (width / height) below stacked_enter_aspect. While dragging,
    each rule keeps the previous arrangement within a band: the widths by
    stacked_hysteresis px, the aspect up to stacked_leave_aspect. Only the ROW
    minimum is one-sided: ROW does not fit below it, so turns STACKED there.
    """
    b = BOUNDARIES
    was_stacked = None if prev is None else prev is Arrangement.STACKED
    if width < row_min_width + (b.stacked_hysteresis if dragging and was_stacked else 0):
        return Arrangement.STACKED
    narrow = _below(width, b.stacked_max_width, b.stacked_hysteresis, was_stacked, dragging)
    if dragging and was_stacked:
        tall = width <= b.stacked_leave_aspect * height
    else:
        tall = width < b.stacked_enter_aspect * height
    return Arrangement.STACKED if narrow and tall else Arrangement.ROW


class SidebarPreference(str, Enum):
    """The persisted choice in View ▸ Sidebar."""

    AUTO = "auto"
    LABELS = "labels"
    ICONS = "icons"


class SidebarMode(str, Enum):
    """What the sidebar actually shows."""

    LABELS = "labels"
    ICONS = "icons"


def resolve_sidebar_mode(preference: SidebarPreference, width_class: WidthClass,
                         override: Optional[SidebarMode] = None) -> SidebarMode:
    """Effective sidebar mode: a session override wins, then an explicit
    preference; AUTO follows the window width class."""
    if override is not None:
        return override
    if preference is SidebarPreference.LABELS:
        return SidebarMode.LABELS
    if preference is SidebarPreference.ICONS:
        return SidebarMode.ICONS
    return SidebarMode.ICONS if width_class is WidthClass.NARROW else SidebarMode.LABELS
