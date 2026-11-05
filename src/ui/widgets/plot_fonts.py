"""The fonts the plots draw with: the manuscript's Helvetica Neue, or the
closest installed match.

macOS always has Helvetica Neue, so plots and exports are unchanged there.
Without it (Windows, Linux) matplotlib would log a findfont warning for every
text it lays out — thousands per session, and 7–20 % slower draws — and fall
back to the wider DejaVu Sans. The fallbacks are metric-compatible with
Helvetica; DejaVu Sans ships with matplotlib, so the chain always resolves.
"""

import functools

from matplotlib import font_manager

_BUNDLED = "DejaVu Sans"
PLOT_FONT_FAMILIES = ("Helvetica Neue", "Helvetica", "Arial", "Liberation Sans",
                      "Nimbus Sans", _BUNDLED)


@functools.cache
def plot_font_family() -> str:
    """The first of :data:`PLOT_FONT_FAMILIES` that matplotlib can find."""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    return next((family for family in PLOT_FONT_FAMILIES if family in installed), _BUNDLED)


def plot_font_families() -> list:
    """:func:`plot_font_family` then DejaVu Sans, which matplotlib uses for any
    glyph the first lacks (Arial has no subscript digits, as in ``CI₉₅``)."""
    family = plot_font_family()
    return [family] if family == _BUNDLED else [family, _BUNDLED]
