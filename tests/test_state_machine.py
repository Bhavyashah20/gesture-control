import math

from gesture_control import config
from gesture_control.filters import apply_gain
from gesture_control.state_machine import State, StateMachine
from gesture_control.types import ButtonDown, ButtonUp, Click, Features, Move, Point2, Scroll, Space


def feat(t, pinch=0.9, pinch2=0.9, curl=1.71, fingers=(True, True, True, True), palm=True,
         ref=(0.5, 0.5), scale=0.20, present=True):
    """`curl` defaults to 1.71, the measured open-hand median (config.py) --
    well above INDEX_CURL_OPEN, so tests that don't care about the clutch
    never accidentally freeze."""
    return Features(
        pinch_ratio=pinch, pinch2_ratio=pinch2, index_curl_ratio=curl,
        fingers_up=fingers, palm_facing=palm,
        hand_scale=scale, cursor_ref=Point2(*ref), t=t, present=present,
    )


def arm(sm, t0=0.0):
    """Drive the machine through the arming dwell. Returns the next timestamp."""
    sm.update(feat(t0))
    sm.update(feat(t0 + 0.4))
    assert sm.state is State.TRACKING
    return t0 + 0.5


def test_starts_disarmed():
    assert StateMachine().state is State.DISARMED


def test_disarmed_emits_nothing():
    sm = StateMachine()
    assert sm.update(feat(0.0)) == []


def test_arms_after_dwell():
    sm = StateMachine()
    sm.update(feat(0.0))
    assert sm.state is State.DISARMED
    sm.update(feat(0.4))
    assert sm.state is State.TRACKING


def test_tracking_moves_the_cursor_without_a_pinch():
    """The core of the redesign: the cursor follows the hand continuously
    while armed. No pinch is required, unlike the old trackpad-mimicry
    model."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, ref=(0.9, 0.9)))
    moves = [i for i in out if isinstance(i, Move)]
    assert len(moves) == 1
    assert moves[0].dx > 0.0
    assert sm.state is State.TRACKING


def test_index_pinch_enters_pressed():
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.2))
    assert out == [ButtonDown()]
    assert sm.state is State.PRESSED


def test_pressed_emits_move_on_hand_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.1, pinch=0.2, ref=(0.6, 0.5)))
    moves = [i for i in out if isinstance(i, Move)]
    assert len(moves) == 1
    assert moves[0].dx > 0.0


def test_pinch_hysteresis_keeps_pressed_between_thresholds():
    """Between the two thresholds the pinch state must not change."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.1, pinch=0.40))
    assert sm.state is State.PRESSED
    sm.update(feat(t + 0.2, pinch=0.50))
    assert sm.state is State.TRACKING


def test_release_returns_to_tracking_and_emits_button_up():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.5, pinch=0.9))
    assert out == [ButtonUp()]
    assert sm.state is State.TRACKING


def test_losing_posture_disarms():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, present=False))
    sm.update(feat(t + 0.6, present=False))
    assert sm.state is State.DISARMED


def test_virtual_position_accumulates_moves():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, ref=(0.6, 0.5)))
    assert sm.virtual_pos.x > 0.0


def test_index_pinch_close_then_release_emits_button_down_then_up():
    """Click(1) no longer exists. A plain index pinch is a mouse button:
    down on close, up on release -- nothing else. macOS decides click vs.
    drag from the down/move/up sequence, exactly as it would for a physical
    mouse."""
    sm = StateMachine()
    t = arm(sm)
    down = sm.update(feat(t, pinch=0.2))
    assert down == [ButtonDown()]
    up = sm.update(feat(t + 0.10, pinch=0.9))
    assert up == [ButtonUp()]
    assert sm.state is State.TRACKING


