from gesture_control.landmarks import to_hand_frame


class FakeLandmark:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class FakeCategory:
    def __init__(self, name):
        self.category_name = name


class FakeResult:
    def __init__(self, hands, handedness):
        self.hand_landmarks = hands
        self.handedness = handedness


def test_empty_result_is_absent():
    f = to_hand_frame(FakeResult([], []), t=2.5)
    assert f.present is False
    assert f.t == 2.5
    assert f.points == ()


def test_none_result_is_absent():
    f = to_hand_frame(None, t=1.0)
    assert f.present is False


def test_single_hand_is_converted():
    pts = [FakeLandmark(i / 21, i / 42, 0.0) for i in range(21)]
    f = to_hand_frame(FakeResult([pts], [[FakeCategory("Right")]]), t=3.0)
    assert f.present is True
    assert len(f.points) == 21
    assert f.handedness == "Right"
    assert f.points[0].x == 0.0


def test_missing_handedness_defaults_to_right():
    pts = [FakeLandmark(0.0, 0.0, 0.0) for _ in range(21)]
    f = to_hand_frame(FakeResult([pts], []), t=0.0)
    assert f.handedness == "Right"
