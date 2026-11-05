"""Detectors for the responsive-layout invariants of plan §3.2.

Every detector is a pure function over a live widget tree, a matplotlib figure
or recorded observations, and returns a list of :class:`Violation` (empty when
the invariant holds). Thresholds are logical px; geometry comparisons allow
``TOLERANCE_PX``.

| ID  | Detector |
|-----|----------|
| I1  | :func:`check_crushed` — no visible widget below its layout minimum |
| I2  | :func:`check_containment` — children inside their parent (scroll viewports exempt) |
| I3  | :func:`check_window_size` (viewports), :func:`check_window_fits` (launch) |
| I4  | :func:`check_page_hscroll` — no horizontal scroll outside tables |
| I5  | :func:`check_text` — no clipped text unless elided with a tooltip; group membership |
| I6  | :func:`check_plot_text` — plot text sizes, containment, overlaps, statistics off data |
| I7  | :func:`observe_arrangement` + :func:`check_arrangement`, :func:`check_widget_count` |
| I7b | :func:`check_history_free`, :func:`check_no_flap` |
| I8  | the cell detectors, run once per interface size (:func:`scale_policy`) |
| I8b | :func:`check_ladder` |
| I9  | :func:`check_exports_identical` |
| I10 | :func:`check_screen_change` |

Expectations that need code a later milestone adds go through
:func:`scale_policy`, which raises :class:`Pending` until that code exists;
tests mark them ``xfail(strict=True, raises=Pending)``.
"""

import importlib
import math
import re
from dataclasses import dataclass
from itertools import combinations

from matplotlib.backends.backend_qt import FigureCanvasQT
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.path import Path
from matplotlib.text import Text
from matplotlib.transforms import Bbox, BboxTransformTo
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontMetricsF, QTextDocument, QTextLayout, QTextOption
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractScrollArea,
                               QAbstractSpinBox, QComboBox, QFocusFrame, QGroupBox, QHeaderView,
                               QLabel, QLayout, QListView, QPushButton, QRubberBand, QScrollBar,
                               QSizeGrip, QSizePolicy, QStackedLayout, QStyle, QStyleOptionButton,
                               QStyleOptionComboBox, QStyleOptionViewItem, QTableView, QWidget)

from src.ui.components.base_grouping_panel import BaseGroupingPanel
from src.ui.policy.layout import WidthClass, choose_arrangement, classify_window
from src.ui.policy.tokens import Dim
from src.ui.views.data_management.components.statistics_card import StatisticsCard
from src.ui.widgets.responsive_figure import ResponsiveFigureWidget

TOLERANCE_PX = 1

# I6 bands (plan §3.2 / §4.6): every plot text ≥ the tick floor, statistic
# annotations ≥ 11 px on screen, nothing above 24 px; floor and cap scale with
# the interface size.
PLOT_TICK_MIN_PX = 9.0
PLOT_STATISTIC_MIN_PX = 11.0
PLOT_TEXT_MAX_PX = 24.0

# In-axes texts that carry a statistic: AUC/CI blocks, p/q values, n counts,
# thresholds in µV and significance marks.
_STATISTIC = re.compile(r"\bAUC\b|\bCI|\b[pq]\s*(?:[=<>≤≥]|\d)|\bn\s*=|µV|^\*{1,3}$|^n\.s\.$")

# A group list must show this many members in full rows (D11).
GROUP_LIST_FULL_ROWS = 3

_IGNORED_TYPES = (QScrollBar, QSizeGrip, QFocusFrame, QRubberBand)


@dataclass(frozen=True)
class Violation:
    invariant: str
    path: str
    detail: str


class Pending(Exception):
    """An expectation that needs production code a later milestone adds."""


def _require(module: str, milestone: str):
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name is None or not module.startswith(exc.name):
            raise
        raise Pending(f"{milestone}: {module} does not exist yet") from None


def scale_policy():
    """``src.ui.policy.scale`` (ZOOM_LADDER, ``compose_scale_env``), added in M4.2."""
    return _require("src.ui.policy.scale", "M4.2")


# ---------------------------------------------------------------- widget tree

def widget_path(widget: QWidget) -> str:
    """``Type#name`` chain from the window down to ``widget``; anonymous plain
    containers among its ancestors are skipped."""
    parts = []
    w = widget
    while w is not None:
        name = w.objectName()
        kind = type(w).__name__
        if w is widget or name or kind not in ("QWidget", "QFrame"):
            parts.append(f"{kind}#{name}" if name else kind)
        w = w.parentWidget()
    return " > ".join(reversed(parts))


