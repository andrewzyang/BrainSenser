"""Interface-size policy (src/ui/policy/scale.py): ladder, D2 suggestion, zoom state
and its notice, start-up env, the one relaunch for another launch display.

Pure Python: no QApplication. The import-purity check (no Qt) lives in
tests/architecture/test_responsive_mvvm.py.
"""

import dataclasses

import pytest

from src.ui.policy.scale import (
    DEFAULT_PERCENT, DEFAULT_STEP, QT_SCALE_FACTOR, QT_SCREEN_SCALE_FACTORS, SCALE_DISPLAY,
    SCALE_INJECTED, SCALE_RELAUNCH, SUGGESTED_PERCENT, UI_SCALE_KILL_SWITCH, ZOOM_LADDER,
    ScreenMetrics, ZoomNotice, ZoomState, active_scale_factor, compose_scale_env,
    compose_zoom_state, is_valid_step, relaunch_scale_env, scale_locked, suggest_interface_size,
    unscaled,
)

RETINA = ScreenMetrics("Built-in Retina Display", 1280, 828, 2.0)
ONE_X = ScreenMetrics("DELL P2419H", 1920, 1080, 1.0)
UHD_AT_100 = ScreenMetrics("LG UltraFine", 3840, 2160, 1.0)

MARKED = {SCALE_INJECTED: "1"}


def state(display, saved_step=None, active_factor=1.0, dismissed=False, locked=False,
          notify=False) -> ZoomState:
    return compose_zoom_state(display=display, saved_step=saved_step, active_factor=active_factor,
                              suggestion_dismissed=dismissed, notify_restart=notify, locked=locked)


def injected(percent, display) -> dict:
    """The environment L0 composes for ``display`` saved at ``percent``."""
    return compose_scale_env({display: step(percent)}, {}, launch_display=display)


def step(percent: int) -> int:
    return ZOOM_LADDER.index(percent)


# ------------------------------------------------------------------ ladder

def test_ladder_is_the_plan_ladder():
    assert ZOOM_LADDER == (90, 100, 110, 125, 150, 175, 200)
    assert list(ZOOM_LADDER) == sorted(set(ZOOM_LADDER))
    assert ZOOM_LADDER[DEFAULT_STEP] == DEFAULT_PERCENT == 100


@pytest.mark.parametrize("candidate, valid", [
    (0, True), (6, True), (-1, False), (7, False), (True, False), (1.0, False), ("1", False),
    (None, False),
])
def test_is_valid_step(candidate, valid):
    assert is_valid_step(candidate) is valid


# ------------------------------------------------------------------ D2 suggestion

@pytest.mark.parametrize("width, height, dpr, expected", [
    (3840, 2160, 1.0, SUGGESTED_PERCENT),   # 4K at 100 %
    (5120, 2880, 1.0, SUGGESTED_PERCENT),   # 5K at 100 %
    (2160, 3840, 1.0, SUGGESTED_PERCENT),   # 4K portrait
    (3200, 1800, 1.0, SUGGESTED_PERCENT),   # exactly at the threshold
    (3199, 1800, 1.0, None),
    (3200, 1799, 1.0, None),
    (3440, 1440, 1.0, None),                # ultrawide
    (5120, 1440, 1.0, None),                # super-ultrawide
    (3840, 1600, 1.0, None),                # ultrawide 4K
    (1920, 1080, 1.0, None),
    (3072, 1728, 1.25, None),               # 4K at 125 % OS scaling
    (2560, 1440, 1.5, None),
    (2560, 1440, 2.0, None),                # Retina
    (3840, 2160, 2.0, None),
])
def test_suggestion_table(width, height, dpr, expected):
    assert suggest_interface_size(ScreenMetrics("display", width, height, dpr)) == expected


def test_suggestion_never_below_the_default():
    for width, height in ((1280, 800), (3840, 2160), (7680, 4320)):
        for dpr in (1.0, 1.25, 2.0):
            offer = suggest_interface_size(ScreenMetrics("d", width, height, dpr))
            assert offer is None or offer > DEFAULT_PERCENT


@pytest.mark.parametrize("reported, factor, native", [
    (ScreenMetrics("r", 1024, 662, 2.5), 1.25, ScreenMetrics("r", 1280, 828, 2.0)),
    (ScreenMetrics("r", 1164, 753, 2.2), 1.1, ScreenMetrics("r", 1280, 828, 2.0)),
    (ScreenMetrics("u", 3072, 1728, 1.25), 1.25, ScreenMetrics("u", 3840, 2160, 1.0)),
    (RETINA, 1.0, RETINA),
])
def test_unscaled_takes_the_session_factor_out(reported, factor, native):
    assert unscaled(reported, factor) == native


