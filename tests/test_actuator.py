from gesture_control.actuator import DryRunActuator
from gesture_control.types import Click, DragEnd, DragStart, Move, Scroll, Space


def test_dry_run_logs_each_intent():
    a = DryRunActuator()
    a.apply([Move(1.0, 2.0), Click(1)])
    assert len(a.log) == 2
    assert "move" in a.log[0]
    assert "click" in a.log[1]


def test_dry_run_distinguishes_single_and_double_click():
    a = DryRunActuator()
    a.apply([Click(1), Click(2)])
    assert a.log[0] != a.log[1]


def test_dry_run_tracks_button_state():
    a = DryRunActuator()
    a.apply([DragStart()])
    assert a.button_down is True
    a.apply([DragEnd()])
    assert a.button_down is False


def test_release_all_is_idempotent():
    a = DryRunActuator()
    a.apply([DragStart()])
    a.release_all()
    a.release_all()
    assert a.button_down is False
    assert a.log.count("release-all") == 1


def test_release_all_does_nothing_when_button_is_up():
    a = DryRunActuator()
    a.release_all()
    assert a.log == []


def test_all_intent_types_are_handled():
    a = DryRunActuator()
    a.apply([Move(0, 0), Click(1), DragStart(), Move(1, 1), DragEnd(),
             Scroll(5.0), Space("right"), Space("left")])
    assert len(a.log) == 8
