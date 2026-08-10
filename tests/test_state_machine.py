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
