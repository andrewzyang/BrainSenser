"""Interface size: the zoom ladder, its per-display state and Qt's start-up environment.

Pure Python (no Qt), so ViewModels, the bootstrap before ``QApplication``
exists (L0) and tests can import it without loading QtGui.

The interface size multiplies the OS display scaling. Qt applies it when the
application starts, so a change takes effect after a restart and scales text,
controls, icons and plots uniformly (plan §4.2, D1 = A). The user picks a size
per display (a :data:`ZOOM_LADDER` step keyed by ``QScreen.name()``); a session
runs at the size of the display it opens on (the last-used screen), through
one global ``QT_SCALE_FACTOR``.

Start-up composes that factor before Qt knows which displays are connected
(L0), for the display the window was last on, and records that display. When
the app then opens on another one (the last one was unplugged) whose size
differs, :func:`relaunch_scale_env` gives the environment of one relaunch at
that display's size.

Why not ``QT_SCREEN_SCALE_FACTORS`` by display name (M4.0 spike: Qt 6.9.2
``qhighdpiscaling.cpp``, checked on named offscreen screens): a per-screen
factor *replaces* the factor Qt derives from the platform's logical DPI instead
of multiplying it. Windows and X11 report their display scaling that way, so a
per-screen 1.25 on a 125 % display leaves it at 1.25 and stops it following
later OS scaling changes. ``QT_SCALE_FACTOR`` multiplies on every platform, is
never rounded by Qt and needs no display names (a name containing ``;`` cannot
be addressed at all).
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

# Interface sizes in percent. A step is an index into this tuple; the
# preferences store a step per display.
ZOOM_LADDER: tuple[int, ...] = (90, 100, 110, 125, 150, 175, 200)
DEFAULT_PERCENT = 100
DEFAULT_STEP = ZOOM_LADDER.index(DEFAULT_PERCENT)

# Zooming out below 100 % is offered only on Retina-class displays: a 1x display blurs.
RETINA_DPR = 2.0

# D2: a dense display at 100 % OS scaling (DPR 1, at least 3200 x 1800 logical
# px in either orientation: 4K/5K, not ultrawides) is offered this size once.
SUGGESTED_PERCENT = 125
SUGGEST_MIN_LONG_SIDE = 3200
SUGGEST_MIN_SHORT_SIDE = 1800

# Environment variables. Qt reads its own once, when QGuiApplication is constructed.
QT_SCALE_FACTOR = "QT_SCALE_FACTOR"
QT_SCREEN_SCALE_FACTORS = "QT_SCREEN_SCALE_FACTORS"
SCALE_INJECTED = "BRAINSENSER_SCALE_INJECTED"  # "1": the app set QT_SCALE_FACTOR and may replace it
SCALE_DISPLAY = "BRAINSENSER_SCALE_DISPLAY"    # the display the app composed the interface size for
SCALE_RELAUNCH = "BRAINSENSER_SCALE_RELAUNCH"  # relaunched for this display: no second relaunch
UI_SCALE_KILL_SWITCH = "BRAINSENSER_UI_SCALE"  # "1": OS scaling only; interface size locked


@dataclass(frozen=True)
class ScreenMetrics:
    """A display as Qt reports it.

    ``logical_w`` x ``logical_h`` is the logical size of the screen's full
    geometry, not of its available area, so a Dock or taskbar change is not a
    display change. Like ``dpr``, it includes this session's interface size,
    which Qt applies to every screen.
    """

    name: str
    logical_w: int
    logical_h: int
    dpr: float


class ZoomNotice(str, Enum):
    """What the interface-size banner shows for the current display."""

    NONE = "none"
    RESTART = "restart"        # a size chosen in this session waits for a restart
    SUGGESTION = "suggestion"  # D2: a larger size is offered for this display


@dataclass(frozen=True)
class ZoomState:
    """What the interface-size UI shows for the current display."""

    display: Optional[str]          # QScreen.name() of the current display; None until reported
    active_percent: int             # applied in this session, on every display
    chosen_percent: int             # chosen for the current display; applied at a start on it
    default_percent: int            # "Default Size"
    can_zoom_in: bool
    can_zoom_out: bool
    can_reset: bool
    restart_required: bool          # chosen != active: a restart changes the size ("Restart Now")
    label: str                      # the chosen size, e.g. "125 %"
    suggest_percent: Optional[int]  # the D2 offer for the current display
    locked: bool                    # kill switch or user/IT-set Qt scaling: commands do nothing
    notice: ZoomNotice              # the banner: a size chosen this session, or the D2 offer


def unscaled(metrics: ScreenMetrics, factor: float) -> ScreenMetrics:
    """``metrics`` without the session's interface-size ``factor``: the display
    as the OS scales it."""
    return ScreenMetrics(metrics.name, round(metrics.logical_w * factor),
                         round(metrics.logical_h * factor), round(metrics.dpr / factor, 2))


def suggest_interface_size(metrics: ScreenMetrics) -> Optional[int]:
    """D2: the interface size to offer a display (``metrics`` as the OS scales
    it, see :func:`unscaled`), or None."""
    long_side = max(metrics.logical_w, metrics.logical_h)
    short_side = min(metrics.logical_w, metrics.logical_h)
    if (math.isclose(metrics.dpr, 1.0, abs_tol=0.01) and long_side >= SUGGEST_MIN_LONG_SIDE
            and short_side >= SUGGEST_MIN_SHORT_SIDE):
        return SUGGESTED_PERCENT
    return None


def compose_zoom_state(*, display: Optional[ScreenMetrics], saved_step: Optional[int],
                       active_factor: float, suggestion_dismissed: bool, notify_restart: bool,
                       locked: bool) -> ZoomState:
    """The interface-size state of ``display`` (as Qt reports it; None before any
    display is known).

    ``saved_step`` is the step chosen for that display (None if never chosen; an
    invalid step counts as never chosen) and ``active_factor`` the factor Qt
    applies this session. Only a display that has never been given a size, and
    whose suggestion was not dismissed, gets the D2 offer.

    A restart is required whenever the display's size differs from the session's,
    but the banner announces it (``notice``) only if ``notify_restart``: a size was
    chosen for the display in this session and not put off with "Later". Moving
    the window to a display that has another saved size announces nothing; the
    "Aa" menu still offers the restart.
    """
    active = round(active_factor * 100)
    if display is None or locked:
        return ZoomState(
            display=None if display is None else display.name, active_percent=active,
            chosen_percent=active, default_percent=DEFAULT_PERCENT, can_zoom_in=False,
            can_zoom_out=False, can_reset=False, restart_required=False, label=_label(active),
            suggest_percent=None, locked=locked, notice=ZoomNotice.NONE)
    native = unscaled(display, active_factor)
    lowest = 0 if native.dpr >= RETINA_DPR else DEFAULT_STEP
    chosen_before = is_valid_step(saved_step)
    step = saved_step if chosen_before else DEFAULT_STEP
    chosen = ZOOM_LADDER[step]
    restart_required = chosen != active
    offer_open = not chosen_before and not suggestion_dismissed
    suggest_percent = suggest_interface_size(native) if offer_open else None
    if restart_required and notify_restart:
        notice = ZoomNotice.RESTART
    elif suggest_percent is not None and not restart_required:
        notice = ZoomNotice.SUGGESTION
    else:
        notice = ZoomNotice.NONE
    return ZoomState(
        display=display.name, active_percent=active, chosen_percent=chosen,
        default_percent=DEFAULT_PERCENT, can_zoom_in=step < len(ZOOM_LADDER) - 1,
        can_zoom_out=step > lowest, can_reset=chosen != DEFAULT_PERCENT,
        restart_required=restart_required, label=_label(chosen),
        suggest_percent=suggest_percent, locked=False, notice=notice)


def compose_scale_env(steps_by_display: Mapping[str, int], environ: Mapping[str, str], *,
                      launch_display: Optional[str]) -> dict[str, str]:
    """The environment to construct ``QApplication`` with: ``environ`` with the
    interface size of ``launch_display`` (its step in ``steps_by_display``)
    applied as ``QT_SCALE_FACTOR``. Returns a new mapping.

    - The display is recorded as ``BRAINSENSER_SCALE_DISPLAY``, at 100 % too, so
      start-up can tell when the app opens on another one (:func:`relaunch_scale_env`).
    - A ``QT_SCALE_FACTOR`` the app set earlier (marked ``BRAINSENSER_SCALE_INJECTED=1``,
      e.g. inherited across a restart) is replaced; a new one is marked again.
    - A ``QT_SCALE_FACTOR`` or ``QT_SCREEN_SCALE_FACTORS`` set by the user or IT is
      never changed, and nothing is added.
    - ``BRAINSENSER_UI_SCALE=1`` adds nothing and drops the app's own factor.
    - 100 %, or a display without a valid step, adds no factor; no display adds nothing.
    """
    env = dict(environ)
    env.pop(SCALE_DISPLAY, None)
    if env.get(SCALE_INJECTED) == "1":
        del env[SCALE_INJECTED]
        env.pop(QT_SCALE_FACTOR, None)
    if env.get(UI_SCALE_KILL_SWITCH) == "1" or _qt_scaling_set(env) or launch_display is None:
        return env
    env[SCALE_DISPLAY] = launch_display
    step = steps_by_display.get(launch_display)
    if not is_valid_step(step) or ZOOM_LADDER[step] == DEFAULT_PERCENT:
        return env
    env[QT_SCALE_FACTOR] = f"{ZOOM_LADDER[step] / 100:g}"
    env[SCALE_INJECTED] = "1"
    return env


def relaunch_scale_env(environ: Mapping[str, str], state: ZoomState) -> Optional[dict[str, str]]:
    """The environment to start the app with once more, or None to carry on.

    ``environ`` is the environment this session started with, ``state`` the
    interface-size state of the display the app opens on. Start-up composed the
    size of the display the window was last on (``BRAINSENSER_SCALE_DISPLAY``)
    before Qt knew which displays are connected. When the app opens on another
    display (the last one was unplugged) and needs another size there, one
    relaunch gives it its own: the returned environment composes that size and
    names the display (``BRAINSENSER_SCALE_RELAUNCH``), so the relaunched
    start-up composes for it and never relaunches again.

    Nothing to do when start-up composed nothing (Qt scaling set by the user or
    IT, the kill switch, no saved display), composed for this very display, or
    when the sizes agree.
    """
    composed_for = environ.get(SCALE_DISPLAY)
    if (SCALE_RELAUNCH in environ or not state.restart_required or composed_for is None
            or composed_for == state.display):
        return None
    env = compose_scale_env({state.display: ZOOM_LADDER.index(state.chosen_percent)}, environ,
                            launch_display=state.display)
    env[SCALE_RELAUNCH] = state.display
    return env


def active_scale_factor(environ: Mapping[str, str]) -> float:
    """The global factor Qt applies when started with ``environ``: a positive,
    finite ``QT_SCALE_FACTOR``, whoever set it, else 1.0. A user's per-screen
    ``QT_SCREEN_SCALE_FACTORS`` is not interpreted."""
    try:
        factor = float(environ.get(QT_SCALE_FACTOR, ""))
    except ValueError:
        return 1.0
    return factor if math.isfinite(factor) and factor > 0 else 1.0


def scale_locked(environ: Mapping[str, str]) -> bool:
    """Whether the interface size is locked under ``environ``: the kill switch is
    on, or Qt's scaling is set by the user or IT (not marked as the app's)."""
    if environ.get(UI_SCALE_KILL_SWITCH) == "1":
        return True
    if environ.get(SCALE_INJECTED) == "1":
        return bool(environ.get(QT_SCREEN_SCALE_FACTORS, "").strip())
    return _qt_scaling_set(environ)


def is_valid_step(step: object) -> bool:
    """Whether ``step`` indexes :data:`ZOOM_LADDER` (bools are not steps)."""
    return isinstance(step, int) and not isinstance(step, bool) and 0 <= step < len(ZOOM_LADDER)


def _qt_scaling_set(environ: Mapping[str, str]) -> bool:
    return any(environ.get(name, "").strip() for name in (QT_SCALE_FACTOR, QT_SCREEN_SCALE_FACTORS))


def _label(percent: int) -> str:
    return f"{percent} %"
