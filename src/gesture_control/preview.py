"""Live OpenCV preview: camera feed + landmark skeleton + state readout.

This is the I/O twin of `hud.py`. `hud.py` drives the pipeline through Tk's
`root.after`; this module drives it through a plain loop and `cv2.waitKey`,
so the two cannot run together (see `main.py`, which picks exactly one).

CRITICAL: the tracker (`landmarks.HandTracker.detect`) must only ever see the
raw, un-mirrored camera frame — see `features._palm_facing` for why. This
module mirrors a separate DISPLAY COPY for the user (`mirror_frame`) and
un-mirrors landmark coordinates to match when drawing (`landmark_to_pixel`).
Never pass the mirrored copy to the tracker.
"""

from __future__ import annotations

import time
import traceback
from typing import Callable

import cv2

from . import config
from .hud import _COLORS, state_label
from .state_machine import State
from .types import (
    Click,
    DragEnd,
    DragStart,
    Features,
    HandFrame,
    Intent,
    Point3,
    Scroll,
    Space,
)

WINDOW_NAME = "Gesture control preview"

# Standard MediaPipe hand-skeleton connections (landmark index pairs).
HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

# --- Presentation constants (drawing only; nothing here governs gesture
# recognition, so it is exempt from the config.py-only rule for literals). ---
POINT_RADIUS = 4
POINT_COLOR = (0, 255, 255)  # BGR yellow
LINE_COLOR = (255, 255, 255)
LINE_THICKNESS = 2

FONT = cv2.FONT_HERSHEY_SIMPLEX
STATE_BAR_HEIGHT = 44
STATE_FONT_SCALE = 1.0
STATE_FONT_THICKNESS = 2
STATE_TEXT_COLOR = (255, 255, 255)
INFO_FONT_SCALE = 0.6
INFO_FONT_THICKNESS = 1
INFO_TEXT_COLOR = (255, 255, 255)
HINT_TEXT_COLOR = (200, 200, 200)

RECENT_INTENT_WINDOW_S = 1.0


def _hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


# Derived from hud._COLORS, which is already keyed by every State member, so
# a future State that forgets a HUD colour fails loudly there rather than
# raising KeyError deep inside the render loop here.
STATE_COLORS_BGR: dict[State, tuple[int, int, int]] = {
    state: _hex_to_bgr(hex_color) for state, hex_color in _COLORS.items()
}


def landmark_to_pixel(p: Point3, width: int, height: int) -> tuple[int, int]:
    """Map a normalized, un-mirrored landmark to mirrored display pixels.

    The tracker sees the raw camera frame; the human sees a mirrored one (so
    their hand moving right matches the cursor moving right). x is flipped
    to match that mirrored display copy; y is left untouched.
    """
    x_px = int(round((1.0 - p.x) * width))
    y_px = int(round(p.y * height))
    return x_px, y_px


def intent_label(intent: Intent | None) -> str | None:
    """Human-readable label for the "notable" (discrete) intents.

    Move returns None deliberately: it fires every frame while tracking, so
    treating it as notable would make the recent-intent readout permanently
    blank the instant the hand moves again, defeating its purpose.
    """
    match intent:
        case Click(n):
            return f"click x{n}"
        case DragStart():
            return "drag start"
        case DragEnd():
            return "drag end"
        case Scroll(dy):
            return f"scroll {dy:+.0f}"
        case Space(d):
            return f"space {d}"
        case _:
            return None


def recent_intent_text(
    intent: Intent | None,
    elapsed_s: float,
    window_s: float = RECENT_INTENT_WINDOW_S,
) -> str | None:
    """Label for the last notable intent, while it is still "recent".

    Returns None if there is no intent, it wasn't notable (see
    `intent_label`), or `elapsed_s` has exceeded `window_s` — so a click
    reads as a flash on screen instead of scrolling past in a log.
    """
    if intent is None or elapsed_s > window_s:
        return None
    return intent_label(intent)


