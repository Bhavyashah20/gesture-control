from __future__ import annotations

from enum import Enum, auto

from . import config
from .filters import Point2Filter, apply_gain
from .gate import Gate
from .types import DragEnd, Features, Intent, Move, Point2


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
        self._virtual = Point2(0.0, 0.0)

    @property
    def state(self) -> State:
        return self._state

    @property
    def virtual_pos(self) -> Point2:
        return self._virtual

    def _reset_transient(self) -> None:
        self._pinch_closed = False
        self._ref = None
        self._t = None

    def _update_pinch(self, f: Features) -> tuple[bool, bool]:
        """Returns (pressed_this_frame, released_this_frame)."""
        if self._pinch_closed:
            if f.pinch_ratio > config.PINCH_OPEN:
                self._pinch_closed = False
                return False, True
        else:
            if f.pinch_ratio < config.PINCH_CLOSE:
                self._pinch_closed = True
                return True, False
        return False, False

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

        pressed, released = self._update_pinch(f)

        if self._state is State.ARMED_IDLE:
            if pressed:
                self._state = State.TRACKING
            return intents

        if self._state is State.TRACKING:
            if released:
                self._state = State.ARMED_IDLE
                return intents
            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                intents.append(Move(dxp, dyp))
            return intents

        return intents