def _is_internal(widget: QWidget) -> bool:
    """Qt's own sub-widgets: scroll viewports and bars, combo and spinbox editors."""
    return (widget.objectName().startswith("qt_") or isinstance(widget, _IGNORED_TYPES)
            or isinstance(widget.parentWidget(), (QComboBox, QAbstractSpinBox)))


def _considered(widget: QWidget) -> bool:
    return widget.isVisible() and not widget.isWindow() and not _is_internal(widget)


def considered_widgets(root: QWidget) -> list:
    """Visible, non-internal descendants of ``root`` (hidden stack pages drop out)."""
    return [w for w in root.findChildren(QWidget) if _considered(w)]


def _is_scroll_viewport(widget: QWidget) -> bool:
    area = widget.parentWidget()
    return isinstance(area, QAbstractScrollArea) and area.viewport() is widget


def _size(size: QSize) -> str:
    return f"{size.width()}×{size.height()}"


def smart_minimum(widget: QWidget) -> QSize:
    """The minimum a layout gives ``widget`` (Qt's ``qSmartMinSize``), hidden or not."""
    hint, min_hint = widget.sizeHint(), widget.minimumSizeHint()
    policy, explicit = widget.sizePolicy(), widget.minimumSize()

    def axis(pol, h, mh, ex):
        if ex > 0:
            return ex
        if pol == QSizePolicy.Policy.Ignored:
            return 0
        shrinks = pol.value & QSizePolicy.PolicyFlag.ShrinkFlag.value
        return max(mh if shrinks else max(h, mh), 0)

    size = QSize(
        axis(policy.horizontalPolicy(), hint.width(), min_hint.width(), explicit.width()),
        axis(policy.verticalPolicy(), hint.height(), min_hint.height(), explicit.height()))
    return size.boundedTo(widget.maximumSize()).expandedTo(explicit)


def minimum_chain(widget: QWidget, vertical: bool, depth: int = 8) -> str:
    """Where a minimum comes from: follow the child with the largest minimum on the
    axis, through hidden stack pages too (a stack's minimum is the max over pages)."""
    links = []
    w = widget
    while w is not None and len(links) < depth:
        name = f"#{w.objectName()}" if w.objectName() else ""
        links.append(f"{type(w).__name__}{name} {_size(smart_minimum(w))}")
        children = _layout_widgets(w.layout()) if w.layout() is not None else []
        if not children:
            break
        w = max(children, key=lambda c: (smart_minimum(c).height() if vertical
                                         else smart_minimum(c).width()))
    return " → ".join(links)


def _layout_widgets(layout: QLayout) -> list:
    """Widgets a layout places, through nested layouts; hidden ones only for stacks."""
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is not None:
            if isinstance(layout, QStackedLayout) or not item.widget().isHidden():
                out.append(item.widget())
        elif item.layout() is not None:
            out.extend(_layout_widgets(item.layout()))
    return out


# ------------------------------------------------------------------------- I1

def _below(size: QSize, need: QSize) -> bool:
    return (size.width() < need.width() - TOLERANCE_PX
            or size.height() < need.height() - TOLERANCE_PX)


def check_crushed(root: QWidget) -> list:
    """I1: no visible widget is smaller than its layout minimum — neither the one
    its parent's layout gives it, nor the one its own layout needs. (Qt never
    shrinks a widget below an explicit minimum; it overlaps the siblings and lets
    the last one overflow, so only the parent's own layout shows the deficit.)"""
    out = []
    for w in [root] + considered_widgets(root):
        layout = w.layout()
        if layout is not None and _below(w.size(), layout.totalMinimumSize()):
            out.append(Violation("I1", widget_path(w),
                                 f"{_size(w.size())} < its layout's minimum "
                                 f"{_size(layout.totalMinimumSize())}"))
    for layout in root.findChildren(QLayout):
        owner = layout.parentWidget()
        if owner is None or not owner.isVisible() or (owner is not root
                                                      and not _considered(owner)):
            continue
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget()
            if w is not None and _considered(w) and _below(w.size(), item.minimumSize()):
                out.append(Violation("I1", widget_path(w),
                                     f"{_size(w.size())} < layout minimum "
                                     f"{_size(item.minimumSize())}"))
    return out


