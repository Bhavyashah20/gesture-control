from __future__ import annotations

from collections import deque
from enum import Enum, auto

from . import config
from .filters import Point2Filter, apply_gain
from .gate import Gate
from .types import ButtonDown, ButtonUp, Click, Features, Intent, Move, Point2, Scroll, Space


class State(Enum):
    DISARMED = auto()
    FROZEN = auto()
    TRACKING = auto()
    PRESSED = auto()
    SCROLL = auto()


class StateMachine:
    """Pure gesture logic. Consumes Features, produces Intents. No I/O.

    Direct-manipulation model (2026-08-11 redesign): while armed, the cursor
    follows the hand continuously (TRACKING). Curling the index finger
    freezes the cursor (FROZEN) so the hand can be repositioned without
    moving it -- the clutch. Pinching index-to-thumb is a plain mouse
    button: down on close, up on release (PRESSED); it no longer classifies
    click vs. drag, because macOS already does that correctly from a
    down/move/up sequence. Pinching middle-to-thumb remains its own
    gesture, an explicit Click(2), independent of PRESSED.
    """

    def __init__(self) -> None:
        self._gate = Gate()
        self._filter = Point2Filter()
        self._state = State.DISARMED
        self._ref: Point2 | None = None
        self._t: float | None = None
        self._pinch_closed = False
        self._curled = False
        self._virtual = Point2(0.0, 0.0)
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
        self._curled = False
        self._ref = None
        self._t = None

    @staticmethod
    def _update_pinch(f: Features, closed: bool) -> tuple[bool, bool, bool]:
        """One hysteresis step over the single, combined pinch state.

        Either channel closing closes the pinch; both channels must reopen
        to release it. This keeps the existing hysteresis guarantee (no
        chatter while either finger is still near the thumb) while letting
        either finger initiate a pinch -- required because pinching the
        middle fingertip to the thumb drags the index along with it, so the
        index channel alone often also reads closed during a deliberate
        middle pinch.

        Returns (closed, pressed_this_frame, released_this_frame).
        """
        if closed:
            if f.pinch_ratio > config.PINCH_OPEN and f.pinch2_ratio > config.PINCH2_OPEN:
                return False, False, True
        else:
            if f.pinch_ratio < config.PINCH_CLOSE or f.pinch2_ratio < config.PINCH2_CLOSE:
                return True, True, False
        return closed, False, False

    @staticmethod
    def _update_curl(f: Features, curled: bool) -> bool:
        """Hysteresis step for the index-curl clutch signal.

        PROVISIONAL thresholds -- see config.py's INDEX_CURL_CLOSE /
        INDEX_CURL_OPEN comment.
        """
        if curled:
            if f.index_curl_ratio > config.INDEX_CURL_OPEN:
                return False
        else:
            if f.index_curl_ratio < config.INDEX_CURL_CLOSE:
                return True
        return curled

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
            # Stuck-button watchdog: if the gate disarms while the button is
            # down (hand vanished, palm turned away, ...), release it before
            # leaving. This must survive regardless of how PRESSED was
            # entered or how long it was held.
            if self._state is State.PRESSED:
                intents.append(ButtonUp())
            self._state = State.DISARMED
            self._reset_transient()
            return intents

        ref = self._filter.filter(f.cursor_ref, f.t)

        if self._state is State.DISARMED:
            self._state = State.TRACKING
            self._ref, self._t = ref, f.t
            return intents

        dt = f.t - self._t if self._t is not None else 0.0
        dxn = ref.x - self._ref.x if self._ref is not None else 0.0
        dyn = ref.y - self._ref.y if self._ref is not None else 0.0
        self._ref, self._t = ref, f.t

        self._pinch_closed, pressed, released = self._update_pinch(f, self._pinch_closed)
        self._curled = self._update_curl(f, self._curled)

        if self._state is State.SCROLL:
            if f.fingers_up != (True, True, False, False):
                self._state = State.TRACKING
                return intents
            px = dyn * config.SCROLL_GAIN
            if abs(px) >= config.SCROLL_MIN_PX:
                intents.append(Scroll(px))
            return intents

        if self._state is State.PRESSED:
            if released:
                self._state = State.TRACKING
                intents.append(ButtonUp())
                return intents
            # Curling the index while pinched must NOT release the button --
            # the cursor keeps following the hand regardless of curl state.
            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                intents.append(Move(dxp, dyp))
            return intents

        # From here, self._state is TRACKING or FROZEN.
        if pressed:
            self._scroll_since = None
            self._swipe_hist.clear()
            # Whichever finger is actually closer to the thumb at pinch-down
            # decides the gesture -- see config.py for why.
            if f.pinch2_ratio < f.pinch_ratio:
                intents.append(Click(2))
            else:
                self._state = State.PRESSED
                intents.append(ButtonDown())
            return intents

        if self._state is State.FROZEN:
            if not self._curled:
                self._state = State.TRACKING
            return intents

        # TRACKING
        if self._curled:
            self._state = State.FROZEN
            return intents

        dxp, dyp = apply_gain(dxn, dyn, dt)
        if dxp or dyp:
            self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
            intents.append(Move(dxp, dyp))

        if f.fingers_up == (True, True, False, False):
            if self._scroll_since is None:
                self._scroll_since = f.t
            elif f.t - self._scroll_since >= config.SCROLL_DWELL_S:
                self._state = State.SCROLL
                self._scroll_since = None
            return intents

        self._scroll_since = None
        return intents + self._detect_swipe(f)
