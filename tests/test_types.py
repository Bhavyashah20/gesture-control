from gesture_control.types import (
    Point2, Point3, HandFrame, Features, Move, Click, DragStart, DragEnd,
    Scroll, Space,
)
from gesture_control import config


def test_points_are_tuples():
    assert Point2(1.0, 2.0) == (1.0, 2.0)
    assert Point3(1.0, 2.0, 3.0).z == 3.0


def test_hand_frame_absent_has_no_points():
    f = HandFrame(points=(), t=0.5, present=False, handedness="")
    assert f.present is False
    assert f.points == ()


def test_features_carry_four_fingers():
    f = Features(
        pinch_ratio=0.5, fingers_up=(True, True, False, False), palm_facing=True,
        hand_scale=0.2, cursor_ref=Point2(0.5, 0.5), t=1.0, present=True,
    )
    assert len(f.fingers_up) == 4


def test_intents_are_comparable_by_value():
    assert Move(1.0, 2.0) == Move(1.0, 2.0)
    assert Click(2) != Click(1)
    assert DragStart() == DragStart()
    assert DragEnd() == DragEnd()
    assert Scroll(3.0) == Scroll(3.0)
    assert Space("right") != Space("left")


def test_pinch_thresholds_have_hysteresis_gap():
    assert config.PINCH_CLOSE < config.PINCH_OPEN


def test_gate_dwells_are_asymmetric():
    assert config.DISARM_S > config.ARM_DWELL_S
