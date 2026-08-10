from __future__ import annotations

import json
from typing import Iterable

from .features import extract
from .state_machine import StateMachine
from .types import HandFrame, Intent, Point3


def write_session(path: str, frames: Iterable[HandFrame]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for f in frames:
            fh.write(json.dumps({
                "t": f.t,
                "present": f.present,
                "handedness": f.handedness,
                "points": [[p.x, p.y, p.z] for p in f.points],
            }) + "\n")


def read_session(path: str) -> list[HandFrame]:
    out: list[HandFrame] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(HandFrame(
                points=tuple(Point3(*p) for p in d["points"]),
                t=d["t"],
                present=d["present"],
                handedness=d["handedness"],
            ))
    return out


def replay(path: str) -> list[Intent]:
    """Run a recorded session through the pure core. No camera, no OS."""
    sm = StateMachine()
    intents: list[Intent] = []
    for frame in read_session(path):
        intents.extend(sm.update(extract(frame)))
    return intents


def record_to(path: str, seconds: float = 10.0, model_path: str | None = None) -> None:
    """Capture a live session to disk. Used to build replay fixtures."""
    import time

    from .capture import Camera
    from .landmarks import DEFAULT_MODEL_PATH, HandTracker

    tracker = HandTracker(model_path or DEFAULT_MODEL_PATH)
    frames: list[HandFrame] = []
    try:
        with Camera() as cam:
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                ok, image = cam.read()
                if not ok:
                    continue
                frames.append(tracker.detect(image, time.monotonic() - t0))
    finally:
        tracker.close()
    write_session(path, frames)
    print(f"wrote {len(frames)} frames to {path}")
