"""Self-tests of the responsive invariant detectors on small synthetic widget
trees and figures: each detector catches a planted violation and passes the
clean twin of the same tree."""

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from tests.ui.responsive import invariants as inv


@pytest.fixture
def window(qapp):
    """A top-level window; tests fill its vertical layout, then show it."""
    win = QWidget()
    QVBoxLayout(win)
    yield win
    win.close()
    win.deleteLater()


def show(win, width=600, height=400):
    win.resize(width, height)
    win.show()
    QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QApplication.processEvents()


def kinds(violations):
    return [v.invariant for v in violations]


# ------------------------------------------------------------------------- I1

def _card_row(width, explicit_minimum=True):
    """Four cards in a row of a fixed width: 128-px explicit minimums (the
    data-page cards) or text whose size hint is the minimum (the upload badges)."""
    row = QWidget()
    row.setFixedSize(width, 40)
    layout = QHBoxLayout(row)
    for _ in range(4):
        card = QLabel("card" if explicit_minimum else "Deduplicated: 45,977")
        if explicit_minimum:
            card.setMinimumWidth(128)
        layout.addWidget(card)
    return row


@pytest.mark.parametrize("width, crushed", [(300, ["QWidget#row"]), (600, [])])
def test_crushed_finds_a_widget_smaller_than_its_own_layout(window, width, crushed):
    row = _card_row(width)
    row.setObjectName("row")
    window.layout().addWidget(row)
    show(window, 700)
    assert [v.path for v in inv.check_crushed(window)] == crushed


@pytest.mark.parametrize("width, crushed", [(300, 4), (700, 0)])
def test_crushed_finds_widgets_below_the_minimum_their_layout_gives_them(window, width, crushed):
    window.layout().addWidget(_card_row(width, explicit_minimum=False))
    show(window, 800)
    found = [v for v in inv.check_crushed(window) if v.path.endswith("QLabel")]
    assert len(found) == crushed


def test_crushed_ignores_hidden_stack_pages(window):
    stack = QStackedWidget()
    stack.addWidget(QLabel("visible page"))
    hidden = QWidget()
    QVBoxLayout(hidden).addWidget(_card_row(300))
    stack.addWidget(hidden)
    window.layout().addWidget(stack)
    show(window, 700)
    assert inv.check_crushed(window) == []


# ------------------------------------------------------------------------- I2

@pytest.mark.parametrize("x, outside", [(250, True), (100, False)])
def test_containment_finds_children_outside_their_parent(window, x, outside):
    parent = QWidget()
    parent.setFixedSize(300, 60)
    QLabel("child", parent).setGeometry(x, 10, 100, 20)
    window.layout().addWidget(parent)
    show(window)
    assert kinds(inv.check_containment(window)) == (["I2"] if outside else [])


def test_containment_allows_scroll_content_beyond_the_viewport(window):
    area = QScrollArea()
    content = QWidget()
    content.setMinimumSize(2000, 2000)
    area.setWidget(content)
    window.layout().addWidget(area)
    show(window)
    assert inv.check_containment(window) == []


# ------------------------------------------------------------------------- I3

def test_window_size_reports_a_forced_window_and_what_sets_its_minimum(window):
    stack = QStackedWidget()
    stack.addWidget(QLabel("small page"))
    big = QWidget()
    big.setObjectName("big_page")
    big.setMinimumSize(900, 700)
    stack.addWidget(big)  # hidden, yet a stack's minimum is the max over its pages
    window.layout().addWidget(stack)
    show(window, 600, 500)
    found = inv.check_window_size(window, (600, 500))
    assert kinds(found) == ["I3"] and "big_page" in found[0].detail
    window.resize(1000, 800)
    QApplication.processEvents()
    assert inv.check_window_size(window, (1000, 800)) == []


def test_window_fits_reports_floor_overflow_and_off_screen_controls(window):
    available = QRect(0, 0, 700, 500)
    window.setMinimumSize(800, 600)
    window.layout().addStretch()
    window.layout().addWidget(QPushButton("Compare Groups"))
    show(window)
    window.setGeometry(0, 28, 800, 600)
    QApplication.processEvents()
    found = inv.check_window_fits(window, available, 28, (600, 500))
    assert len(found) == 2 and "Compare Groups" in found[1].detail
    window.setMinimumSize(500, 400)
    window.setGeometry(0, 28, 700, 472)
    QApplication.processEvents()
    assert inv.check_window_fits(window, available, 28, (600, 500)) == []


