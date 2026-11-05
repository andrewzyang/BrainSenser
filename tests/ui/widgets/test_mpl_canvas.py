"""The shared matplotlib canvas (``src/ui/widgets/mpl_canvas.py``; plan M1.2).

It binds PySide6 even when imported first (PyQt5 is installed here too), keeps
one set of screen-signal connections however often its page is shown, hints
its minimum height so a large figure cannot hold a page at its size, and hands
wheel events to the enclosing scroll area so the page scrolls under a plot.
"""

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import SIGNAL, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QScrollArea,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.views.timeline_peri_event.components import matplotlib_canvas
from src.ui.views.timeline_peri_event.components.peri_event_plot import PeriEventPlot
from src.ui.widgets.mpl_canvas import MatplotlibCanvas, MatplotlibWidget

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_old_import_path_reexports_the_canvas():
    assert matplotlib_canvas.MatplotlibCanvas is MatplotlibCanvas
    assert matplotlib_canvas.MatplotlibWidget is MatplotlibWidget


def test_canvas_binds_pyside6_when_imported_first():
    probe = ("import sys\n"
             "import src.ui.widgets.mpl_canvas\n"
             "from matplotlib.backends.qt_compat import QT_API\n"
             "print(QT_API, 'PyQt5' in sys.modules)\n")
    env = {key: value for key, value in os.environ.items() if key != "QT_API"}
    env.update(QT_QPA_PLATFORM="offscreen", PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", probe], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, check=True, timeout=120)
    assert out.stdout.split() == ["PySide6", "False"]


def test_container_holds_only_the_canvas(qtbot):
    widget = MatplotlibWidget()
    qtbot.addWidget(widget)
    assert widget.findChildren(QWidget) == [widget.canvas]
    assert not widget.findChildren(QToolBar)


def test_screen_listeners_stay_flat_over_25_page_switches(qtbot):
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())
    stack.addWidget(MatplotlibWidget())
    stack.resize(400, 300)
    stack.show()
    qtbot.waitExposed(stack)
    window, screen = stack.windowHandle(), stack.windowHandle().screen()

    def listeners():
        return (window.receivers(SIGNAL("screenChanged(QScreen*)")),
                screen.receivers(SIGNAL("logicalDotsPerInchChanged(qreal)")),
                screen.receivers(SIGNAL("physicalDotsPerInchChanged(qreal)")))

    initial = listeners()  # the canvas has not been shown yet
    for _ in range(25):
        stack.setCurrentIndex(1)
        stack.setCurrentIndex(0)
    assert all(after <= before + 1 for before, after in zip(initial, listeners())), (
        initial, listeners())


def test_size_hint_height_is_the_minimum_whatever_the_figure_size(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    plot = PeriEventPlot()
    layout.addWidget(plot)
    host.resize(2400, 900)
    host.show()
    qtbot.waitUntil(plot.is_layout_settled)
    canvas = plot.findChild(MatplotlibCanvas)
    assert canvas.figure.get_size_inches()[1] * 100 > 800  # the live figure is large
    assert canvas.sizeHint().height() == canvas.minimumHeight()
    # What the page's layout sees: the plot's own minimum, never the live size.
    assert layout.itemAt(0).sizeHint().height() == plot.minimumHeight()


def test_wheel_over_the_canvas_scrolls_the_page(qtbot):
    area = QScrollArea()
    qtbot.addWidget(area)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    page = QWidget()
    page.setMinimumHeight(1500)
    layout = QVBoxLayout(page)
    plot = MatplotlibWidget()
    plot.setMinimumHeight(300)
    layout.addWidget(plot)
    layout.addStretch(1)
    area.setWidget(page)
    area.resize(600, 400)
    area.show()
    qtbot.waitExposed(area)
    canvas = plot.canvas
    scrolled = []
    canvas.mpl_connect("scroll_event", scrolled.append)
    position = QPointF(100, 100)
    event = QWheelEvent(position, canvas.mapToGlobal(position), QPoint(0, 0), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(canvas, event)
    assert area.verticalScrollBar().value() > 0
    assert len(scrolled) == 1  # matplotlib still sees the wheel

