import json

import pytest

from gesture_control import config
from gesture_control.features import extract
from gesture_control.recorder import read_session, replay, write_session
from gesture_control.state_machine import StateMachine
from gesture_control.types import ButtonDown, ButtonUp, Click, HandFrame, Point3, Scroll, Space


def _frames():
    a = HandFrame(
        points=tuple(Point3(i / 21, i / 42, 0.0) for i in range(21)),
        t=0.0, present=True, handedness="Right",
    )
    b = HandFrame(points=(), t=0.033, present=False, handedness="")
    return [a, b]


def test_round_trip_preserves_frames(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), _frames())
    assert read_session(str(p)) == _frames()


def test_file_is_one_json_object_per_line(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), _frames())
    lines = p.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["present"] is True


def test_replay_of_absent_frames_yields_no_intents(tmp_path):
    p = tmp_path / "s.jsonl"
    write_session(str(p), [
        HandFrame(points=(), t=i / 30, present=False, handedness="")
        for i in range(60)
    ])
    assert replay(str(p)) == []


# --- Replay fixture assertions ---
#
# All six behavioural fixtures below were recorded under the OLD
# trackpad-mimicry model (pinch to move, hold-still-while-pinched to drag).
# Replayed through the new direct-manipulation state machine, their intent
# sequences are different in kind, not just count: continuous hand tracking
# now emits a Move on essentially every present frame, index pinches are
# now ButtonDown/ButtonUp pairs instead of Click(1), and nothing here was
# re-recorded -- these are the numbers the new state machine actually
# produces against the old landmark data. See the redesign report for the
# full before/after table.
FIXTURES = "recordings"


def _replay(name):
    path = f"{FIXTURES}/{name}.jsonl"
    try:
        return replay(path)
    except FileNotFoundError:
        pytest.skip(f"fixture {path} not recorded yet")


def test_five_clicks_yields_five_button_down_up_pairs():
    """Five deliberate index taps are now five ButtonDown/ButtonUp pairs --
    the button press-and-release macOS reads as a click on its own. No
    Click intent is emitted for the index finger under the new model."""
    out = _replay("five_clicks")
    downs = [i for i in out if isinstance(i, ButtonDown)]
    ups = [i for i in out if isinstance(i, ButtonUp)]
    assert len(downs) == 5
    assert len(ups) == 5
    assert not any(isinstance(i, Click) for i in out)


def test_one_double_click_yields_two_button_down_up_pairs_never_a_click_two():
    """`one_double_click.jsonl` was recorded under the OLD timing-based
    double-click design as two rapid INDEX taps. Under the new model the
    index finger only ever produces ButtonDown/ButtonUp -- this is the
    regression test that two quick index pinches never misread as the
    middle-finger double-click gesture.
    """
    out = _replay("one_double_click")
    downs = [i for i in out if isinstance(i, ButtonDown)]
    ups = [i for i in out if isinstance(i, ButtonUp)]
    assert len(downs) == 2
    assert len(ups) == 2
    assert Click(2) not in out


def test_live_clicks_yields_twelve_button_down_up_pairs_never_a_click_two():
    """`live_clicks.jsonl` contained three false Click(2)s under the old
    timing-based double-click design. Under the new model none of its taps
    are on the middle finger, so it must produce twelve ButtonDown/ButtonUp
    pairs and never a Click(2)."""
    out = _replay("live_clicks")
    downs = [i for i in out if isinstance(i, ButtonDown)]
    ups = [i for i in out if isinstance(i, ButtonUp)]
    assert len(downs) == 12
    assert len(ups) == 12
    assert Click(2) not in out


def test_live_clicks_contains_one_incidental_space():
    """Pinned here so a future swipe-tuning change surfaces its effect on
    this fixture too, not just on one_sweep.jsonl.

    Was 2 before the 2026-08-20 absent-frame fix (see state_machine.py's
    `if not f.present` branch). Both were sentinel artifacts, not genuine
    swipes: this recording has a real absent frame at index 225 (t=7.548)
    right before one 'right' Space and a run of three absent frames at
    indices 256-258 right before the other. Under the OLD code,
    `_detect_swipe` still ran on absent frames and appended the sentinel's
    frame-centre cursor_ref (0.5, 0.5) into the swipe history; the very
    next real frame then computed its displacement against that stale
    centre point instead of the hand's actual prior position, reading as a
    fast rightward swipe it never made. Skipping absent frames entirely
    (this fix) removes both artifacts and leaves the one genuine swipe: a
    real, sustained leftward sweep from cursor_ref.x=0.927 (frame 232) to
    0.457 (frame 249), comfortably clearing SWIPE_DIST and SWIPE_VEL on
    its own."""
    out = _replay("live_clicks")
    spaces = [i for i in out if isinstance(i, Space)]
    assert len(spaces) == 1
    assert spaces[0] == Space("left")


