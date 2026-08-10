from gesture_control.landmarks import HandTracker, to_hand_frame


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


def test_next_ms_is_strictly_increasing():
    tr = HandTracker.__new__(HandTracker)
    tr._last_ms = -1
    stamps = [tr._next_ms(t) for t in (0.0, 0.0004, 0.0009, 0.001, 0.05)]
    assert stamps == sorted(set(stamps))
    assert len(stamps) == len(set(stamps))


def test_next_ms_tracks_real_time_when_gaps_are_large():
    tr = HandTracker.__new__(HandTracker)
    tr._last_ms = -1
    tr._next_ms(0.0)
    assert tr._next_ms(1.5) == 1500
