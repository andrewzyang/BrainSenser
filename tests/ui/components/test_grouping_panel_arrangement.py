"""
The grouping panel's ROW arrangement and its controls (plan M1.6, D9, D11).

The four sections sit in one row of a grid. On panels up to ~1245 px they get
exactly the widths today's QHBoxLayout gave them; wider panels cap the three
setup sections and give the rest to the table. Fields stop at Dim.FIELD_MAX_W
and buttons at Dim.BUTTON_MAX_W, left-aligned. Lists show one row per item and
never scroll sideways, and group lists show whole rows; every list item shows
its full text on hover, as do the squeezed Correction combo and the long
control tooltips.
"""

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent, QTextDocument
from PySide6.QtWidgets import QApplication, QHBoxLayout, QToolTip, QWidget

from src.ui.app_style import apply_app_stylesheet
from src.ui.policy.tokens import DENSITY_SPECS, Dim, Space
from src.ui.views.snapshots_5hz_band.components.grouping_panel import (
    Snapshots5HzBandGroupingPanel,
)
from src.ui.views.snapshots_psd.components.grouping_panel import SnapshotsGroupingPanel
from src.ui.views.timeline_lfp_threshold.components.grouping_panel import (
    TimelineLfpThresholdGroupingPanel,
)
from src.ui.views.timeline_peri_event.components.grouping_panel import (
    TimelinePeriEventGroupingPanel,
)
from tests.ui.responsive.invariants import list_item_issue

PANELS = [SnapshotsGroupingPanel, Snapshots5HzBandGroupingPanel,
          TimelineLfpThresholdGroupingPanel, TimelinePeriEventGroupingPanel]
# The synthetic state of tests/ui/_synthetic.py: long and short member names.
EVENTS = {"Anxious": 14, "Craving": 37, "Depressed": 9, "Drinking": 22,
          "Drinking/Craving": 11, "Happy": 31, "Neutral": 48, "Sad": 12}
GROUP_1 = ["Anxious", "Happy", "Neutral", "Sad", "Depressed"]
GROUP_2 = ["Craving", "Drinking", "Drinking/Craving"]
UNBOUNDED = 16777215  # QWIDGETSIZE_MAX


def _plain(text: str) -> str:
    doc = QTextDocument()
    doc.setHtml(text)
    return doc.toPlainText()


def _assign(panel, groups) -> None:
    """Select each group's names in the Event Types list and send them to it."""
    for group, names in groups:
        for row in range(panel.event_types_list.count()):
            item = panel.event_types_list.item(row)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in names)
        panel._add_to_group(group)


def _make(cls, qtbot):
    panel = cls()
    qtbot.addWidget(panel)
    panel.set_available_event_types(EVENTS)
    _assign(panel, ((1, GROUP_1), (2, GROUP_2)))
    return panel


def _rects(view) -> list:
    return [view.visualRect(view.model().index(row, 0)) for row in range(view.count())]


def _show(widget: QWidget, width: int, height: int = 240) -> None:
    widget.resize(width, height)
    widget.show()
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture(scope="module", autouse=True)
def app_style(qapp):
    """The production stylesheet, once for the module (a restyle re-polishes
    every live widget); the previous one is back afterwards."""
    previous = qapp.styleSheet()
    apply_app_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


@pytest.fixture(params=PANELS, ids=lambda cls: cls.__name__)
def panel(request, qtbot):
    return _make(request.param, qtbot)


def _sections(panel) -> list:
    return [section.width() for section in panel._sections]


