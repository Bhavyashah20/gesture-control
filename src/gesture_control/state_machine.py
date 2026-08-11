from __future__ import annotations

import math
from collections import deque
from enum import Enum, auto

from . import config
from .filters import Point2Filter, apply_gain
from .gate import Gate
from .types import Click, DragEnd, DragStart, Features, Intent, Move, Point2, Scroll, Space


class State(Enum):
    DISARMED = auto()
    ARMED_IDLE = auto()
    TRACKING = auto()
    DRAG = auto()
    SCROLL = auto()


class StateMachine:
    """Pure gesture logic. Consumes Features, produces Intents. No I/O."""

    def __init__(self) -> None:
        self._gate = Gate()
        self._filter = Point2Filter()
        self._state = State.DISARMED
        self._ref: Point2 | None = None
        self._t: float | None = None
        self._pinch_closed = False
        self._pinch2_closed = False
        self._click_n: int | None = None
        self._virtual = Point2(0.0, 0.0)
        self._pinch_t0: float | None = None
        self._pinch_travel = 0.0
        self._scroll_since: float | None = None
        self._swipe_hist: deque[tuple[float, float]] = deque()
        self._swipe_last: float | None = None

    @property
    def state(self) -> State:
        return self._state

    @property
    def virtual_pos(self) -> Point2:
        return self._virtual

    def _reset_transient(self) -> None:
        self._pinch_closed = False
        self._pinch2_closed = False
        self._click_n = None
        self._ref = None
        self._t = None
        self._pinch_t0 = None
        self._pinch_travel = 0.0

    @staticmethod
    def _update_pinch(
        ratio: float, closed: bool, close_thr: float, open_thr: float
    ) -> tuple[bool, bool, bool]:
        """One hysteresis step for a single pinch channel.

        Returns (closed, pressed_this_frame, released_this_frame).
        """
        if closed:
            if ratio > open_thr:
                return False, False, True
        else:
            if ratio < close_thr:
                return True, True, False
        return closed, False, False

    def _classify_release(self, f: Features) -> list[Intent]:
        held = f.t - self._pinch_t0 if self._pinch_t0 is not None else 0.0
        if held > config.TAP_MAX_S or self._pinch_travel >= config.TAP_MAX_PX:
            return []
        return [Click(self._click_n)]

    def _detect_swipe(self, f: Features) -> list[Intent]:
        self._swipe_hist.append((f.t, f.cursor_ref.x))
        while self._swipe_hist and f.t - self._swipe_hist[0][0] > config.SWIPE_WINDOW_S:
            self._swipe_hist.popleft()

        if self._swipe_last is not None and f.t - self._swipe_last < config.SWIPE_COOLDOWN_S:
            return []
        if sum(f.fingers_up) < config.ARM_FINGERS_MIN or len(self._swipe_hist) < 2:
            return []

        t0, x0 = self._swipe_hist[0]
        elapsed = f.t - t0
        disp = f.cursor_ref.x - x0
        if elapsed < config.SWIPE_HOLD_S:
            return []
        if abs(disp) < config.SWIPE_DIST or abs(disp) / elapsed < config.SWIPE_VEL:
            return []

        self._swipe_last = f.t
        self._swipe_hist.clear()
        return [Space("right" if disp > 0.0 else "left")]

    def update(self, f: Features) -> list[Intent]:
        intents: list[Intent] = []
        armed = self._gate.update(f)

        if not armed:
            if self._state is State.DRAG:
                intents.append(DragEnd())
            self._state = State.DISARMED
            self._reset_transient()
            return intents

        ref = self._filter.filter(f.cursor_ref, f.t)

        if self._state is State.DISARMED:
            self._state = State.ARMED_IDLE
            self._ref, self._t = ref, f.t
            return intents

        dt = f.t - self._t if self._t is not None else 0.0
        dxn = ref.x - self._ref.x if self._ref is not None else 0.0
        dyn = ref.y - self._ref.y if self._ref is not None else 0.0
        self._ref, self._t = ref, f.t

        self._pinch_closed, pressed1, released1 = self._update_pinch(
            f.pinch_ratio, self._pinch_closed, config.PINCH_CLOSE, config.PINCH_OPEN
        )
        self._pinch2_closed, pressed2, released2 = self._update_pinch(
            f.pinch2_ratio, self._pinch2_closed, config.PINCH2_CLOSE, config.PINCH2_OPEN
        )
        # Index wins: a false single click is less damaging than a false
        # double, so the middle pinch is only ever consulted when the index
        # pinch is not the one that's closed.
        released = released1 if self._click_n == 1 else released2

        if self._state is State.ARMED_IDLE:
            click_n = 1 if pressed1 else 2 if pressed2 and not self._pinch_closed else None
            if click_n is not None:
                self._click_n = click_n
                self._state = State.TRACKING
                self._pinch_t0 = f.t
                self._pinch_travel = 0.0
                self._scroll_since = None
                self._swipe_hist.clear()
                return intents

            if f.fingers_up == (True, True, False, False):
                if self._scroll_since is None:
                    self._scroll_since = f.t
                elif f.t - self._scroll_since >= config.SCROLL_DWELL_S:
                    self._state = State.SCROLL
                    self._scroll_since = None
                return intents

            self._scroll_since = None
            return intents + self._detect_swipe(f)

        if self._state is State.SCROLL:
            if f.fingers_up != (True, True, False, False):
                self._state = State.ARMED_IDLE
                return intents
            px = dyn * config.SCROLL_GAIN
            if abs(px) >= config.SCROLL_MIN_PX:
                intents.append(Scroll(px))
            return intents

        if self._state is State.TRACKING:
            if released:
                self._state = State.ARMED_IDLE
                return self._classify_release(f)

            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                self._pinch_travel += math.hypot(dxp, dyp)
                intents.append(Move(dxp, dyp))

            held = f.t - self._pinch_t0 if self._pinch_t0 is not None else 0.0
            if held > config.DRAG_DWELL_S and self._pinch_travel < config.TAP_MAX_PX:
                self._state = State.DRAG
                intents.append(DragStart())
            return intents

        if self._state is State.DRAG:
            if released:
                self._state = State.ARMED_IDLE
                intents.append(DragEnd())
                return intents
            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                intents.append(Move(dxp, dyp))
            return intents

        return intents
