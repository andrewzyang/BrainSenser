"""
The Data page in its PageHost (height-for-width, plan §4.5) at every §3.2
viewport: nothing crushed, clipped or scrolling sideways; an honest minimum;
statistics cards in 4 / 2 / 1 columns by their own minimum widths with room
for six-digit counts; metadata in 2 / 1 columns; content at most
Dim.CONTENT_MAX_W wide and centred. Synthetic data, production stylesheet.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

from src.ui.components.badge import Badge
from src.ui.layouts.page_host import PageHost
from src.ui.policy.tokens import TYPE_PX, Dim, Space, TypeRole
from src.ui.views.data_management.components.statistics_card import StatisticsCard
from src.ui.views.data_management.data_management_page import DataManagementPage
from tests.ui.responsive import invariants
from tests.ui.responsive.profiles import VIEWPORTS
from tests.ui.views.data_management._data import make_statistics, populate

SIX_DIGITS = 999_999
SEVEN_DIGITS = 1_234_567


@pytest.fixture
def hosted(qtbot, stub_viewmodel, app_stylesheet) -> SimpleNamespace:
    page = DataManagementPage(viewmodel=stub_viewmodel)
    host = PageHost(page, height_for_width=True)
    qtbot.addWidget(host)
    return SimpleNamespace(host=host, page=page)


def _show(hosted, window: tuple) -> None:
    """Size the host as the content area of a ``window``-sized main window."""
    width, height = window
    _resize_host(hosted, width - Dim.SIDEBAR_W, height - Dim.TOPBAR_H)


def _resize_host(hosted, width: int, height: int) -> None:
    hosted.host.resize(width, height)
    hosted.host.show()
    for _ in range(4):
        QApplication.processEvents()


def _violations(widget) -> list:
    return (invariants.check_crushed(widget) + invariants.check_containment(widget)
            + invariants.check_page_hscroll(widget) + invariants.check_text(widget))


def _cards(page) -> list:
    return page.findChildren(StatisticsCard)


def _card_columns(page) -> int:
    cards = _cards(page)
    return sum(card.y() == cards[0].y() for card in cards)


def _metadata_columns(page) -> tuple:
    """The patient and device columns, in that order."""
    panel = page.patient_overview.metadata_panel
    return (panel.name_label.parentWidget(), panel.neurostimulator_label.parentWidget())


class TestEveryViewport:
    @pytest.mark.parametrize("window", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
    @pytest.mark.parametrize("state", ["empty", "populated"])
    def test_nothing_crushed_clipped_or_scrolling_sideways(self, hosted, window, state):
        if state == "populated":
            populate(hosted.page, count=SIX_DIGITS)
        _show(hosted, window)
        assert not _violations(hosted.host)
        assert hosted.host.horizontalScrollBar().maximum() == 0

    @pytest.mark.parametrize("window", [(1280, 769), (1093, 546), (600, 500)])
    def test_seven_digit_counts_reflow_instead_of_clipping(self, hosted, window):
        populate(hosted.page, count=SEVEN_DIGITS)
        _show(hosted, window)
        assert not _violations(hosted.host)


class TestMinimum:
    def test_populated_page_fits_the_window_floor_beside_the_sidebar(self, hosted):
        populate(hosted.page, count=SIX_DIGITS)
        content = Dim.WINDOW_MIN_W - Dim.SIDEBAR_W - Dim.SCROLLBAR
        assert hosted.page.minimumSizeHint().width() <= content

    def test_empty_page_is_sized_by_the_empty_state_alone(self, hosted):
        empty = hosted.page.minimumSizeHint()
        populate(hosted.page)
        hosted.page._on_patient_cleared()
        assert hosted.page.minimumSizeHint() == empty
        assert empty.height() < hosted.page.patient_overview.minimumSizeHint().height()
        _show(hosted, (1024, 560))
        assert hosted.host.verticalScrollBar().maximum() == 0

    def test_page_scrolls_vertically_only_below_its_reflowed_height(self, hosted):
        populate(hosted.page)
        _show(hosted, (1280, 769))
        width = hosted.host.viewport().width()
        needed = hosted.page.heightForWidth(width)
        _resize_host(hosted, width, needed)
        assert hosted.host.verticalScrollBar().maximum() == 0
        _resize_host(hosted, width, needed - 40)
        viewport = hosted.host.viewport()
        assert hosted.host.verticalScrollBar().maximum() > 0
        assert hosted.page.height() == hosted.page.heightForWidth(viewport.width())


class TestCards:
    @pytest.mark.parametrize("columns, narrower", [(4, 2), (2, 1), (1, 1)])
    def test_as_many_columns_as_the_cards_minimum_allows(self, hosted, columns, narrower):
        populate(hosted.page, count=SIX_DIGITS)
        _show(hosted, (1600, 1100))
        card_min = max(card.minimumSizeHint().width() for card in _cards(hosted.page))
        side_gutters = 4 * Space.X8  # page and overview margins, both sides
        width = columns * card_min + (columns - 1) * Space.X6 + side_gutters
        _resize_host(hosted, width, 2000)  # tall: no vertical scrollbar takes width
        assert _card_columns(hosted.page) == columns
        _resize_host(hosted, width - 1, 2000)
        assert _card_columns(hosted.page) == narrower

    @pytest.mark.parametrize("window", [(1280, 769), (1024, 560), (600, 500)])
    def test_cards_are_equal_and_never_below_the_reference_height(self, hosted, window):
        populate(hosted.page)
        _show(hosted, window)
        sizes = {(card.width(), card.height()) for card in _cards(hosted.page)}
        assert len(sizes) == 1
        assert sizes.pop()[1] >= Dim.STAT_CARD_H

    def test_six_digit_counts_fit_the_reserve(self, hosted):
        populate(hosted.page)

        def card_minimums(count: int) -> list:
            hosted.page.patient_overview.update_statistics(make_statistics(count))
            _show(hosted, (1280, 769))  # lay out, so nested layouts drop cached sizes
            return [card.minimumSizeHint().width() for card in _cards(hosted.page)]

        small = card_minimums(12)
        assert card_minimums(SIX_DIGITS) == small
        assert all(seven > width for seven, width in zip(card_minimums(SEVEN_DIGITS), small))


class TestMetadata:
    def test_two_columns_side_by_side_then_stacked(self, hosted):
        populate(hosted.page)
        patient, device = _metadata_columns(hosted.page)
        _show(hosted, (1280, 769))
        assert (patient.y(), patient.x() < device.x()) == (device.y(), True)
        _show(hosted, (600, 500))
        assert (patient.x(), patient.y() < device.y()) == (device.x(), True)

    def test_side_margins_give_way_only_at_the_columns_minimum(self, hosted):
        populate(hosted.page)
        patient, device = _metadata_columns(hosted.page)
        _show(hosted, (1280, 769))
        assert patient.x() == Space.X12
        _show(hosted, (600, 500))
        assert patient.x() < Space.X12
        assert patient.width() >= patient.minimumSizeHint().width()
        assert device.width() >= device.minimumSizeHint().width()


class TestFonts:
    def test_todays_sizes_and_weights_under_the_stylesheet(self, hosted):
        def rendered(labels) -> dict:
            return {label: (QFontInfo(label.font()).pixelSize(), label.font().weight())
                    for label in labels}

        body = TYPE_PX[TypeRole.BODY]
        _show(hosted, (1280, 769))
        empty = hosted.page.empty_state
        assert rendered([empty.title_label, empty.description_label]) == {
            empty.title_label: (body, QFont.Weight.Bold),
            empty.description_label: (body, QFont.Weight.Normal)}

        populate(hosted.page)
        _show(hosted, (1280, 769))
        overview = hosted.page.patient_overview
        card = overview.snapshots_card
        weights = {
            card.title_label: QFont.Weight.Medium,
            card.original_count_label: QFont.Weight.Medium,
            card.dedup_count_label: QFont.Weight.Medium,
            card.original_label_text: QFont.Weight.Normal,
            card.dedup_label_text: QFont.Weight.Normal,
            overview.metadata_panel.name_label: QFont.Weight.Normal,
        }
        weights.update({badge: QFont.Weight.Medium for badge in hosted.page.findChildren(Badge)})
        assert rendered(weights) == {label: (body, weight) for label, weight in weights.items()}


class TestHugeScreens:
    def test_content_is_capped_and_centred(self, hosted):
        populate(hosted.page)
        _show(hosted, (3840, 2120))
        content = hosted.page.content_stack
        assert content.width() == Dim.CONTENT_MAX_W
        left = content.x()
        right = hosted.page.width() - (content.x() + content.width())
        assert abs(left - right) <= 1

    def test_regular_pages_use_the_full_width(self, hosted):
        _show(hosted, (1280, 769))
        content = hosted.page.content_stack
        assert content.x() == Space.X8
        assert content.width() == hosted.page.width() - 2 * Space.X8
