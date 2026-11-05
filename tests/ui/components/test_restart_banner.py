"""RestartBanner: a thin mapper of ZoomState.notice (plan M4.3, D2).

The banner decides nothing: each notice maps to its text and buttons, NONE
hides it, and each button only reports the answer to the notice on show (the
ViewModel turns "Later" into a new state). No ViewModel here.
"""

import dataclasses

import pytest
from PySide6.QtWidgets import QWidget

from src.ui.components.restart_banner import RestartBanner
from src.ui.policy.scale import ScreenMetrics, ZoomNotice, compose_zoom_state

UHD = ScreenMetrics("DELL U2720Q", 3840, 2160, 1.0)

BASE = compose_zoom_state(display=UHD, saved_step=None, active_factor=1.0,
                          suggestion_dismissed=False, notify_restart=False, locked=False)
SUGGESTION = BASE  # a 4K display at 100 %, never given a size: offered 125 %
RESTART = dataclasses.replace(BASE, chosen_percent=125, label="125 %", restart_required=True,
                              suggest_percent=None, notice=ZoomNotice.RESTART)
NOTHING = dataclasses.replace(RESTART, notice=ZoomNotice.NONE)  # e.g. after Later


@pytest.fixture
def banner(qtbot):
    parent = QWidget()  # kept alive by this frame until teardown
    qtbot.addWidget(parent)
    banner = RestartBanner(parent)
    answers = []
    for name in ("restart_requested", "restart_postponed", "suggestion_accepted",
                 "suggestion_dismissed"):
        getattr(banner, name).connect(lambda name=name: answers.append(name))
    banner.answers = answers
    yield banner


def _texts(banner):
    return (banner.message.text(), banner.primary_button.text(), banner.secondary_button.text())


def test_hidden_until_a_notice(banner):
    assert banner.isHidden()
    banner.show_state(NOTHING)
    assert banner.isHidden()


def test_restart_notice(banner):
    banner.show_state(RESTART)
    assert not banner.isHidden()
    assert _texts(banner) == ("Interface size changes after restart", "Restart Now", "Later")


def test_suggestion_notice(banner):
    assert SUGGESTION.notice is ZoomNotice.SUGGESTION
    banner.show_state(SUGGESTION)
    assert not banner.isHidden()
    assert _texts(banner) == ("Text on this display may be easier to read at 125 %.",
                              "Use 125 %", "Keep 100 %")


@pytest.mark.parametrize("state, button, answer", [
    (RESTART, "primary_button", "restart_requested"),
    (RESTART, "secondary_button", "restart_postponed"),
    (SUGGESTION, "primary_button", "suggestion_accepted"),
    (SUGGESTION, "secondary_button", "suggestion_dismissed"),
])
def test_each_button_answers_the_notice_shown(banner, state, button, answer):
    banner.show_state(state)
    getattr(banner, button).click()
    assert banner.answers == [answer]


def test_later_decides_nothing_by_itself(banner):
    """Later only reports; the banner stays until the ViewModel's next state says otherwise."""
    banner.show_state(RESTART)
    banner.secondary_button.click()
    assert banner.answers == ["restart_postponed"] and not banner.isHidden()
    banner.show_state(NOTHING)
    assert banner.isHidden()
    banner.show_state(RESTART)  # announced again (another size was chosen)
    assert not banner.isHidden()


def test_no_answer_without_a_notice(banner):
    banner.show_state(RESTART)
    banner.show_state(NOTHING)
    banner.primary_button.click()
    banner.secondary_button.click()
    assert banner.answers == []
