"""
The app font and appearance that ``configure_application`` sets: the system UI
font at the body size (the stylesheet names no family, so Qt never looks font
aliases up), the light colour scheme requested before any window exists, and
the sidebar title at 18 px in regular weight on a 96-dpi screen (where the old
18 pt was 24 px).

Each check runs in a fresh offscreen process: Qt looks aliases up at most once
per process, and the scheme and font only count before the first window.
Offscreen has no platform theme and reports a system font family that doesn't
exist ("Sans Serif"), so the child stands in cocoa's, as the macOS golden
profile does.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.qt_subprocess,
    pytest.mark.skipif(sys.platform != "darwin", reason="stands in cocoa's system font"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]
ALIAS_LOOKUP = "Populating font family aliases"
SYSTEM_FONT = (".AppleSystemUIFont", 13)
# The family list style.qss carried before M1.1.
WEB_FONT_FAMILIES = '* { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }'

CHILD = r"""
import json, sys
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QStyleHints
from PySide6.QtWidgets import (QApplication, QComboBox, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QWidget)

messages = []
qInstallMessageHandler(lambda _mode, _context, message: messages.append(message))
schemes = []
QStyleHints.setColorScheme = lambda _hints, scheme: schemes.append(
    [scheme.name, len(QApplication.topLevelWidgets())])
family, points = json.loads(sys.argv[2])
QFontDatabase.systemFont = staticmethod(lambda _which: QFont(family, points))

app = QApplication([])
from src.ui.app_bootstrap import configure_application
from src.ui.components import Sidebar, TopBar
configure_application(app)
app.setStyleSheet(sys.argv[1] + app.styleSheet())

tops = [Sidebar(), TopBar(), QLabel("Label"), QPushButton("Button"), QComboBox(),
        QLineEdit("Text"), QTableWidget(2, 2)]
for top in tops:
    top.grab()  # polishes, lays out and paints it and its children
app_font = QFontInfo(app.font())
title = QFontInfo(tops[0].findChild(QLabel, "app_title").font())
print(json.dumps({
    "messages": messages,
    "schemes": schemes,
    "app_font": [app_font.family(), app_font.pixelSize()],
    "families": sorted({QFontInfo(w.font()).family()
                        for top in tops for w in [top, *top.findChildren(QWidget)]}),
    "title": [title.pixelSize(), title.weight()],
}))
"""


def _run_child(tmp_path: Path, extra_qss: str = "") -> dict:
    """Start the app's look in a fresh offscreen process; what it measured."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("QT_", "BRAINSENSER_"))}
    env.update(QT_QPA_PLATFORM="offscreen", BRAINSENSER_DATA_DIR=str(tmp_path),
               HOME=str(tmp_path), PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.run([sys.executable, "-c", CHILD, extra_qss, json.dumps(SYSTEM_FONT)],
                           env=env, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert child.returncode == 0, child.stderr[-3000:]
    return json.loads(child.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def started(tmp_path_factory) -> dict:
    return _run_child(tmp_path_factory.mktemp("app_font"))


def test_app_font_is_the_system_font_at_the_body_size(started):
    assert started["app_font"] == [SYSTEM_FONT[0], 15]
    assert started["families"] == [SYSTEM_FONT[0]]


def test_no_font_alias_lookup(started):
    assert not [m for m in started["messages"] if ALIAS_LOOKUP in m]


def test_light_appearance_is_requested_before_any_window(started):
    assert started["schemes"] == [["Light", 0]]


def test_sidebar_title_is_18_px_regular(started):
    assert started["title"] == [18, 400]


def test_a_web_font_family_list_would_bring_the_lookup_back(tmp_path):
    """The check above can fail: the old family list triggers the lookup."""
    measured = _run_child(tmp_path, WEB_FONT_FAMILIES)

    assert [m for m in measured["messages"] if ALIAS_LOOKUP in m]