# ------------------------------------------------------------------------- I4

def test_page_hscroll_flags_scroll_areas_but_not_tables(window):
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    content.setMinimumWidth(2000)
    area.setWidget(content)
    table = QTableWidget(2, 30)
    window.layout().addWidget(area)
    window.layout().addWidget(table)
    show(window)
    found = inv.check_page_hscroll(window)
    assert kinds(found) == ["I4"] and found[0].path.endswith("QScrollArea")
    content.setMinimumWidth(0)
    QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
    QApplication.processEvents()
    assert inv.check_page_hscroll(window) == []


# ------------------------------------------------------------------------- I5

def _fixed(widget, width):
    widget.setFixedWidth(width)
    return widget


@pytest.mark.parametrize("make", [
    lambda: _fixed(QLabel("Deduplicated: 45,977"), 40),
    lambda: _fixed(QPushButton("Compare Groups"), 40),
    lambda: _fixed(QSpinBox(maximum=10**9, value=10**9 - 1), 30),
])
def test_text_finds_clipped_labels_buttons_and_spinboxes(window, make):
    clipped = make()
    window.layout().addWidget(clipped)
    show(window)
    assert kinds(inv.check_text(window)) == ["I5"]
    clipped.setFixedWidth(400)
    QApplication.processEvents()
    assert inv.check_text(window) == []


def test_text_finds_an_icon_larger_than_its_button(window):
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.black)
    button = QPushButton()
    button.setIcon(QIcon(pixmap))
    button.setIconSize(pixmap.size())
    button.setFixedSize(20, 20)
    window.layout().addWidget(button)
    show(window)
    assert kinds(inv.check_text(window)) == ["I5"]
    button.setFixedSize(48, 48)
    QApplication.processEvents()
    assert inv.check_text(window) == []


@pytest.mark.parametrize("editable", [False, True])
def test_text_accepts_a_clipped_combo_only_with_a_tooltip(window, editable):
    combo = _fixed(QComboBox(editable=editable), 80)
    if editable:  # the top-bar patient search: an empty editable combo shows a placeholder
        combo.lineEdit().setPlaceholderText(text := "Select patient...")
    else:
        combo.addItem(text := "FDR (Benjamini-Hochberg)")
    window.layout().addWidget(combo)
    show(window)
    assert kinds(inv.check_text(window)) == ["I5"]
    combo.setToolTip(text)
    assert inv.check_text(window) == []


def test_text_accepts_elided_cells_and_headers_only_with_tooltips(window):
    table = QTableWidget(1, 1)
    table.setHorizontalHeaderItem(0, QTableWidgetItem("Effect size 95% CI"))
    table.setItem(0, 0, QTableWidgetItem("[-0.512, 0.387] rank-biserial"))
    table.setColumnWidth(0, 40)
    window.layout().addWidget(table)
    show(window)
    assert kinds(inv.check_text(window)) == ["I5", "I5"]
    table.horizontalHeaderItem(0).setToolTip("Effect size 95% CI")
    table.item(0, 0).setToolTip("[-0.512, 0.387] rank-biserial")
    assert inv.check_text(window) == []


def test_text_measures_list_items_as_drawn(window):
    """A list item elided to its row is found whatever its size hint says: the
    grouping lists' zero-wide hints hid "Neutral… (n=62)" from it. The item
    passes with its full text as tooltip, or wrapped onto two lines."""
    members = QListWidget()
    members.setFixedWidth(120)
    members.addItem(text := "Neutral/Happy (n=62)")
    members.item(0).setSizeHint(QSize(0, members.sizeHintForRow(0)))
    window.layout().addWidget(members)
    show(window)
    assert kinds(inv.check_text(window)) == ["I5"]
    members.item(0).setToolTip(text)
    assert inv.check_text(window) == []
    members.clear()
    members.setWordWrap(True)
    members.addItem(text)
    QApplication.processEvents()
    one_line = members.sizeHintForRow(0)  # measured without a width: unwrapped
    assert members.visualRect(members.model().index(0, 0)).height() > one_line
    assert inv.check_text(window) == []