# ------------------------------------------------------------------------- I2

def check_containment(root: QWidget) -> list:
    """I2: children stay inside their parent unless the parent is a scroll viewport."""
    out = []
    for w in considered_widgets(root):
        parent = w.parentWidget()
        if parent is None or _is_scroll_viewport(parent):
            continue
        inside, g = parent.rect(), w.geometry()
        tol = TOLERANCE_PX
        if not inside.adjusted(-tol, -tol, tol, tol).contains(g):
            over = (max(0, -g.left()), max(0, -g.top()), max(0, g.right() - inside.right()),
                    max(0, g.bottom() - inside.bottom()))
            out.append(Violation("I2", widget_path(w),
                                 f"outside its {_size(parent.size())} parent by "
                                 f"left/top/right/bottom {over}"))
    return out


# ------------------------------------------------------------------------- I3

def check_window_size(window: QWidget, requested: tuple) -> list:
    """I3 at a viewport: the window attains the requested client size; reports which
    widgets set the minimum on each axis that was forced larger."""
    width, height = requested
    forced = [(axis, vertical) for axis, vertical, got, want in
              (("width", False, window.width(), width),
               ("height", True, window.height(), height))
              if got > want]
    if not forced:
        return []
    chains = "; ".join(f"{axis}: {minimum_chain(window, vertical)}" for axis, vertical in forced)
    return [Violation("I3", widget_path(window), f"asked for {width}×{height}, forced to "
                                                 f"{_size(window.size())} ({chains})")]


def check_window_fits(window: QWidget, available: QRect, title_bar: int,
                      floor: tuple) -> list:
    """I3 at launch: the window's minimum is ≤ the floor clamped to the screen, and the
    window (with its title bar) lies inside the available area. Lists the controls
    that end up off-screen."""
    out = []
    minimum = window.minimumSize()
    floor_size = QSize(*floor).boundedTo(QSize(available.width(), available.height() - title_bar))
    if minimum.width() > floor_size.width() or minimum.height() > floor_size.height():
        out.append(Violation("I3", widget_path(window),
                             f"minimum {_size(minimum)} above the floor {_size(floor_size)}"))
    frame = window.geometry().adjusted(0, -title_bar, 0, 0)
    if not available.contains(frame):
        off = [text_of(w) or type(w).__name__ for w in considered_widgets(window)
               if isinstance(w, (QAbstractButton, QComboBox, QAbstractSpinBox))
               and not available.contains(QRect(w.mapToGlobal(w.rect().topLeft()), w.size()))]
        out.append(Violation("I3", widget_path(window),
                             f"window {_size(frame.size())} incl. {title_bar}-px title bar "
                             f"exceeds the {_size(available.size())} available area; off-screen: "
                             f"{', '.join(off) or 'nothing interactive'}"))
    return out


# ------------------------------------------------------------------------- I4

def check_page_hscroll(root: QWidget) -> list:
    """I4: nothing scrolls horizontally except tables (which scroll inside themselves)."""
    return [Violation("I4", widget_path(area),
                      f"horizontal scroll range {area.horizontalScrollBar().maximum()} px")
            for area in considered_widgets(root)
            if isinstance(area, QAbstractScrollArea) and not isinstance(area, QTableView)
            and area.horizontalScrollBar().maximum() > 0]


# ------------------------------------------------------------------------- I5

def _plain(text: str) -> str:
    if Qt.mightBeRichText(text):
        doc = QTextDocument()
        doc.setHtml(text)
        return doc.toPlainText()
    return text


def _has_tooltip_for(tooltip, text: str) -> bool:
    return bool(tooltip) and text.strip() in _plain(str(tooltip))


def text_of(widget: QWidget) -> str:
    """The text a label, button or combo shows ("" for other widgets)."""
    if isinstance(widget, (QLabel, QAbstractButton)):
        return widget.text()
    if isinstance(widget, QComboBox):
        return widget.currentText()
    return ""


