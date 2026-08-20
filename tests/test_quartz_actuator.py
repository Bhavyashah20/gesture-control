"""Coverage for QuartzActuator with a faked Quartz module.

QuartzActuator posts real macOS events, so it can't be exercised against the
real Quartz module in a test. Following the pattern in test_hud.py and
test_landmarks.py, we bypass __init__ (which imports Quartz and queries the
display) via __new__, and inject a fake standing in for self._q that records
what would have been posted instead of touching the real event stream.

Space switching is the one exception: it shells out to `osascript` instead of
posting a CGEvent (see QuartzActuator._space_switch's docstring for why).
Tests below inject a fake subprocess runner for it and must never invoke the
real `osascript`.
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


class FakeRun:
    """Stands in for subprocess.run: records calls, never spawns a process."""

    def __init__(self, returncode: int = 0, exc: Exception | None = None):
        self.calls: list[tuple[list, dict]] = []
        self.returncode = returncode
        self._exc = exc

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self._exc is not None:
            raise self._exc
        return _FakeCompleted(self.returncode)


class _FakeCompleted:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = b""


def _bare_actuator() -> QuartzActuator:
    """A QuartzActuator with its Quartz plumbing faked out, so this runs
    without touching real hardware or posting real events."""
    a = QuartzActuator.__new__(QuartzActuator)
    a._q = FakeQuartz()
    a.button_down = False
    a._w = 1920.0
    a._h = 1080.0
    a._run = FakeRun()
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


def test_click_single_posts_one_down_up_pair_at_state_one():
    """`Click(1)` is unchanged: one down/up pair, click-state 1."""
    a = _bare_actuator()
    a.apply([Click(1)])
    moves = _mouse_events(a._q)
    assert len(moves) == 2
    assert [e.cg_kind for e in moves] == [
        a._q.kCGEventLeftMouseDown,
        a._q.kCGEventLeftMouseUp,
    ]
    for ev in moves:
        assert ev.flags == 0
        assert ev.fields[a._q.kCGMouseEventClickState] == 1


def test_click_double_posts_a_real_macos_double_click_sequence():
    """`Click(2)` must be a valid macOS double-click: a full click at
    click-state 1 followed by a full click at click-state 2 -- NOT a single
    down/up pair posted with click-state 2, which macOS does not recognize
    as a double-click at all (that was the bug: the user had to
    double-click twice to open a file). Asserts the exact four-event
    sequence, all at the same cursor position captured once up front, all
    with flags cleared.
    """
    a = _bare_actuator()
    a.apply([Click(2)])
    moves = _mouse_events(a._q)
    assert len(moves) == 4
    assert [e.cg_kind for e in moves] == [
        a._q.kCGEventLeftMouseDown,
        a._q.kCGEventLeftMouseUp,
        a._q.kCGEventLeftMouseDown,
        a._q.kCGEventLeftMouseUp,
    ]
    assert [e.fields[a._q.kCGMouseEventClickState] for e in moves] == [1, 1, 2, 2]
    for ev in moves:
        assert ev.flags == 0
        assert ev.point == (100.0, 200.0)


def test_space_right_invokes_osascript_with_key_code_124_and_control_down():
    """Replaces test_space_posts_control_flagged_key_down_and_matching_key_up.

    That test asserted the old, broken behaviour: Space posting a
    Control-flagged CGEvent key down/up pair via _key. Measured live, that
    CGEvent path never actually switches Spaces (Mission Control's shortcuts
    are consumed by WindowServer before the event tap delivers to them), so
    Space now shells out to `osascript` instead -- this test asserts that
    routing rather than the CGEvent sequence.
    """
    a = _bare_actuator()
    a.apply([Space("right")])
    assert len(a._q.posted) == 0  # no CGEvent touched at all
    assert len(a._run.calls) == 1
    args, kwargs = a._run.calls[0]
    assert args[0] == "osascript"
    joined = " ".join(args)
    assert "key code 124" in joined
    assert "using control down" in joined


def test_space_left_invokes_osascript_with_key_code_123():
    a = _bare_actuator()
    a.apply([Space("left")])
    assert len(a._run.calls) == 1
    args, _ = a._run.calls[0]
    joined = " ".join(args)
    assert "key code 123" in joined
    assert "using control down" in joined


def test_space_switch_failure_does_not_raise_out_of_apply():
    """A failed osascript call (non-zero exit) must never take down the
    gesture pipeline mid-gesture."""
    a = _bare_actuator()
    a._run = FakeRun(returncode=1)
    a.apply([Space("right")])  # must not raise


def test_space_switch_timeout_does_not_raise_out_of_apply():
    import subprocess

    a = _bare_actuator()
    a._run = FakeRun(exc=subprocess.TimeoutExpired(cmd="osascript", timeout=2))
    a.apply([Space("right")])  # must not raise


def test_space_switch_failure_prints_actionable_message_to_stderr(capsys):
    a = _bare_actuator()
    a._run = FakeRun(returncode=1)
    a.apply([Space("right")])
    err = capsys.readouterr().err
    assert err.strip() != ""


def test_space_then_button_down_does_not_touch_mouse_flags():
    """Regression test for the original reported bug: single clicks coming
    out as right-clicks because a Control-flagged Space CGEvent leaked its
    flag onto a mouse-down posted shortly after. Space no longer posts any
    CGEvent at all, so there is nothing to leak; this pins that a ButtonDown
    following Space still posts a clean, flag-cleared mouse-down.
    """
    a = _bare_actuator()
    a.apply([Space("right"), ButtonDown()])
    moves = _mouse_events(a._q)
    assert len(moves) == 1
    assert moves[0].flags == 0


def test_scroll_clears_flags():
    """Scroll events are built with CGEventCreateScrollWheelEvent and must
    explicitly clear their flags to prevent inherited Control flags from
    triggering accessibility screen zoom on macOS.
    """
    from gesture_control.types import Scroll

    a = _bare_actuator()
    a.apply([Scroll(dy=50)])
    scrolls = [e for e in a._q.posted if e.kind == "scroll"]
    assert len(scrolls) == 1
    assert scrolls[0].flags == 0


def test_space_then_scroll_does_not_touch_scroll_flags():
    """Regression test for the original concern (Control-flagged Space
    CGEvents leaking onto a following Scroll and triggering accessibility
    screen zoom). Space no longer posts any CGEvent, so there is nothing to
    leak; this pins that a Scroll following Space still posts with flags
    cleared.
    """
    from gesture_control.types import Scroll

    a = _bare_actuator()
    a.apply([Space("right"), Scroll(dy=50)])
    scrolls = [e for e in a._q.posted if e.kind == "scroll"]
    assert len(scrolls) == 1
    assert scrolls[0].flags == 0
