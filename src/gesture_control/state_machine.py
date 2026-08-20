from __future__ import annotations

import math
from collections import deque
from enum import Enum, auto

from . import config
from .filters import Point2Filter, apply_gain
from .gate import Gate
from .types import ButtonDown, ButtonUp, Click, Features, Intent, Move, Point2, Scroll, Space


def _scroll_finger_shape(f: Features) -> bool:
    """Finger shape shared by scroll entry and exit: index and middle
    extended, ring not extended. The pinky is ignored (it is unreliable
    and contributes nothing to distinguishing this posture from others).
    Symmetric between entry and exit -- only the thumb-tuck threshold
    differs (see _can_enter_scroll / _can_stay_in_scroll below), the same
    way gate.py's arm/sustain checks share their finger-count condition
    but diverge on dwell."""
    return f.fingers_up[0] and f.fingers_up[1] and not f.fingers_up[2]


def _can_enter_scroll(f: Features) -> bool:
    """Strict: the thumb must be tucked below THUMB_TUCK_MAX to enter
    scroll, so a deliberate scroll gesture can never be confused with the
    thumb opening out for a middle-pinch double-click (see config.py's
    THUMB_TUCK_MAX comment)."""
    return _scroll_finger_shape(f) and f.thumb_tuck_ratio < config.THUMB_TUCK_MAX


def _swipe_finger_shape(f: Features) -> bool:
    """Exact three-finger posture for the Space-switch swipe: index, middle
    and ring extended, pinky NOT extended -- matching the macOS trackpad
    three-finger-swipe convention. Replaces the old "three or more fingers"
    gate (sum(f.fingers_up) >= ARM_FINGERS_MIN), which an open palm also
    satisfies -- and open palm is the resting hand shape, so that gate let
    ordinary armed hand movement fire a spurious Space switch.

    Measured against recordings/three_finger.jsonl (2026-08-20): finger
    detection needed no change at all -- (True, True, True, False) is
    already the dominant pattern at 267 of 448 present frames. Simulated
    against the existing fixtures, the old >= 3 rule produced spurious
    swipes in one_sweep, live_clicks, middle_pinch and reaching_past; this
    exact posture produces none in any of them. See config.py's SWIPE_VEL
    comment for the velocity threshold that had to change alongside it.

    Distinguishable from the scroll posture (_scroll_finger_shape above) by
    the ring finger: scroll needs it down, this needs it up."""
    return f.fingers_up == (True, True, True, False)