def test_middle_pinch_close_emits_click_two():
    """Double-click remains its own gesture: middle-tip-to-thumb, no timing
    and no travel budget -- it fires the instant the pinch closes."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch2=0.2))
    assert out == [Click(2)]
    assert sm.state is State.TRACKING


def test_middle_pinch_never_enters_pressed():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch2=0.2))
    assert sm.state is State.TRACKING


def test_both_pinches_closed_index_closer_enters_pressed():
    """Whichever finger is actually closer to the thumb at pinch-down decides."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.10, pinch2=0.32))
    assert out == [ButtonDown()]
    assert sm.state is State.PRESSED


def test_both_pinches_closed_middle_closer_gives_click_two():
    """Whichever finger is actually closer to the thumb at pinch-down decides."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.32, pinch2=0.10))
    assert out == [Click(2)]
    assert sm.state is State.TRACKING


def test_middle_pinch_wins_even_when_index_also_reads_closed():
    """Anatomically, pinching the middle fingertip to the thumb drags the index
    along with it, so the index often reads below PINCH_CLOSE too. Values
    below are drawn from a real frame in recordings/middle_pinch.jsonl
    (t=3.776s: pinch=0.32, pinch2=0.1686) -- exactly the case that would
    turn an intended double-click into a spurious ButtonDown under fixed
    priority (index always wins whenever closed).
    """
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.32, pinch2=0.1686))
    assert out == [Click(2)]
    assert sm.state is State.TRACKING


def test_rapid_index_pinches_never_emit_click_two():
    sm = StateMachine()
    t = arm(sm)
    outs = []
    for i in range(3):
        outs += sm.update(feat(t + i * 0.20, pinch=0.2))
        outs += sm.update(feat(t + i * 0.20 + 0.08, pinch=0.9))
    assert outs == [ButtonDown(), ButtonUp()] * 3


def test_pressed_emits_moves_then_one_button_up():
    """Pinch, move, release: exactly the drag sequence macOS reads from a
    down/move/up mouse sequence. No dwell, no travel budget -- movement
    while pressed is unconditionally a drag."""
    sm = StateMachine()
    t = arm(sm)
    down = sm.update(feat(t, pinch=0.2))
    assert down == [ButtonDown()]
    mid = sm.update(feat(t + 0.05, pinch=0.2, ref=(0.6, 0.5)))
    assert any(isinstance(i, Move) for i in mid)
    end = sm.update(feat(t + 0.10, pinch=0.9))
    assert end == [ButtonUp()]
    assert sm.state is State.TRACKING


def test_pinching_does_not_read_as_curl_at_calibrated_values():
    """Calibration data point (see config.py): index_curl_ratio measures up
    to 1.39 while genuinely pinching -- comfortably above INDEX_CURL_CLOSE
    (0.95, calibrated against recordings/clutch.jsonl), so a pinch must
    never be misread as a curl -- that would freeze the cursor mid-drag
    instead of pressing the button."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.2, curl=1.39))
    assert out == [ButtonDown()]
    assert sm.state is State.PRESSED


def test_hand_vanishing_while_pressed_releases_the_button():
    """The stuck-button guard. Without this macOS keeps the button held.

    The absent frames must keep the pinch CLOSED. If they carried an open
    pinch, the ordinary release path would end the press and the watchdog
    would never be exercised.
    """
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.state is State.PRESSED
    sm.update(feat(t + 0.20, pinch=0.2, present=False))
    assert sm.state is State.PRESSED  # still held, within DISARM_S
    out = sm.update(feat(t + 0.20 + config.DISARM_S + 0.10, pinch=0.2, present=False))
    assert ButtonUp() in out
    assert sm.state is State.DISARMED


# --- The clutch: curling the index finger freezes the cursor ---
#
# Curl values below are derived from the calibrated config constants, not
# hardcoded to a specific calibration, so they stay correct across any
# future recalibration:
CURLED = config.INDEX_CURL_CLOSE - 0.05  # below CLOSE: a genuine curl
BETWEEN = (config.INDEX_CURL_CLOSE + config.INDEX_CURL_OPEN) / 2  # hysteresis band
UNCURLED = config.INDEX_CURL_OPEN + 0.05  # above OPEN: a genuine point


