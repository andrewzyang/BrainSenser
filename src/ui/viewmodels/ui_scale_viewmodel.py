"""
UiScaleViewModel - presentation state of the interface size.

The interface size multiplies the OS display scaling. The user picks one per
display; Qt applies it when the app starts (src/ui/policy/scale.py), so a new
size shows after a restart and the state says when one is pending (plan §4.7,
D1 = A, D2).

- The constructor restores the saved sizes and dismissed suggestions once,
  through the injected ZoomPreferenceStore, and emits nothing: ``state`` is
  readable at once. Afterwards ``state_changed`` fires only when the state
  changes, carrying the new frozen ZoomState.
- ``active_factor`` is the factor Qt applies this session (from the start-up
  environment). ``locked`` (the kill switch, or Qt scaling set by the user or
  IT) makes every command a no-op that writes nothing.
- The View reports the window's display; commands act on that display and take
  no parameters, so a QAction's ``triggered(bool)`` can connect to them directly.
- ``ZoomState.notice`` decides the banner: a restart is announced only for a
  size chosen in this session, until "Later" (:meth:`postpone_restart`, not
  saved) or another choice; never because the window moved to a display with
  another saved size.
- Store and restart failures are logged, never raised.

Author: iEEG BrainSense Development Team
Last Updated: 2026-10-27
"""

import logging
import math
from typing import Optional

from PySide6.QtCore import QObject, Signal

from src.domain.ui_preferences import AppRestarter, ZoomPreferenceStore
from src.ui.policy.scale import (
    DEFAULT_STEP, ZOOM_LADDER, ScreenMetrics, ZoomNotice, ZoomState, compose_zoom_state,
    is_valid_step,
)

logger = logging.getLogger(__name__)


class UiScaleViewModel(QObject):
    """
    Interface size of the current display: "Aa" menu, restart banner, D2 offer.

    Signals:
        state_changed: The new ZoomState, emitted only when it changes.

    Example:
        >>> scale_vm = UiScaleViewModel(store, restarter, active_factor=1.0)
        >>> scale_vm.set_current_display(ScreenMetrics("Built-in Retina Display", 1280, 828, 2.0))
        >>> apply(scale_vm.state)                    # read first,
        >>> scale_vm.state_changed.connect(apply)    # then connect
        >>> zoom_in_action.triggered.connect(scale_vm.zoom_in)
    """

    state_changed = Signal(object)  # ZoomState

    def __init__(self, store: ZoomPreferenceStore, restarter: AppRestarter, *,
                 active_factor: float, locked: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        if not (math.isfinite(active_factor) and active_factor > 0):
            raise ValueError(f"active_factor must be positive and finite, not {active_factor!r}")
        self._store = store
        self._restarter = restarter
        self._active_factor = active_factor
        self._locked = locked
        self._display: Optional[ScreenMetrics] = None
        self._steps = self._load_steps()
        self._dismissed = self._load_dismissed()
        # Displays given a size in this session whose restart notice is due (not saved)
        self._announced: frozenset[str] = frozenset()
        self._state = self._compose()

    @property
    def state(self) -> ZoomState:
        """The interface-size state of the current display."""
        return self._state

    def set_current_display(self, metrics: ScreenMetrics) -> None:
        """The display the window is on, as the View reads it; equal metrics change nothing."""
        if metrics == self._display:
            return
        self._display = metrics
        self._update()

    def zoom_in(self) -> None:
        """One step larger for the current display; saved, applied after a restart."""
        if self._state.can_zoom_in:
            self._choose(ZOOM_LADDER.index(self._state.chosen_percent) + 1)

    def zoom_out(self) -> None:
        """One step smaller for the current display."""
        if self._state.can_zoom_out:
            self._choose(ZOOM_LADDER.index(self._state.chosen_percent) - 1)

    def reset_zoom(self) -> None:
        """Back to the default size ("Default Size") for the current display."""
        if self._state.can_reset:
            self._choose(DEFAULT_STEP)

    def accept_suggestion(self) -> None:
        """Take the size suggested for the current display."""
        if self._state.suggest_percent is not None:
            self._choose(ZOOM_LADDER.index(self._state.suggest_percent))

    def dismiss_suggestion(self) -> None:
        """Never suggest a size for the current display again."""
        if self._state.suggest_percent is None:
            return
        self._dismissed = self._dismissed | {self._display.name}
        try:
            self._store.save_dismissed_suggestions(self._dismissed)
        except Exception:
            logger.exception("Could not save the dismissed interface-size suggestions")
        self._update()

    def restart_now(self) -> None:
        """Restart to apply the chosen size; nothing happens if none is pending."""
        if not self._state.restart_required:
            return
        logger.info("Restarting to apply interface size %s", self._state.label)
        try:
            self._restarter.restart()
        except Exception:
            logger.exception("Could not restart the application")

    def postpone_restart(self) -> None:
        """Later: stop announcing the pending restart until another size is
        chosen. For this session only; Restart Now stays available."""
        if self._state.notice is not ZoomNotice.RESTART:
            return
        self._announced = self._announced - {self._display.name}
        self._update()

    def _choose(self, step: int) -> None:
        self._steps = {**self._steps, self._display.name: step}
        self._announced = self._announced | {self._display.name}
        logger.info("Interface size for %r: %d %%", self._display.name, ZOOM_LADDER[step])
        try:
            self._store.save_zoom_steps(dict(self._steps))
        except Exception:
            logger.exception("Could not save the interface size")
        self._update()

    def _update(self) -> None:
        state = self._compose()
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _compose(self) -> ZoomState:
        display = self._display
        return compose_zoom_state(
            display=display,
            saved_step=None if display is None else self._steps.get(display.name),
            active_factor=self._active_factor,
            suggestion_dismissed=display is not None and display.name in self._dismissed,
            notify_restart=display is not None and display.name in self._announced,
            locked=self._locked,
        )

    def _load_steps(self) -> dict[str, int]:
        try:
            saved = self._store.load_zoom_steps()
            steps = {name: step for name, step in saved.items()
                     if isinstance(name, str) and is_valid_step(step)}
        except Exception:
            logger.exception("Could not load the interface sizes; using the default")
            return {}
        if len(steps) != len(saved):
            logger.warning("Ignoring %d invalid saved interface size(s)", len(saved) - len(steps))
        return steps

    def _load_dismissed(self) -> frozenset[str]:
        try:
            return frozenset(name for name in self._store.load_dismissed_suggestions()
                             if isinstance(name, str))
        except Exception:
            logger.exception("Could not load the dismissed interface-size suggestions")
            return frozenset()