def _strip_mnemonic(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def _label_issue(label: QLabel):
    if not label.text().strip() or not label.pixmap().isNull():
        return None
    rect = label.contentsRect()
    if label.wordWrap():
        need = label.heightForWidth(label.width())
        if need > label.height() + TOLERANCE_PX:
            return f"wrapped text needs {need} px of height, has {label.height()}"
        return None
    text = label.text()
    metrics = QFontMetricsF(label.font())
    rich = (label.textFormat() == Qt.TextFormat.RichText
            or (label.textFormat() == Qt.TextFormat.AutoText and Qt.mightBeRichText(text)))
    if rich:
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(label.font())
        doc.setHtml(text)
        need_w, need_h = doc.idealWidth(), doc.size().height()
    else:
        lines = text.split("\n")
        need_w = max(metrics.horizontalAdvance(line) for line in lines)
        need_h = metrics.height() + (len(lines) - 1) * metrics.lineSpacing()
    have_w = rect.width() - 2 * label.margin() - max(0, label.indent())
    if need_w > have_w + TOLERANCE_PX:
        return f"text needs {need_w:.0f} px, has {have_w}"
    if need_h > rect.height() + TOLERANCE_PX:
        return f"text needs {need_h:.0f} px of height, has {rect.height()}"
    return None


def _button_issue(button: QAbstractButton):
    text = _strip_mnemonic(button.text())
    if not isinstance(button, QPushButton):
        if text and button.sizeHint().width() > button.width() + TOLERANCE_PX:
            return f"needs {button.sizeHint().width()} px, has {button.width()}"
        return None
    option = QStyleOptionButton()
    button.initStyleOption(option)
    contents = button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents,
                                             option, button)
    icon = button.iconSize() if not button.icon().isNull() else QSize(0, 0)
    if not text:
        if _below(contents.size(), icon):
            return f"{_size(icon)} icon in a {_size(contents.size())} button"
        return None
    need = QFontMetricsF(button.font()).horizontalAdvance(text)
    need += icon.width() + 4 if icon.width() else 0
    if need > contents.width() + TOLERANCE_PX:
        return f"label needs {need:.0f} px, has {contents.width()}"
    return None


def _line_edit_text_width(editor) -> int:
    """The width a QLineEdit draws (or elides) text in: its contents minus the text
    margins and its 2-px side margins."""
    margins = editor.textMargins()
    return editor.contentsRect().width() - margins.left() - margins.right() - 4


def _combo_issue(combo: QComboBox):
    editor = combo.lineEdit()
    text = combo.currentText() or (editor.placeholderText() if editor is not None
                                   else combo.placeholderText())
    if not text:
        return None
    if editor is not None:  # an editable combo draws its text inside its line edit
        have = _line_edit_text_width(editor)
    else:
        option = QStyleOptionComboBox()
        combo.initStyleOption(option)
        have = combo.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                            QStyle.SubControl.SC_ComboBoxEditField, combo).width()
    need = QFontMetricsF(combo.font()).horizontalAdvance(text)
    if need > have + TOLERANCE_PX and not _has_tooltip_for(combo.toolTip(), text):
        return f"'{text}' needs {need:.0f} px, has {have} (no tooltip)"
    return None


def _spinbox_issue(spinbox: QAbstractSpinBox):
    editor = spinbox.lineEdit()
    if editor is None or not spinbox.text():
        return None
    need = QFontMetricsF(spinbox.font()).horizontalAdvance(spinbox.text())
    have = _line_edit_text_width(editor)
    if need > have + TOLERANCE_PX:
        return f"'{spinbox.text()}' needs {need:.0f} px, has {have}"
    return None


def _header_issues(header: QHeaderView):
    model = header.model()
    for i in range(header.count()):
        if header.isSectionHidden(i) or header.sectionSize(i) == 0:
            continue
        text = str(model.headerData(i, header.orientation()) or "")
        need, have = header.sectionSizeFromContents(i).width(), header.sectionSize(i)
        tooltip = model.headerData(i, header.orientation(), Qt.ItemDataRole.ToolTipRole)
        if text and need > have + TOLERANCE_PX and not _has_tooltip_for(tooltip, text):
            yield f"header '{text}' needs {need} px, has {have} (no tooltip)"


