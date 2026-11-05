"""
The Data page's gutters follow the window's density (plan §3.3; M3.4).

The page in its PageHost, sized as the content area beside the sidebar the
window class calls for (the icon rail when NARROW) and commanded with the
density its height gets. Compact pages have 16-px gutters at the sides and
the bottom and 12 at the top, and 12 px between the metadata, the cards and the
table; regular pages keep today's. At every §3.2 viewport the statistics cards
and the metadata take as many columns as fit between those gutters, and the
page never scrolls sideways. Synthetic data, production stylesheet.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.layouts.page_host import PageHost
from src.ui.policy.layout import (Arrangement, Density, HeightClass, WidthClass,
                                  classify_content, classify_window)
from src.ui.policy.tokens import Dim, Space
from src.ui.views.data_management.components.statistics_card import StatisticsCard
from src.ui.views.data_management.data_management_page import DataManagementPage
from tests.ui.responsive import invariants
from tests.ui.responsive.profiles import VIEWPORTS
from tests.ui.views.data_management._data import populate

# (page margin, overview margins (left, top, right, bottom), gap between sections)
GUTTERS = {
    HeightClass.REGULAR: (Space.X8, (Space.X8, Space.X4, Space.X8, Space.X8), Space.X5),
    HeightClass.COMPACT: (Space.X2, (Space.X2, Space.X1, Space.X2, Space.X2), Space.X3),
}
CARD_GAP = Space.X6        # between card columns (EqualColumnsLayout)
METADATA_GAP = Space.X16   # between the metadata columns
METADATA_SIDE = Space.X12  # the metadata's side margins; they give way only to one column


@pytest.fixture
def hosted(qtbot, stub_viewmodel, app_stylesheet) -> SimpleNamespace:
    page = DataManagementPage(viewmodel=stub_viewmodel)
    host = PageHost(page, height_for_width=True)
    qtbot.addWidget(host)
    populate(page, count=999_999)
    return SimpleNamespace(host=host, page=page)


def _density(height: HeightClass) -> Density:
    return Density(WidthClass.WIDE, height, Arrangement.ROW)


def _show(hosted, window: tuple) -> HeightClass:
    """Size the host as the content area of a ``window``-sized main window and
    command the page with the density that height gets."""
    width, height = window
    narrow = classify_window(width) is WidthClass.NARROW
    content = (width - (Dim.SIDEBAR_RAIL_W if narrow else Dim.SIDEBAR_W), height - Dim.TOPBAR_H)
    density = classify_content(content[1])
    hosted.page.apply_density(_density(density))
    hosted.host.resize(*content)
    hosted.host.show()
    for _ in range(4):
        QApplication.processEvents()
    return density


def _gutters(page) -> tuple:
    page_margins = page.layout().contentsMargins()
    overview = page.patient_overview.layout()
    margins = overview.contentsMargins()
    return (page_margins.left(),
            (margins.left(), margins.top(), margins.right(), margins.bottom()),
            overview.spacing())


def _columns(widgets) -> int:
    return sum(widget.y() == widgets[0].y() for widget in widgets)


def _inner_width(hosted, density: HeightClass) -> int:
    """The width between the page's and the overview's side margins."""
    page_margin, (left, _, right, _), _ = GUTTERS[density]
    return hosted.host.viewport().width() - 2 * page_margin - left - right


def _fitting(count_choices, minimum: int, gap: int, width: int) -> int:
    return next(n for n in count_choices if n * minimum + (n - 1) * gap <= width or n == 1)


class TestGutters:
    @pytest.mark.parametrize("density", list(HeightClass))
    def test_each_density_has_its_gutters(self, hosted, density):
        hosted.page.apply_density(_density(density))
        assert _gutters(hosted.page) == GUTTERS[density]

    def test_regular_gutters_are_todays_and_come_back(self, hosted):
        today = _gutters(hosted.page)
        assert today == GUTTERS[HeightClass.REGULAR]
        hosted.page.apply_density(_density(HeightClass.COMPACT))
        hosted.page.apply_density(_density(HeightClass.REGULAR))
        assert _gutters(hosted.page) == today

    def test_compact_gutters_give_the_content_the_height_they_free(self, hosted):
        """At a width where the columns stay the same, the page needs exactly the
        gutters' difference less height."""
        _show(hosted, (1440, 1100))
        width = hosted.host.viewport().width()
        regular = hosted.page.heightForWidth(width)
        hosted.page.apply_density(_density(HeightClass.COMPACT))
        compact = hosted.page.heightForWidth(width)
        freed = 0
        for density, sign in ((HeightClass.REGULAR, 1), (HeightClass.COMPACT, -1)):
            page_margin, (_, top, _, bottom), gap = GUTTERS[density]
            freed += sign * (2 * page_margin + top + bottom + 2 * gap)
        assert regular - compact == freed


class TestEveryViewport:
    @pytest.mark.parametrize("window", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
    def test_columns_fit_between_the_densitys_gutters(self, hosted, window):
        density = _show(hosted, window)
        inner = _inner_width(hosted, density)
        cards = hosted.page.findChildren(StatisticsCard)
        card_min = max(card.minimumSizeHint().width() for card in cards)
        assert _columns(cards) == _fitting((4, 2, 1), card_min, CARD_GAP, inner)
        panel = hosted.page.patient_overview.metadata_panel
        columns = [panel.name_label.parentWidget(), panel.neurostimulator_label.parentWidget()]
        column_min = max(column.minimumSizeHint().width() for column in columns)
        assert _columns(columns) == _fitting((2, 1), column_min, METADATA_GAP,
                                             inner - 2 * METADATA_SIDE)

    @pytest.mark.parametrize("window", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
    def test_nothing_crushed_clipped_or_scrolling_sideways(self, hosted, window):
        _show(hosted, window)
        assert hosted.host.horizontalScrollBar().maximum() == 0
        assert not (invariants.check_crushed(hosted.host) + invariants.check_containment(hosted.host)
                    + invariants.check_page_hscroll(hosted.host) + invariants.check_text(hosted.host))

    def test_short_laptop_windows_get_four_card_columns(self, hosted):
        """Windows 1366×768 @ 125 % and macOS Larger Text: one row of cards beside the rail."""
        for window in ((1093, 546), (1024, 600)):
            assert _show(hosted, window) is HeightClass.COMPACT
            assert _columns(hosted.page.findChildren(StatisticsCard)) == 4, window
