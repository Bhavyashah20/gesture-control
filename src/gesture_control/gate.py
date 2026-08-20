from __future__ import annotations

from . import config
from .types import Features


class Gate:
    """Decides whether the user is addressing the system.

    Arming is strict (open palm, held). Sustaining is loose -- hand present
    is all it takes -- so that pinching cannot disarm.

    Sustaining dropped its palm_facing requirement on 2026-08-21. It used
    to require `f.present and f.palm_facing`, matching arming's condition
    minus the finger/dwell/scale checks. That was wrong for the same
    reason a strict sustain condition on fingers would be wrong: gestures
    rotate the hand, and a sustain condition that fights the motion a
    gesture is made of works against every gesture, not just the one that
    exposed it. Diagnosed against recordings/three_finger.jsonl: the
    user's three-finger swipe worked leftward but was lost rightward,
    because swiping right rotates the palm edge-on to the camera for
    roughly 0.3-0.4 s per swipe -- long enough to trip DISARM_S. Over the
    448-frame recording the gate disarmed 3 times, for stretches up to 41
    frames (1.4 s), with 62 of 267 three-finger frames caught disarmed;
    handedness stayed "Right" throughout with zero label changes, and only
    4% of frames sat in the genuinely ambiguous edge-on band, so this was
    real hand rotation, not a detection artifact -- the normalized palm
    normal reached -0.46 at p05 against a +0.39 median. Requiring
    palm_facing throughout was never a safety property; the safety
    property is `f.present` (see `_can_sustain` and the DISARM_S watchdog
    below), which is untouched.

    Consequence: turning the palm away no longer stops the system by
    itself. To stop, drop the hand out of frame (armed -> disarmed after
    DISARM_S with the hand absent) or press Esc (the kill switch, see
    README and the spec's Safety section).
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
        # Presence only -- see the class docstring for why palm_facing was
        # dropped from this condition on 2026-08-21. _can_arm above is
        # unchanged and still requires it.
        return f.present

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
