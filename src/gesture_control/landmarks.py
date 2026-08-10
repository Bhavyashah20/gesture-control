from __future__ import annotations

from typing import Any

from .types import HandFrame, Point3

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
DEFAULT_MODEL_PATH = "models/hand_landmarker.task"


def to_hand_frame(result: Any, t: float) -> HandFrame:
    """Convert a MediaPipe HandLandmarkerResult to our HandFrame. Pure."""
    hands = getattr(result, "hand_landmarks", None) if result is not None else None
    if not hands:
        return HandFrame(points=(), t=t, present=False, handedness="")

    pts = tuple(Point3(lm.x, lm.y, lm.z) for lm in hands[0])

    handed = "Right"
    categories = getattr(result, "handedness", None) or []
    if categories and categories[0]:
        handed = categories[0][0].category_name

    return HandFrame(points=pts, t=t, present=True, handedness=handed)


class HandTracker:
    """MediaPipe HandLandmarker in VIDEO mode: synchronous and deterministic."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = HandLandmarker.create_from_options(options)

    def detect(self, bgr: Any, t: float) -> HandFrame:
        import cv2

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, int(t * 1000))
        return to_hand_frame(result, t)

    def close(self) -> None:
        self._landmarker.close()
