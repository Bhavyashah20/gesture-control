from __future__ import annotations

from . import config
from .types import Features


class Gate:
    """Decides whether the user is addressing the system.

    Arming is strict (open palm, held). Sustaining is loose (hand present,
    palm roughly toward camera) so that pinching cannot disarm.
    """

    def __init__(self) -> None:
        self._armed = False
        self._arm_since: float | None = None
        self._lost_since: float | None = None

    @property
    def armed(self) -> bool:
        return self._armed

    def _can_arm(self, f: Features) -> bool:
        return (
            f.present
            and f.palm_facing
            and sum(f.fingers_up) >= config.ARM_FINGERS_MIN
            and config.HAND_SCALE_MIN <= f.hand_scale <= config.HAND_SCALE_MAX
        )

    def _can_sustain(self, f: Features) -> bool:
        return f.present and f.palm_facing

    def update(self, f: Features) -> bool:
        if self._armed:
            if self._can_sustain(f):
                self._lost_since = None
            else:
                if self._lost_since is None:
                    self._lost_since = f.t
                elif f.t - self._lost_since >= config.DISARM_S:
                    self._armed = False
                    self._lost_since = None
                    self._arm_since = None
        else:
            if self._can_arm(f):
                if self._arm_since is None:
                    self._arm_since = f.t
                elif f.t - self._arm_since >= config.ARM_DWELL_S:
                    self._armed = True
                    self._arm_since = None
                    self._lost_since = None
            else:
                self._arm_since = None

        return self._armed