def test_drag_yields_one_button_down_and_one_button_up():
    """A drag from A to B is now just a press, move, release -- exactly the
    down/move/up sequence macOS reads as a drag from a physical mouse.
    There is no DragStart/DragEnd dwell classification left to test."""
    out = _replay("drag_a_to_b")
    assert len([i for i in out if isinstance(i, ButtonDown)]) == 1
    assert len([i for i in out if isinstance(i, ButtonUp)]) == 1


def test_reaching_past_camera_yields_nothing():
    """Reaching past the camera must produce NO intents at all.

    Not merely no clicks. Under the new model the cursor tracks
    continuously while armed, so a stray Move is now the most likely false
    positive of all -- if the gate ever mis-arms here, every subsequent
    frame emits one. This fixture is what proves it never does.

    If this fails on a real recording, tune the gate. Do not weaken the
    assertion — that would discard the only evidence the system stays quiet.
    """
    assert _replay("reaching_past") == []


def test_talking_with_hands_yields_nothing():
    """Same standard: total silence while the system is not being addressed."""
    assert _replay("talking_hands") == []


def test_one_sweep_yields_exactly_one_space():
    out = _replay("one_sweep")
    spaces = [i for i in out if isinstance(i, Space)]
    assert len(spaces) == 1
    assert not any(isinstance(i, (ButtonDown, ButtonUp, Click)) for i in out)


def test_scroll_attempt_produces_a_meaningful_amount_of_scroll():
    """recordings/scroll_attempt.jsonl was recorded as a sweeping motion,
    for the old displacement model (see the previous version of this test's
    docstring in git history) -- scroll distance followed how far the hand
    physically moved. Rate-based scrolling (2026-08-20 redesign) reads
    completely differently: offset is measured from a single neutral point
    recorded once when SCROLL is entered, so a Scroll event only fires
    while the hand is held away from that neutral, not on every frame of
    vertical motion. A sweep that keeps passing back near neutral -- which
    is exactly what this recording is -- produces fewer, larger events
    concentrated at the sweep's peaks, not a near-continuous stream of
    small ones the way it did under displacement.

    Measured after the redesign: 22 Scroll events across 7 separate SCROLL
    entries, totalling ~2097 px over the 15 s recording (155 of its frames
    are spent in SCROLL; scroll fires on about a third of the recording's
    duration). This does not try to reproduce the old pixel total -- that
    would just re-encode SCROLL_RATE_GAIN as a second magic number here,
    and this recording was never re-taken as a deliberate rate-model
    gesture (hold-and-release, not sweep) -- it pins the property that
    still matters: a 15 s deliberate scroll session produces multiple real
    Scroll events adding up to a meaningful amount, comfortably under the
    measured figures so ordinary retuning doesn't break it.
    """
    out = _replay("scroll_attempt")
    scrolls = [i for i in out if isinstance(i, Scroll)]
    assert len(scrolls) >= 10
    total = sum(abs(s.dy) for s in scrolls)
    assert total > 500.0


def test_middle_pinch_recording_yields_click_two_and_still_proves_disambiguation():
    """recordings/middle_pinch.jsonl: 15 s, 8 deliberate middle-pinches,
    plus one accidental hold and two genuine index pinches (see the spec).

    Under the new model there is no click-vs-drag travel or dwell budget
    left to lose registrations to: Click(2) fires the instant the pinch
    closes, resolved by the same closer-finger-at-pinch-down rule as
    before. That rule is still doing real work here -- several of these
    frames read the index channel as closed too (pinching the middle
    fingertip to the thumb drags the index along with it), and the closer
    check is what keeps those from registering as a spurious ButtonDown.
    9 middle-pinch closures resolve to Click(2), and exactly one
    (index-closer) closure produces a ButtonDown/ButtonUp pair -- more
    Click(2)s than under any prior travel-budget rule, and zero cases of
    the wrong gesture firing.
    """
    out = _replay("middle_pinch")
    assert [i for i in out if isinstance(i, Click)] == [Click(2)] * 9
    assert len([i for i in out if isinstance(i, ButtonDown)]) == 1
    assert len([i for i in out if isinstance(i, ButtonUp)]) == 1


def test_live_clicks_recording_never_produces_a_click_two():
    """Every tap in live_clicks.jsonl is a genuine index click; the index
    reads closer to the thumb than the middle on every one of them, so the
    closer-finger rule must never resolve any of them to Click(2)."""
    assert Click(2) not in _replay("live_clicks")


def test_five_clicks_recording_never_produces_a_click_two():
    """Same standard as live_clicks.jsonl: five genuine index clicks, zero
    Click(2)s under the closer-finger rule."""
    assert Click(2) not in _replay("five_clicks")


# --- The clutch: INDEX_CURL_CLOSE / INDEX_CURL_OPEN calibration ---
#
# Calibrated against recordings/clutch.jsonl (see config.py). A pinch
# misread as a curl would freeze the cursor mid-drag -- the worst possible
# failure for this feature -- so this is verified against every
# pinch-containing fixture, not just the dedicated clutch recording.
PINCH_FIXTURES = ("five_clicks", "one_double_click", "live_clicks", "drag_a_to_b", "middle_pinch")