def list_item_issue(view: QListView, text: str, rect: QRect):
    """Why a list item's ``text`` does not fit its ``rect`` (None when it does), laid
    out as the style draws it: in the item's text rect less the focus-frame margins,
    wrapped at word boundaries when the list wraps. QCommonStyle marks a line for
    eliding when its natural width exceeds that, however little, and the elider then
    keeps it whole if its advance fits ("Drinking/": the "/" overhangs its advance).

    Measured rather than read from the item's size hint, which need not say: the
    grouping lists' zero-wide hints hid the names they middle-elided."""
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.font = view.font()
    option.rect = rect
    option.text = text
    option.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
    option.showDecorationSelected = True  # the text rect is then the item less its padding
    style = view.style()
    box = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
    width = box.width() - 2 * (style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin,
                                                 None, view) + 1)
    wrap = QTextOption()
    wrap.setWrapMode(QTextOption.WrapMode.WordWrap if view.wordWrap()
                     else QTextOption.WrapMode.ManualWrap)
    layout = QTextLayout(text, view.font())
    layout.setTextOption(wrap)
    advance = QFontMetricsF(view.font()).horizontalAdvance
    layout.beginLayout()
    elided, height = None, 0.0
    while (line := layout.createLine()).isValid():
        line.setLineWidth(width)
        segment = text[line.textStart():line.textStart() + line.textLength()]
        if elided is None and line.naturalTextWidth() > width and advance(segment) > width:
            elided = line.naturalTextWidth()
        height += line.height()
    layout.endLayout()
    if elided is not None:
        return f"item '{text}' needs {elided:.0f} px, has {width}"
    if height > box.height() + TOLERANCE_PX:
        return f"item '{text}' needs {height:.0f} px of height, has {box.height()}"
    return None


def _item_issues(view: QAbstractItemView):
    """Cells whose text the view elides without a tooltip carrying the full text."""
    model = view.model()
    if model is None:
        return
    table = isinstance(view, QTableView)
    columns = range(model.columnCount()) if table else [view.modelColumn()]
    for row in range(model.rowCount()):
        if table and view.isRowHidden(row):
            continue
        for column in columns:
            if table and view.isColumnHidden(column):
                continue
            index = model.index(row, column)
            text = index.data(Qt.ItemDataRole.DisplayRole)
            if (not isinstance(text, str) or not text.strip()
                    or view.indexWidget(index) is not None):
                continue
            rect = view.visualRect(index)
            if rect.width() <= 0:
                continue
            if isinstance(view, QListView):
                issue = list_item_issue(view, text, rect)
            else:
                need = view.sizeHintForIndex(index).width()
                issue = (f"item '{text}' needs {need} px, has {rect.width()}"
                         if need > rect.width() + TOLERANCE_PX else None)
            if issue and not _has_tooltip_for(index.data(Qt.ItemDataRole.ToolTipRole), text):
                yield f"{issue} (no tooltip)"


def check_group_membership(header: QLabel, members: QListView) -> list:
    """I5 for one group: the header's tooltip names every member (a path that needs no
    hovering over truncated items), and the list shows its first rows in full."""
    out = []
    model = members.model()
    names = [str(model.index(i, 0).data()).rsplit(" (n=", 1)[0] for i in range(model.rowCount())]
    if not names:
        return out
    missing = [n for n in names if not _has_tooltip_for(header.toolTip(), n)]
    if missing:
        out.append(Violation("I5", widget_path(header),
                             f"group header tooltip does not list {', '.join(missing)}"))
    viewport = members.viewport().rect()
    full = sum(1 for i in range(model.rowCount())
               if viewport.contains(members.visualRect(model.index(i, 0))))
    want = min(len(names), GROUP_LIST_FULL_ROWS)
    if full < want:
        row = max(1, members.sizeHintForRow(0))
        out.append(Violation("I5", widget_path(members),
                             f"shows {viewport.height() / row:.1f} rows, needs {want} full rows"))
    return out


def check_text(root: QWidget) -> list:
    """I5: no clipped label/button/combo/spinbox/header/item text, except elision that
    keeps the full text in a tooltip; grouping panels keep members reachable."""
    out = []
    for w in considered_widgets(root):
        issues = []
        if isinstance(w, QLabel):
            issues = [_label_issue(w)]
        elif isinstance(w, QAbstractButton):
            issues = [_button_issue(w)]
        elif isinstance(w, QComboBox):
            issues = [_combo_issue(w)]
        elif isinstance(w, QAbstractSpinBox):
            issues = [_spinbox_issue(w)]
        elif isinstance(w, QHeaderView):
            if w.orientation() == Qt.Orientation.Horizontal:
                issues = list(_header_issues(w))
        elif isinstance(w, QAbstractItemView):
            issues = list(_item_issues(w))
        elif isinstance(w, BaseGroupingPanel):
            out.extend(check_group_membership(w.group1_label, w.group1_list))
            out.extend(check_group_membership(w.group2_label, w.group2_list))
        out.extend(Violation("I5", widget_path(w), issue) for issue in issues if issue)
    return out