def mirror_frame(image):
    """The display-only mirrored copy. Never feed this to the tracker."""
    return cv2.flip(image, 1)


def draw(
    image,
    hand_frame: HandFrame,
    state: State,
    features: Features,
    recent_text: str | None,
):
    """Draw the skeleton and readouts onto an already-mirrored display frame."""
    h, w = image.shape[:2]

    if hand_frame.present and len(hand_frame.points) >= 21:
        pixels = [landmark_to_pixel(p, w, h) for p in hand_frame.points]
        for a, b in HAND_CONNECTIONS:
            cv2.line(image, pixels[a], pixels[b], LINE_COLOR, LINE_THICKNESS, cv2.LINE_AA)
        for x, y in pixels:
            cv2.circle(image, (x, y), POINT_RADIUS, POINT_COLOR, -1, cv2.LINE_AA)

    color = STATE_COLORS_BGR[state]
    cv2.rectangle(image, (0, 0), (w, STATE_BAR_HEIGHT), color, -1)
    cv2.putText(
        image, state_label(state, hand_frame.present), (10, STATE_BAR_HEIGHT - 14),
        FONT, STATE_FONT_SCALE, STATE_TEXT_COLOR, STATE_FONT_THICKNESS, cv2.LINE_AA,
    )

    pinch_closed = features.pinch_ratio < config.PINCH_CLOSE
    pinch_text = f"pinch_ratio {features.pinch_ratio:.2f} ({'closed' if pinch_closed else 'open'})"
    cv2.putText(
        image, pinch_text, (10, h - 55),
        FONT, INFO_FONT_SCALE, INFO_TEXT_COLOR, INFO_FONT_THICKNESS, cv2.LINE_AA,
    )

    if recent_text:
        cv2.putText(
            image, recent_text, (10, h - 80),
            FONT, INFO_FONT_SCALE, INFO_TEXT_COLOR, INFO_FONT_THICKNESS, cv2.LINE_AA,
        )

    cv2.putText(
        image, "esc or q to quit", (10, h - 15),
        FONT, INFO_FONT_SCALE, HINT_TEXT_COLOR, INFO_FONT_THICKNESS, cv2.LINE_AA,
    )

    return image


def _never_stop() -> bool:
    return False


def run(
    step: Callable[[], object],
    shutdown: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
    should_stop: Callable[[], bool] = _never_stop,
) -> None:
    """Drive the pipeline with cv2's loop instead of Tk's `root.after`.

    `step` must be the SAME per-frame function the Tk path uses (see
    `main.py`'s `_step`), and `shutdown` the SAME shutdown callable — this
    function does not implement its own version of either, so the
    stuck-button guarantee (`actuator.release_all()` before the camera and
    tracker close) holds identically in both drivers.

    Every exit — the quit key, `should_stop()` going true, or an exception
    raised by `step()` — falls through to the `finally` below, so
    `shutdown()` always runs exactly once per call to `run`.
    """
    cv2.namedWindow(WINDOW_NAME)
    last_intent: Intent | None = None
    last_intent_t: float | None = None
    try:
        while not should_stop():
            try:
                result = step()
            except Exception:
                traceback.print_exc()
                break

            now = clock()
            notable = next(
                (i for i in reversed(result.intents) if intent_label(i) is not None),
                None,
            )
            if notable is not None:
                last_intent, last_intent_t = notable, now
            elapsed = now - last_intent_t if last_intent_t is not None else float("inf")
            recent_text = recent_intent_text(last_intent, elapsed)

            if result.image is not None:
                display = mirror_frame(result.image)
                draw(display, result.frame, result.state, result.features, recent_text)
                cv2.imshow(WINDOW_NAME, display)

            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key in (ord("q"), ord("Q")):
                break
    finally:
        shutdown()
        try:
            cv2.destroyWindow(WINDOW_NAME)
        except cv2.error:
            pass
