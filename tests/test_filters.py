import math

from gesture_control import config
from gesture_control.filters import OneEuroFilter, Point2Filter, accel, apply_gain
from gesture_control.types import Point2


def test_first_sample_passes_through():
    f = OneEuroFilter()
    assert f.filter(5.0, 0.0) == 5.0


def test_converges_on_constant_input():
    f = OneEuroFilter()
    f.filter(0.0, 0.0)
    out = 0.0
    for i in range(1, 200):
        out = f.filter(10.0, i / 30.0)
    assert math.isclose(out, 10.0, abs_tol=0.05)


def test_attenuates_alternating_noise():
    f = OneEuroFilter()
    f.filter(0.0, 0.0)
    out = []
    for i in range(1, 61):
        out.append(f.filter(1.0 if i % 2 else -1.0, i / 30.0))
    assert max(abs(v) for v in out[-10:]) < 0.9


def test_point2_filter_returns_point2():
    f = Point2Filter()
    p = f.filter(Point2(0.3, 0.7), 0.0)
    assert isinstance(p, Point2)
    assert p == (0.3, 0.7)


def test_accel_config_bounds_are_consistent():
    assert config.ACCEL_MIN < config.ACCEL_MAX


def test_accel_is_clamped_at_both_ends():
    assert accel(0.0) == config.ACCEL_MIN
    assert accel(1e6) == config.ACCEL_MAX


def test_accel_is_monotonic():
    speeds = [0.0, 0.2, 0.5, 1.0, 2.0, 4.0]
    values = [accel(s) for s in speeds]
    assert values == sorted(values)


def test_slow_movement_gets_less_travel_per_unit_than_fast():
    slow_dx, _ = apply_gain(0.01, 0.0, 1.0)
    fast_dx, _ = apply_gain(0.01, 0.0, 0.01)
    assert fast_dx > slow_dx


def test_zero_dt_does_not_divide_by_zero():
    dx, dy = apply_gain(0.01, 0.0, 0.0)
    assert dx == 0.01 * config.BASE_GAIN_PX * config.ACCEL_MIN
    assert dy == 0.0
