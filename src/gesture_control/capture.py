from __future__ import annotations

from typing import Any

import cv2

from . import config


class Camera:
    """Webcam frames via AVFoundation."""

    def __init__(
        self,
        index: int = config.CAMERA_INDEX,
        width: int = config.FRAME_WIDTH,
        height: int = config.FRAME_HEIGHT,
        fps: int = config.FRAME_FPS,
    ) -> None:
        self._index, self._width, self._height, self._fps = index, width, height, fps
        self._cap: Any = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self._index, cv2.CAP_AVFOUNDATION)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera {self._index}. Grant camera access to your "
                "terminal in System Settings, Privacy and Security, Camera."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

    def read(self) -> tuple[bool, Any]:
        if self._cap is None:
            return False, None
        return self._cap.read()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