# UPDATE (2026-08-19 follow-up, PINCH_MIN_EXTENSION/PINCH2_MIN_EXTENSION):
# the NOTE that used to sit here recorded that clutch.jsonl still produced
# one spurious Click(2), at t=1.628s (index_curl_ratio=1.948), and asserted
# it was "a transient pinch2_ratio dip during ordinary pointing motion with
# no connection to curling at all" -- structurally outside what the
# curl-gate above could fix. That diagnosis was wrong: at that exact frame
# middle_curl_ratio=0.966, well below PINCH2_MIN_EXTENSION (1.10) -- the
# middle finger itself was genuinely curled at that moment, just not the
# index finger the old curl-gate watches. The extension gate added below
# (config.py's PINCH_MIN_EXTENSION comment) catches it, along with every
# other spurious press in this recording: replaying clutch.jsonl now
# produces zero ButtonDown, ButtonUp, or Click(2) of any kind -- see
# test_clutch_recording_never_ends_with_the_button_stuck_down below, which
# pins the exact count instead of the "at least one, but matched" property
# it used to.
def test_clutch_recording_produces_no_press_on_a_curled_frame():
    """The core of the fix, pinned at the mechanism, not just an aggregate
    count. In recordings/clutch.jsonl every one of the 124 curled frames
    reads pinch_ratio as low as 0.01 -- geometrically indistinguishable
    from a real pinch (see config.py's INDEX_CURL_CLOSE comment) -- so
    before this fix any of them could fire a spurious ButtonDown or
    Click(2). Replays the recording through a fresh state machine and
    asserts no ButtonDown or Click(2) is ever emitted on a frame where
    index_curl_ratio itself reads as curled.
    """
    sm = StateMachine()
    for fr in read_session(f"{FIXTURES}/clutch.jsonl"):
        f = extract(fr)
        out = sm.update(f)
        if f.present and f.index_curl_ratio < config.INDEX_CURL_CLOSE:
            assert not any(isinstance(i, (ButtonDown, Click)) for i in out), (
                f"t={f.t:.3f}: curled frame (index_curl_ratio="
                f"{f.index_curl_ratio:.3f}) produced {out}"
            )


def test_clutch_recording_never_ends_with_the_button_stuck_down():
    """The safety property the 2026-08-11 curl-gate fix exists for. Before
    it, recordings/clutch.jsonl left the state machine stuck in PRESSED: a
    spurious pinch reading during a curl fired ButtonDown at t=14.208s,
    never matched by a ButtonUp before the recording ended -- a stuck
    mouse button. Curl is evaluated before pinch every frame, and an
    already-open button is safety-released (ButtonUp) the instant curl
    engages, so every ButtonDown in this recording must be matched by a
    ButtonUp -- this holds regardless of how many presses fire, so it is
    pinned independently of the exact-zero count below.

    That count used to be "at least one" -- this recording used to still
    produce a couple of spurious presses even after the curl-gate fix (see
    the UPDATE note above test_clutch_recording_produces_no_press_on_a_
    curled_frame). The 2026-08-19 extension gate (PINCH_MIN_EXTENSION /
    PINCH2_MIN_EXTENSION, see config.py) eliminates the rest of them: this
    recording now produces zero ButtonDown, ButtonUp, and Click(2) events
    of any kind.
    """
    out = _replay("clutch")
    downs = [i for i in out if isinstance(i, ButtonDown)]
    ups = [i for i in out if isinstance(i, ButtonUp)]
    clicks = [i for i in out if isinstance(i, Click)]
    assert len(downs) == len(ups)  # never stuck, regardless of count
    assert downs == []
    assert clicks == []


def test_a_pinch_never_reads_as_a_curl():
    """Driven by real fixture data across all five pinch-containing
    recordings: replaying through the state machine and asserting it never
    enters FROZEN while pressed is redundant with the enum itself (PRESSED
    and FROZEN are mutually exclusive states, so that would hold trivially
    regardless of calibration). The real guarantee lives one level down, at
    the feature values: no frame where the pinch reads closed
    (`pinch_ratio < PINCH_CLOSE`) may also read as a curl
    (`index_curl_ratio < INDEX_CURL_CLOSE`). The lowest index_curl_ratio
    seen during any pinch, across all five fixtures, is 1.03 -- comfortably
    above INDEX_CURL_CLOSE.
    """
    for name in PINCH_FIXTURES:
        path = f"{FIXTURES}/{name}.jsonl"
        try:
            frames = read_session(path)
        except FileNotFoundError:
            pytest.skip(f"fixture {path} not recorded yet")
        for frame in frames:
            f = extract(frame)
            if f.present and f.pinch_ratio < config.PINCH_CLOSE:
                assert f.index_curl_ratio >= config.INDEX_CURL_CLOSE, (
                    f"{name} t={f.t:.3f}: pinch_ratio={f.pinch_ratio:.3f} "
                    f"closed, but index_curl_ratio={f.index_curl_ratio:.3f} "
                    f"also reads as curled -- this pinch would freeze the "
                    f"cursor mid-drag"
                )
