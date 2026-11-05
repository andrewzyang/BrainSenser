"""PageHost and wheel guard on the real MainWindow (plan M1.2 / M1.3 acceptance).

Every page sits in a PageHost (only the Data page keeps height-for-width), the
stack no longer forces the largest page minimum on the window, which can shrink
to the 600×500 floor; every page then scrolls vertically and never sideways, a
word-wrapped banner does not lock the PSD plot at a large window's height, and
a wheel over any combo or spinbox scrolls the page without changing the value.
No patient data: the analysis pages show their (empty) content view.
"""

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

from src.ui.layouts import PageHost

PAGES = ("data_management", "timeline_lfp_threshold", "timeline_peri_event",
         "snapshots_canonical_bands", "snapshots_5hz_band")
ANALYSIS_PAGES = PAGES[1:]


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    """One MainWindow for the module, analysis pages on their content view."""
    import main
    import src.domain.effect_size_preference as effect_size_preference
    from src.ui.app_bootstrap import build_presentation

    # Module fixtures run before the per-test isolation in tests/conftest.py.
    ini_path = tmp_path_factory.mktemp("qsettings") / "iEEG-App.ini"

    def isolated_settings(*_args, **_kwargs):
        return QSettings(str(ini_path), QSettings.Format.IniFormat)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(effect_size_preference, "QSettings", isolated_settings)
        effect_size_preference.EffectSizePreference.reset_singleton()
        win = main.MainWindow(container=build_presentation().container)
        for name in ANALYSIS_PAGES:
            win.main_layout.get_page(name).content_stack.setCurrentIndex(1)
        win.resize(1280, 769)
        win.show()
        yield win
        win.close()
        win.deleteLater()
        qapp.processEvents()
    effect_size_preference.EffectSizePreference.reset_singleton()


def _settle(qapp, rounds: int = 10) -> None:
    for _ in range(rounds):
        qapp.processEvents()


def _show(window, qapp, page: str, size) -> PageHost:
    window.resize(*size)
    window.main_layout.switch_page(page)
    _settle(qapp)
    return window.main_layout.content_stack.currentWidget()


def test_every_page_sits_in_a_page_host(window):
    stack = window.main_layout.content_stack
    hosts = [stack.widget(i) for i in range(stack.count())]
    assert all(isinstance(host, PageHost) for host in hosts)
    for name in PAGES:
        host = next(h for h in hosts if h.widget().isAncestorOf(window.main_layout.get_page(name)))
        opted_in = host.widget().layout().hasHeightForWidth()
        assert opted_in == (name == "data_management" and
                            window.main_layout.get_page(name).hasHeightForWidth())


def test_window_floor_and_stack_minimum(window):
    assert window.minimumSize() == QSize(600, 500)
    minimum = window.main_layout.content_stack.minimumSizeHint()
    assert minimum.width() < 100 and minimum.height() < 100


@pytest.mark.parametrize("size", [(600, 500), (800, 500), (1024, 560), (1280, 769), (1920, 1040)])
@pytest.mark.parametrize("page", PAGES)
def test_pages_scroll_vertically_never_sideways(window, qapp, page, size):
    host = _show(window, qapp, page, size)
    assert window.size() == QSize(*size)
    view, viewport = window.main_layout.get_page(page), host.viewport().size()
    assert host.horizontalScrollBar().maximum() == 0
    assert view.width() == viewport.width()
    assert view.height() >= viewport.height()
    assert host.verticalScrollBar().maximum() == view.height() - viewport.height()
    if size == (600, 500) and page in ANALYSIS_PAGES:
        assert host.verticalScrollBar().maximum() > 0  # below the page's minimum: it scrolls
    if size[1] >= 769:
        assert host.verticalScrollBar().maximum() == 0  # the user's Mac and up: no scroll


@pytest.mark.parametrize("page", ANALYSIS_PAGES)
def test_wheel_over_a_control_scrolls_the_page_and_keeps_the_value(window, qapp, page):
    # The window floor: there the panel stacks and the page scrolls (at 800×500
    # the compact page fits).
    host = _show(window, qapp, page, (600, 500))
    bar = host.verticalScrollBar()
    view = window.main_layout.get_page(page)
    controls = [c for c in view.findChildren(QComboBox) + view.findChildren(QAbstractSpinBox)
                if c.isVisible()]
    assert controls
    for control in controls:
        window.top_bar.patient_dropdown.setFocus()  # focus outside the page
        bar.setValue(0)
        host.ensureWidgetVisible(control)
        _settle(qapp, 3)
        start = bar.value()
        before = control.currentIndex() if isinstance(control, QComboBox) else control.value()
        center = QPointF(control.mapTo(window, control.rect().center()))
        QTest.wheelEvent(window.windowHandle(), center, QPoint(0, 120 if start else -120))
        _settle(qapp, 3)
        after = control.currentIndex() if isinstance(control, QComboBox) else control.value()
        assert after == before, f"{type(control).__name__} changed {before} -> {after}"
        assert bar.value() != start, f"the page did not scroll over {type(control).__name__}"


def test_a_wrapped_banner_does_not_lock_the_psd_plot(window, qapp):
    """Review 11 B1, 1920×1200 → 1280×769: the plot shrinks, the page does not
    scroll, and the stale-results banner stays in view."""
    view = window.main_layout.get_page("snapshots_canonical_bands")
    _show(window, qapp, "snapshots_canonical_bands", (1920, 1200))
    view.status_label.setWordWrap(True)
    view.viewmodel.analysis_refresh_required.emit("cohens_d")
    _settle(qapp)
    try:
        tall = view.psd_plot.height()
        host = _show(window, qapp, "snapshots_canonical_bands", (1280, 769))
        assert view.psd_plot.height() < tall
        assert host.verticalScrollBar().maximum() == 0
        assert view.status_label.isVisible()
        banner_top = view.status_label.mapTo(host.viewport(), QPoint(0, 0)).y()
        assert 0 <= banner_top < host.viewport().height()
    finally:
        view.status_label.setWordWrap(False)
        view.viewmodel.analysis_refresh_cleared.emit()
