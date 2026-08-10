from __future__ import annotations

from .types import Click, DragEnd, DragStart, Intent, Move, Scroll, Space

KEY_LEFT_ARROW = 123
KEY_RIGHT_ARROW = 124


class DryRunActuator:
    """Logs what would happen. Used by --dry-run and by the unit tests."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.button_down = False

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self.log.append(f"move {dx:.1f} {dy:.1f}")
                case Click(n):
                    self.log.append(f"click x{n}")
                case DragStart():
                    self.button_down = True
                    self.log.append("drag-start")
                case DragEnd():
                    self.button_down = False
                    self.log.append("drag-end")
                case Scroll(dy):
                    self.log.append(f"scroll {dy:.1f}")
                case Space(d):
                    self.log.append(f"space {d}")

    def release_all(self) -> None:
        if self.button_down:
            self.button_down = False
            self.log.append("release-all")


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
                case DragStart():
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=1)
                    self.button_down = True
                case DragEnd():
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
