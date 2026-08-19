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
RING_MCP = 13
PINKY_MCP = 17

# cursor_ref's four knuckles (see its assignment in extract() below).
CURSOR_REF_LANDMARKS = (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)

FINGER_JOINTS = ((6, 8), (10, 12), (14, 16), (18, 20))

_ABSENT = Features(
    pinch_ratio=1.0,
    pinch2_ratio=1.0,
    # Matches the measured open-hand median (see config.py's INDEX_CURL_*
    # comment) so an absent frame reads as "uncurled", not "curled" -- an
    # absent hand must never freeze the cursor via the curl path.
    index_curl_ratio=1.71,
    # Matches the measured five_clicks median (see config.py's
    # THUMB_TUCK_MAX comment), the most "resting hand" of the recordings, so
    # an absent frame reads as "thumb not tucked" -- an absent hand must
    # never satisfy the scroll gate via the tuck path. fingers_up is already
    # all-False for an absent frame, so this is belt-and-suspenders, not
    # load-bearing on its own.
    thumb_tuck_ratio=0.95,
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
    # Thumb tip to pinky knuckle, scale-normalized. Small means the thumb is
    # tucked across the palm. Drives the scroll gate's thumb condition (see
    # config.py's THUMB_TUCK_MAX): required in addition to the finger
    # posture so that opening the middle finger for a middle-pinch
    # double-click (which extends the thumb out to meet it) cannot also
    # read as scroll.
    thumb_tuck = _dist(pts[THUMB_TIP], pts[PINKY_MCP]) / scale

    fingers = tuple(
        _dist(pts[WRIST], pts[tip]) > config.FINGER_EXT_RATIO * _dist(pts[WRIST], pts[pip])
        for pip, tip in FINGER_JOINTS
    )

    return Features(
        pinch_ratio=pinch,
        pinch2_ratio=pinch2,
        index_curl_ratio=index_curl,
        thumb_tuck_ratio=thumb_tuck,
        fingers_up=fingers,
        palm_facing=_palm_facing(pts, frame.handedness),
        hand_scale=scale,
        # Palm centroid, not a single knuckle (see the "cursor_ref" section
        # of the spec for the full rationale and measured jitter numbers):
        # the mean of the four MCP knuckles (index, middle, ring, pinky)
        # keeps the "barely moves during a pinch" property a single knuckle
        # has, while also cancelling each knuckle's independent tracking
        # noise, which a single point cannot.
        cursor_ref=Point2(
            sum(pts[i].x for i in CURSOR_REF_LANDMARKS) / len(CURSOR_REF_LANDMARKS),
            sum(pts[i].y for i in CURSOR_REF_LANDMARKS) / len(CURSOR_REF_LANDMARKS),
        ),
        t=frame.t,
        present=True,
    )
