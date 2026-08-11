"""Coverage for QuartzActuator with a faked Quartz module.

QuartzActuator posts real macOS events, so it can't be exercised against the
real Quartz module in a test. Following the pattern in test_hud.py and
test_landmarks.py, we bypass __init__ (which imports Quartz and queries the
display) via __new__, and inject a fake standing in for self._q that records
what would have been posted instead of touching the real event stream.
"""

from gesture_control.actuator import QuartzActuator
from gesture_control.types import ButtonDown, ButtonUp, Click, Space


class FakeEvent:
    def __init__(self, kind, **extra):
        self.kind = kind
        self.__dict__.update(extra)
        self.flags = None
        self.fields = {}


class FakeQuartz:
    """Records posted events; never touches the real event stream."""

    kCGMouseButtonLeft = "left"
    kCGEventLeftMouseDown = "mouse-down"
    kCGEventLeftMouseUp = "mouse-up"
    kCGEventMouseMoved = "mouse-moved"
    kCGEventLeftMouseDragged = "mouse-dragged"
    kCGMouseEventClickState = "click-state-field"
    kCGEventFlagMaskControl = 1 << 18
    kCGHIDEventTap = "hid-tap"
    kCGScrollEventUnitPixel = "scroll-unit-pixel"

    def __init__(self):
        self.posted: list[FakeEvent] = []

    def CGEventCreateMouseEvent(self, source, kind, point, button):
        return FakeEvent("mouse", cg_kind=kind, point=point, button=button)

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return FakeEvent("key", code=code, down=down)

    def CGEventCreateScrollWheelEvent(self, source, unit, wheel_count, dy):
        return FakeEvent("scroll", dy=dy)

    def CGEventSetIntegerValueField(self, ev, field, value):
        ev.fields[field] = value

    def CGEventSetFlags(self, ev, flags):
        ev.flags = flags

    def CGEventPost(self, tap, ev):
        self.posted.append(ev)

    def CGEventGetLocation(self, ev):
        class _Loc:
            x = 100.0
            y = 200.0

        return _Loc()

    def CGEventCreate(self, source):
        return None


def _bare_actuator() -> QuartzActuator:
    """A QuartzActuator with its Quartz plumbing faked out, so this runs
    without touching real hardware or posting real events."""
    a = QuartzActuator.__new__(QuartzActuator)
    a._q = FakeQuartz()
    a.button_down = False
    a._w = 1920.0
    a._h = 1080.0
    return a


def _mouse_events(q: FakeQuartz) -> list[FakeEvent]:
    return [e for e in q.posted if e.kind == "mouse"]


def test_move_clears_flags():
    a = _bare_actuator()
    a._move_by(3.0, -4.0)
    moves = _mouse_events(a._q)
    assert len(moves) == 1
    assert moves[0].flags == 0


def test_button_down_clears_flags():
    a = _bare_actuator()
    a.apply([ButtonDown()])
    assert a.button_down is True
    moves = _mouse_events(a._q)
    assert len(moves) == 1
    assert moves[0].flags == 0


def test_button_up_clears_flags():
    a = _bare_actuator()
    a.button_down = True
    a.apply([ButtonUp()])
    assert a.button_down is False
    moves = _mouse_events(a._q)
    assert len(moves) == 1
    assert moves[0].flags == 0


def test_click_double_clears_flags():
    a = _bare_actuator()
    a.apply([Click(2)])
    moves = _mouse_events(a._q)
    assert len(moves) == 2
    for ev in moves:
        assert ev.flags == 0
        assert ev.fields[a._q.kCGMouseEventClickState] == 2


def test_space_posts_control_flagged_key_down_and_matching_key_up():
    a = _bare_actuator()
    a.apply([Space("right")])
    keys = [e for e in a._q.posted if e.kind == "key"]
    assert len(keys) == 2
    down, up = keys
    assert down.down is True and down.flags == a._q.kCGEventFlagMaskControl
    assert up.down is False and up.flags == a._q.kCGEventFlagMaskControl


def test_space_then_button_down_does_not_leak_control_flag_onto_click():
    """Regression test for the reported bug: single clicks coming out as
    right-clicks. Space posts Control-flagged key events for the arrow-key
    Space switch; a ButtonDown posted shortly after must not inherit that
    Control flag onto its mouse-down event, since Control+click is
    right-click on macOS.
    """
    a = _bare_actuator()
    a.apply([Space("right"), ButtonDown()])
    moves = _mouse_events(a._q)
    assert len(moves) == 1
    assert moves[0].flags == 0
