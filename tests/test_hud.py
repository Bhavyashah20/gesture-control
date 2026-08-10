from gesture_control.hud import state_label
from gesture_control.state_machine import State


def test_every_state_has_a_label():
    for s in State:
        assert state_label(s, present=True)


def test_labels_are_lowercase_sentence_case():
    for s in State:
        label = state_label(s, present=True)
        assert label == label.lower()


def test_absent_hand_is_flagged_while_armed():
    assert state_label(State.ARMED_IDLE, present=False) != state_label(
        State.ARMED_IDLE, present=True
    )


def test_disarmed_label_ignores_presence():
    assert state_label(State.DISARMED, present=False) == state_label(
        State.DISARMED, present=True
    )
