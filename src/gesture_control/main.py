from __future__ import annotations

import argparse
import atexit
import os
import signal
import sys
import time

from . import config
from .actuator import DryRunActuator, QuartzActuator, accessibility_granted, request_accessibility
from .capture import Camera
from .features import extract
from .hud import Hud
from .landmarks import DEFAULT_MODEL_PATH, HandTracker, MODEL_URL
from .recorder import write_session
from .state_machine import StateMachine
from .types import HandFrame


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gesture-control")
    p.add_argument("--dry-run", action="store_true",
                   help="run the full pipeline but post no real events")
    p.add_argument("--record", default=None, metavar="PATH",
                   help="also write the session to a jsonl file")
    p.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    p.add_argument("--model", default=DEFAULT_MODEL_PATH)
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

    actuator = DryRunActuator(sink=print) if args.dry_run else QuartzActuator()
    tracker = HandTracker(args.model)
    machine = StateMachine()
    camera = Camera(index=args.camera)
    camera.open()
    recorded: list = []
    t0 = time.monotonic()

    def shutdown(*_args: object) -> None:
        actuator.release_all()

    atexit.register(shutdown)

    def tick() -> None:
        ok, image = camera.read()
        if not ok:
            # Still drive the pipeline with an absent frame so the gate's
            # timers advance and the watchdog can disarm and release a held
            # button. Otherwise a camera stall (sleep/wake, disconnect) mid
            # drag parks the state machine forever with the button down.
            frame = HandFrame(points=(), t=time.monotonic() - t0, present=False, handedness="")
        else:
            frame = tracker.detect(image, time.monotonic() - t0)
        if args.record is not None:
            recorded.append(frame)
        features = extract(frame)
        actuator.apply(machine.update(features))
        hud.set_state(machine.state, features.present)

    hud = Hud(on_tick=tick, tick_ms=config.HUD_TICK_MS, on_error=actuator.release_all)
    signal.signal(signal.SIGINT, lambda *_a: (shutdown(), hud.stop()))
    signal.signal(signal.SIGTERM, lambda *_a: (shutdown(), hud.stop()))

    try:
        hud.run()
    finally:
        shutdown()
        camera.close()
        tracker.close()
        if args.record is not None:
            write_session(args.record, recorded)
            print(f"Wrote {len(recorded)} frames to {args.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
