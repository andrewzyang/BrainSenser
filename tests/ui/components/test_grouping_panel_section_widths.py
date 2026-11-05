"""Cross-page contract test: the bottom-strip section widths.

Every analysis page's grouping panel lays its bottom strip out as four
side-by-side boxes — Event Types | Active Groups | Statistical Controls |
Statistics Table — via column stretch factors on the top-level grid built in
``BaseGroupingPanel._setup_ui``. The contract:

  1. **Table = half** the strip's stretch on every page, so exactly half until
     the three left boxes reach their caps on a wide panel (≥ ~1245 px); the
     table takes the extra width after that.
  2. The other half is split **2:2:3** across the three left boxes, so only the
     Controls box gives up width versus the older 1:1:2:3 ratio — Event Types
     and Active Groups keep their 14.3% each.

All four panels inherit ``_setup_ui`` unchanged, so this is enforced in one
place. The test still constructs every page to guard against a future override
that would silently re-split the strip. (Unlike the perm/boot contract test,
the PSD page IS included here — it renders the same four-section strip even
though it has no permutation/bootstrap selector.)
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.components.selector_combo_style import SELECTOR_COMBO_QSS

from src.ui.views.snapshots_psd.components.grouping_panel import (
    SnapshotsGroupingPanel,
)
from src.ui.views.snapshots_5hz_band.components.grouping_panel import (
    Snapshots5HzBandGroupingPanel,
)
from src.ui.views.timeline_lfp_threshold.components.grouping_panel import (
    TimelineLfpThresholdGroupingPanel,
)
from src.ui.views.timeline_peri_event.components.grouping_panel import (
    TimelinePeriEventGroupingPanel,
)


SECTION_PANELS = [
    SnapshotsGroupingPanel,
    Snapshots5HzBandGroupingPanel,
    TimelineLfpThresholdGroupingPanel,
    TimelinePeriEventGroupingPanel,
]

# Event Types : Active Groups : Statistical Controls : Statistics Table
EXPECTED_STRETCH = [2, 2, 3, 7]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(params=SECTION_PANELS, ids=lambda c: c.__name__)
def panel(qapp, request):
    widget = request.param()
    yield widget
    widget.deleteLater()


def _section_stretches(panel) -> list:
    """Stretch factor of every box in the panel's top-level layout, in
    left-to-right order (Event Types, Active Groups, Controls, Table)."""
    return panel.section_stretches()


def test_section_stretch_ratio(panel):
    assert _section_stretches(panel) == EXPECTED_STRETCH


def test_table_is_exactly_half(panel):
    stretches = _section_stretches(panel)
    assert stretches[-1] / sum(stretches) == 0.5


def test_left_boxes_keep_event_and_group_width(panel):
    # Event Types and Active Groups stay equal and at the pre-change 14.3% (1/7):
    # the table gained its half entirely from the Controls box, not from these.
    stretches = _section_stretches(panel)
    assert stretches[0] == stretches[1]
    assert stretches[0] / sum(stretches) == pytest.approx(1 / 7)


def test_table_width_is_identical_across_pages_when_narrow(qapp):
    """Q1 regression: at a window-realistic narrow strip the statistics table is
    the SAME width on every page.

    Canonical-bands used to be narrower because its Controls column — the only one
    that shows the Test + Correction selectors — had a larger minimum width, so it
    bottomed out before the other pages and stole width from the table. The
    selector combos now elide instead of dictating width, so the 2:2:3:7 ratio
    holds uniformly. 1050 px sits inside the band where the old layout diverged
    (canonical's Controls clamped below ~1166 px) but the fixed layout does not.
    """
    panels = [cls() for cls in SECTION_PANELS]
    try:
        for p in panels:
            p.resize(1050, 240)
            p.show()
        qapp.processEvents()
        widths = {type(p).__name__: p._stats_group.geometry().width() for p in panels}
        assert len(set(widths.values())) == 1, f"table widths diverge: {widths}"
    finally:
        for p in panels:
            p.hide()
            p.deleteLater()


def test_all_selector_dropdowns_share_one_style(qapp):
    """Q2 anti-drift: every selector dropdown — Test, Correction, Effect Size, and
    the perm/boot menus — uses the one shared stylesheet, so they cannot drift
    into different looks again (the bug where Effect Size was a bordered box while
    Test and Correction were borderless)."""
    canon = SnapshotsGroupingPanel()          # shows Test / Correction / Effect Size
    band = Snapshots5HzBandGroupingPanel()    # shows the perm / boot menus
    try:
        for combo in (
            canon.test_method_combo,
            canon.correction_method_combo,
            canon.effect_size_selector.dropdown,
            band.n_perm_combo,
            band.n_boot_combo,
        ):
            assert combo.styleSheet() == SELECTOR_COMBO_QSS
    finally:
        canon.deleteLater()
        band.deleteLater()