def test_group_membership_needs_a_member_tooltip_and_three_full_rows(window):
    header = QLabel("Group 2 (n=70)")
    members = QListWidget()
    members.addItems(["Craving (n=37)", "Drinking (n=22)", "Drinking/Craving (n=11)"])
    window.layout().addWidget(header)
    window.layout().addWidget(members)
    row = members.sizeHintForRow(0)
    members.setFixedHeight(round(2.7 * row))
    show(window)
    found = inv.check_group_membership(header, members)
    assert ["does not list Craving, Drinking, Drinking/Craving" in found[0].detail,
            "needs 3 full rows" in found[1].detail] == [True, True]
    header.setToolTip("Craving, Drinking, Drinking/Craving")
    members.setFixedHeight(3 * row + 2 * members.frameWidth() + 4)
    QApplication.processEvents()
    assert inv.check_group_membership(header, members) == []


# ------------------------------------------------------------------------- I6

def _figure(*extra_texts, data=False, **statistic):
    """A drawn 5×4-inch, 100-dpi figure: a data line along the diagonal, a dashed
    reference line at y = 0.9, 7.5-pt ticks and a statistic in the lower right
    (``statistic`` overrides its ax.text arguments, in axes coordinates unless
    ``data``; ``extra_texts`` adds texts)."""
    figure = Figure(figsize=(5, 4), dpi=100)
    FigureCanvasAgg(figure)
    ax = figure.subplots()
    ax.plot([0, 1], [0, 1])
    ax.axhline(0.9, linestyle="--")
    ax.tick_params(labelsize=7.5)
    ax.set_title("Electrode 1", fontsize=9)
    options = dict(x=0.95, y=0.05, s="AUC 0.712 [0.611, 0.803]", fontsize=9, ha="right")
    options.update(statistic)
    ax.text(options.pop("x"), options.pop("y"), options.pop("s"),
            transform=ax.transData if data else ax.transAxes, **options)
    for text in extra_texts:
        ax.text(**text, transform=ax.transAxes)
    figure.canvas.draw()
    return figure


def test_plot_text_passes_a_clean_figure():
    assert inv.check_plot_text(_figure(), 1.0, "plot") == []


@pytest.mark.parametrize("statistic, problem", [
    (dict(fontsize=6), "statistic texts below"),
    (dict(fontsize=20), "above the 24-px cap"),
    (dict(x=1.6), "outside the figure"),
    (dict(x=0.5, y=0.5, ha="center"), "drawn over data"),
])
def test_plot_text_finds_planted_problems(statistic, problem):
    found = inv.check_plot_text(_figure(**statistic), 1.0, "plot")
    assert any(problem in v.detail for v in found), found


def test_plot_text_finds_overlapping_texts():
    legend_like = dict(x=0.97, y=0.06, s="Group 2 (n = 70)", fontsize=9, ha="right")
    found = inv.check_plot_text(_figure(legend_like), 1.0, "plot")
    assert [v.detail for v in found] == ["'AUC 0.712 [0.611, 0.803]' overlaps 'Group 2 (n = 70)'"]


def test_plot_text_floor_and_cap_follow_the_interface_size():
    figure = _figure()
    figure.axes[0].tick_params(labelsize=5)  # 6.9 px: below 9 px, above 9 × 0.75
    figure.canvas.draw()
    assert "tick floor" in inv.check_plot_text(figure, 1.0, "plot")[0].detail
    assert inv.check_plot_text(figure, 1.0, "plot", ui_scale=0.75) == []


def test_plot_text_statistics_may_sit_on_reference_lines():
    figure = _figure(x=0.3, y=0.9, s="985 µV", ha="center", va="center", data=True)
    figure.axes[0].lines[0].set_visible(False)  # keep only the dashed reference line
    figure.canvas.draw()
    assert inv.check_plot_text(figure, 1.0, "plot") == []
    figure.axes[0].lines[0].set_visible(True)  # the diagonal passes (0.3, 0.3), not the text
    figure.axes[0].plot([0.3, 0.3], [0, 1])    # a vertical data line through the text does
    figure.canvas.draw()
    assert "drawn over data" in inv.check_plot_text(figure, 1.0, "plot")[0].detail


