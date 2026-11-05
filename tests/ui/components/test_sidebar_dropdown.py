"""
Tests for the Sidebar's navigation groups (labelled mode).

Snapshots and Timeline are read-only group headers with their pages always
shown below them; only pages are navigation targets. Validates which pages sit
in which group, the navigation signal, and the active state. (Rewritten for
the M3.6 sidebar, plan D15: the collapsible groups these tests once covered
are gone.)

Author: iEEG BrainSense Development Team
"""

import pytest
from PySide6.QtWidgets import QPushButton

from src.ui.components.sidebar import Sidebar

SNAPSHOTS = ("snapshots_canonical_bands", "snapshots_5hz_band")
TIMELINE = ("timeline_peri_event", "timeline_lfp_threshold")


@pytest.fixture
def sidebar(qtbot):
    s = Sidebar()
    qtbot.addWidget(s)
    return s


def _group_header(sidebar, text):
    return next(b for b in sidebar.findChildren(QPushButton, "nav_group_header")
                if b.text() == text)


class TestGroups:
    """Which buttons are pages, and where they sit."""

    def test_group_pages_registered_in_nav_items(self, sidebar):
        assert set(SNAPSHOTS + TIMELINE) <= set(sidebar.nav_items)

    def test_group_headers_are_not_navigation_targets(self, sidebar):
        assert "snapshots" not in sidebar.nav_items
        assert "timeline" not in sidebar.nav_items

    def test_pages_sit_under_their_group_header(self, sidebar):
        for header_text, pages in (("Snapshots", SNAPSHOTS), ("Timeline", TIMELINE)):
            group = _group_header(sidebar, header_text).parentWidget()
            assert all(group.isAncestorOf(sidebar.nav_items[page]) for page in pages)

    def test_group_pages_are_always_shown(self, sidebar):
        sidebar.show()
        assert all(sidebar.nav_items[page].isVisible() for page in SNAPSHOTS + TIMELINE)

    def test_group_header_click_does_not_emit_navigation(self, sidebar):
        received = []
        sidebar.navigation_changed.connect(received.append)
        header = _group_header(sidebar, "Snapshots")
        header.click()
        assert received == []
        assert sidebar.nav_items["snapshots_canonical_bands"].property("active") is False


class TestChildNavigation:
    """Tests for child item navigation."""

    def test_child_click_emits_navigation_changed(self, sidebar, qtbot):
        with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
            sidebar.nav_items["snapshots_canonical_bands"].click()
        assert blocker.args == ["snapshots_canonical_bands"]

    def test_5hz_child_click_emits_correct_page_name(self, sidebar, qtbot):
        with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
            sidebar.nav_items["snapshots_5hz_band"].click()
        assert blocker.args == ["snapshots_5hz_band"]

    def test_timeline_child_click_emits_correct_page_name(self, sidebar, qtbot):
        with qtbot.waitSignal(sidebar.navigation_changed, timeout=1000) as blocker:
            sidebar.nav_items["timeline_lfp_threshold"].click()
        assert blocker.args == ["timeline_lfp_threshold"]

    def test_click_marks_the_page_active(self, sidebar):
        sidebar.nav_items["timeline_peri_event"].click()
        assert sidebar.nav_items["timeline_peri_event"].property("active") is True
        assert sidebar.nav_items["data_management"].property("active") is False


class TestActiveState:
    """Tests for active state highlighting."""

    def test_data_management_is_active_at_first(self, sidebar):
        assert sidebar.nav_items["data_management"].property("active") is True

    def test_set_active_page_highlights_child(self, sidebar):
        sidebar.set_active_page("snapshots_canonical_bands")
        assert sidebar.nav_items["snapshots_canonical_bands"].property("active") is True

    def test_set_active_page_deactivates_other_child(self, sidebar):
        sidebar.set_active_page("snapshots_canonical_bands")
        assert sidebar.nav_items["snapshots_5hz_band"].property("active") is False

    def test_group_header_never_active(self, sidebar):
        """The header is read-only: it has no active state, even when a child is active."""
        sidebar.set_active_page("snapshots_canonical_bands")
        assert not _group_header(sidebar, "Snapshots").property("active")

    def test_non_snapshots_page_deactivates_all_children(self, sidebar):
        sidebar.set_active_page("snapshots_canonical_bands")
        sidebar.set_active_page("data_management")
        assert sidebar.nav_items["snapshots_canonical_bands"].property("active") is False
        assert sidebar.nav_items["snapshots_5hz_band"].property("active") is False

    def test_flat_nav_items_still_work(self, sidebar):
        sidebar.set_active_page("data_management")
        assert sidebar.nav_items["data_management"].property("active") is True

    def test_unknown_page_highlights_nothing(self, sidebar):
        sidebar.set_active_page("timeline")  # a group, not a page
        assert not any(button.property("active") for button in sidebar.nav_items.values())

    def test_set_active_page_does_not_emit(self, sidebar):
        received = []
        sidebar.navigation_changed.connect(received.append)
        sidebar.set_active_page("timeline_peri_event")
        assert received == []