def _can_stay_in_scroll(f: Features) -> bool:
    """Loose: once in scroll, the thumb must exceed THUMB_TUCK_RELEASE --
    a much higher bar than THUMB_TUCK_MAX -- before scroll is left. A
    momentary thumb un-tuck mid-scroll must not eject the user into
    TRACKING, because TRACKING processes pinches: dropping out of SCROLL
    on a brief thumb drift let a stray pinch reading fire a click the
    user never intended (see config.py's THUMB_TUCK_RELEASE comment).
    This mirrors the arm/sustain asymmetry in gate.py, for the same
    reason -- sustaining/staying is deliberately harder to fall out of
    than entering/arming is to trigger."""
    return _scroll_finger_shape(f) and f.thumb_tuck_ratio < config.THUMB_TUCK_RELEASE


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

    Curl and pinch are mutually exclusive by construction (2026-08-11 fix):
    curling the index finger brings the fingertip onto the thumb, which
    reads as a pinch geometrically -- recordings/clutch.jsonl (index-only
    curling, never a real pinch) trips PINCH_CLOSE on every single curled
    frame, bottoming out at pinch_ratio=0.01. So the curl check runs before
    the pinch check every frame: while curled, both pinch channels are
    ignored outright, and if a pinch was already open when the curl
    engages, it is released (ButtonUp) in that same frame rather than held
    through the freeze. See config.py's INDEX_CURL_CLOSE comment.

    The three-finger swipe posture and the pinch channels are mutually
    exclusive the same way (2026-08-21 fix): a hand forming or releasing
    the swipe posture passes through configurations that read as a pinch,
    firing spurious presses partway through the gesture. While the posture
    is held, or within SWIPE_PINCH_LOCKOUT_S of when it was last held, both
    pinch channels are ignored, and an already-open pinch is released
    (ButtonUp) rather than held through -- same safety rule as the curl
    gate, same reason: never leave a button down while ignoring the
    channel that would release it. See config.py's SWIPE_PINCH_LOCKOUT_S
    comment.
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
        # Rate-scroll neutral: the vertical hand position recorded on
        # entering SCROLL. Re-recorded every entry (see config.py's
        # SCROLL_NEUTRAL_DEADZONE comment) so re-entering after
        # repositioning never inherits a stale neutral from a previous
        # visit to SCROLL.
        self._scroll_neutral: float | None = None
        # Scroll-exit debounce (see config.py's SCROLL_EXIT_S comment),
        # mirroring gate.py's `_lost_since`: set the frame the posture first
        # fails while in SCROLL, cleared the moment it passes again. SCROLL
        # is only actually left once this has run continuously for
        # SCROLL_EXIT_S -- a single frame of landmark noise on the finger or
        # thumb condition must not eject the user and force a fresh neutral.
        self._scroll_exit_since: float | None = None
        self._swipe_hist: deque[tuple[float, float]] = deque()
        self._swipe_last: float | None = None
        # Timestamp the three-finger swipe posture was last seen (including
        # this frame, if held now). Not reset on disarm, mirroring
        # _swipe_last/_swipe_hist above -- it is a timing record, not a
        # current-hold flag, so a stale value only ever makes the pinch
        # gate below more cautious, never less. See config.py's
        # SWIPE_PINCH_LOCKOUT_S comment.
        self._swipe_posture_last: float | None = None
        # Jitter accumulator (see config.py's MOVE_DEADZONE_PX comment):
        # sub-threshold per-frame pixel deltas accumulate here instead of
        # being emitted or discarded outright.
        self._move_residual_x = 0.0
        self._move_residual_y = 0.0

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
        self._scroll_neutral = None
        self._scroll_exit_since = None
        self._reset_move_residual()

    def _reset_move_residual(self) -> None:
        """Called on disarm and on every transition into FROZEN (the
        clutch) so a residual accumulated before the reset can never
        combine with fresh motion afterward to fire an oversized jump. See
        config.py's MOVE_DEADZONE_PX comment."""
        self._move_residual_x = 0.0
        self._move_residual_y = 0.0

    def _accumulate_move(self, dxp: float, dyp: float) -> list[Intent]:
        """Jitter deadzone with accumulation (see config.py's
        MOVE_DEADZONE_PX comment). Adds this frame's gained pixel delta to
        the residual; emits a Move for the full residual and resets it to
        zero once the residual's magnitude crosses MOVE_DEADZONE_PX,
        otherwise emits nothing and keeps the residual for next frame.

        Random tremor is random in direction, so it cancels within the
        residual and the cursor sits genuinely still. Consistent slow
        movement is directional, so it keeps accumulating and still emits
        -- just in coarser steps than one Move per frame. This is what
        makes the deadzone safe for precision movement, which is slow
        movement: a plain deadzone that dropped sub-threshold deltas
        outright would swallow deliberate slow motion along with tremor.
        """
        rx = self._move_residual_x + dxp
        ry = self._move_residual_y + dyp
        if math.hypot(rx, ry) < config.MOVE_DEADZONE_PX:
            self._move_residual_x, self._move_residual_y = rx, ry
            return []
        self._move_residual_x, self._move_residual_y = 0.0, 0.0
        self._virtual = Point2(self._virtual.x + rx, self._virtual.y + ry)
        return [Move(rx, ry)]

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

        Each channel's CLOSE transition additionally requires that channel's
        finger to be reasonably extended (see config.py's
        PINCH_MIN_EXTENSION comment): curling a finger brings its tip
        toward the palm, where the thumb rests, so tip-to-thumb proximity
        alone cannot tell a genuine pinch from a partial curl. This check
        applies to closing only -- the release condition above is
        untouched, so a pinch already held is never dropped just because
        the finger flexes slightly below the extension threshold.

        Returns (closed, pressed_this_frame, released_this_frame).
        """
        if closed:
            if f.pinch_ratio > config.PINCH_OPEN and f.pinch2_ratio > config.PINCH2_OPEN:
                return False, False, True
        else:
            index_can_close = (
                f.pinch_ratio < config.PINCH_CLOSE
                and f.index_curl_ratio > config.PINCH_MIN_EXTENSION
            )
            middle_can_close = (
                f.pinch2_ratio < config.PINCH2_CLOSE
                and f.middle_curl_ratio > config.PINCH2_MIN_EXTENSION
            )
            if index_can_close or middle_can_close:
                return True, True, False
        return closed, False, False

    @staticmethod
    def _update_curl(f: Features, curled: bool) -> bool:
        """Hysteresis step for the index-curl clutch signal.

        Thresholds calibrated against recordings/clutch.jsonl -- see
        config.py's INDEX_CURL_CLOSE / INDEX_CURL_OPEN comment.
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
        if not _swipe_finger_shape(f) or len(self._swipe_hist) < 2:
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
        # macOS natural-scrolling convention: the hand pushes the desktop,
        # so hand-left means desktop-right (and vice versa) -- content
        # follows the hand, exactly like a three-finger trackpad swipe with
        # natural scrolling enabled. Do NOT "fix" this back to hand-right
        # means Space-right; that reads backwards to anyone used to the
        # trackpad gesture, which is the whole point of matching it.
        return [Space("left" if disp > 0.0 else "right")]

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

        if self._state is State.DISARMED:
            # Arming requires f.present (see gate._can_arm), so this frame's
            # cursor_ref is always real here, never the sentinel.
            ref = self._filter.filter(f.cursor_ref, f.t)
            self._state = State.TRACKING
            self._ref, self._t = ref, f.t
            return intents

        if not f.present:
            # The hand is momentarily lost while still armed -- exactly what
            # the gate's DISARM_S sustain window is for (gate.py), and what
            # main.py deliberately feeds on a camera read failure.
            # features.extract returns the _ABSENT sentinel for this frame,
            # whose cursor_ref is frame-centre (0.5, 0.5), not a real hand
            # position (see features.py). It must never reach the movement
            # path: skip the One Euro filter, the ref/dt bookkeeping below,
            # and the curl/pinch channels entirely this frame, and leave the
            # current state (PRESSED, SCROLL, ...) exactly as it was -- a
            # held button stays down, a scroll's neutral stays put, and no
            # Move or Scroll is emitted for the gap.
            #
            # Clearing _ref/_t (rather than leaving them pointing at the
            # last real position) reuses the same re-seed mechanism the
            # DISARMED->TRACKING transition above relies on: dt/dxn/dyn
            # below default to 0.0 whenever _ref/_t is None, so the next
            # real frame re-anchors from wherever the hand actually is, with
            # no delta replayed for the gap, instead of jumping from the
            # stale pre-dropout position.
            self._ref, self._t = None, None
            return intents

        ref = self._filter.filter(f.cursor_ref, f.t)

        dt = f.t - self._t if self._t is not None else 0.0
        dxn = ref.x - self._ref.x if self._ref is not None else 0.0
        dyn = ref.y - self._ref.y if self._ref is not None else 0.0
        self._ref, self._t = ref, f.t

        # Curl is evaluated before pinch, every frame: curling the index
        # reads as a pinch geometrically (see class docstring), so a pinch
        # reading while curled is always spurious and must never open a new
        # press. If a real pinch was already open when the curl engages,
        # release it now rather than trust the spurious reading to hold it.
        self._curled = self._update_curl(f, self._curled)

        # Mutual exclusion between the three-finger swipe posture and the
        # pinch channels, mirroring the curl-vs-pinch and scroll-vs-double-
        # click gates above: a hand forming or releasing the swipe posture
        # passes through configurations that read as a pinch (see
        # config.py's SWIPE_PINCH_LOCKOUT_S comment). Track the last time
        # the exact posture was seen -- this frame counts, so "currently
        # held" and "recently held" are the same check -- and gate new
        # pinch closes while within the lockout window.
        if _swipe_finger_shape(f):
            self._swipe_posture_last = f.t
        swipe_locked = (
            self._swipe_posture_last is not None
            and f.t - self._swipe_posture_last < config.SWIPE_PINCH_LOCKOUT_S
        )

        if self._curled or swipe_locked:
            pressed = False
            if self._state is State.PRESSED and self._pinch_closed:
                self._pinch_closed = False
                released = True
            else:
                released = False
        else:
            self._pinch_closed, pressed, released = self._update_pinch(f, self._pinch_closed)

        if self._state is State.SCROLL:
            if _can_stay_in_scroll(f):
                self._scroll_exit_since = None
            else:
                # Reluctant to leave (see config.py's SCROLL_EXIT_S
                # comment), mirroring gate.py's own arm/disarm asymmetry:
                # start (or continue) a debounce timer instead of leaving on
                # the spot. The frame's scroll output below is computed
                # exactly as it would be with the posture satisfied -- a
                # single flickered frame must not visibly stutter, the same
                # way the gate's DISARM_S grace window does not pause cursor
                # tracking while `_can_sustain` is momentarily false. Only
                # once the posture has been absent continuously for
                # SCROLL_EXIT_S does scroll actually end, and only then is
                # the neutral cleared, so a fragment that recovers in time
                # never has its offset reset to zero.
                if self._scroll_exit_since is None:
                    self._scroll_exit_since = f.t
                elif f.t - self._scroll_exit_since >= config.SCROLL_EXIT_S:
                    self._state = State.TRACKING
                    self._scroll_neutral = None
                    self._scroll_exit_since = None
                    return intents
            # Rate-based scroll (see config.py's SCROLL_NEUTRAL_DEADZONE
            # comment): offset is the hand's current vertical position
            # relative to the neutral point recorded on entry, not a
            # frame-to-frame delta -- this is what lets a held offset keep
            # scrolling every frame with no further hand movement at all,
            # and what makes hand range irrelevant (the user holds a
            # position instead of sweeping through one).
            assert self._scroll_neutral is not None
            offset = ref.y - self._scroll_neutral
            if abs(offset) > config.SCROLL_NEUTRAL_DEADZONE:
                magnitude = abs(offset) - config.SCROLL_NEUTRAL_DEADZONE
                speed = math.copysign(magnitude, offset) * config.SCROLL_RATE_GAIN
                px = speed * dt
                if abs(px) >= config.SCROLL_MIN_PX:
                    intents.append(Scroll(px))
            return intents

        if self._state is State.PRESSED:
            if released:
                intents.append(ButtonUp())
                # A curl-forced release enters FROZEN directly (the curl
                # that caused it is already in effect); an ordinary pinch
                # release returns to plain TRACKING.
                if self._curled:
                    self._state = State.FROZEN
                    self._reset_move_residual()
                else:
                    self._state = State.TRACKING
                return intents
            dxp, dyp = apply_gain(dxn, dyn, dt)
            return intents + self._accumulate_move(dxp, dyp)

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
            self._reset_move_residual()
            return intents

        dxp, dyp = apply_gain(dxn, dyn, dt)
        intents += self._accumulate_move(dxp, dyp)

        if _can_enter_scroll(f):
            if self._scroll_since is None:
                self._scroll_since = f.t
            elif f.t - self._scroll_since >= config.SCROLL_DWELL_S:
                self._state = State.SCROLL
                self._scroll_since = None
                self._scroll_neutral = ref.y
            return intents

        self._scroll_since = None
        return intents + self._detect_swipe(f)
