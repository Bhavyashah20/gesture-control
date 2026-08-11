from __future__ import annotations

from typing import Callable

from .types import ButtonDown, ButtonUp, Click, Intent, Move, Scroll, Space

KEY_LEFT_ARROW = 123
KEY_RIGHT_ARROW = 124

# How many entries `log` retains. Unbounded growth is the bug: at ~30
# ticks/second a dry-run session left running overnight would otherwise
# grow `log` without limit.
LOG_MAXLEN = 1000


class DryRunActuator:
    """Logs what would happen. Used by --dry-run and by the unit tests."""

    def __init__(self, sink: Callable[[str], None] | None = None) -> None:
        # Deliberately a plain list, not collections.deque(maxlen=...): the
        # existing tests compare `log` to a list literal (`a.log == []`),
        # which deque never equals. Capped by hand in _emit instead.
        self.log: list[str] = []
        self.button_down = False
        self._sink = sink

    def _emit(self, entry: str) -> None:
        self.log.append(entry)
        if len(self.log) > LOG_MAXLEN:
            del self.log[0]
        if self._sink is not None:
            self._sink(entry)

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self._emit(f"move {dx:.1f} {dy:.1f}")
                case Click(n):
                    self._emit(f"click x{n}")
                case ButtonDown():
                    self.button_down = True
                    self._emit("button-down")
                case ButtonUp():
                    self.button_down = False
                    self._emit("button-up")
                case Scroll(dy):
                    self._emit(f"scroll {dy:.1f}")
                case Space(d):
                    self._emit(f"space {d}")

    def release_all(self) -> None:
        if self.button_down:
            self.button_down = False
            self._emit("release-all")


def accessibility_granted() -> bool:
    """Whether this process may post synthetic events.

    Uses `CGPreflightPostEventAccess` rather than `AXIsProcessTrusted`: it asks
    the precise question this app needs answered, and it lives in Quartz, which
    is already a dependency. `AXIsProcessTrusted` would require the separate
    `pyobjc-framework-ApplicationServices` package.
    """
    import Quartz

    return bool(Quartz.CGPreflightPostEventAccess())


def request_accessibility() -> bool:
    """Ask macOS for event-posting access, returning whether it is now granted.

    Calling this is what makes the app appear in the Accessibility list at all —
    the toggle does not exist until a process has asked. Used by the startup
    preflight so the user has something to switch on.
    """
    import Quartz

    return bool(Quartz.CGRequestPostEventAccess())


class QuartzActuator:
    """Posts real events. The only module that can affect the user's machine."""

    def __init__(self) -> None:
        import Quartz

        self._q = Quartz
        self.button_down = False
        bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        self._w = float(bounds.size.width)
        self._h = float(bounds.size.height)

    def _cursor(self) -> tuple[float, float]:
        loc = self._q.CGEventGetLocation(self._q.CGEventCreate(None))
        return float(loc.x), float(loc.y)

    def _post_mouse(self, kind: int, x: float, y: float, clicks: int = 0) -> None:
        ev = self._q.CGEventCreateMouseEvent(
            None, kind, (x, y), self._q.kCGMouseButtonLeft
        )
        if clicks:
            self._q.CGEventSetIntegerValueField(
                ev, self._q.kCGMouseEventClickState, clicks
            )
        # A CGEvent created without explicit flags inherits the current
        # system modifier state. Every synthesized mouse event here is a
        # plain left-button action, so clear unconditionally: without this,
        # a Control-flagged Space key event (see _key) posted shortly before
        # a click can leave its flag inherited onto the click, and
        # Control+click is right-click on macOS.
        self._q.CGEventSetFlags(ev, 0)
        self._q.CGEventPost(self._q.kCGHIDEventTap, ev)

    def _move_by(self, dx: float, dy: float) -> None:
        x, y = self._cursor()
        nx = min(max(x + dx, 0.0), self._w - 1.0)
        ny = min(max(y + dy, 0.0), self._h - 1.0)
        kind = (
            self._q.kCGEventLeftMouseDragged
            if self.button_down
            else self._q.kCGEventMouseMoved
        )
        self._post_mouse(kind, nx, ny)

    def _key(self, code: int) -> None:
        for down in (True, False):
            ev = self._q.CGEventCreateKeyboardEvent(None, code, down)
            self._q.CGEventSetFlags(ev, self._q.kCGEventFlagMaskControl)
            self._q.CGEventPost(self._q.kCGHIDEventTap, ev)

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self._move_by(dx, dy)
                case Click(n):
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=n)
                    self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=n)
                case ButtonDown():
                    # Set the flag before posting, not after: a signal landing
                    # mid-sequence then leaves release_all() believing the
                    # button IS held (a spurious LeftMouseUp is a harmless
                    # no-op), instead of leaving a genuinely-held button with
                    # no record that it needs releasing.
                    x, y = self._cursor()
                    self.button_down = True
                    self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=1)
                case ButtonUp():
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=1)
                    self.button_down = False
                case Scroll(dy):
                    ev = self._q.CGEventCreateScrollWheelEvent(
                        None, self._q.kCGScrollEventUnitPixel, 1, int(dy)
                    )
                    self._q.CGEventPost(self._q.kCGHIDEventTap, ev)
                case Space(d):
                    self._key(KEY_RIGHT_ARROW if d == "right" else KEY_LEFT_ARROW)

    def release_all(self) -> None:
        if self.button_down:
            x, y = self._cursor()
            self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=1)
            self.button_down = False
