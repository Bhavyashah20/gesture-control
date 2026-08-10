from gesture_control.state_machine import State, StateMachine
from gesture_control.types import Features, Move, Point2


def feat(t, pinch=0.9, fingers=(True, True, True, True), palm=True,
         ref=(0.5, 0.5), scale=0.20, present=True):
    return Features(
        pinch_ratio=pinch, fingers_up=fingers, palm_facing=palm,
        hand_scale=scale, cursor_ref=Point2(*ref), t=t, present=present,
    )


def arm(sm, t0=0.0):
    """Drive the machine through the arming dwell. Returns the next timestamp."""
    sm.update(feat(t0))
    sm.update(feat(t0 + 0.4))
    assert sm.state is State.ARMED_IDLE
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
    assert sm.state is State.ARMED_IDLE


def test_armed_idle_does_not_move_the_cursor():
    """This is what makes the clutch a clutch."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, ref=(0.9, 0.9)))
    assert out == []
    assert sm.state is State.ARMED_IDLE


def test_pinch_enters_tracking():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.state is State.TRACKING


def test_tracking_emits_move_on_hand_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.1, pinch=0.2, ref=(0.6, 0.5)))
    moves = [i for i in out if isinstance(i, Move)]
    assert len(moves) == 1
    assert moves[0].dx > 0.0


def test_pinch_uses_hysteresis():
    """Between the two thresholds the pinch state must not change."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.1, pinch=0.40))
    assert sm.state is State.TRACKING
    sm.update(feat(t + 0.2, pinch=0.50))
    assert sm.state is State.ARMED_IDLE


def test_release_returns_to_armed_idle():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.5, pinch=0.9))
    assert sm.state is State.ARMED_IDLE


def test_losing_posture_disarms():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, present=False))
    sm.update(feat(t + 0.6, present=False))
    assert sm.state is State.DISARMED


def test_virtual_position_accumulates_moves():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.1, pinch=0.2, ref=(0.6, 0.5)))
    assert sm.virtual_pos.x > 0.0


from gesture_control.types import Click, DragEnd, DragStart


def test_quick_pinch_release_emits_single_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.10, pinch=0.9))
    assert out == [Click(1)]


def test_slow_release_is_not_a_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.30, pinch=0.9))
    assert out == []


def test_release_after_moving_far_is_not_a_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.05, pinch=0.2, ref=(0.75, 0.5)))
    out = sm.update(feat(t + 0.10, pinch=0.9))
    assert not any(isinstance(i, Click) for i in out)


def test_two_quick_taps_emit_click_two():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.update(feat(t + 0.08, pinch=0.9)) == [Click(1)]
    sm.update(feat(t + 0.20, pinch=0.2))
    assert sm.update(feat(t + 0.28, pinch=0.9)) == [Click(2)]


def test_slow_second_tap_is_a_fresh_single_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.update(feat(t + 0.08, pinch=0.9)) == [Click(1)]
    sm.update(feat(t + 1.00, pinch=0.2))
    assert sm.update(feat(t + 1.08, pinch=0.9)) == [Click(1)]


def test_triple_tap_does_not_emit_click_three():
    sm = StateMachine()
    t = arm(sm)
    for i in range(3):
        sm.update(feat(t + i * 0.20, pinch=0.2))
        out = sm.update(feat(t + i * 0.20 + 0.08, pinch=0.9))
        assert out[0].n in (1, 2)


def test_holding_pinch_still_starts_a_drag():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.45, pinch=0.2))
    assert DragStart() in out
    assert sm.state is State.DRAG


def test_drag_emits_moves_then_one_drag_end():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.45, pinch=0.2))
    mid = sm.update(feat(t + 0.55, pinch=0.2, ref=(0.6, 0.5)))
    assert any(isinstance(i, Move) for i in mid)
    end = sm.update(feat(t + 0.70, pinch=0.9))
    assert end == [DragEnd()]
    assert sm.state is State.ARMED_IDLE


def test_moving_before_the_dwell_prevents_a_drag():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.10, pinch=0.2, ref=(0.80, 0.5)))
    out = sm.update(feat(t + 0.50, pinch=0.2))
    assert not any(isinstance(i, DragStart) for i in out)
    assert sm.state is State.TRACKING


def test_hand_vanishing_mid_drag_releases_the_button():
    """The stuck-button guard. Without this macOS keeps the button held.

    The absent frames must keep the pinch CLOSED. If they carried an open
    pinch, the ordinary release path would end the drag and the watchdog
    would never be exercised.
    """
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.45, pinch=0.2))
    assert sm.state is State.DRAG
    sm.update(feat(t + 0.60, pinch=0.2, present=False))
    assert sm.state is State.DRAG  # still held, within DISARM_S
    out = sm.update(feat(t + 1.20, pinch=0.2, present=False))
    assert DragEnd() in out
    assert sm.state is State.DISARMED
