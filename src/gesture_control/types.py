from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Point2(NamedTuple):
    x: float
    y: float


class Point3(NamedTuple):
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class HandFrame:
    points: tuple[Point3, ...]
    t: float
    present: bool
    handedness: str


@dataclass(frozen=True)
class Features:
    pinch_ratio: float
    pinch2_ratio: float
    index_curl_ratio: float
    middle_curl_ratio: float
    thumb_tuck_ratio: float
    fingers_up: tuple[bool, bool, bool, bool]
    palm_facing: bool
    hand_scale: float
    cursor_ref: Point2
    t: float
    present: bool


@dataclass(frozen=True)
class Move:
    dx: float
    dy: float


@dataclass(frozen=True)
class Click:
    n: int


@dataclass(frozen=True)
class ButtonDown:
    pass


@dataclass(frozen=True)
class ButtonUp:
    pass


@dataclass(frozen=True)
class Scroll:
    dy: float


@dataclass(frozen=True)
class Space:
    direction: str


Intent = Move | Click | ButtonDown | ButtonUp | Scroll | Space
