import math

from gesture_control import config
from gesture_control.features import extract
from gesture_control.types import HandFrame, Point3


def make_hand(scale=1.0, pinch=0.30, pinch2=None, curl=None, midcurl=None, tuck=None,
              fingers=(True, True, True, True),
              left=False, offset=(0.0, 0.0), t=0.0,
              thumb_z=0.0, wrist_z=0.0):
    """Build a synthetic right hand, palm to camera, fingers up.

    Coordinates are pre-mirror (raw camera space), so extract() will flip x.
    In raw space a right hand has its index knuckle to the RIGHT of its pinky.

    `thumb_z` / `wrist_z` are scale-relative z offsets (default 0.0, matching
    every other test in this file) used solely to test the 3D-distance fix:
    they let a test move a landmark purely in depth, with x/y held fixed, so
    a distance that ignored z would be unchanged while one that includes it
    would not.
    """
    ox, oy = offset
    pts = [Point3(0.0, 0.0, 0.0)] * 21

    def put(i, x, y, z=0.0):
        pts[i] = Point3(ox + x * scale, oy + y * scale, z * scale)

    thumb_y = 0.42 - pinch * 0.20            # thumb tip y, pinch is a ratio

    put(0, 0.50, 0.60, wrist_z)             # wrist
    put(9, 0.50, 0.40)                      # middle MCP -> hand_scale = 0.20
    put(5, 0.56, 0.42)                      # index MCP (raw: right of pinky)
    put(13, 0.47, 0.42)                     # ring MCP (between middle and pinky)
    put(17, 0.44, 0.42)                     # pinky MCP
    put(4, 0.56, thumb_y, thumb_z)          # thumb tip

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

    if curl is not None:
        # Placed directly above the wrist, at the requested distance ratio,
        # overriding whatever the `fingers` loop above set for landmark 8 --
        # so dist(wrist, index_tip) / hand_scale == curl exactly, independent
        # of `fingers`, `pinch`, and `pinch2`.
        put(8, 0.50, 0.60 - curl * 0.20)

    if midcurl is not None:
        # Placed directly above the wrist, at the requested distance ratio,
        # overriding whatever the `fingers` loop (or `pinch2`) set for
        # landmark 12 -- so dist(wrist, middle_tip) / hand_scale == midcurl
        # exactly, independent of `fingers`, `pinch`, and `pinch2`. Applied
        # after the `pinch2` override above so `midcurl` always wins if both
        # are given (mirrors `curl` overriding landmark 8 after `fingers`).
        put(12, 0.50, 0.60 - midcurl * 0.20)

    if tuck is not None:
        # Placed at a fixed offset from the (already-positioned) pinky MCP,
        # same x, following the same pattern as `curl` overriding landmark 8:
        # dist(thumb_tip, pinky_mcp) / hand_scale == tuck exactly,
        # independent of `pinch`, which only ever moves landmark 4 relative
        # to landmark 8.
        put(4, 0.44, 0.42 - tuck * 0.20)

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
    """Raw MCP x's (index 0.56, middle 0.50, ring 0.47, pinky 0.44) must each
    surface mirrored (1 - x) before being averaged: (0.44 + 0.50 + 0.53 +
    0.56) / 4 = 0.5075. A double mirror, or a mirror applied after
    averaging the raw values instead of before, would both give a different
    number."""
    f = extract(make_hand())
    assert math.isclose(f.cursor_ref.x, 0.5075, abs_tol=1e-6)


def test_cursor_ref_is_mean_of_the_four_mcp_knuckles():
    """Pins the formula itself, independent of the mirroring test above:
    cursor_ref must be the unweighted mean of landmarks 5, 9, 13, 17 (index,
    middle, ring, pinky MCP), not a single knuckle and not some other
    subset."""
    f = extract(make_hand())
    expected_x = (0.56 + 0.50 + 0.47 + 0.44) / 4  # raw, pre-mirror
    expected_x = 1.0 - expected_x  # mirror is applied per-landmark, before averaging
    expected_y = (0.42 + 0.40 + 0.42 + 0.42) / 4  # index, middle, ring, pinky MCP y's
    assert math.isclose(f.cursor_ref.x, expected_x, abs_tol=1e-6)
    assert math.isclose(f.cursor_ref.y, expected_y, abs_tol=1e-6)


def test_cursor_ref_is_palm_centroid_not_fingertip():
    """Closing the pinch (moving only the thumb tip, landmark 4) must barely
    move cursor_ref: none of its four source landmarks (5, 9, 13, 17) sit
    anywhere near the thumb or index fingertip. This is the property the
    palm centroid inherits from -- and improves on -- the single-knuckle
    design it replaced (see the spec's "cursor_ref" section): a fingertip
    translates several millimetres during a pinch, which is what makes the
    cursor jump at the exact instant of a pinch on a naive webcam pointer.
    """
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


def test_index_curl_ratio_matches_wrist_to_index_tip_distance():
    f = extract(make_hand(curl=1.71))
    assert math.isclose(f.index_curl_ratio, 1.71, abs_tol=1e-6)


def test_index_curl_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, curl=1.71))
    far = extract(make_hand(scale=0.5, curl=1.71))
    assert math.isclose(near.index_curl_ratio, far.index_curl_ratio, abs_tol=1e-6)


def test_index_curl_ratio_is_lower_when_curled_than_open():
    """dist(landmark[8], landmark[0]) / hand_scale must shrink as the index
    fingertip moves toward the wrist -- the signal the clutch depends on."""
    open_hand = extract(make_hand(curl=1.71))
    curled = extract(make_hand(curl=1.15))
    assert curled.index_curl_ratio < open_hand.index_curl_ratio


