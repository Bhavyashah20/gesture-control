from gesture_control import config
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
    """PROVISIONAL calibration data point (see config.py): index_curl_ratio
    measures ~1.39 while genuinely pinching, well above INDEX_CURL_CLOSE
    (1.15), so a pinch must never be misread as a curl -- that would freeze
    the cursor mid-drag instead of pressing the button."""
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


def test_curling_the_index_freezes_the_cursor():
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, curl=1.10, ref=(0.9, 0.9)))
    assert out == []
    assert sm.state is State.FROZEN


def test_frozen_emits_nothing_even_as_the_hand_keeps_moving():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=1.10, ref=(0.9, 0.9)))
    assert sm.state is State.FROZEN
    out = sm.update(feat(t + 0.05, curl=1.10, ref=(0.1, 0.1)))
    assert out == []
    assert sm.state is State.FROZEN


def test_uncurling_resumes_tracking():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=1.10))
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.05, curl=1.71))
    assert sm.state is State.TRACKING


def test_uncurling_does_not_jump_the_cursor():
    """The whole point of the clutch: repositioning the hand while frozen
    must not produce a jump in the next Move once tracking resumes."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, ref=(0.5, 0.5)))
    sm.update(feat(t + 0.05, curl=1.10, ref=(0.5, 0.5)))
    assert sm.state is State.FROZEN
    # Reposition the physical hand far away while frozen.
    sm.update(feat(t + 0.10, curl=1.10, ref=(0.9, 0.9)))
    # Uncurl at the new position: resuming tracking here must not replay
    # the (0.5,0.5) -> (0.9,0.9) jump as a Move.
    out = sm.update(feat(t + 0.15, curl=1.71, ref=(0.9, 0.9)))
    moves = [i for i in out if isinstance(i, Move)]
    assert moves == []
    assert sm.state is State.TRACKING


def test_curl_uses_hysteresis():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, curl=1.10))
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.05, curl=1.20))  # between CLOSE and OPEN
    assert sm.state is State.FROZEN
    sm.update(feat(t + 0.10, curl=1.35))  # above OPEN
    assert sm.state is State.TRACKING


def test_curling_while_pressed_does_not_release_the_button():
    """Non-negotiable per the design: freezing the cursor must not release
    the button. Curling the index while pinched keeps the button down, and
    the cursor keeps following the hand regardless of curl."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.state is State.PRESSED
    out = sm.update(feat(t + 0.05, pinch=0.2, curl=1.10, ref=(0.6, 0.5)))
    assert not any(isinstance(i, ButtonUp) for i in out)
    assert sm.state is State.PRESSED
    assert any(isinstance(i, Move) for i in out)


def test_curling_while_pressed_then_releasing_still_emits_button_up():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.05, pinch=0.2, curl=1.10))
    assert sm.state is State.PRESSED
    out = sm.update(feat(t + 0.10, pinch=0.9, curl=1.10))
    assert out == [ButtonUp()]


# --- Scroll (unchanged behaviour, new resting-state name) ---

TWO = (True, True, False, False)


def test_two_finger_posture_enters_scroll_after_dwell():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
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
