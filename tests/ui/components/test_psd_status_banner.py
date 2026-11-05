"""
The Snapshots PSD stale-results banner fits any width (plan M1.6, adv:B1).

It stays one line: too long for its width, it ends in "…" and its tooltip has
the whole message, and the message never widens the page. It never wraps,
which would put the page's scroll area into height-for-width mode.
"""

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.app_style import apply_app_stylesheet
from src.ui.viewmodels.snapshots_psd_viewmodel import SnapshotsPsdViewModel
from src.ui.views.snapshots_psd.snapshots_psd_view import SnapshotsPsdView

MESSAGE = "Effect size changed to Cohen's d. Press Compare Groups to refresh results."
VM_SIGNALS = ("patient_changed", "data_loaded", "analysis_started", "analysis_complete",
              "psd_curves_ready", "band_statistics_ready", "error_occurred", "progress_updated",
              "analysis_refresh_required", "analysis_refresh_cleared")


@pytest.fixture(scope="module", autouse=True)
def app_style(qapp):
    previous = qapp.styleSheet()
    apply_app_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


@pytest.fixture
def view(qtbot):
    viewmodel = MagicMock(spec=SnapshotsPsdViewModel)
    for name in VM_SIGNALS:
        setattr(viewmodel, name, MagicMock())
    viewmodel.get_effect_size_value.return_value = "rank_biserial"
    widget = SnapshotsPsdView(viewmodel=viewmodel)
    qtbot.addWidget(widget)
    return widget


def _show(view, width: int) -> None:
    view.resize(width, 700)
    view.show()
    for _ in range(3):
        QApplication.processEvents()


def test_the_banner_never_widens_the_page(view):
    _show(view, 1200)
    before = view.minimumSizeHint().width()
    view._on_analysis_refresh_required("cohens_d")
    assert view.status_label.isVisible()
    assert view.minimumSizeHint().width() == before


def test_a_narrow_banner_is_elided_with_the_message_as_tooltip(view):
    view._on_analysis_refresh_required("cohens_d")
    _show(view, 400)
    banner = view.status_label
    assert not banner.wordWrap()
    assert banner.text().endswith("…")
    assert banner.fontMetrics().horizontalAdvance(banner.text()) <= banner.contentsRect().width()
    assert banner.toolTip() == MESSAGE


def test_a_wide_banner_shows_the_whole_message(view):
    view._on_analysis_refresh_required("cohens_d")
    _show(view, 1600)
    assert (view.status_label.text(), view.status_label.toolTip()) == (MESSAGE, "")


def test_clearing_the_banner_hides_it(view):
    _show(view, 400)
    view._on_analysis_refresh_required("cohens_d")
    view._on_analysis_refresh_cleared()
    assert not view.status_label.isVisible()
    assert view.status_label.toolTip() == ""