def test_curling_the_index_freezes_the_cursor():
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, curl=CURLED, ref=(0.9, 0.9)))
    assert out == []
    assert sm.state is State.FROZEN


def test_frozen_emits_nothing_even_as_the_hand_keeps_moving():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=CURLED, ref=(0.9, 0.9)))
    assert sm.state is State.FROZEN
    out = sm.update(feat(t + 0.05, curl=CURLED, ref=(0.1, 0.1)))
    assert out == []
    assert sm.state is State.FROZEN


def test_uncurling_resumes_tracking():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=CURLED))
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.05, curl=UNCURLED))
    assert sm.state is State.TRACKING


def test_uncurling_does_not_jump_the_cursor():
    """The whole point of the clutch: repositioning the hand while frozen
    must not produce a jump in the next Move once tracking resumes."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, ref=(0.5, 0.5)))
    sm.update(feat(t + 0.05, curl=CURLED, ref=(0.5, 0.5)))
    assert sm.state is State.FROZEN
    # Reposition the physical hand far away while frozen.
    sm.update(feat(t + 0.10, curl=CURLED, ref=(0.9, 0.9)))
    # Uncurl at the new position: resuming tracking here must not replay
    # the (0.5,0.5) -> (0.9,0.9) jump as a Move.
    out = sm.update(feat(t + 0.15, curl=UNCURLED, ref=(0.9, 0.9)))
    moves = [i for i in out if isinstance(i, Move)]
    assert moves == []
    assert sm.state is State.TRACKING


def test_curl_uses_hysteresis():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=CURLED))
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.05, curl=BETWEEN))  # between CLOSE and OPEN
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.10, curl=UNCURLED))  # above OPEN
    assert sm.state is State.TRACKING


def test_curling_while_pressed_releases_the_button_and_freezes():
    """Supersedes the old design decision ("the clutch must never release
    the button"). That decision predates the discovery that curl and pinch
    are not independent signals: curling the index brings the fingertip
    onto the thumb, which reads as a pinch geometrically -- in
    recordings/clutch.jsonl every one of 124 curled frames trips
    PINCH_CLOSE, bottoming out at pinch_ratio=0.01. Since a pinch reading
    during a curl is always spurious, holding the button through a curl
    would mean trusting exactly that spurious reading to keep the mouse
    down indefinitely -- the stuck-button failure mode this project guards
    against everywhere else. So curling while PRESSED must now release the
    button (emit ButtonUp) and enter FROZEN in the same frame, not hold
    through it.
    """
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.state is State.PRESSED
    out = sm.update(feat(t + 0.05, pinch=0.2, curl=CURLED, ref=(0.6, 0.5)))
    assert out == [ButtonUp()]
    assert sm.state is State.FROZEN


def test_uncurling_after_a_curl_release_resumes_tracking_without_reopening():
    """After a curl forces the button up and the machine into FROZEN,
    uncurling must return to plain TRACKING -- not silently reopen the
    button from residual pinch state."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.05, pinch=0.2, curl=CURLED))
    assert sm.state is State.FROZEN
    out = sm.update(feat(t + 0.10, pinch=0.9, curl=UNCURLED))
    assert out == []
    assert sm.state is State.TRACKING


def test_curling_ignores_a_spurious_pinch_reading():
    """The core clutch fix. Curling the index brings the fingertip onto the
    thumb, which is geometrically indistinguishable from a pinch --
    recordings/clutch.jsonl (index-only curling, never a real pinch) reads
    pinch_ratio as low as 0.01 on every one of its 124 curled frames, and
    pinch2_ratio below PINCH2_CLOSE on 56 of them. While curled, both pinch
    channels must be ignored entirely: no ButtonDown, no Click(2). The
    machine goes straight to FROZEN instead.
    """
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, curl=CURLED, pinch=0.01, pinch2=0.05, ref=(0.9, 0.9)))
    assert out == []
    assert sm.state is State.FROZEN


