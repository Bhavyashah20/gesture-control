from gesture_control import config
from gesture_control.main import MoveCoalescer


class _FakeClock:
    """A controllable clock: advances only when the test tells it to."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_consecutive_moves_are_not_printed_individually():
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=_FakeClock())
    for _ in range(5):
        c.feed("move 1.0 2.0")
    assert out == []


def test_a_non_move_entry_flushes_the_pending_moves_first():
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=_FakeClock())
    for _ in range(5):
        c.feed("move 1.0 2.0")
    c.feed("click x1")
    assert out == ["move x5", "click x1"]


def test_non_move_entries_print_immediately_every_time():
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=_FakeClock())
    c.feed("click x1")
    c.feed("click x2")
    c.feed("button-down")
    assert out == ["click x1", "click x2", "button-down"]


def test_a_long_run_of_moves_flushes_on_its_own_after_the_timeout():
    clock = _FakeClock()
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=clock)
    c.feed("move 1.0 2.0")
    clock.t = config.DRY_RUN_FLUSH_S + 0.01
    c.feed("move 1.0 2.0")
    assert out == ["move x1"]


def test_flush_emits_the_final_pending_count():
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=_FakeClock())
    c.feed("move 1.0 2.0")
    c.feed("move 1.0 2.0")
    c.flush()
    assert out == ["move x2"]


def test_flush_is_a_noop_with_nothing_pending():
    out: list[str] = []
    c = MoveCoalescer(out.append, clock=_FakeClock())
    c.flush()
    assert out == []
    c.feed("click x1")
    c.flush()
    assert out == ["click x1"]  # flush after a non-move entry adds nothing more
