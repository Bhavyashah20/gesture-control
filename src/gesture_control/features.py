from __future__ import annotations

import math

from . import config
from .types import Features, HandFrame, Point2, Point3

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
PINKY_MCP = 17

FINGER_JOINTS = ((6, 8), (10, 12), (14, 16), (18, 20))

_ABSENT = Features(
    pinch_ratio=1.0,
    pinch2_ratio=1.0,
    # Matches the measured open-hand median (see config.py's INDEX_CURL_*
    # comment) so an absent frame reads as "uncurled", not "curled" -- an
    # absent hand must never freeze the cursor via the curl path.
    index_curl_ratio=1.71,
    fingers_up=(False, False, False, False),
    palm_facing=False,
    hand_scale=0.0,
    cursor_ref=Point2(0.5, 0.5),
    t=0.0,
    present=False,
)


def _mirror(p: Point3) -> Point3:
    return Point3(1.0 - p.x, p.y, p.z)


def _dist(a: Point3, b: Point3) -> float:
    """True 3D distance, including MediaPipe's z (depth, wrist-relative).

    A 2D-only projection (hypot on x, y alone) shrinks whenever the hand
    rotates, even though the physical distance between the two landmarks
    has not changed -- the same pinch reads as tighter or looser purely
    from hand orientation. Every caller of `_dist` (pinch, pinch2, curl,
    AND hand_scale) goes through this one function, so the pinch distances
    and their normalizer stay on the same footing; do not special-case any
    of them back to 2D without updating the others to match.
    """
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def _palm_facing(pts: tuple[Point3, ...], handedness: str) -> bool:
    """Correctness here depends on two compensating inversions.

    MediaPipe reports handedness as if the input image were mirrored (as a
    selfie-view camera app would show it), but we feed it the raw, un-mirrored
    camera frame. That mismatch is exactly what cancels the mirror-induced
    sign flip in the cross product below. Do not "fix" this by adding a
    cv2.flip for a preview window without also flipping the sign convention
    here: doing so silently inverts palm_facing for one handedness, the gate
    never arms, and no test catches it because none renders a mirrored
    preview.
    """
    wrist = pts[WRIST]
    v1x, v1y = pts[INDEX_MCP].x - wrist.x, pts[INDEX_MCP].y - wrist.y
    v2x, v2y = pts[PINKY_MCP].x - wrist.x, pts[PINKY_MCP].y - wrist.y
    cross_z = v1x * v2y - v1y * v2x
    return cross_z > 0.0 if handedness == "Right" else cross_z < 0.0


def extract(frame: HandFrame) -> Features:
    if not frame.present or len(frame.points) < 21:
        return Features(**{**_ABSENT.__dict__, "t": frame.t})

    pts = tuple(_mirror(p) for p in frame.points)
    scale = _dist(pts[WRIST], pts[MIDDLE_MCP])
    if scale <= 0.0:
        return Features(**{**_ABSENT.__dict__, "t": frame.t})

    pinch = _dist(pts[THUMB_TIP], pts[INDEX_TIP]) / scale
    pinch2 = _dist(pts[THUMB_TIP], pts[MIDDLE_TIP]) / scale
    # Index fingertip to wrist, scale-normalized. Drives the clutch (see
    # config.py's INDEX_CURL_CLOSE / INDEX_CURL_OPEN): curling the index
    # toward the palm shrinks this ratio, freezing the cursor.
    index_curl = _dist(pts[WRIST], pts[INDEX_TIP]) / scale

    fingers = tuple(
        _dist(pts[WRIST], pts[tip]) > config.FINGER_EXT_RATIO * _dist(pts[WRIST], pts[pip])
        for pip, tip in FINGER_JOINTS
    )

    return Features(
        pinch_ratio=pinch,
        pinch2_ratio=pinch2,
        index_curl_ratio=index_curl,
        fingers_up=fingers,
        palm_facing=_palm_facing(pts, frame.handedness),
        hand_scale=scale,
        cursor_ref=Point2(pts[INDEX_MCP].x, pts[INDEX_MCP].y),
        t=frame.t,
        present=True,
    )
