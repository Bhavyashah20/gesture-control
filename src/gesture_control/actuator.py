from __future__ import annotations

import subprocess
import sys
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
        # Injected as a plain attribute (same pattern as self._q) so tests
        # can swap in a fake without touching the real subprocess module.
        self._run = subprocess.run

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
        # a real Control key the user is physically holding down (or was,
        # moments ago) can leave its flag inherited onto the click, and
        # Control+click is right-click on macOS. (Space switching no longer
        # posts a CGEvent at all -- see _space_switch -- so it is not a
        # source of this leak any more, but the physical keyboard still is.)
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

    def _space_switch(self, direction: str) -> None:
        """Switch Spaces via AppleScript instead of a CGEvent.

        Every other intent in this module posts a CGEvent to
        kCGHIDEventTap -- that is the whole point of this class. Space is
        the one deliberate exception, and it looks like an oversight if you
        don't know why: it isn't.

        Confirmed live, on the machine this runs on: the real keyboard's
        Ctrl+Left/Right switches Spaces fine, and Mission Control's
        shortcuts are enabled (11 Spaces exist, 3 fullscreen, so there was
        somewhere to go). Accessibility is granted; mouse CGEvents work; no
        Secure Input holder was present. Four different CGEvent
        constructions were tried for the Space key combo -- HID source with
        a session tap, HID source with a HID tap, combined source with a
        session tap, and a real Control keydown physically held around the
        arrow keydown/up -- and none of them moved the desktop. Meanwhile a
        synthetic Cmd+Space posted the exact same way DID open Spotlight, so
        synthetic keystrokes reach the system fine in general -- this is
        specific to Mission Control's Space shortcuts. And
        `osascript -e 'tell application "System Events" to key code 124
        using control down'` DID switch the desktop. The working theory:
        Mission Control's Space shortcuts are consumed by WindowServer
        before the event-tap CGEventPost delivers to, while AppleScript's
        System Events path reaches them by a different route. Do not
        collapse this back onto CGEvent/_key -- that was the actual bug and
        it was tried and measured, not merely assumed.

        Runs subprocess.run synchronously (blocking the caller) rather than
        firing it off in a background thread or process. An osascript spawn
        costs on the order of tens of milliseconds; a blocked tick loop
        costs roughly 3 dropped camera frames per 100ms. Space switches are
        also rate-limited upstream by SWIPE_COOLDOWN_S (800ms), so this can
        run at most once every 800ms -- a one-tick (tens of ms) stall on an
        already-rare, already-deliberate gesture is an acceptable trade for
        the simplicity of a synchronous call: no thread/process bookkeeping,
        no risk of two osascript calls racing or piling up, and a failure
        path that is trivial to test and to reason about.

        Never raises: a failed or slow Space switch must not take down the
        gesture pipeline mid-gesture. Failures are reported to stderr
        instead of swallowed, since a silent failure here just looks like
        "gestures stopped working" with no clue why.
        """
        code = KEY_RIGHT_ARROW if direction == "right" else KEY_LEFT_ARROW
        script = (
            f'tell application "System Events" to key code {code} '
            "using control down"
        )
        try:
            result = self._run(
                ["osascript", "-e", script], capture_output=True, timeout=2
            )
            if result.returncode != 0:
                detail = result.stderr.decode(errors="replace").strip()
                self._report_space_failure(detail or f"exit {result.returncode}")
        except Exception as exc:
            self._report_space_failure(str(exc))

    @staticmethod
    def _report_space_failure(detail: str) -> None:
        print(
            f"gesture_control: Space switch failed ({detail}); grant "
            "System Events Automation access in System Settings > Privacy "
            "& Security > Automation",
            file=sys.stderr,
        )

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self._move_by(dx, dy)
                case Click(n):
                    # A macOS double-click is NOT one down/up pair posted with
                    # kCGMouseEventClickState = 2 -- that is not a sequence
                    # macOS recognizes as a double-click at all (this was the
                    # bug: the user had to double-click twice to open a
                    # file). It expects the full sequence: a complete click
                    # at state 1, then a complete click at state 2. So post n
                    # consecutive down/up pairs with the click-state field
                    # set to 1, 2, ... n in order, all at the same cursor
                    # position captured once before the sequence starts (the
                    # position must not drift between the n sub-clicks).
                    x, y = self._cursor()
                    for state in range(1, n + 1):
                        self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=state)
                        self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=state)
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
                    # Scroll events must explicitly clear their flags to prevent
                    # inherited Control flags from triggering accessibility screen
                    # zoom. Same flag-clearing discipline as _post_mouse.
                    self._q.CGEventSetFlags(ev, 0)
                    self._q.CGEventPost(self._q.kCGHIDEventTap, ev)
                case Space(d):
                    self._space_switch(d)

    def release_all(self) -> None:
        if self.button_down:
            x, y = self._cursor()
            self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=1)
            self.button_down = False