# ------------------------------------------------------------------------- I6

def _annotation_role(text: Text) -> str:
    return "statistic" if _STATISTIC.search(text.get_text()) else "annotation"


def _drawn_texts(figure):
    """(text, role) for every text the figure draws; role is "tick", "statistic",
    "annotation" or "label". Tick labels outside the view interval are not drawn."""
    for ax in figure.axes:
        if not ax.get_visible():
            continue
        for axis in (ax.xaxis, ax.yaxis):
            if not axis.get_visible():
                continue
            lo, hi = sorted(axis.get_view_interval())
            eps = (hi - lo) * 1e-9
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if lo - eps <= tick.get_loc() <= hi + eps:
                    yield tick.label1, "tick"
                    yield tick.label2, "tick"
            yield axis.label, "label"
            yield axis.get_offset_text(), "label"
        legend = ax.get_legend()
        if legend is not None and legend.get_visible():
            yield from ((t, "label") for t in [legend.get_title(), *legend.get_texts()])
        # The axes' own Text children: its titles and its annotations (ax.texts).
        for child in ax.get_children():
            if isinstance(child, Text):
                yield child, _annotation_role(child) if child in ax.texts else "label"
    for text in figure.texts:
        yield text, _annotation_role(text)


def _is_drawn(text: Text) -> bool:
    alpha = text.get_alpha()
    return text.get_visible() and bool(text.get_text().strip()) and (alpha is None or alpha > 0)


def _data_marks(ax, dpi: float):
    """(display path, filled) for the axes' data artists: lines, collections and
    patches positioned in data coordinates. Reference lines in blended or axes
    coordinates (axhline, cluster bars) are not data. Markers become small squares."""
    data = ax.transData
    for line in ax.lines:
        if not line.get_visible() or not line.get_transform().contains_branch(data):
            continue
        path = line.get_transform().transform_path(line.get_path())
        if line.get_linestyle() not in ("None", "", " ") and len(path.vertices) > 1:
            yield path, False
        if line.get_marker() not in (None, "None", "", " "):
            yield from _marker_boxes(path.vertices, line.get_markersize() * dpi / 72 / 2)
    for collection in ax.collections:
        if not collection.get_visible():
            continue
        if collection.get_transform().contains_branch(data):
            filled = not isinstance(collection, LineCollection)
            for p in collection.get_paths():
                yield collection.get_transform().transform_path(p), filled
        elif (isinstance(collection, PathCollection)
              and collection.get_offset_transform().contains_branch(data)):
            offsets = collection.get_offset_transform().transform(collection.get_offsets())
            sizes = collection.get_sizes()
            yield from _marker_boxes(offsets, math.sqrt(max(sizes, default=36.0)) * dpi / 72 / 2)
    for patch in ax.patches:
        if patch.get_visible() and patch.get_transform().contains_branch(data):
            yield patch.get_transform().transform_path(patch.get_path()), patch.get_fill()


def _marker_boxes(points, radius):
    for x, y in points:
        box = Bbox.from_extents(x - radius, y - radius, x + radius, y + radius)
        yield Path.unit_rectangle().transformed(BboxTransformTo(box)), True


def plot_canvases(root: QWidget) -> list:
    """(plot widget, its matplotlib canvas) for every visible analysis plot."""
    return [(plot, plot.findChild(FigureCanvasQT))
            for plot in root.findChildren(ResponsiveFigureWidget) if plot.isVisible()]


def check_plots(root: QWidget, ui_scale: float = 1.0) -> list:
    """I6 for every visible analysis plot under ``root``."""
    return [v for plot, canvas in plot_canvases(root)
            for v in check_plot_text(canvas.figure, canvas.device_pixel_ratio,
                                     widget_path(plot), ui_scale)]