def _row_of(widget: QWidget):
    """The layout that holds ``widget`` itself (rows nest inside a column)."""
    def find(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget() is widget:
                return layout
            if item.layout() is not None and (found := find(item.layout())) is not None:
                return found
        return None
    return find(widget.parentWidget().layout())


def _today_row(cls, qtbot):
    """A fresh panel's four sections in today's layout — one QHBoxLayout with
    4-px margins, 8-px spacing and 2:2:3:7 stretches, no caps. Returns the row
    and its sections (the row must be kept: qtbot holds widgets weakly)."""
    donor = _make(cls, qtbot)
    row = QWidget()
    qtbot.addWidget(row)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(8)
    for section, stretch in zip(donor._sections, (2, 2, 3, 7)):
        section.setMaximumWidth(UNBOUNDED)
        layout.addWidget(section, stretch)
    return row, donor._sections


class TestRowArrangement:
    @pytest.mark.parametrize("width", [600, 760, 861, 1048, 1050, 1208, 1245])
    def test_widths_are_todays_up_to_the_caps(self, qtbot, width):
        for cls in PANELS:
            panel = _make(cls, qtbot)
            row, sections = _today_row(cls, qtbot)
            _show(panel, width)
            _show(row, width)
            assert _sections(panel) == [section.width() for section in sections], cls.__name__

    def test_setup_sections_stop_at_their_caps_and_the_table_takes_the_rest(self, panel):
        width = 1688  # a maximised 1920-px window
        _show(panel, width)
        caps = [Dim.EVENT_TYPES_MAX_W, Dim.GROUPS_MAX_W, Dim.CONTROLS_MAX_W]
        assert _sections(panel)[:3] == caps
        assert _sections(panel)[3] == width - 2 * Space.X1 - 3 * Space.X2 - sum(caps)

    def test_the_controls_cap_binds_first(self, panel):
        _show(panel, 1300)
        widths = _sections(panel)
        assert widths[2] == Dim.CONTROLS_MAX_W
        assert abs(widths[0] - widths[1]) <= 1 and max(widths[:2]) < Dim.EVENT_TYPES_MAX_W
        assert widths[3] > sum(widths[:3])

    def test_sections_are_placed_once_in_one_row(self, panel):
        grid = panel.layout()
        positions = [grid.getItemPosition(grid.indexOf(section)) for section in panel._sections]
        assert positions == [(0, column, 1, 1) for column in range(4)]
        assert panel.section_stretches() == [2, 2, 3, 7]


class TestFieldsAndButtons:
    def _controls(self, panel):
        """The panel's visible controls-section fields with their row labels."""
        names = ("test_method_combo", "correction_method_combo", "n_boot_combo",
                 "n_perm_combo", "window_spinbox")
        return [getattr(panel, name) for name in names
                if getattr(panel, name, None) is not None and getattr(panel, name).isVisible()]

    def test_fields_and_buttons_are_capped(self, panel):
        _show(panel, 1048)
        assert self._controls(panel)
        assert all(field.maximumWidth() == Dim.FIELD_MAX_W for field in self._controls(panel))
        assert panel.effect_size_selector.dropdown.maximumWidth() == Dim.FIELD_MAX_W
        assert panel.compare_btn.maximumWidth() == Dim.BUTTON_MAX_W
        assert panel.clear_groups_btn.maximumWidth() == Dim.BUTTON_MAX_W

    def test_uncapped_sections_keep_fields_and_buttons_left_aligned(self, panel):
        # As the stacked arrangement will (M3): setup sections without caps.
        for section in panel._sections[:3]:
            section.setMaximumWidth(UNBOUNDED)
        _show(panel, 3600)
        for field in self._controls(panel):
            assert field.width() == Dim.FIELD_MAX_W
            row = _row_of(field)
            label = row.itemAt(0).widget()
            # Right after its label, not spread across the row.
            assert field.x() == label.geometry().right() + 1 + row.spacing()
        for button in (panel.compare_btn, panel.clear_groups_btn):
            assert (button.x(), button.width()) == (0, Dim.BUTTON_MAX_W)

    @pytest.mark.parametrize("cls", PANELS[1:], ids=lambda cls: cls.__name__)
    def test_pages_without_test_controls_hide_the_whole_rows(self, cls, qtbot):
        panel = _make(cls, qtbot)
        assert panel._test_row_widget.isHidden()
        assert panel._correction_row_widget.isHidden()
        assert panel.effect_size_selector.isHidden()

    def test_the_psd_page_keeps_its_test_controls(self, qtbot):
        panel = _make(SnapshotsGroupingPanel, qtbot)
        _show(panel, 1048)
        assert panel._test_row_widget.isVisible() and panel._correction_row_widget.isVisible()


class TestGroupLists:
    def test_group_lists_show_whole_rows_at_the_panel_minimum(self, panel):
        _show(panel, 1048, panel.minimumSizeHint().height())
        rows = DENSITY_SPECS["regular"].list_rows
        for members in (panel.group1_list, panel.group2_list):
            assert members.count() >= rows
            assert members.viewport().height() == rows * members.sizeHintForRow(0)
            viewport = members.viewport().rect()
            assert all(viewport.contains(members.visualRect(members.model().index(row, 0)))
                       for row in range(rows))

    def test_lists_elide_instead_of_scrolling_sideways(self, panel):
        _show(panel, 760)
        for view in (panel.event_types_list, panel.group1_list, panel.group2_list):
            assert view.textElideMode() == Qt.TextElideMode.ElideMiddle
            assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            assert view.horizontalScrollBar().maximum() == 0
            for row in range(view.count()):
                assert view.visualRect(view.model().index(row, 0)).width() == view.viewport().width()

    def _tooltip_at(self, qtbot, view, row: int) -> str:
        QToolTip.hideText()  # takes effect on a timer
        qtbot.waitUntil(lambda: not QToolTip.isVisible())
        view.scrollTo(view.model().index(row, 0))
        center = view.visualRect(view.model().index(row, 0)).center()
        QApplication.sendEvent(view.viewport(), QHelpEvent(
            QEvent.Type.ToolTip, center, view.viewport().mapToGlobal(center)))
        return QToolTip.text() if QToolTip.isVisible() else ""

    def test_hovering_any_item_shows_its_full_name(self, panel, qtbot):
        """Every item's pop-up is its full text, elided in its row or not: nothing
        measures whether it is cut, so the pop-up can't disagree with the paint."""
        _show(panel, 1048)
        for view in (panel.event_types_list, panel.group1_list, panel.group2_list):
            texts = [view.item(row).text() for row in range(view.count())]
            assert [view.item(row).toolTip() for row in range(view.count())] == texts
        view = panel.group2_list
        texts = [view.item(row).text() for row in range(view.count())]
        long_row = texts.index("Drinking/Craving (n=11)")
        short_row = texts.index("Craving (n=37)")
        advance = view.fontMetrics().horizontalAdvance
        assert advance(texts[long_row]) > view.viewport().width() > advance(texts[short_row]) + 8
        assert self._tooltip_at(qtbot, view, long_row) == texts[long_row]
        assert self._tooltip_at(qtbot, view, short_row) == texts[short_row]
        QToolTip.hideText()

    @pytest.mark.parametrize("width", [1100, 760])
    def test_long_names_take_one_row_and_show_in_full_on_hover(self, qtbot, width):
        """The names that were cut: at 1100 px the Event Types column is ~145 px,
        too narrow for "Anxious/Sad (n=21)" and "Neutral/Happy (n=62)". They stay on
        one row as tall as every other, so no row or selection box overlaps
        another, and hovering shows them whole."""
        panel = SnapshotsGroupingPanel()
        qtbot.addWidget(panel)
        panel.set_available_event_types(
            {"Anxious": 9, "Anxious/Sad": 21, "Craving": 25, "Depressed": 2, "Neutral/Happy": 62})
        _assign(panel, ((1, ["Neutral/Happy", "Anxious/Sad", "Anxious"]),
                        (2, ["Craving", "Depressed"])))
        _show(panel, width)
        for view in (panel.event_types_list, panel.group1_list, panel.group2_list):
            rects = _rects(view)
            assert {rect.height() for rect in rects} == {view.sizeHintForRow(0)}
            assert all(below.top() == above.bottom() + 1 for above, below in zip(rects, rects[1:]))
            assert [view.item(row).toolTip() for row in range(view.count())] == [
                view.item(row).text() for row in range(view.count())]
        events = panel.event_types_list
        texts = [events.item(row).text() for row in range(events.count())]
        row = texts.index("Neutral/Happy (n=62)")
        assert list_item_issue(events, texts[row], _rects(events)[row]) is not None  # elided
        assert self._tooltip_at(qtbot, events, row) == "Neutral/Happy (n=62)"
        QToolTip.hideText()

    def test_group_labels_list_their_members(self, panel):
        assert panel.group1_label.toolTip()
        for label, members in ((panel.group1_label, panel.group1_list),
                               (panel.group2_label, panel.group2_list)):
            listed = _plain(label.toolTip()).splitlines()
            assert listed == [members.item(row).text() for row in range(members.count())]

    def test_empty_groups_have_no_member_tooltip(self, panel):
        panel.clear_active_groups()
        assert (panel.group1_label.toolTip(), panel.group2_label.toolTip()) == ("", "")
        assert panel.group1_label.text() == "Group 1 (n=0)"


class TestCorrectionCombo:
    def test_a_squeezed_correction_is_elided_with_its_text_as_tooltip(self, qtbot):
        panel = _make(SnapshotsGroupingPanel, qtbot)
        combo = panel.correction_method_combo
        _show(panel, 1048)
        assert combo.minimumSizeHint().width() < combo.fontMetrics().horizontalAdvance(combo.currentText())
        assert combo.toolTip() == "FDR (Benjamini-Hochberg)"
        _show(panel, 1600)
        assert combo.toolTip() == ""
        combo.setCurrentText("Holm")
        _show(panel, 1048)
        assert combo.toolTip() == ""


TOOLTIP_SITES = [
    (TimelineLfpThresholdGroupingPanel, ("n_perm_combo", "n_boot_combo", "window_spinbox")),
    (TimelinePeriEventGroupingPanel, ("n_boot_combo", "n_perm_combo", "window_spinbox")),
    (Snapshots5HzBandGroupingPanel, ("n_perm_combo", "n_boot_combo")),
]


@pytest.mark.parametrize("cls, names", TOOLTIP_SITES, ids=[cls.__name__ for cls, _ in TOOLTIP_SITES])
def test_long_control_tooltips_wrap(cls, names, qtbot):
    panel = _make(cls, qtbot)
    for name in names:
        tooltip = getattr(panel, name).toolTip()
        assert Qt.mightBeRichText(tooltip), name
        assert len(_plain(tooltip)) > 100, name


def test_a_wrapped_tooltip_shows_narrower_than_its_line(qtbot):
    panel = _make(TimelineLfpThresholdGroupingPanel, qtbot)
    _show(panel, 1048)
    tooltip = panel.window_spinbox.toolTip()
    QToolTip.showText(QPoint(10, 10), tooltip, panel)
    label = next(w for w in QApplication.topLevelWidgets() if w.objectName() == "qtooltip_label")
    one_line = label.fontMetrics().horizontalAdvance(_plain(tooltip))
    assert label.wordWrap() and label.width() < one_line
    QToolTip.hideText()
