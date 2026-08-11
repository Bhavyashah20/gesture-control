from __future__ import annotations

import argparse
import atexit
import os
import signal
import time

from . import config
from .actuator import DryRunActuator, QuartzActuator, accessibility_granted, request_accessibility
from .capture import Camera
from .features import extract
from .hud import Hud
from .landmarks import DEFAULT_MODEL_PATH, HandTracker
from .recorder import write_session
from .state_machine import StateMachine


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gesture-control")
    p.add_argument("--dry-run", action="store_true",
                   help="run the full pipeline but post no real events")
    p.add_argument("--record", default=None, metavar="PATH",
                   help="also write the session to a jsonl file")
    p.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    p.add_argument("--model", default=DEFAULT_MODEL_PATH)
    return p.parse_args(argv)


def preflight(dry_run: bool, model: str = DEFAULT_MODEL_PATH) -> list[str]:
    problems: list[str] = []
    if not os.path.exists(model):
        problems.append(
            f"Model file not found at {model}. Download it with:\n"
            "  curl -sL -o models/hand_landmarker.task \\\n"
            "    https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/1/hand_landmarker.task"
        )
    if not dry_run and not accessibility_granted():
        if not request_accessibility():
            problems.append(
                "Accessibility permission is not granted. Enable this app under "
                "System Settings, Privacy and Security, Accessibility, then restart it."
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else [])

    problems = preflight(args.dry_run, args.model)
    if problems:
        for p in problems:
            print(f"Error: {p}")
        return 1

    print("Space switching requires the Mission Control shortcuts "
          "Ctrl-left and Ctrl-right to be enabled in System Settings, Keyboard.")

    actuator = DryRunActuator() if args.dry_run else QuartzActuator()
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
            return
        frame = tracker.detect(image, time.monotonic() - t0)
        if args.record is not None:
            recorded.append(frame)
        features = extract(frame)
        actuator.apply(machine.update(features))
        hud.set_state(machine.state, features.present)

    hud = Hud(on_tick=tick, tick_ms=config.HUD_TICK_MS)
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