def check_plot_text(figure, dpr: float, name: str, ui_scale: float = 1.0) -> list:
    """I6 for one drawn figure: text sizes in band, inside the figure, not
    overlapping each other, and statistic text never over a data mark."""
    out = []
    renderer = figure.canvas.get_renderer()
    bounds = figure.bbox
    px_per_pt = figure.dpi / dpr / 72
    tol = TOLERANCE_PX * dpr
    floor = PLOT_TICK_MIN_PX * min(1.0, ui_scale)
    cap = PLOT_TEXT_MAX_PX * ui_scale
    small, small_stats, large, outside, extents = [], [], [], [], []
    for text, role in _drawn_texts(figure):
        if not _is_drawn(text):
            continue
        px = text.get_fontsize() * px_per_pt
        label = text.get_text().replace("\n", " ")[:32]
        if role == "statistic" and px < PLOT_STATISTIC_MIN_PX - 0.05:
            small_stats.append((px, label))
        elif role != "statistic" and px < floor - 0.05:
            small.append((px, label))
        if px > cap + 0.05:
            large.append((px, label))
        box = text.get_window_extent(renderer)
        extents.append((text, role, label, box))
        if (box.x0 < bounds.x0 - tol or box.y0 < bounds.y0 - tol
                or box.x1 > bounds.x1 + tol or box.y1 > bounds.y1 + tol):
            outside.append(label)
    for found, worst, what in (
            (small, min, f"texts below the {floor:g}-px tick floor"),
            (small_stats, min, f"statistic texts below {PLOT_STATISTIC_MIN_PX:g} px"),
            (large, max, f"texts above the {cap:g}-px cap")):
        if found:
            px, example = worst(found)
            out.append(Violation("I6", name,
                                 f"{len(found)} {what} (e.g. '{example}' at {px:.1f} px)"))
    if outside:
        out.append(Violation("I6", name, f"{len(outside)} texts outside the figure "
                                         f"(e.g. '{outside[0]}')"))
    for (_, _, label_a, a), (_, _, label_b, b) in combinations(extents, 2):
        if min(a.x1, b.x1) - max(a.x0, b.x0) > tol and min(a.y1, b.y1) - max(a.y0, b.y0) > tol:
            out.append(Violation("I6", name, f"'{label_a}' overlaps '{label_b}'"))
    for text, role, label, box in extents:
        if role != "statistic" or text.axes is None:
            continue
        # Data is clipped to the axes, so only the part of the text inside them can cover it.
        inner = Bbox.intersection(
            Bbox.from_extents(box.x0 + tol, box.y0 + tol, box.x1 - tol, box.y1 - tol),
            text.axes.bbox)
        if inner is not None and inner.width > 0 and inner.height > 0 and any(
                path.intersects_bbox(inner, filled=filled)
                for path, filled in _data_marks(text.axes, figure.dpi)):
            out.append(Violation("I6", name, f"statistic '{label}' drawn over data"))
    return out


# ------------------------------------------------------------------------- I7

def section_arrangement(rects: list) -> str:
    """"ROW" when the grouping panel's sections sit side by side, "STACKED" when the
    first three share a row above a full-width table, else "OTHER"."""
    tops = [r.top() for r in rects]
    if all(abs(t - tops[0]) <= TOLERANCE_PX for t in tops) and all(
            a.left() < b.left() for a, b in zip(rects, rects[1:])):
        return "ROW"
    *setup, table = rects
    span = max(r.right() for r in rects) - min(r.left() for r in rects)
    if (all(abs(r.top() - setup[0].top()) <= TOLERANCE_PX for r in setup)
            and table.top() > max(r.bottom() for r in setup)
            and table.width() >= 0.9 * span):
        return "STACKED"
    return "OTHER"


def observe_arrangement(window, page: QWidget) -> dict:
    """The geometry facts the layout classes decide: grouping-panel arrangement
    and table share, data-page card columns, sidebar width."""
    facts = {"sidebar_width": window.sidebar.width()}
    panel = getattr(page, "grouping_panel", None)
    if panel is not None and panel.isVisible():
        sections = [g.geometry() for g in panel.findChildren(
            QGroupBox, options=Qt.FindChildOption.FindDirectChildrenOnly)]
        if len(sections) == 4:
            facts["panel"] = section_arrangement(sections)
            total = max(1, sum(s.width() for s in sections))
            facts["table_share"] = round(sections[3].width() / total, 3)
    cards = [c for c in page.findChildren(StatisticsCard) if c.isVisible()]
    if cards:
        top = min(c.geometry().top() for c in cards)
        facts["card_columns"] = sum(abs(c.geometry().top() - top) <= TOLERANCE_PX for c in cards)
    return facts


def policy_arrangement(window: tuple, row_min_width: int) -> str:
    """The panel arrangement src.ui.policy.layout gives a window of client size
    ``window`` without history: its content stack sits beside the sidebar its
    width class calls for (the icon rail when NARROW) and below the top bar."""
    width, height = window
    narrow = classify_window(width) is WidthClass.NARROW
    sidebar = Dim.SIDEBAR_RAIL_W if narrow else Dim.SIDEBAR_W
    return choose_arrangement(width - sidebar, height - Dim.TOPBAR_H, row_min_width).name


