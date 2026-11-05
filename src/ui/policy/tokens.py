"""Design tokens: the app's sizes in logical px at 100 % interface size.

Pure Python (no Qt), so ViewModels, policy code and tests can import it without
pulling in QtGui. Values equal today's literals: interface size is applied by
Qt (QT_SCREEN_SCALE_FACTORS / QT_SCALE_FACTOR), never by multiplying these
numbers, so design px == logical px on the core path. Never use pt and never
multiply by the device pixel ratio.

New and migrated View code takes its sizes from here; a raw number other than
0 or 1 in a layout call needs a comment saying why. Font sizes live only in the
global stylesheet (``style.qss``) — :data:`TYPE_PX` documents its ramp.
"""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class TypeRole(str, Enum):
    """Text roles of the type ramp (see TYPE_PX)."""

    DENSE = "dense"
    CAPTION = "caption"
    SMALL = "small"
    SECONDARY = "secondary"
    CONTROL = "control"
    BODY = "body"
    TITLE = "title"
    DISPLAY = "display"


# Font pixel size per role at 100 %; BODY is the `* { font-size }` rule.
TYPE_PX: Mapping[TypeRole, int] = MappingProxyType({
    TypeRole.DENSE: 10,      # stats tables, → Group buttons, spinboxes, PSD input
    TypeRole.CAPTION: 11,    # field/group labels, selector combos, Compare, Cancel, empty upload row
    TypeRole.SMALL: 12,      # progress step
    TypeRole.SECONDARY: 13,  # sidebar child items, tooltips
    TypeRole.CONTROL: 14,    # push buttons, header sections, top-bar combo
    TypeRole.BODY: 15,       # `*`, inputs, nav items, labels, combo popups
    TypeRole.TITLE: 18,      # app title
    TypeRole.DISPLAY: 28,    # reserved for the empty-state title (M6)
})


class Space:
    """Spacing steps (Tailwind scale)."""

    HALF = 2
    X1 = 4
    X1_5 = 6
    X2 = 8
    X3 = 12
    X4 = 16
    X5 = 20
    X6 = 24
    X8 = 32
    X10 = 40
    X12 = 48
    X16 = 64


class Radius:
    """Corner radii."""

    XXS = 2
    XS = 4
    SM = 6
    MD = 8
    LG = 12


class IconSize:
    """Icon edge lengths."""

    SM = 16
    MD = 24
    LG = 32
    XL = 48


class Dim:
    """Fixed dimensions of chrome, cards, plots and windows."""

    CONTROL_H = 30            # QSS min-height of controls (content height, padding excluded)
    TOPBAR_H = 50
    SIDEBAR_W = 200
    SIDEBAR_RAIL_W = 64       # icon rail: the 32-px logo with 16 px either side
    SIDEBAR_HEADER_H = TOPBAR_H  # shared, so the header's lower edge lines up with the top bar's
    SIDEBAR_FOOTER_BUTTON = 32  # height of the footer's toggle and "Aa" buttons; the toggle is square
    NAV_ITEM_H = 50
    NAV_CHILD_H = 40
    NAV_GROUP_GAP = 28
    PATIENT_COMBO_MAX_W = 240  # top-bar patient combo; it grows with the longest name up to this
    STAT_CARD_H = 128
    SCROLLBAR = 8
    TABLE_SCROLLBAR = 10      # stats/upload tables: easier to grab than the 8-px default
    TABLE_NEAR_FIT = 24       # stats tables this close to fitting tighten their padding instead of scrolling
    PROGRESS_H = 8
    DIALOG_W = 360
    PLOT_MIN_H = 260
    PLOT_MIN_H_COMPACT = 220  # the plots' minimum at compact density (D5)
    CONTENT_MAX_W = 1680      # data page content is centred at this width on huge screens
    EMPTY_STATE_REGULAR_H = 1000  # empty states up to this tall keep their block at the top
    EMPTY_STATE_TOP_MAX = 320     # the lowest the block's top sits on taller ones (D18)
    WINDOW_MIN_W = 600        # design floor (D3); clamped to the screen's available area
    WINDOW_MIN_H = 500
    EVENT_TYPES_MAX_W = 200   # grouping-panel setup-section caps (bind on panels ≥ ~1245 px)
    GROUPS_MAX_W = 200
    CONTROLS_MAX_W = 260
    FIELD_MAX_W = 220         # combos/spinboxes inside the controls section
    BUTTON_MAX_W = 280


@dataclass(frozen=True)
class DensitySpec:
    """Sizes a page is commanded with for one density."""

    page_margin: int
    page_spacing: int
    plot_min_height: int
    plot_gap: int             # plot to grouping panel, on the page that separates them
    group_spacing: int        # between the Active Groups labels, member lists and Reset
    list_rows: int            # group lists always show this many full rows (D11)


# Keyed by HeightClass value. Compact controls are ~28 px tall: the
# [density="compact"] rules in style.qss give them a 12-px smaller content height.
DENSITY_SPECS: Mapping[str, DensitySpec] = MappingProxyType({
    "regular": DensitySpec(
        page_margin=Space.X4,
        page_spacing=Space.X3,
        plot_min_height=Dim.PLOT_MIN_H,
        plot_gap=Space.X4,
        group_spacing=Space.X1_5,
        list_rows=3,
    ),
    "compact": DensitySpec(
        page_margin=Space.X2,
        page_spacing=Space.X1,
        plot_min_height=Dim.PLOT_MIN_H_COMPACT,
        plot_gap=Space.X1,
        group_spacing=Space.X1,
        list_rows=3,
    ),
})
