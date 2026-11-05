"""
Cross-page behavioural tests for ``BaseGroupingPanel._add_to_group``.

The four analysis pages — Snapshots PSD, Snapshots 5 Hz Band, Timeline LFP
Threshold, Timeline Peri-Event — all inherit one shared assignment method,
``BaseGroupingPanel._add_to_group``; none override it. These tests parametrize
over all four concrete panels so the frictionless **accumulate-and-move +
auto-deselect** behaviour is pinned uniformly across every page.

Contract under test:
  * Sending selected types to a group clears the list selection (auto-deselect).
  * Successive sends to the same group accumulate (append, deduplicated).
  * Sending a type to the other group MOVES it (removed from its old group),
    and both group displays refresh.
  * Re-sending an already-grouped type does not duplicate it.
  * An empty selection is a no-op.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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


PANEL_CLASSES = [
    SnapshotsGroupingPanel,
    Snapshots5HzBandGroupingPanel,
    TimelineLfpThresholdGroupingPanel,
    TimelinePeriEventGroupingPanel,
]


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(params=PANEL_CLASSES, ids=lambda c: c.__name__)
def panel(qapp, request):
    """A concrete grouping panel pre-populated with event types A, B, C."""
    widget = request.param()
    widget.set_available_event_types({"A": 3, "B": 5, "C": 2})
    yield widget
    widget.deleteLater()


def _select(panel, *event_types: str) -> None:
    """Select exactly the list items whose stored event type is in
    *event_types* (and deselect all others) — self-contained, so each call
    fully defines the selection regardless of prior state."""
    wanted = set(event_types)
    for i in range(panel.event_types_list.count()):
        item = panel.event_types_list.item(i)
        item.setSelected(item.data(Qt.UserRole) in wanted)


def _selected_types(panel) -> set:
    return {it.data(Qt.UserRole) for it in panel.event_types_list.selectedItems()}


def test_send_clears_selection(panel):
    _select(panel, "A", "B")
    assert _selected_types(panel) == {"A", "B"}  # sanity: selection took
    panel._add_to_group(1)
    assert panel.event_types_list.selectedItems() == []


def test_accumulate_into_same_group(panel):
    _select(panel, "A")
    panel._add_to_group(1)
    _select(panel, "B")
    panel._add_to_group(1)
    assert panel._active_groups[1] == ["A", "B"]
    assert panel._active_groups[2] == []


def test_move_between_groups(panel):
    _select(panel, "A")
    panel._add_to_group(1)
    _select(panel, "A")
    panel._add_to_group(2)
    assert panel._active_groups[1] == []
    assert panel._active_groups[2] == ["A"]
    # Both displays refreshed: G1 list emptied, G2 list shows the moved type.
    assert panel.group1_list.count() == 0
    assert panel.group2_list.count() == 1


def test_resend_does_not_duplicate(panel):
    _select(panel, "A")
    panel._add_to_group(1)
    _select(panel, "A")
    panel._add_to_group(1)
    assert panel._active_groups[1] == ["A"]


def test_empty_selection_is_noop(panel):
    _select(panel, "A")
    panel._add_to_group(1)
    panel.event_types_list.clearSelection()
    panel._add_to_group(2)  # nothing selected
    assert panel._active_groups[1] == ["A"]
    assert panel._active_groups[2] == []