# ------------------------------------------------------------------ zoom state

def test_zoom_state_is_frozen_with_the_contract_fields():
    fields = [f.name for f in dataclasses.fields(ZoomState)]
    assert fields == ["display", "active_percent", "chosen_percent", "default_percent",
                      "can_zoom_in", "can_zoom_out", "can_reset", "restart_required", "label",
                      "suggest_percent", "locked", "notice"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state(RETINA).chosen_percent = 125


def test_state_before_any_display_offers_nothing():
    s = state(None, active_factor=1.25, notify=True)
    assert s == ZoomState(display=None, active_percent=125, chosen_percent=125, default_percent=100,
                          can_zoom_in=False, can_zoom_out=False, can_reset=False,
                          restart_required=False, label="125 %", suggest_percent=None, locked=False,
                          notice=ZoomNotice.NONE)


def test_default_state_on_retina_allows_90_percent():
    s = state(RETINA)
    assert (s.display, s.active_percent, s.chosen_percent, s.default_percent) == (
        RETINA.name, 100, 100, 100)
    assert (s.can_zoom_in, s.can_zoom_out, s.can_reset, s.restart_required) == (
        True, True, False, False)
    assert (s.label, s.suggest_percent, s.locked) == ("100 %", None, False)


def test_one_x_display_starts_the_ladder_at_100():
    assert state(ONE_X).can_zoom_out is False
    assert state(ONE_X, saved_step=step(110)).can_zoom_out is True


def test_retina_is_judged_without_the_session_factor():
    # At 125 % the Retina panel reports 1024 x 662 at DPR 2.5; it is still Retina,
    # and a 1x display reporting DPR 2.0 at 200 % is still 1x.
    assert state(ScreenMetrics("r", 1024, 662, 2.5), active_factor=1.25).can_zoom_out is True
    s = state(ScreenMetrics("x", 960, 540, 2.0), saved_step=step(110), active_factor=2.0)
    assert s.chosen_percent == 110 and s.can_zoom_out is True
    assert state(ScreenMetrics("x", 960, 540, 2.0), saved_step=step(100),
                 active_factor=2.0).can_zoom_out is False


def test_saved_90_on_a_1x_display_is_kept_not_clamped():
    # A display can switch from a HiDPI to a 1x mode under the same name. Clamping
    # to 100 % would leave the 90 % applied at start-up forever "pending".
    s = state(ONE_X, saved_step=step(90), active_factor=0.9)
    assert (s.chosen_percent, s.restart_required, s.can_zoom_out, s.can_zoom_in) == (
        90, False, False, True)


def test_chosen_size_differing_from_the_session_needs_a_restart():
    s = state(RETINA, saved_step=step(125))
    assert (s.chosen_percent, s.label, s.can_reset, s.restart_required) == (
        125, "125 %", True, True)
    assert state(ScreenMetrics("r", 1024, 662, 2.5), saved_step=step(125),
                 active_factor=1.25).restart_required is False


def test_top_of_the_ladder_cannot_zoom_in():
    s = state(RETINA, saved_step=step(200))
    assert (s.can_zoom_in, s.can_zoom_out, s.can_reset) == (False, True, True)


@pytest.mark.parametrize("saved_step", [None, 99, -1, True, "3", 1.5])
def test_invalid_saved_step_counts_as_never_chosen(saved_step):
    s = state(UHD_AT_100, saved_step=saved_step)
    assert s.chosen_percent == DEFAULT_PERCENT
    assert s.suggest_percent == SUGGESTED_PERCENT


def test_suggestion_only_for_displays_never_given_a_size():
    assert state(UHD_AT_100).suggest_percent == SUGGESTED_PERCENT
    assert state(UHD_AT_100, dismissed=True).suggest_percent is None
    # Any saved size, the default included, is the user's answer.
    assert state(UHD_AT_100, saved_step=DEFAULT_STEP).suggest_percent is None
    assert state(UHD_AT_100, saved_step=step(110)).suggest_percent is None


def test_suggestion_judges_the_display_without_the_session_factor():
    reported = ScreenMetrics(UHD_AT_100.name, 3072, 1728, 1.25)
    s = state(reported, active_factor=1.25)
    assert s.suggest_percent == SUGGESTED_PERCENT
    assert s.restart_required is True  # never chosen = 100 %, but the session runs at 125 %


def test_locked_state_pins_everything():
    s = state(UHD_AT_100, saved_step=step(150), active_factor=1.25, locked=True, notify=True)
    assert s == ZoomState(display=UHD_AT_100.name, active_percent=125, chosen_percent=125,
                          default_percent=100, can_zoom_in=False, can_zoom_out=False,
                          can_reset=False, restart_required=False, label="125 %",
                          suggest_percent=None, locked=True, notice=ZoomNotice.NONE)


# ------------------------------------------------------------------ notice (the banner)

@pytest.mark.parametrize("display, saved, factor, dismissed, notify, notice", [
    # A size chosen this session that differs from the session's: announced
    (RETINA, step(125), 1.0, False, True, ZoomNotice.RESTART),
    # ... until Later (or, never chosen this session, e.g. a display the window moved to)
    (RETINA, step(125), 1.0, False, False, ZoomNotice.NONE),
    # chosen this session, but back at the session's size: nothing pending
    (RETINA, step(100), 1.0, False, True, ZoomNotice.NONE),
    # the window moved to a display with another saved size: nothing announced
    (ONE_X, None, 1.25, False, False, ZoomNotice.NONE),
    (ONE_X, step(150), 1.25, False, False, ZoomNotice.NONE),
    # D2: a dense display never given a size, at the session's size
    (UHD_AT_100, None, 1.0, False, False, ZoomNotice.SUGGESTION),
    (UHD_AT_100, None, 1.0, True, False, ZoomNotice.NONE),
    # ... not while the session runs at another size there
    (ScreenMetrics(UHD_AT_100.name, 3072, 1728, 1.25), None, 1.25, False, False, ZoomNotice.NONE),
    # accepted this session: the restart is announced instead
    (UHD_AT_100, step(125), 1.0, False, True, ZoomNotice.RESTART),
])
def test_notice_table(display, saved, factor, dismissed, notify, notice):
    s = state(display, saved_step=saved, active_factor=factor, dismissed=dismissed, notify=notify)
    assert s.notice is notice
    if notice is ZoomNotice.RESTART:
        assert s.restart_required


def test_moving_to_a_display_with_another_size_keeps_the_restart_available():
    s = state(ONE_X, saved_step=step(100), active_factor=1.25)
    assert (s.restart_required, s.notice, s.chosen_percent) == (True, ZoomNotice.NONE, 100)


# ------------------------------------------------------------------ start-up environment

@pytest.mark.parametrize("percent, factor", [
    (90, "0.9"), (110, "1.1"), (125, "1.25"), (150, "1.5"), (175, "1.75"), (200, "2"),
])
def test_compose_sets_the_launch_displays_factor_and_marks_it(percent, factor):
    env = compose_scale_env({"air15": step(percent)}, {}, launch_display="air15")
    assert env == {QT_SCALE_FACTOR: factor, SCALE_INJECTED: "1", SCALE_DISPLAY: "air15"}


def test_compose_never_writes_per_screen_factors():
    # M4.0: QT_SCREEN_SCALE_FACTORS replaces the OS scaling on Windows/X11.
    env = compose_scale_env({"a": step(150), "b": step(125)}, {}, launch_display="b")
    assert env == {QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1", SCALE_DISPLAY: "b"}


@pytest.mark.parametrize("steps, launch_display", [
    ({"air15": DEFAULT_STEP}, "air15"),
    ({"air15": step(150)}, "other"),
    ({"air15": 99}, "air15"),
    ({"air15": True}, "air15"),
    ({}, "air15"),
])
def test_compose_adds_no_factor_at_100_or_without_a_valid_step(steps, launch_display):
    """... but records the display composed for, which start-up compares with the
    one it opens on (relaunch_scale_env)."""
    assert compose_scale_env(steps, {"PATH": "/bin"}, launch_display=launch_display) == {
        "PATH": "/bin", SCALE_DISPLAY: launch_display}


def test_compose_adds_nothing_without_a_display():
    assert compose_scale_env({"air15": step(150)}, {"PATH": "/bin"}, launch_display=None) == {
        "PATH": "/bin"}


def test_compose_replaces_its_own_display_record():
    inherited = {SCALE_DISPLAY: "old", QT_SCALE_FACTOR: "1.25", **MARKED}
    assert compose_scale_env({"new": step(150)}, inherited, launch_display="new") == {
        QT_SCALE_FACTOR: "1.5", SCALE_INJECTED: "1", SCALE_DISPLAY: "new"}
    assert compose_scale_env({}, {SCALE_DISPLAY: "old"}, launch_display=None) == {}


@pytest.mark.parametrize("user_env", [
    {QT_SCALE_FACTOR: "1.5"},
    {QT_SCREEN_SCALE_FACTORS: "DELL U2720Q=1.5"},
    {QT_SCALE_FACTOR: "1.5", SCALE_INJECTED: "0"},
    {QT_SCALE_FACTOR: "abc"},
])
def test_compose_respects_a_user_or_it_set_qt_scale(user_env):
    assert compose_scale_env({"air15": step(125)}, user_env, launch_display="air15") == user_env


def test_compose_treats_a_blank_variable_as_unset():
    env = compose_scale_env({"air15": step(125)}, {QT_SCALE_FACTOR: " "}, launch_display="air15")
    assert env == {QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1", SCALE_DISPLAY: "air15"}


def test_compose_replaces_its_own_earlier_factor():
    inherited = {QT_SCALE_FACTOR: "1.25", **MARKED, SCALE_DISPLAY: "air15", "HOME": "/h"}
    assert compose_scale_env({"air15": step(150)}, inherited, launch_display="air15") == {
        QT_SCALE_FACTOR: "1.5", SCALE_INJECTED: "1", SCALE_DISPLAY: "air15", "HOME": "/h"}
    assert compose_scale_env({"air15": DEFAULT_STEP}, inherited, launch_display="air15") == {
        SCALE_DISPLAY: "air15", "HOME": "/h"}


def test_compose_keeps_a_user_per_screen_factor_next_to_its_own():
    inherited = {QT_SCALE_FACTOR: "1.25", **MARKED, QT_SCREEN_SCALE_FACTORS: "x=2"}
    assert compose_scale_env({"air15": step(150)}, inherited, launch_display="air15") == {
        QT_SCREEN_SCALE_FACTORS: "x=2"}


@pytest.mark.parametrize("environ, expected", [
    ({UI_SCALE_KILL_SWITCH: "1"}, {UI_SCALE_KILL_SWITCH: "1"}),
    ({UI_SCALE_KILL_SWITCH: "1", QT_SCALE_FACTOR: "1.25", **MARKED}, {UI_SCALE_KILL_SWITCH: "1"}),
    ({UI_SCALE_KILL_SWITCH: "1", QT_SCALE_FACTOR: "2"}, {UI_SCALE_KILL_SWITCH: "1",
                                                         QT_SCALE_FACTOR: "2"}),
    ({UI_SCALE_KILL_SWITCH: "0"}, {UI_SCALE_KILL_SWITCH: "0", QT_SCALE_FACTOR: "1.25",
                                   SCALE_INJECTED: "1", SCALE_DISPLAY: "air15"}),
])
def test_compose_kill_switch(environ, expected):
    assert compose_scale_env({"air15": step(125)}, environ, launch_display="air15") == expected


def test_compose_returns_a_new_mapping():
    environ = {QT_SCALE_FACTOR: "1.25", **MARKED}
    snapshot = dict(environ)
    result = compose_scale_env({"air15": step(150)}, environ, launch_display="air15")
    assert environ == snapshot and result is not environ


@pytest.mark.parametrize("value, factor", [
    ("1.25", 1.25), (" 1.5 ", 1.5), ("2", 2.0), ("", 1.0), ("abc", 1.0), ("0", 1.0),
    ("-2", 1.0), ("inf", 1.0), ("nan", 1.0), (None, 1.0),
])
def test_active_scale_factor(value, factor):
    environ = {} if value is None else {QT_SCALE_FACTOR: value}
    assert active_scale_factor(environ) == factor


@pytest.mark.parametrize("environ, locked", [
    ({}, False),
    ({QT_SCALE_FACTOR: "1.25", **MARKED}, False),
    ({QT_SCALE_FACTOR: " "}, False),
    ({QT_SCALE_FACTOR: "1.25"}, True),
    ({QT_SCREEN_SCALE_FACTORS: "a=1.5"}, True),
    ({QT_SCREEN_SCALE_FACTORS: "a=1.5", **MARKED}, True),
    ({UI_SCALE_KILL_SWITCH: "1"}, True),
    ({UI_SCALE_KILL_SWITCH: "1", QT_SCALE_FACTOR: "1.25", **MARKED}, True),
    ({UI_SCALE_KILL_SWITCH: "0"}, False),
])
def test_scale_locked(environ, locked):
    assert scale_locked(environ) is locked


@pytest.mark.parametrize("percent", ZOOM_LADDER)
def test_composed_env_round_trips_to_the_active_factor(percent):
    env = compose_scale_env({"d": step(percent)}, {}, launch_display="d")
    assert active_scale_factor(env) == percent / 100
    assert scale_locked(env) is False


# ------------------------------------------------------------------ relaunch for the launch display

EXTERNAL = "DELL U2720Q"
LAPTOP_AT_125 = ScreenMetrics(RETINA.name, 1024, 662, 2.5)  # the Retina panel under 125 %


def test_undocked_laptop_relaunches_once_at_its_own_size():
    """Last session on the external display at 125 %; it is gone, the app opens on
    the laptop, never given a size (100 %)."""
    environ = {"PATH": "/bin", **injected(125, EXTERNAL)}
    s = state(LAPTOP_AT_125, active_factor=active_scale_factor(environ))
    assert (s.chosen_percent, s.restart_required, s.notice) == (100, True, ZoomNotice.NONE)
    assert relaunch_scale_env(environ, s) == {
        "PATH": "/bin", SCALE_DISPLAY: RETINA.name, SCALE_RELAUNCH: RETINA.name}


def test_undocked_laptop_relaunches_at_the_size_chosen_for_it():
    environ = injected(125, EXTERNAL)
    s = state(LAPTOP_AT_125, saved_step=step(110), active_factor=1.25)
    assert relaunch_scale_env(environ, s) == {
        QT_SCALE_FACTOR: "1.1", SCALE_INJECTED: "1", SCALE_DISPLAY: RETINA.name,
        SCALE_RELAUNCH: RETINA.name}


def test_last_display_at_100_and_the_launch_display_larger_relaunches_too():
    environ = injected(100, EXTERNAL)
    assert environ == {SCALE_DISPLAY: EXTERNAL}
    s = state(RETINA, saved_step=step(125), active_factor=1.0)
    assert relaunch_scale_env(environ, s) == {
        QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1", SCALE_DISPLAY: RETINA.name,
        SCALE_RELAUNCH: RETINA.name}


@pytest.mark.parametrize("environ, s", [
    # composed for this very display
    (injected(125, RETINA.name), state(LAPTOP_AT_125, saved_step=step(125), active_factor=1.25)),
    # another display, but the same size
    (injected(125, EXTERNAL), state(LAPTOP_AT_125, saved_step=step(125), active_factor=1.25)),
    # already relaunched for it: never again
    ({**injected(125, EXTERNAL), SCALE_RELAUNCH: "elsewhere"},
     state(LAPTOP_AT_125, active_factor=1.25)),
    # start-up composed nothing: no saved display (first launch), or no L0 at all
    ({}, state(RETINA, saved_step=step(125), active_factor=1.0)),
    ({QT_SCALE_FACTOR: "1.25", SCALE_INJECTED: "1"}, state(LAPTOP_AT_125, active_factor=1.25)),
    # Qt scaling set by the user or IT, or the kill switch: locked
    ({QT_SCALE_FACTOR: "1.25", SCALE_DISPLAY: EXTERNAL},
     state(LAPTOP_AT_125, active_factor=1.25, locked=True)),
    ({UI_SCALE_KILL_SWITCH: "1", SCALE_DISPLAY: EXTERNAL},
     state(RETINA, saved_step=step(125), locked=True)),
    # no display known
    (injected(125, EXTERNAL), state(None, active_factor=1.25)),
])
def test_no_relaunch(environ, s):
    assert relaunch_scale_env(environ, s) is None


def test_the_relaunched_start_up_never_relaunches_again():
    """The relaunch names the display; L0 composes for it (not for the saved last
    screen); the relaunched session agrees with it, and even a launch display that
    changed once more cannot start another relaunch."""
    steps = {EXTERNAL: step(125), RETINA.name: step(110)}
    first = compose_scale_env(steps, {}, launch_display=EXTERNAL)
    relaunch = relaunch_scale_env(first, state(LAPTOP_AT_125, saved_step=step(110),
                                               active_factor=active_scale_factor(first)))
    # what L0 does in the new process: the display named by the relaunch
    second = compose_scale_env(steps, relaunch, launch_display=relaunch[SCALE_RELAUNCH])
    assert (second[QT_SCALE_FACTOR], second[SCALE_DISPLAY]) == ("1.1", RETINA.name)
    laptop_at_110 = ScreenMetrics(RETINA.name, 1164, 753, 2.2)
    assert relaunch_scale_env(second, state(laptop_at_110, saved_step=step(110),
                                            active_factor=1.1)) is None
    elsewhere = ScreenMetrics("Sidecar", 1000, 700, 2.2)
    assert relaunch_scale_env(second, state(elsewhere, active_factor=1.1)) is None
