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


def test_resting_state_cutoff_is_lower_than_the_euro_paper_default_of_one():
    """`EURO_MIN_CUTOFF` was lowered from 1.0: at `BASE_GAIN_PX = 2000` and
    `ACCEL_MIN = 0.5`, the same hand tremor now produces roughly twice the
    cursor movement it used to, so resting-state smoothing has to increase
    (a LOWER cutoff means MORE smoothing when the hand is nearly still) to
    land on small targets again. Config-relative, not a hardcoded 0.4, so
    this doesn't need updating if the value is retuned again later -- only
    the *direction* of the change is pinned here.
    """
    assert config.EURO_MIN_CUTOFF < 1.0


def test_lower_min_cutoff_smooths_a_near_still_tremor_harder():
    """The mechanism, not just the config value: at low speed the adaptive
    cutoff is dominated by `min_cutoff` (beta * |dx_hat| is small), so a
    lower `min_cutoff` must attenuate small tremor around a resting position
    more than the old default of 1.0 would -- directly addressing "cursor
    too jumpy to hit small targets" without touching `EURO_BETA`, which is
    what keeps fast movement from gaining lag.
    """
    def settle(min_cutoff: float) -> float:
        f = OneEuroFilter(min_cutoff=min_cutoff)
        out = 0.0
        for i in range(60):
            t = i / 30.0
            # A small tremor around 0.0 -- the "hand nearly still" case.
            x = 0.01 if i % 2 else -0.01
            out = f.filter(x, t)
        return abs(out)

    old_default_residual = settle(1.0)
    current_residual = settle(config.EURO_MIN_CUTOFF)
    assert current_residual < old_default_residual


def test_zero_dt_does_not_divide_by_zero():
    dx, dy = apply_gain(0.01, 0.0, 0.0)
    assert dx == 0.01 * config.BASE_GAIN_PX * config.ACCEL_MIN
    assert dy == 0.0
