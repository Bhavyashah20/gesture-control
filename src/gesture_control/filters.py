from __future__ import annotations

import math

from . import config
from .types import Point2


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Speed-adaptive low-pass filter (Casiez, Roussel, Vogel, 2012)."""

    def __init__(
        self,
        min_cutoff: float = config.EURO_MIN_CUTOFF,
        beta: float = config.EURO_BETA,
        d_cutoff: float = config.EURO_D_CUTOFF,
    ) -> None:
        self._min_cutoff = min_cutoff
        self._beta = beta
        self._d_cutoff = d_cutoff
        self._x_prev: float | None = None
        self._dx_prev = 0.0
        self._t_prev: float | None = None

    def filter(self, x: float, t: float) -> float:
        if self._x_prev is None or self._t_prev is None:
            self._x_prev, self._t_prev = x, t
            return x

        dt = t - self._t_prev
        if dt <= 0.0:
            return self._x_prev

        dx = (x - self._x_prev) / dt
        a_d = _alpha(self._d_cutoff, dt)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev

        cutoff = self._min_cutoff + self._beta * abs(dx_hat)
        a = _alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self._x_prev

        self._x_prev, self._dx_prev, self._t_prev = x_hat, dx_hat, t
        return x_hat


class Point2Filter:
    def __init__(self) -> None:
        self._fx = OneEuroFilter()
        self._fy = OneEuroFilter()

    def filter(self, p: Point2, t: float) -> Point2:
        return Point2(self._fx.filter(p.x, t), self._fy.filter(p.y, t))


def accel(speed: float) -> float:
    """Pointer acceleration curve. speed is in frame widths per second."""
    raw = config.ACCEL_MIN + speed / config.ACCEL_VREF
    return min(max(raw, config.ACCEL_MIN), config.ACCEL_MAX)


def apply_gain(dx: float, dy: float, dt: float) -> tuple[float, float]:
    """Normalized hand delta -> screen pixel delta."""
    speed = math.hypot(dx, dy) / dt if dt > 0.0 else 0.0
    a = accel(speed)
    return dx * config.BASE_GAIN_PX * a, dy * config.BASE_GAIN_PX * a