def test_curling_ignores_a_spurious_pinch_reading_while_already_frozen():
    """Same guarantee, sustained: once FROZEN, a continuing spurious pinch
    reading must not open the button on a later frame either."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=CURLED, pinch=0.01, ref=(0.9, 0.9)))
    assert sm.state is State.FROZEN
    out = sm.update(feat(t + 0.05, curl=CURLED, pinch=0.01, ref=(0.5, 0.5)))
    assert out == []
    assert sm.state is State.FROZEN


def test_genuine_pinch_still_opens_when_index_not_curled():
    """Pins the fix against over-suppression. BETWEEN sits inside the
    hysteresis band, well above INDEX_CURL_CLOSE, matching the real
    index_curl_ratio range measured during genuine pinches (1.03-1.39
    across all five pinch-containing fixtures -- see config.py). At this
    value the index reads as not-curled, so a pinch must still open
    PRESSED exactly as it did before this fix."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, pinch=0.2, curl=BETWEEN))
    assert out == [ButtonDown()]
    assert sm.state is State.PRESSED


def test_releasing_an_ordinary_pinch_never_leaves_the_cursor_frozen():
    """Traces the hysteresis-band concern raised while calibrating
    INDEX_CURL_CLOSE/OPEN: a genuine pinch measures index_curl_ratio in the
    1.03-1.39 range (see config.py) -- below INDEX_CURL_OPEN but above
    INDEX_CURL_CLOSE, i.e. inside the hysteresis band, for its entire
    duration. `curl=BETWEEN` here stands in for that band. Because curled
    only latches True below CLOSE, and this ratio never goes that low, the
    clutch's `curled` flag stays False throughout the press and release, so
    TRACKING (never FROZEN) is what follows the ButtonUp. Confirmed against
    real data too: the lowest index_curl_ratio recorded during any pinch,
    across all five pinch-containing fixtures, is 1.03 -- above CLOSE
    (0.95) -- so this is not just a synthetic case.
    """
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2, curl=BETWEEN))
    assert sm.state is State.PRESSED
    out = sm.update(feat(t + 0.05, pinch=0.9, curl=BETWEEN))
    assert out == [ButtonUp()]
    assert sm.state is State.TRACKING


# --- Scroll (unchanged behaviour, new resting-state name) ---

TWO = (True, True, False, False)
TWO_PINKY_EXTENDED = (True, True, False, True)
FULLY_OPEN = (True, True, True, True)


def test_two_finger_posture_enters_scroll_after_dwell():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    assert sm.state is State.SCROLL


def test_scroll_posture_with_extended_pinky_enters_scroll_after_dwell():
    """The relaxed scroll posture: index and middle extended, ring not extended,
    pinky ignored. Real recordings show the pinky is extended nearly always,
    so this must work: (True, True, False, True) is the actual measured gesture."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO_PINKY_EXTENDED))
    sm.update(feat(t + 0.25, fingers=TWO_PINKY_EXTENDED))
    assert sm.state is State.SCROLL


def test_fully_open_hand_does_not_enter_scroll():
    """Fully extended fingers (all True) are not a scroll gesture and must not
    trigger scroll even after dwell. The relaxation allows pinky to be
    extended, but requires ring to be curled."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=FULLY_OPEN))
    sm.update(feat(t + 0.25, fingers=FULLY_OPEN))
    assert sm.state is State.TRACKING


