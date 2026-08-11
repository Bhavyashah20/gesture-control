from gesture_control.gate import Gate
from gesture_control.types import Features, Point2


def feat(t, fingers=(True, True, True, True), palm=True, scale=0.20, present=True):
    return Features(
        pinch_ratio=0.9, pinch2_ratio=0.9, index_curl_ratio=1.71,
        fingers_up=fingers, palm_facing=palm,
        hand_scale=scale, cursor_ref=Point2(0.5, 0.5), t=t, present=present,
    )


def test_starts_disarmed():
    assert Gate().armed is False


def test_arms_only_after_full_dwell():
    g = Gate()
    assert g.update(feat(0.00)) is False
    assert g.update(feat(0.29)) is False
    assert g.update(feat(0.31)) is True


def test_dwell_restarts_if_posture_breaks():
    g = Gate()
    g.update(feat(0.00))
    g.update(feat(0.20, fingers=(False, False, False, False)))
    assert g.update(feat(0.35)) is False
    assert g.update(feat(0.70)) is True


def test_requires_three_fingers():
    g = Gate()
    g.update(feat(0.00, fingers=(True, True, False, False)))
    assert g.update(feat(0.50, fingers=(True, True, False, False))) is False


def test_rejects_hand_too_close_or_too_far():
    g = Gate()
    g.update(feat(0.00, scale=0.60))
    assert g.update(feat(0.50, scale=0.60)) is False
    g2 = Gate()
    g2.update(feat(0.00, scale=0.02))
    assert g2.update(feat(0.50, scale=0.02)) is False


def test_stays_armed_when_fingers_curl_to_pinch():
    """The asymmetry: pinching must never disarm."""
    g = Gate()
    g.update(feat(0.00))
    assert g.update(feat(0.40)) is True
    for t in (0.5, 1.0, 2.0, 5.0):
        assert g.update(feat(t, fingers=(False, False, False, False))) is True


def test_disarms_after_hand_absent_for_dwell():
    """Pins both sides of the DISARM_S boundary. Absence starts at t=0.60."""
    g = Gate()
    g.update(feat(0.00))
    assert g.update(feat(0.40)) is True
    assert g.update(feat(0.60, present=False)) is True
    assert g.update(feat(0.80, present=False)) is True
    assert g.update(feat(1.00, present=False)) is True   # 0.40s absent, under 0.5
    assert g.update(feat(1.20, present=False)) is False  # 0.60s absent, over 0.5


def test_brief_dropout_does_not_disarm():
    """A reconnection must genuinely clear the loss timer, not merely postpone it.

    Checking only that the gate is still armed while the hand is present proves
    nothing: that path never reads the loss timer. A second absence is required
    to observe whether the first one was actually cleared.
    """
    g = Gate()
    g.update(feat(0.00))
    g.update(feat(0.40))
    g.update(feat(0.50, present=False))  # first loss starts at 0.50
    g.update(feat(0.60))                 # reconnect: timer must be cleared here
    g.update(feat(0.90, present=False))  # second loss starts at 0.90
    # 1.30 - 0.90 = 0.40s, under DISARM_S. A stale timer from 0.50 would read
    # 0.80s and wrongly disarm.
    assert g.update(feat(1.30, present=False)) is True
    assert g.update(feat(1.45, present=False)) is False  # 0.55s, over DISARM_S


def test_disarms_when_palm_turns_away():
    g = Gate()
    g.update(feat(0.00))
    g.update(feat(0.40))
    g.update(feat(0.50, palm=False))
    assert g.update(feat(1.10, palm=False)) is False
