"""Shared fixtures for the UI tests."""

import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_app_wide_style():
    """Undo any application stylesheet, font or palette change a test leaves behind.

    Tests that measure the app apply the production stylesheet to the one
    session-wide ``QApplication``; without this, every later test would measure
    a differently styled UI depending on test order. A test that creates the
    application gets Qt's default (empty) stylesheet back.
    """
    app = _application()
    saved = (app.styleSheet(), app.font(), app.palette()) if app is not None else ("", None, None)
    yield
    app = _application()
    if app is None:
        return
    style_sheet, font, palette = saved
    if app.styleSheet() != style_sheet:
        app.setStyleSheet(style_sheet)
    if font is not None and app.font() != font:
        app.setFont(font)
    if palette is not None and app.palette() != palette:
        app.setPalette(palette)


def _application():
    """The running ``QApplication``, or None (without importing QtWidgets)."""
    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None:
        return None
    app = widgets.QApplication.instance()
    return app if isinstance(app, widgets.QApplication) else None