def test_scroll_entry_and_exit_consistency():
    """Entry and exit conditions must be logically consistent: entering scroll
    and then holding the same posture must not immediately exit. This tests
    that the entry condition (dwell to SCROLL) and exit condition (any posture
    change leaving SCROLL) are proper negations."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO_PINKY_EXTENDED))
    sm.update(feat(t + 0.25, fingers=TWO_PINKY_EXTENDED))
    assert sm.state is State.SCROLL
    # Holding the same posture must not exit.
    out = sm.update(feat(t + 0.30, fingers=TWO_PINKY_EXTENDED))
    assert sm.state is State.SCROLL


def test_brief_two_finger_flash_does_not_enter_scroll():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.10, fingers=TWO))
    assert sm.state is State.TRACKING


def test_scroll_emits_on_vertical_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    out = sm.update(feat(t + 0.35, fingers=TWO, ref=(0.5, 0.6)))
    scrolls = [i for i in out if isinstance(i, Scroll)]
    assert len(scrolls) == 1
    assert scrolls[0].dy != 0.0


def test_scroll_ignores_horizontal_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    out = sm.update(feat(t + 0.35, fingers=TWO, ref=(0.9, 0.5)))
    assert not any(isinstance(i, Scroll) for i in out)


def test_losing_two_finger_posture_leaves_scroll():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    sm.update(feat(t + 0.40))
    assert sm.state is State.TRACKING


def _sweep(sm, t, x_from, x_to, steps=8, span=0.20):
    """Drive a smooth horizontal sweep. Returns all intents emitted."""
    out = []
    for i in range(steps + 1):
        x = x_from + (x_to - x_from) * i / steps
        out += sm.update(feat(t + span * i / steps, ref=(x, 0.5)))
    return out


def test_fast_sweep_right_emits_space_right():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80)
    assert Space("right") in out


def test_fast_sweep_left_emits_space_left():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.80, 0.20)
    assert Space("left") in out


def test_one_sweep_emits_exactly_one_space():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80)
    assert len([i for i in out if isinstance(i, Space)]) == 1


def test_slow_drift_does_not_emit_space():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80, steps=40, span=4.0)
    assert not any(isinstance(i, Space) for i in out)


def test_sweep_while_pressed_does_not_emit_space():
    """A fast drag must never be read as a Space switch."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = []
    for i in range(9):
        out += sm.update(feat(t + 0.02 * i, pinch=0.2, ref=(0.2 + 0.075 * i, 0.5)))
    assert not any(isinstance(i, Space) for i in out)


# --- MOVE_DEADZONE_PX: jitter accumulator ---
#
# A plain deadzone that discards sub-threshold motion outright would also
# swallow slow, deliberate movement -- precision movement IS slow movement.
# Instead, sub-threshold per-frame pixel deltas accumulate in a residual;
# Move is emitted (for the full accumulated amount) only once the residual
# crosses MOVE_DEADZONE_PX, and the residual resets to zero on emission.
#
# `_DT`/`_DX` below drive a tiny, constant per-frame ref delta -- deliberately
# not derived from config (they describe a synthetic test scenario, not a
# governing threshold), tuned so a single frame's gained delta sits well
# under MOVE_DEADZONE_PX (verified below) and several frames are needed to
# cross it.
_DT, _DX = 0.05, 0.0002


def _step_px():
    """The gained pixel delta a single `_DT`/`_DX` step produces, computed
    directly from `apply_gain` so the tests never hardcode a pixel figure
    that would silently go stale if BASE_GAIN_PX or the accel curve changes."""
    px, _ = apply_gain(_DX, 0.0, _DT)
    return px


def test_a_single_subthreshold_step_is_smaller_than_the_deadzone():
    """Sanity check on the test fixtures above, not the implementation:
    if this fails, `_DT`/`_DX` no longer describe a sub-threshold step and
    every test below is meaningless."""
    assert _step_px() < config.MOVE_DEADZONE_PX


def _run_with_deadzone(deadzone, drive):
    """Run `drive(sm, arm_fn)` with MOVE_DEADZONE_PX temporarily overridden.

    `config.MOVE_DEADZONE_PX` is read fresh by state_machine.py on every
    frame (same pattern as every other config constant in this codebase), so
    monkeypatching it here changes real behaviour, not a mock.
    """
    old = config.MOVE_DEADZONE_PX
    config.MOVE_DEADZONE_PX = deadzone
    try:
        sm = StateMachine()
        return drive(sm)
    finally:
        config.MOVE_DEADZONE_PX = old