def test_middle_curl_ratio_matches_wrist_to_middle_tip_distance():
    f = extract(make_hand(midcurl=1.88))
    assert math.isclose(f.middle_curl_ratio, 1.88, abs_tol=1e-6)


def test_middle_curl_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, midcurl=1.88))
    far = extract(make_hand(scale=0.5, midcurl=1.88))
    assert math.isclose(near.middle_curl_ratio, far.middle_curl_ratio, abs_tol=1e-6)


def test_middle_curl_ratio_is_lower_when_curled_than_open():
    """dist(landmark[12], landmark[0]) / hand_scale must shrink as the middle
    fingertip moves toward the wrist -- the signal PINCH2_MIN_EXTENSION
    depends on (see config.py)."""
    open_hand = extract(make_hand(midcurl=1.88))
    curled = extract(make_hand(midcurl=0.60))
    assert curled.middle_curl_ratio < open_hand.middle_curl_ratio


def test_middle_curl_ratio_is_independent_of_pinch():
    """Closing the index-thumb pinch (moving landmark 4) must not move
    landmark 12, so middle_curl_ratio must not change with it."""
    a = extract(make_hand(pinch=0.10, midcurl=1.88))
    b = extract(make_hand(pinch=0.90, midcurl=1.88))
    assert math.isclose(a.middle_curl_ratio, b.middle_curl_ratio, abs_tol=1e-6)


def test_pinch_ratio_includes_depth_not_just_the_2d_projection():
    """MediaPipe also supplies z. If the thumb tip sits behind the index
    tip in depth (same x/y projection as a flatter pinch, but separated in
    z), a purely-2D distance is blind to that separation and under-reports
    the pinch as tighter than it physically is -- exactly the failure the
    user reported as "clicks fail at some hand orientations": rotating the
    hand moves distance into the z axis, the 2D projection shrinks, and a
    real pinch misreads as tighter (or a real non-pinch misreads as a
    pinch) than it actually is. `_dist` must be a true 3D distance so the
    reading is stable across orientation.
    """
    flat = extract(make_hand(pinch=0.30, thumb_z=0.0))
    rotated = extract(make_hand(pinch=0.30, thumb_z=0.20))
    assert rotated.pinch_ratio > flat.pinch_ratio
    # And it must match a true 3D calculation, not just "some effect of z".
    hand_scale = 0.20  # wrist(0,0) to middle MCP(0,-0.20) at scale=1.0, see put(9, ...)
    expected = math.dist((0.56, 0.42 - 0.30 * 0.20, 0.20), (0.56, 0.24, 0.0)) / hand_scale
    assert math.isclose(rotated.pinch_ratio, expected, abs_tol=1e-6)


def test_hand_scale_also_uses_3d_distance_consistently_with_pinch():
    """If `pinch_ratio`'s distance became 3D but `hand_scale`'s did not (or
    vice versa), the two would no longer be normalized against the same
    kind of measurement and every threshold calibrated against `hand_scale`
    would silently shift. Moving the wrist purely in z (x/y held fixed)
    must change `hand_scale`, proving both distances go through the same
    3D `_dist`.
    """
    flat = extract(make_hand(wrist_z=0.0))
    rotated = extract(make_hand(wrist_z=0.20))
    assert rotated.hand_scale > flat.hand_scale
    expected = math.dist((0.50, 0.60, 0.20), (0.50, 0.40, 0.0))
    assert math.isclose(rotated.hand_scale, expected, abs_tol=1e-6)


def test_thumb_tuck_ratio_matches_thumb_to_pinky_mcp_distance():
    f = extract(make_hand(tuck=0.55))
    assert math.isclose(f.thumb_tuck_ratio, 0.55, abs_tol=1e-6)


def test_thumb_tuck_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, tuck=0.55))
    far = extract(make_hand(scale=0.5, tuck=0.55))
    assert math.isclose(near.thumb_tuck_ratio, far.thumb_tuck_ratio, abs_tol=1e-6)


def test_thumb_tuck_ratio_is_lower_when_tucked_than_extended():
    """dist(landmark[4], landmark[17]) / hand_scale must shrink as the thumb
    moves toward the palm -- the signal the scroll gate depends on."""
    tucked = extract(make_hand(tuck=0.55))
    extended = extract(make_hand(tuck=0.90))
    assert tucked.thumb_tuck_ratio < extended.thumb_tuck_ratio


def test_thumb_tuck_ratio_is_independent_of_pinch():
    """Closing the index-thumb pinch moves landmark 4, but `tuck` overrides
    landmark 4's position afterward, so thumb_tuck_ratio must not change
    with `pinch`."""
    a = extract(make_hand(pinch=0.10, tuck=0.55))
    b = extract(make_hand(pinch=0.90, tuck=0.55))
    assert math.isclose(a.thumb_tuck_ratio, b.thumb_tuck_ratio, abs_tol=1e-6)


def test_index_curl_ratio_is_independent_of_pinch():
    """Closing the index-thumb pinch (moving landmark 4) must not move
    landmark 8, so index_curl_ratio must not change with it."""
    a = extract(make_hand(pinch=0.10, curl=1.71))
    b = extract(make_hand(pinch=0.90, curl=1.71))
    assert math.isclose(a.index_curl_ratio, b.index_curl_ratio, abs_tol=1e-6)
