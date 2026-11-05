"""PageHost: the vertical scroll fallback around every page (plan §4.5, M1.2).

Synthetic pages only. The stack no longer takes the largest page minimum, a page
scrolls vertically below its minimum and never sideways, the holder keeps one
word-wrapped label from locking a live-sized plot (review 11 B1), and the
wheel guard keeps a scrolling wheel from changing combos and spinboxes.
"""

import pytest
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFrame, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from src.ui.components import Sidebar, TopBar
from src.ui.layouts import MainLayout, PageHost

WRAPPED_TEXT = ("Results are stale: the effect size changed after this analysis ran. "
                "Click Compare Groups to refresh the statistics.")


def _settle(qapp, rounds: int = 5) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def _page(min_size=(840, 618)) -> QWidget:
    """A page whose layout needs ``min_size`` (like the real pages: no explicit
    minimum on the page itself, which Qt would never squeeze)."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    content = QLabel("page")
    content.setMinimumSize(*min_size)
    layout.addWidget(content)
    return page


class _LiveSizedPlot(QWidget):
    """Like a matplotlib canvas: its size hint is the size it was last given."""

    def sizeHint(self) -> QSize:
        return self.size().expandedTo(self.minimumSize())


def _plot_page() -> tuple:
    """A PSD-like page: a word-wrapped banner, a live-sized plot and a panel."""
    page = QWidget()
    layout = QVBoxLayout(page)
    banner = QLabel(WRAPPED_TEXT)
    banner.setWordWrap(True)
    plot = _LiveSizedPlot()
    plot.setMinimumHeight(260)
    panel = QFrame()
    panel.setMinimumHeight(220)
    layout.addWidget(banner)
    layout.addWidget(plot, 7)
    layout.addWidget(panel, 3)
    return page, plot


def _shown_host(qtbot, qapp, page, size, **kwargs) -> PageHost:
    host = PageHost(page, **kwargs)
    qtbot.addWidget(host)
    host.resize(*size)
    host.show()
    _settle(qapp)
    return host


def test_host_is_a_transparent_frameless_vertical_scroller(qtbot):
    host = PageHost(_page())
    qtbot.addWidget(host)
    assert host.objectName() == "page_host"
    assert host.widgetResizable()
    assert host.frameShape() == QFrame.Shape.NoFrame
    assert host.alignment() == Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
    assert host.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert host.focusPolicy() == Qt.FocusPolicy.NoFocus  # no extra Tab stop
    assert not host.viewport().autoFillBackground()
    assert not host.widget().autoFillBackground()


def test_add_page_wraps_the_page_and_get_page_returns_it(qtbot):
    layout = MainLayout(Sidebar(), TopBar())
    qtbot.addWidget(layout)
    wrapped, direct = _page(), _page()
    layout.add_page("wrapped", wrapped)
    layout.add_page("direct", direct, scroll_fallback=False)
    assert layout.get_page("wrapped") is wrapped
    assert isinstance(layout.content_stack.widget(0), PageHost)
    assert layout.content_stack.widget(1) is direct

    with qtbot.waitSignal(layout.page_changed) as changed:
        layout.switch_page("wrapped")
    assert changed.args == ["wrapped"]
    assert layout.current_page == "wrapped"
    assert layout.content_stack.currentWidget().widget().isAncestorOf(wrapped)


def test_stack_minimum_no_longer_takes_the_largest_page_minimum(qtbot):
    layout = MainLayout(Sidebar(), TopBar())
    qtbot.addWidget(layout)
    layout.add_page("data_management", _page((840, 618)))
    layout.add_page("analysis", _page((520, 520)))
    minimum = layout.content_stack.minimumSizeHint()
    assert minimum.width() < 100 and minimum.height() < 100


@pytest.mark.parametrize("size", [(400, 300), (600, 449), (1080, 718), (1600, 1000)])
def test_page_scrolls_vertically_below_its_minimum_and_never_sideways(qtbot, qapp, size):
    page = _page((840, 618))
    host = _shown_host(qtbot, qapp, page, size)
    viewport = host.viewport().size()
    assert host.horizontalScrollBar().maximum() == 0
    assert page.width() == viewport.width()  # squeezed to the viewport, never cut off
    assert page.height() == max(viewport.height(), 618)
    assert host.verticalScrollBar().maximum() == page.height() - viewport.height()


def test_holder_reports_height_for_width_only_when_the_page_opts_in(qtbot):
    opted_out = PageHost(_plot_page()[0])
    opted_in = PageHost(_plot_page()[0], height_for_width=True)
    for host in (opted_out, opted_in):
        qtbot.addWidget(host)
    assert not opted_out.widget().layout().hasHeightForWidth()
    assert opted_in.widget().layout().hasHeightForWidth()


@pytest.mark.parametrize("height_for_width, locked", [(False, False), (True, True)])
def test_wrapped_label_does_not_lock_a_live_sized_plot(qtbot, qapp, height_for_width, locked):
    """B1: 1920×1200 → 1280×769. With height-for-width the page's height becomes
    the sum of the size hints, the plot's being its old height, so the page keeps
    scrolling; the holder hides it, and the plot shrinks into the viewport."""
    page, plot = _plot_page()
    host = _shown_host(qtbot, qapp, page, (1720, 1149), height_for_width=height_for_width)
    tall = plot.height()
    host.resize(1080, 718)
    _settle(qapp, 10)
    scrolled = host.verticalScrollBar().maximum()
    assert (scrolled > 0) == locked
    if not locked:
        assert page.height() == host.viewport().height()
        assert plot.height() < tall


# ---------------------------------------------------------------- wheel guard

def _controls_page() -> tuple:
    page = QWidget()
    layout = QVBoxLayout(page)
    combo = QComboBox()
    combo.addItems(["Bonferroni", "FDR (Benjamini-Hochberg)", "Holm", "None"])
    spin = QSpinBox()
    spin.setRange(1, 120)
    spin.setValue(20)
    double = QDoubleSpinBox()
    double.setValue(5.0)
    focus_elsewhere = QPushButton("elsewhere")
    for widget in (focus_elsewhere, combo, spin, double):
        layout.addWidget(widget)
    layout.addStretch(1)
    page.setMinimumHeight(1500)  # taller than the host, so the page can scroll
    return page, focus_elsewhere, [combo, spin, double]


def _value(control):
    return control.currentIndex() if isinstance(control, QComboBox) else control.value()


def _wheel(host, control, notches: int = -1) -> None:
    """A real (spontaneous) wheel event over ``control``, as the window system sends it."""
    position = QPointF(control.mapTo(host, control.rect().center()))
    QTest.wheelEvent(host.windowHandle(), position, QPoint(0, 120 * notches))


def test_wheel_over_an_unfocused_control_scrolls_the_page_instead(qtbot, qapp):
    page, elsewhere, controls = _controls_page()
    host = _shown_host(qtbot, qapp, page, (300, 400))
    bar = host.verticalScrollBar()
    for control in controls:
        elsewhere.setFocus()
        bar.setValue(0)
        before = _value(control)
        _wheel(host, control)
        _settle(qapp)
        assert _value(control) == before, type(control).__name__
        assert bar.value() > 0, f"the page did not scroll over {type(control).__name__}"


def test_a_focused_control_still_takes_the_wheel(qtbot, qapp):
    page, _elsewhere, controls = _controls_page()
    host = _shown_host(qtbot, qapp, page, (300, 400))
    spin = controls[1]
    spin.setFocus()
    _wheel(host, spin)  # one notch down
    _settle(qapp)
    assert spin.value() == 19


def test_the_wheel_no_longer_focuses_a_control(qtbot):
    page, _elsewhere, controls = _controls_page()
    combo, spin, double = controls
    combo.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # Qt's macOS default for combos
    host = PageHost(page)
    qtbot.addWidget(host)
    assert spin.focusPolicy() == double.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert combo.focusPolicy() == Qt.FocusPolicy.TabFocus  # already wheel-proof: kept


def test_controls_added_later_are_guarded(qtbot, qapp):
    page, elsewhere, _controls = _controls_page()
    host = _shown_host(qtbot, qapp, page, (300, 400))
    late = QSpinBox()
    late.setValue(7)
    page.layout().insertWidget(1, late)
    _settle(qapp)
    assert late.focusPolicy() == Qt.FocusPolicy.StrongFocus
    elsewhere.setFocus()
    _wheel(host, late)
    _settle(qapp)
    assert late.value() == 7


def test_controls_of_a_dialog_parented_inside_the_page_are_left_alone(qtbot, qapp):
    page, _elsewhere, _controls = _controls_page()
    dialog = QDialog(page)
    dialog_spin = QSpinBox(dialog)
    host = _shown_host(qtbot, qapp, page, (300, 400))
    assert dialog_spin in host.widget().findChildren(QSpinBox)  # a descendant, yet not in the page
    assert dialog_spin.focusPolicy() == Qt.FocusPolicy.WheelFocus