def test_consistent_subthreshold_movement_eventually_emits_move_equal_to_total():
    """Sub-threshold motion in a consistent direction must not be dropped:
    it accumulates until the residual crosses MOVE_DEADZONE_PX, then emits
    once for the full accumulated amount -- not the single-frame delta.

    Ground truth comes from a second run with MOVE_DEADZONE_PX forced to
    0.0, which emits a Move for every individual frame's gained delta (no
    accumulation possible with a zero threshold); summing those pins the
    exact total the accumulator is supposed to reproduce in one shot,
    without hardcoding a pixel figure that depends on filter internals.
    """

    def drive(sm):
        t = arm(sm)
        moves = []
        x = 0.5
        for i in range(1, 61):
            x += _DX
            out = sm.update(feat(t + _DT * i, ref=(x, 0.5)))
            moves += [m for m in out if isinstance(m, Move)]
            if len(moves) >= 1 and deadzone_is_real:
                break
        return moves

    # First pass: MOVE_DEADZONE_PX == 0.0, every frame fires -- sum of all
    # of them is the ground-truth total for however many frames it takes
    # the real run below to cross the deadzone.
    deadzone_is_real = False
    baseline_all = _run_with_deadzone(0.0, drive)
    assert len(baseline_all) == 61 - 1  # every one of the 60 frames fired

    deadzone_is_real = True
    real_moves = _run_with_deadzone(config.MOVE_DEADZONE_PX, drive)
    assert len(real_moves) == 1

    n = None
    # Figure out how many baseline frames the real run's single Move covers
    # by matching a running sum against the emitted total.
    running = 0.0
    for i, m in enumerate(baseline_all, start=1):
        running += m.dx
        if math.isclose(running, real_moves[0].dx, rel_tol=1e-6):
            n = i
            break
    assert n is not None, "accumulated Move did not match any prefix sum of the per-frame ground truth"
    assert n > 1  # proves it took more than one frame to accumulate
    assert math.isclose(real_moves[0].dy, sum(m.dy for m in baseline_all[:n]), rel_tol=1e-6)


def test_alternating_subthreshold_movement_emits_nothing():
    """Tremor is random in direction. Because the residual sums signed
    deltas, alternating sub-threshold motion cancels within it and never
    crosses MOVE_DEADZONE_PX -- the cursor sits genuinely still. A plain
    (non-accumulating) deadzone would also pass this particular test, but
    the consistent-direction test above is what proves accumulation, not
    this one; this one just pins the cancellation property the brief calls
    out explicitly."""

    def drive(sm):
        t = arm(sm)
        moves = []
        x = 0.5
        for i in range(1, 61):
            x = 0.5 + (_DX if i % 2 else -_DX)
            out = sm.update(feat(t + _DT * i, ref=(x, 0.5)))
            moves += [m for m in out if isinstance(m, Move)]
        return moves

    assert _run_with_deadzone(config.MOVE_DEADZONE_PX, drive) == []


def test_pressed_path_also_accumulates_subthreshold_movement():
    """The accumulator must apply during a drag too (PRESSED), not only
    plain TRACKING -- otherwise a drag would still jitter at the pixel
    level even though ordinary cursor movement doesn't."""

    def make_drive(deadzone_is_real):
        def drive(sm):
            t = arm(sm)
            sm.update(feat(t, pinch=0.2))
            assert sm.state is State.PRESSED
            moves = []
            x = 0.5
            for i in range(1, 61):
                x += _DX
                out = sm.update(feat(t + _DT * i, pinch=0.2, ref=(x, 0.5)))
                moves += [m for m in out if isinstance(m, Move)]
                if moves and deadzone_is_real:
                    break
            return moves, sm.state

        return drive

    baseline_moves, _ = _run_with_deadzone(0.0, make_drive(False))
    real_moves, real_state = _run_with_deadzone(config.MOVE_DEADZONE_PX, make_drive(True))

    assert len(real_moves) == 1
    assert real_state is State.PRESSED

    running = 0.0
    n = None
    for i, m in enumerate(baseline_moves, start=1):
        running += m.dx
        if math.isclose(running, real_moves[0].dx, rel_tol=1e-6):
            n = i
            break
    assert n is not None
    assert n > 1


