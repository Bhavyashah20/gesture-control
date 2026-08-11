from gesture_control import preview
from gesture_control.state_machine import State
from gesture_control.types import Click, DragEnd, DragStart, Move, Point3, Scroll, Space


def test_landmark_to_pixel_mirrors_x():
    x, _ = preview.landmark_to_pixel(Point3(0.25, 0.75, 0.0), 100, 200)
    assert x == 75  # (1.0 - 0.25) * 100


def test_landmark_to_pixel_does_not_mirror_y():
    _, y = preview.landmark_to_pixel(Point3(0.25, 0.75, 0.0), 100, 200)
    assert y == 150  # 0.75 * 200, untouched


def test_landmark_to_pixel_left_edge_maps_toward_mirrored_right_edge():
    """A landmark near the camera's left (x=0) must land near the mirrored
    display's right edge, since the display copy is flipped but the tracker's
    raw landmarks are not."""
    x, _ = preview.landmark_to_pixel(Point3(0.0, 0.5, 0.0), 640, 480)
    assert x == 640


def test_landmark_to_pixel_right_edge_maps_toward_mirrored_left_edge():
    x, _ = preview.landmark_to_pixel(Point3(1.0, 0.5, 0.0), 640, 480)
    assert x == 0


def test_state_colors_cover_every_state():
    for s in State:
        assert s in preview.STATE_COLORS_BGR


def test_state_colors_are_valid_bgr_tuples():
    for s in State:
        bgr = preview.STATE_COLORS_BGR[s]
        assert len(bgr) == 3
        assert all(0 <= c <= 255 for c in bgr)


def test_recent_intent_distinguishes_click_counts():
    single = preview.recent_intent_text(Click(1), elapsed_s=0.1)
    double = preview.recent_intent_text(Click(2), elapsed_s=0.1)
    assert single != double
    assert single == "click x1"
    assert double == "click x2"


def test_recent_intent_shows_other_notable_intents():
    assert preview.recent_intent_text(DragStart(), elapsed_s=0.1) == "drag start"
    assert preview.recent_intent_text(DragEnd(), elapsed_s=0.1) == "drag end"
    assert preview.recent_intent_text(Space("right"), elapsed_s=0.1) == "space right"


def test_recent_intent_returns_none_once_window_elapses():
    stale = preview.RECENT_INTENT_WINDOW_S + 0.01
    assert preview.recent_intent_text(Click(1), elapsed_s=stale) is None


def test_recent_intent_returns_none_for_no_intent():
    assert preview.recent_intent_text(None, elapsed_s=0.0) is None


def test_move_is_not_a_notable_intent():
    """Move fires every frame while tracking; treating it as notable would
    permanently blank out real clicks the instant the hand moves again."""
    assert preview.intent_label(Move(1.0, 2.0)) is None


def test_scroll_is_a_notable_intent():
    assert preview.intent_label(Scroll(12.0)) is not None
