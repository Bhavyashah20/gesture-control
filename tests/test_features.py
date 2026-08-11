import math

from gesture_control import config
from gesture_control.features import extract
from gesture_control.types import HandFrame, Point3


def make_hand(scale=1.0, pinch=0.30, pinch2=None, fingers=(True, True, True, True),
              left=False, offset=(0.0, 0.0), t=0.0):
    """Build a synthetic right hand, palm to camera, fingers up.

    Coordinates are pre-mirror (raw camera space), so extract() will flip x.
    In raw space a right hand has its index knuckle to the RIGHT of its pinky.
    """
    ox, oy = offset
    pts = [Point3(0.0, 0.0, 0.0)] * 21

    def put(i, x, y):
        pts[i] = Point3(ox + x * scale, oy + y * scale, 0.0)

    thumb_y = 0.42 - pinch * 0.20            # thumb tip y, pinch is a ratio

    put(0, 0.50, 0.60)                      # wrist
    put(9, 0.50, 0.40)                      # middle MCP -> hand_scale = 0.20
    put(5, 0.56, 0.42)                      # index MCP (raw: right of pinky)
    put(17, 0.44, 0.42)                     # pinky MCP
    put(4, 0.56, thumb_y)                   # thumb tip

    for idx, (pip, tip) in enumerate([(6, 8), (10, 12), (14, 16), (18, 20)]):
        base_x = 0.56 - idx * 0.04
        put(pip, base_x, 0.34)
        put(tip, base_x, 0.24 if fingers[idx] else 0.36)

    if pinch2 is not None:
        # Placed at a fixed offset from the (already-positioned) thumb tip,
        # same x, so dist(thumb, middle_tip) / hand_scale == pinch2 exactly
        # (hand_scale in raw units is 0.20) -- independent of `pinch`, which
        # only ever moves landmark 4 relative to landmark 8.
        put(12, 0.56, thumb_y - pinch2 * 0.20)

    if left:
        pts = [Point3(1.0 - p.x, p.y, p.z) for p in pts]

    return HandFrame(points=tuple(pts), t=t, present=True,
                     handedness="Left" if left else "Right")


def test_absent_frame_yields_absent_features():
    f = extract(HandFrame(points=(), t=1.0, present=False, handedness=""))
    assert f.present is False
    assert f.t == 1.0


def test_hand_scale_is_wrist_to_middle_knuckle():
    f = extract(make_hand())
    assert math.isclose(f.hand_scale, 0.20, abs_tol=1e-6)


def test_pinch_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, pinch=0.30))
    far = extract(make_hand(scale=0.5, pinch=0.30))
    assert math.isclose(near.pinch_ratio, far.pinch_ratio, abs_tol=1e-6)


def test_pinch_ratio_tracks_thumb_distance():
    """Higher `pinch` means more pinched, so it must yield a LOWER ratio."""
    open_hand = extract(make_hand(pinch=0.10))
    closed = extract(make_hand(pinch=0.90))
    assert open_hand.pinch_ratio > closed.pinch_ratio


def test_pinch2_ratio_matches_thumb_to_middle_tip_distance():
    f = extract(make_hand(pinch2=0.42))
    assert math.isclose(f.pinch2_ratio, 0.42, abs_tol=1e-6)


def test_pinch2_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, pinch2=0.30))
    far = extract(make_hand(scale=0.5, pinch2=0.30))
    assert math.isclose(near.pinch2_ratio, far.pinch2_ratio, abs_tol=1e-6)


def test_pinch2_ratio_is_independent_of_index_pinch():
    """pinch2_ratio must track the middle fingertip, not the index tip."""
    a = extract(make_hand(pinch=0.10, pinch2=0.50))
    b = extract(make_hand(pinch=0.90, pinch2=0.50))
    assert math.isclose(a.pinch2_ratio, b.pinch2_ratio, abs_tol=1e-6)
    assert not math.isclose(a.pinch_ratio, b.pinch_ratio, abs_tol=1e-2)


def test_finger_extension_detected_per_finger():
    f = extract(make_hand(fingers=(True, True, False, False)))
    assert f.fingers_up == (True, True, False, False)


def test_mirroring_applied_exactly_once():
    """Raw index MCP at x=0.56 must surface as 1 - 0.56 = 0.44."""
    f = extract(make_hand())
    assert math.isclose(f.cursor_ref.x, 0.44, abs_tol=1e-6)


def test_cursor_ref_is_index_knuckle_not_fingertip():
    """Closing the pinch must barely move cursor_ref."""
    a = extract(make_hand(pinch=0.90))
    b = extract(make_hand(pinch=0.05))
    moved = math.dist(a.cursor_ref, b.cursor_ref)
    assert moved < 1e-9


def test_palm_facing_true_for_right_hand_toward_camera():
    assert extract(make_hand()).palm_facing is True


def test_palm_facing_true_for_left_hand_toward_camera():
    assert extract(make_hand(left=True)).palm_facing is True


def test_cursor_ref_translates_with_the_hand():
    a = extract(make_hand())
    b = extract(make_hand(offset=(0.10, 0.0)))
    assert b.cursor_ref.x < a.cursor_ref.x  # mirrored: raw +x is user -x
