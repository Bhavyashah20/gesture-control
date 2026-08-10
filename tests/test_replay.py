import json

import pytest

from gesture_control.recorder import read_session, replay, write_session
from gesture_control.types import Click, DragEnd, DragStart, HandFrame, Point3, Space


def _frames():
    a = HandFrame(
        points=tuple(Point3(i / 21, i / 42, 0.0) for i in range(21)),
        t=0.0, present=True, handedness="Right",
    )
    b = HandFrame(points=(), t=0.033, present=False, handedness="")
    return [a, b]


def test_round_trip_preserves_frames(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), _frames())
    assert read_session(str(p)) == _frames()


def test_file_is_one_json_object_per_line(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), _frames())
    lines = p.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["present"] is True


def test_replay_of_absent_frames_yields_no_intents(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), [
        HandFrame(points=(), t=i / 30, present=False, handedness="")
        for i in range(60)
    ])
    assert replay(str(p)) == []


# --- Replay fixture assertions ---
FIXTURES = "recordings"


def _replay(name):
    path = f"{FIXTURES}/{name}.jsonl"
    try:
        return replay(path)
    except FileNotFoundError:
        pytest.skip(f"fixture {path} not recorded yet")


def test_five_clicks_yields_exactly_five_single_clicks():
    clicks = [i for i in _replay("five_clicks") if isinstance(i, Click)]
    assert clicks == [Click(1)] * 5


def test_double_click_yields_one_click_two():
    clicks = [i for i in _replay("one_double_click") if isinstance(i, Click)]
    assert Click(2) in clicks
    assert len(clicks) == 2


def test_drag_yields_one_start_and_one_end():
    out = _replay("drag_a_to_b")
    assert len([i for i in out if isinstance(i, DragStart)]) == 1
    assert len([i for i in out if isinstance(i, DragEnd)]) == 1


def test_reaching_past_camera_yields_nothing():
    """Reaching past the camera must produce NO intents at all.

    Not merely no clicks. Cursor drift and stray scrolling are false positives
    too, and for something running all day they are the most irritating kind.
    Filtering to (Click, DragStart, Space) would let a Move or Scroll stream
    through unnoticed, which is the exact failure this fixture exists to catch.

    If this fails on a real recording, tune the gate. Do not weaken the
    assertion — that would discard the only evidence the system stays quiet.
    """
    assert _replay("reaching_past") == []


def test_talking_with_hands_yields_nothing():
    """Same standard: total silence while the system is not being addressed."""
    assert _replay("talking_hands") == []


def test_one_sweep_yields_exactly_one_space():
    spaces = [i for i in _replay("one_sweep") if isinstance(i, Space)]
    assert len(spaces) == 1