def check_arrangement(observed: dict, expected: dict, where: str) -> list:
    """I7: the observed arrangement facts equal what the classes call for."""
    return [Violation("I7", where, f"{key}: {observed.get(key)!r}, class wants {want!r}")
            for key, want in expected.items() if observed.get(key) != want]


def check_widget_count(counts: dict, where: str) -> list:
    """I7 (no widget re-creation): one state's widget count is the same in every cell."""
    if len(set(counts.values())) <= 1:
        return []
    cell, count = next(iter(counts.items()))
    return [Violation("I7", where, f"widget count changes across cells: "
                                   f"{sorted(set(counts.values()))} (e.g. {cell}: {count})")]


# ------------------------------------------------------------------------ I7b

def check_history_free(observations: dict, where: str) -> list:
    """I7b over ``{common size: [facts, ...]}``: the class facts seen around a common
    size (±8 px), arriving from any earlier size, are all the same."""
    return [Violation("I7b", where, f"at {size}: facts depend on history: {facts}")
            for size, facts in observations.items()
            if any(f != facts[0] for f in facts[1:])]


def check_no_flap(sequence: list, where: str) -> list:
    """I7b over ``[(size, facts), ...]`` along a ±1-px drag around a boundary: the
    facts change at most once."""
    changes = [(a[0], b[0]) for a, b in zip(sequence, sequence[1:]) if a[1] != b[1]]
    if len(changes) <= 1:
        return []
    return [Violation("I7b", where, f"facts flap {len(changes)}× (first between {changes[0]})")]


# ------------------------------------------------------------------------ I8b

def check_ladder(levels: list, where: str) -> list:
    """I8b over ``[(interface size, {path: (font px, control height px)})]`` in device
    px: stepping up never shrinks a font; a control's height steps down at most once."""
    out = []
    levels = sorted(levels, key=lambda level: level[0])
    for path in set().union(*(metrics for _, metrics in levels)):
        series = [(size, metrics[path]) for size, metrics in levels if path in metrics]
        steps = list(zip(series, series[1:]))
        shrunk = [(a[0], b[0]) for a, b in steps if b[1][0] < a[1][0]]
        if shrunk:
            out.append(Violation("I8b", f"{where}: {path}",
                                 f"font shrinks from {shrunk[0][0]:g} to {shrunk[0][1]:g}"))
        if sum(1 for a, b in steps if b[1][1] < a[1][1]) > 1:
            out.append(Violation("I8b", f"{where}: {path}",
                                 "control height steps down more than once"))
    return out


# ------------------------------------------------------------------------- I9

def check_exports_identical(digests: dict) -> list:
    """I9 over ``{(plot, format): {cell: md5}}``: one digest per plot and format."""
    return [Violation("I9", f"{plot}.{fmt}", f"{len(set(by_cell.values()))} different "
                                             f"exports across {len(by_cell)} cells")
            for (plot, fmt), by_cell in sorted(digests.items())
            if len(set(by_cell.values())) > 1]


# ------------------------------------------------------------------------ I10

def check_screen_change(window, screen, title_bar: int, floor: tuple,
                        changes: list) -> list:
    """I10 after moving the window to ``screen``: the move was noticed, the window and
    every plot canvas follow the screen's DPR, and the window keeps to the screen's
    floor and available area."""
    out = []
    path = widget_path(window)
    if not changes or changes[-1] != screen.name():
        out.append(Violation("I10", path, f"no screenChanged to {screen.name()} (saw {changes})"))
    dpr = screen.devicePixelRatio()
    if abs(window.devicePixelRatioF() - dpr) > 1e-6:
        out.append(Violation("I10", path,
                             f"window DPR {window.devicePixelRatioF():g}, screen {dpr:g}"))
    for plot, canvas in plot_canvases(window):
        if abs(canvas.device_pixel_ratio - dpr) > 1e-6:
            out.append(Violation("I10", widget_path(plot),
                                 f"plot canvas DPR {canvas.device_pixel_ratio:g}, screen {dpr:g}"))
    out.extend(Violation("I10", v.path, v.detail)
               for v in check_window_fits(window, screen.availableGeometry(), title_bar, floor))
    return out
