from gesture_control.hud import Hud, state_label
from gesture_control.state_machine import State


def test_every_state_has_a_label():
    for s in State:
        assert state_label(s, present=True)


def test_labels_are_lowercase_sentence_case():
    for s in State:
        label = state_label(s, present=True)
        assert label == label.lower()


def test_absent_hand_is_flagged_while_armed():
    assert state_label(State.ARMED_IDLE, present=False) != state_label(
        State.ARMED_IDLE, present=True
    )


def test_disarmed_label_ignores_presence():
    assert state_label(State.DISARMED, present=False) == state_label(
        State.DISARMED, present=True
    )


class _FakeLabel:
    def __init__(self):
        self.cfg = {}

    def config(self, **kw):
        self.cfg.update(kw)


class _FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn):
        self.scheduled.append((ms, fn))


def _bare_hud(on_tick, on_error=None):
    """A Hud with its Tk plumbing faked out, so these run without a display."""
    h = Hud.__new__(Hud)
    h._on_tick = on_tick
    h._tick_ms = 10
    h._on_error = on_error
    h._running = True
    h._root = _FakeRoot()
    h._label = _FakeLabel()
    return h


def test_tick_reschedules_while_running():
    h = _bare_hud(lambda: None)
    h._tick()
    assert len(h._root.scheduled) == 1


def test_tick_does_not_reschedule_after_on_tick_stops_it():
    """A pipeline step that stops the hud must not leave a pending callback.

    Rescheduling after stop() has destroyed the root raises TclError.
    """
    holder = {}
    holder["h"] = None

    def stopper():
        holder["h"]._running = False

    h = _bare_hud(stopper)
    holder["h"] = h
    h._tick()
    assert h._root.scheduled == []


def test_on_tick_exception_stops_the_loop_and_shows_the_error():
    """A dead pipeline must not leave a healthy-looking hud."""

    def boom():
        raise RuntimeError("pipeline exploded")

    h = _bare_hud(boom)
    h._tick()
    assert h._running is False
    assert h._root.scheduled == []
    assert "error" in h._label.cfg["text"]


def test_on_error_callback_fires_when_on_tick_raises():
    """A pipeline exception must not leave a button held with no release path.

    _fail() deliberately keeps the window open (so the user can see what
    happened), which means mainloop() never returns and the caller's
    `finally: shutdown()` never runs. on_error is the only remaining path
    back to actuator.release_all() short of the user pressing Esc.
    """
    calls = []

    def boom():
        raise RuntimeError("pipeline exploded")

    h = _bare_hud(boom, on_error=lambda: calls.append(1))
    h._tick()
    assert calls == [1]
    assert h._running is False