# ------------------------------------------------------------------ I7 / I7b

def test_section_arrangement_classifies_row_and_stacked():
    row = [QRect(0, 0, 100, 200), QRect(108, 0, 100, 200), QRect(216, 0, 150, 200),
           QRect(374, 0, 374, 200)]
    stacked = [QRect(0, 0, 200, 150), QRect(208, 0, 200, 150), QRect(416, 0, 300, 150),
               QRect(0, 158, 716, 300)]
    assert inv.section_arrangement(row) == "ROW"
    assert inv.section_arrangement(stacked) == "STACKED"
    assert inv.section_arrangement([row[0], row[1], stacked[3], row[3]]) == "OTHER"


def test_check_arrangement_reports_facts_the_class_does_not_want():
    assert inv.check_arrangement({"panel": "ROW"}, {"panel": "ROW"}, "1280×769") == []
    found = inv.check_arrangement({"panel": "ROW"}, {"panel": "STACKED"}, "960×1010")
    assert kinds(found) == ["I7"]


def test_widget_count_must_not_change_across_cells():
    assert inv.check_widget_count({"a": 661, "b": 661}, "p") == []
    assert kinds(inv.check_widget_count({"a": 661, "b": 662}, "p")) == ["I7"]


def test_history_free_and_no_flap():
    labels, rail = {"panel": "ROW", "sidebar": 200}, {"panel": "ROW", "sidebar": 56}
    assert inv.check_history_free({"1280x769": [labels, labels]}, "p") == []
    assert kinds(inv.check_history_free({"1280x769": [labels, rail]}, "p")) == ["I7b"]
    settles = [(1119, rail), (1120, labels), (1121, labels), (1120, labels)]
    assert inv.check_no_flap(settles, "w") == []
    assert kinds(inv.check_no_flap([(1119, rail), (1120, labels), (1119, rail)], "w")) == ["I7b"]


# ------------------------------------------------------------------ I8b / I9

def test_ladder_fonts_never_shrink_and_heights_step_down_once():
    def levels(fonts, heights):
        return [(p, {"button": (f, h)}) for p, f, h in zip((100, 125, 150), fonts, heights)]
    assert inv.check_ladder(levels((30, 37.5, 45), (76, 70, 84)), "p") == []
    assert "font shrinks" in inv.check_ladder(levels((30, 28, 45), (76, 95, 114)), "p")[0].detail
    assert "more than once" in inv.check_ladder(levels((30, 37.5, 45), (76, 70, 64)), "p")[0].detail


def test_exports_identical():
    same = {("PeriEventPlot", "png"): {"a/600x500": "x", "b/3840x2120": "x"}}
    assert inv.check_exports_identical(same) == []
    differ = {("PeriEventPlot", "svg"): {"a": "x", "b": "y"}}
    assert kinds(inv.check_exports_identical(differ)) == ["I9"]


# ------------------------------------------------------------------------ I10

def test_screen_change_needs_the_move_noticed_and_the_floor_kept(window):
    window.setMinimumSize(300, 200)
    show(window)
    screen = window.screen()
    area = screen.availableGeometry()
    window.setGeometry(area.x(), area.y() + 28, 400, 300)
    QApplication.processEvents()
    assert inv.check_screen_change(window, screen, 28, (600, 500), [screen.name()]) == []
    unnoticed = inv.check_screen_change(window, screen, 28, (600, 500), [])
    assert "no screenChanged" in unnoticed[0].detail
    window.setMinimumSize(700, 550)
    too_big = inv.check_screen_change(window, screen, 28, (600, 500), [screen.name()])
    assert "above the floor" in too_big[0].detail


# --------------------------------------------------------------------- hooks

def test_a_missing_production_module_is_pending():
    with pytest.raises(inv.Pending, match="M9"):
        inv._require("src.ui.policy.not_written_yet", "M9")
