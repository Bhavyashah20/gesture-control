from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import time
from typing import Any, Callable, NamedTuple

from . import config
from .actuator import DryRunActuator, QuartzActuator, accessibility_granted, request_accessibility
from .capture import Camera
from .features import extract
from .hud import Hud
from .landmarks import DEFAULT_MODEL_PATH, HandTracker, MODEL_URL
from .recorder import write_session
from .state_machine import State, StateMachine
from .types import Features, HandFrame, Intent


class MoveCoalescer:
    """Collapses consecutive `move` log lines into a single `move xN` summary.

    --dry-run posts a `move` roughly every camera tick (~30/s). Printed one
    per line, a click or drag event scrolls past and off screen almost
    instantly, which is what made a working double-click look "broken" —
    11 of 12 taps had in fact registered. Every non-move entry still prints
    immediately, on its own line; only runs of `move` get folded together.

    Pure bookkeeping (an injected `emit` and `clock`, no I/O of its own) so
    it's testable without a running pipeline; `main()` is what wires it to
    `print` and `time.monotonic`.
    """

    def __init__(
        self, emit: Callable[[str], None], clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._emit = emit
        self._clock = clock
        self._count = 0
        self._since: float | None = None

    def feed(self, entry: str) -> None:
        if entry.startswith("move "):
            now = self._clock()
            if self._count and now - self._since >= config.DRY_RUN_FLUSH_S:
                self.flush()
            if self._count == 0:
                self._since = now
            self._count += 1
            return
        self.flush()
        self._emit(entry)

    def flush(self) -> None:
        if self._count:
            self._emit(f"move x{self._count}")
            self._count = 0
            self._since = None


class TickResult(NamedTuple):
    """Everything one pipeline step produced, for whichever driver is running.

    `image` is the RAW camera frame (or None if the read failed) — the exact
    frame the tracker saw. Never mirror this one; `preview.py` makes its own
    mirrored copy for display. See `features._palm_facing` for why the
    tracker must never see a flipped frame.
    """

    image: Any
    frame: HandFrame
    features: Features
    state: State
    intents: list[Intent]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gesture-control")
    p.add_argument("--dry-run", action="store_true",
                   help="run the full pipeline but post no real events")
    p.add_argument("--record", default=None, metavar="PATH",
                   help="also write the session to a jsonl file")
    p.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    p.add_argument("--model", default=DEFAULT_MODEL_PATH)
    p.add_argument("--preview", action="store_true",
                   help="show a live camera window with hand landmarks and the "
                        "current state instead of the HUD pill")
    return p.parse_args(argv)


def preflight(
    dry_run: bool,
    model: str = DEFAULT_MODEL_PATH,
    camera_index: int = config.CAMERA_INDEX,
) -> list[str]:
    problems: list[str] = []
    if not os.path.exists(model):
        problems.append(
            f"Model file not found at {model}. Download it with:\n"
            "  curl -sL -o models/hand_landmarker.task \\\n"
            f"    {MODEL_URL}"
        )
    if not dry_run and not accessibility_granted():
        if not request_accessibility():
            problems.append(
                "Accessibility permission is not granted. Enable this app under "
                "System Settings, Privacy and Security, Accessibility, then restart it."
            )

    # Verify the camera the same way the spec requires: open the capture
    # device and read one frame. This turns a Camera.open() crash later into
    # a tidy Error line here, and also catches the device opening but never
    # delivering frames, which `not dry_run and not accessibility_granted()`
    # above would never see.
    camera = Camera(index=camera_index)
    try:
        camera.open()
        ok, _frame = camera.read()
        if not ok:
            problems.append(
                f"Camera {camera_index} opened but produced no frame. Check that "
                "no other app is holding it, then try again."
            )
    except Exception as exc:
        problems.append(str(exc))
    finally:
        camera.close()

    return problems


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    problems = preflight(args.dry_run, args.model, args.camera)
    if problems:
        for p in problems:
            print(f"Error: {p}")
        return 1

    print("Space switching requires the Mission Control shortcuts "
          "Ctrl-left and Ctrl-right to be enabled in System Settings, Keyboard.")

    coalescer = MoveCoalescer(print)
    actuator = DryRunActuator(sink=coalescer.feed) if args.dry_run else QuartzActuator()
    tracker = HandTracker(args.model)
    machine = StateMachine()
    camera = Camera(index=args.camera)
    camera.open()
    recorded: list = []
    t0 = time.monotonic()

    def shutdown(*_args: object) -> None:
        actuator.release_all()

    atexit.register(shutdown)

    def _step() -> TickResult:
        """One pipeline tick. The single source of per-frame work for both
        drivers below — the Tk HUD path and the OpenCV preview path each call
        this and only differ in how they render the result and drive time.
        """
        ok, image = camera.read()
        now = time.monotonic() - t0
        if not ok:
            # Still drive the pipeline with an absent frame so the gate's
            # timers advance and the watchdog can disarm and release a held
            # button. Otherwise a camera stall (sleep/wake, disconnect) mid
            # drag parks the state machine forever with the button down.
            frame = HandFrame(points=(), t=now, present=False, handedness="")
        else:
            frame = tracker.detect(image, now)
        if args.record is not None:
            recorded.append(frame)
        features = extract(frame)
        intents = machine.update(features)
        actuator.apply(intents)
        return TickResult(
            image=image if ok else None,
            frame=frame,
            features=features,
            state=machine.state,
            intents=intents,
        )

    def _teardown() -> None:
        # Reused verbatim by both drivers below: release_all() before the
        # camera and tracker close, same as the original single-driver code.
        shutdown()
        coalescer.flush()
        camera.close()
        tracker.close()
        if args.record is not None:
            write_session(args.record, recorded)
            print(f"Wrote {len(recorded)} frames to {args.record}")

    if args.preview:
        from . import preview as preview_ui

        stopped = False

        def request_stop(*_a: object) -> None:
            nonlocal stopped
            stopped = True
            shutdown()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)

        try:
            preview_ui.run(
                _step,
                shutdown,
                clock=lambda: time.monotonic() - t0,
                should_stop=lambda: stopped,
            )
        finally:
            _teardown()
        return 0

    def tick() -> None:
        result = _step()
        hud.set_state(result.state, result.features.present)

    hud = Hud(on_tick=tick, tick_ms=config.HUD_TICK_MS, on_error=actuator.release_all)
    signal.signal(signal.SIGINT, lambda *_a: (shutdown(), hud.stop()))
    signal.signal(signal.SIGTERM, lambda *_a: (shutdown(), hud.stop()))

    try:
        hud.run()
    finally:
        _teardown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