def test_move_residual_resets_on_disarm():
    """A stale residual must not silently fire an oversized jump the moment
    the system re-arms.

    Differential test: run the identical frame sequence (accumulate a
    sub-threshold residual, disarm, re-arm, then one large post-rearm move)
    twice -- once with the real deadzone, once with it forced to 0.0 (so
    there is nothing to leak by construction). The filter and gate see
    exactly the same calls either way, so the two runs' final Move must be
    numerically identical if -- and only if -- the pre-disarm residual was
    actually cleared rather than carried across the re-arm.
    """

    def make_drive(deadzone_is_real):
        def drive(sm):
            t = arm(sm)
            x = 0.5
            for i in range(1, 4):
                x += _DX
                out = sm.update(feat(t + _DT * i, ref=(x, 0.5)))
                if deadzone_is_real:
                    assert out == []  # confirm residual is real but sub-threshold
            last_t = t + _DT * 3
            sm.update(feat(last_t + 0.1, present=False))
            sm.update(feat(last_t + 0.1 + config.DISARM_S + 0.05, present=False))
            assert sm.state is State.DISARMED
            t2 = arm(sm, t0=last_t + 0.1 + config.DISARM_S + 0.2)
            out = sm.update(feat(t2, ref=(0.9, 0.9)))
            return [m for m in out if isinstance(m, Move)]

        return drive

    baseline_moves = _run_with_deadzone(0.0, make_drive(False))
    real_moves = _run_with_deadzone(config.MOVE_DEADZONE_PX, make_drive(True))

    assert len(baseline_moves) == 1
    assert len(real_moves) == 1
    assert math.isclose(real_moves[0].dx, baseline_moves[0].dx, rel_tol=1e-6)
    assert math.isclose(real_moves[0].dy, baseline_moves[0].dy, rel_tol=1e-6)


def test_move_residual_resets_on_entering_frozen():
    """Same guarantee as disarm, for the clutch: repositioning the hand
    while frozen must not let a pre-freeze residual fire a jump the instant
    tracking resumes. Same differential technique as the disarm test above."""

    def make_drive(deadzone_is_real):
        def drive(sm):
            t = arm(sm)
            x = 0.5
            for i in range(1, 4):
                x += _DX
                out = sm.update(feat(t + _DT * i, ref=(x, 0.5)))
                if deadzone_is_real:
                    assert out == []  # confirm residual is real but sub-threshold
            last_t = t + _DT * 3
            sm.update(feat(last_t + 0.05, curl=CURLED, ref=(x, 0.5)))
            assert sm.state is State.FROZEN
            sm.update(feat(last_t + 0.10, curl=UNCURLED, ref=(x, 0.5)))
            assert sm.state is State.TRACKING
            out = sm.update(feat(last_t + 0.15, ref=(0.9, 0.9)))
            return [m for m in out if isinstance(m, Move)]

        return drive

    baseline_moves = _run_with_deadzone(0.0, make_drive(False))
    real_moves = _run_with_deadzone(config.MOVE_DEADZONE_PX, make_drive(True))

    assert len(baseline_moves) == 1
    assert len(real_moves) == 1
    assert math.isclose(real_moves[0].dx, baseline_moves[0].dx, rel_tol=1e-6)
    assert math.isclose(real_moves[0].dy, baseline_moves[0].dy, rel_tol=1e-6)
