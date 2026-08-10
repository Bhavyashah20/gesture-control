# Gesture Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS webcam gesture controller that replaces trackpad pointer input with one-handed gestures — move, click, double-click, drag, scroll, and fullscreen Space switching.

**Architecture:** A one-way pipeline (camera → landmarks → features → gate → state machine → filter → actuator) in which only the final actuator stage touches the OS. Everything upstream is pure and unit-testable, which is what makes threshold tuning measurable rather than guesswork. Recorded landmark sessions replay through the pure core to assert exact intent sequences.

**Tech Stack:** Python 3.13, MediaPipe 1.0.0 (HandLandmarker), OpenCV 5.0, pyobjc Quartz (CGEvent), Tkinter (HUD), pytest.

## Global Constraints

Every task's requirements implicitly include this section.

- Target platform: macOS 26, Apple Silicon (arm64). Primary display only.
- Python 3.13 in a project venv at `.venv`. The system `python3` is miniconda base — do not install into it.
- Pinned dependencies: `mediapipe==1.0.0`, `opencv-python>=5.0`, `pyobjc-framework-Quartz>=12.2`, `pytest>=8.0`.
- Only `actuator.py`, `capture.py`, `landmarks.py`, `hud.py`, and `main.py` may perform I/O or import OS libraries. `features.py`, `gate.py`, `state_machine.py`, `filters.py`, and `types.py` must import nothing outside the standard library.
- All tuning constants live in `config.py`. No numeric literal governing behaviour may appear in any other module.
- All timestamps are monotonic seconds as `float`. Config durations are in seconds (`_S` suffix), never milliseconds.
- Image coordinates are normalized `[0, 1]`, mirrored (`x → 1 - x`) exactly once, in `features.py`.
- Screen coordinates use Quartz top-left origin throughout. Never use `NSEvent.mouseLocation`.
- Sentence case in all user-facing strings. No emoji in code or output.

## Design deviations from the spec

Two implementation refinements, both deliberate:

1. **`types.py` is added** to the module list. The spec's dataclasses are shared by `features`, `state_machine`, and `actuator`; a separate module prevents an import cycle.
2. **MediaPipe runs in VIDEO mode, not LIVE_STREAM.** LIVE_STREAM delivers results via an async callback with no ordering guarantee, which would make replay tests non-deterministic. VIDEO mode is synchronous and takes an explicit timestamp — the determinism is worth more here than the marginal throughput.

## File structure

| File | Responsibility |
|---|---|
| `src/gesture_control/types.py` | Shared data types: `Point2`, `Point3`, `HandFrame`, `Features`, and the `Intent` union |
| `src/gesture_control/config.py` | Every tuning constant, one place |
| `src/gesture_control/features.py` | 21 landmarks → `Features`. Pure |
| `src/gesture_control/gate.py` | Posture arming with asymmetric hysteresis. Pure |
| `src/gesture_control/filters.py` | One Euro filter and the pointer gain curve. Pure |
| `src/gesture_control/state_machine.py` | States, transitions, intent emission. Pure |
| `src/gesture_control/capture.py` | Webcam frames |
| `src/gesture_control/landmarks.py` | MediaPipe HandLandmarker wrapper |
| `src/gesture_control/recorder.py` | Read/write `.jsonl` landmark sessions |
| `src/gesture_control/actuator.py` | `Intent` → CGEvent, plus the dry-run logger |
| `src/gesture_control/hud.py` | Always-on-top state pill; owns the Tk main loop |
| `src/gesture_control/main.py` | CLI, permission preflight, pipeline wiring |

---

### Task 1: Project scaffolding, types, and config

**Files:**
- Create: `pyproject.toml`
- Create: `src/gesture_control/__init__.py`
- Create: `src/gesture_control/types.py`
- Create: `src/gesture_control/config.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Point2(x, y)`, `Point3(x, y, z)` as `NamedTuple`; `HandFrame(points, t, present, handedness)`; `Features(pinch_ratio, fingers_up, palm_facing, hand_scale, cursor_ref, t, present)`; intents `Move(dx, dy)`, `Click(n)`, `DragStart()`, `DragEnd()`, `Scroll(dy)`, `Space(direction)`; and the `Intent` union alias. All config constants by name.

- [ ] **Step 1: Create the venv and install dependencies**

```bash
cd ~/temp/gesture_control
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "mediapipe==1.0.0" "opencv-python>=5.0" "pyobjc-framework-Quartz>=12.2" "pytest>=8.0"
.venv/bin/python -c "import mediapipe, cv2, Quartz, tkinter; print('deps ok')"
```

Expected: `deps ok`

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "gesture-control"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "mediapipe==1.0.0",
    "opencv-python>=5.0",
    "pyobjc-framework-Quartz>=12.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_types.py
from gesture_control.types import (
    Point2, Point3, HandFrame, Features, Move, Click, DragStart, DragEnd,
    Scroll, Space,
)
from gesture_control import config


def test_points_are_tuples():
    assert Point2(1.0, 2.0) == (1.0, 2.0)
    assert Point3(1.0, 2.0, 3.0).z == 3.0


def test_hand_frame_absent_has_no_points():
    f = HandFrame(points=(), t=0.5, present=False, handedness="")
    assert f.present is False
    assert f.points == ()


def test_features_carry_four_fingers():
    f = Features(
        pinch_ratio=0.5, fingers_up=(True, True, False, False), palm_facing=True,
        hand_scale=0.2, cursor_ref=Point2(0.5, 0.5), t=1.0, present=True,
    )
    assert len(f.fingers_up) == 4


def test_intents_are_comparable_by_value():
    assert Move(1.0, 2.0) == Move(1.0, 2.0)
    assert Click(2) != Click(1)
    assert DragStart() == DragStart()
    assert DragEnd() == DragEnd()
    assert Scroll(3.0) == Scroll(3.0)
    assert Space("right") != Space("left")


def test_pinch_thresholds_have_hysteresis_gap():
    assert config.PINCH_CLOSE < config.PINCH_OPEN


def test_gate_dwells_are_asymmetric():
    assert config.DISARM_S > config.ARM_DWELL_S
```

Value equality on intents matters: every replay test asserts on lists of intents, so `Move(1.0, 2.0) == Move(1.0, 2.0)` must hold.

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control'`

- [ ] **Step 5: Write `src/gesture_control/types.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class Point2(NamedTuple):
    x: float
    y: float


class Point3(NamedTuple):
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class HandFrame:
    points: tuple[Point3, ...]
    t: float
    present: bool
    handedness: str


@dataclass(frozen=True)
class Features:
    pinch_ratio: float
    fingers_up: tuple[bool, bool, bool, bool]
    palm_facing: bool
    hand_scale: float
    cursor_ref: Point2
    t: float
    present: bool


@dataclass(frozen=True)
class Move:
    dx: float
    dy: float


@dataclass(frozen=True)
class Click:
    n: int


@dataclass(frozen=True)
class DragStart:
    pass


@dataclass(frozen=True)
class DragEnd:
    pass


@dataclass(frozen=True)
class Scroll:
    dy: float


@dataclass(frozen=True)
class Space:
    direction: str


Intent = Move | Click | DragStart | DragEnd | Scroll | Space
```

- [ ] **Step 6: Write `src/gesture_control/config.py`**

```python
"""Every constant that governs behaviour. Tuning happens here and nowhere else."""

PINCH_CLOSE = 0.35
PINCH_OPEN = 0.45

ARM_DWELL_S = 0.300
DISARM_S = 0.500
HAND_SCALE_MIN = 0.08
HAND_SCALE_MAX = 0.45
FINGER_EXT_RATIO = 1.15
ARM_FINGERS_MIN = 3

TAP_MAX_S = 0.250
TAP_MAX_PX = 15.0
DOUBLE_MAX_S = 0.350
DOUBLE_MAX_PX = 30.0
DRAG_DWELL_S = 0.400

BASE_GAIN_PX = 1600.0
ACCEL_MIN = 0.35
ACCEL_MAX = 2.5
ACCEL_VREF = 1.2

SCROLL_GAIN = 900.0
SCROLL_DWELL_S = 0.200
SCROLL_MIN_PX = 1.0

SWIPE_VEL = 0.8
SWIPE_DIST = 0.20
SWIPE_HOLD_S = 0.100
SWIPE_WINDOW_S = 0.350
SWIPE_COOLDOWN_S = 0.800

EURO_MIN_CUTOFF = 1.0
EURO_BETA = 0.7
EURO_D_CUTOFF = 1.0

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_FPS = 30
```

Also create an empty `src/gesture_control/__init__.py`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_types.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/gesture_control/__init__.py src/gesture_control/types.py src/gesture_control/config.py tests/test_types.py
git commit -m "feat: add project scaffolding, shared types, and tuning config"
```

---

### Task 2: Feature extraction

**Files:**
- Create: `src/gesture_control/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Consumes: `HandFrame`, `Features`, `Point2`, `Point3` from `types`; `FINGER_EXT_RATIO` from `config`
- Produces: `extract(frame: HandFrame) -> Features`; landmark index constants `WRIST`, `THUMB_TIP`, `INDEX_MCP`, `MIDDLE_MCP`, `PINKY_MCP`; helper `make_hand(...)` is NOT produced here — test fixtures live in the test file.

**Background the implementer needs.** MediaPipe returns 21 landmarks per hand in a fixed order: 0 is the wrist; 1–4 are the thumb (4 = tip); 5–8 index (5 = MCP knuckle, 6 = PIP, 8 = tip); 9–12 middle; 13–16 ring; 17–20 pinky. Coordinates are normalized to `[0, 1]` with **y increasing downward**, as in image space.

Two decisions carry the design and must not be "simplified" away:

- **`cursor_ref` is landmark 5, the index MCP knuckle** — not a fingertip. The knuckle barely moves when the thumb and index close, so the cursor does not jump at the instant of a pinch. A fingertip translates several millimetres during the same motion, which makes small targets unhittable.
- **Every distance is divided by `hand_scale`**, so thresholds hold at any distance from the camera.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_features.py
import math

from gesture_control import config
from gesture_control.features import extract
from gesture_control.types import HandFrame, Point3


def make_hand(scale=1.0, pinch=0.30, fingers=(True, True, True, True),
              left=False, offset=(0.0, 0.0), t=0.0):
    """Build a synthetic right hand, palm to camera, fingers up.

    Coordinates are pre-mirror (raw camera space), so extract() will flip x.
    In raw space a right hand has its index knuckle to the RIGHT of its pinky.

    `pinch` is how far the thumb has closed toward the index tip: 0.0 is wide
    open and 0.9 is fully closed. It is therefore INVERSELY related to the
    resulting pinch_ratio.
    """
    ox, oy = offset
    pts = [Point3(0.0, 0.0, 0.0)] * 21

    def put(i, x, y):
        pts[i] = Point3(ox + x * scale, oy + y * scale, 0.0)

    put(0, 0.50, 0.60)                      # wrist
    put(9, 0.50, 0.40)                      # middle MCP -> hand_scale = 0.20
    put(5, 0.56, 0.42)                      # index MCP (raw: right of pinky)
    put(17, 0.44, 0.42)                     # pinky MCP
    put(4, 0.56, 0.42 - pinch * 0.20)       # thumb tip, pinch is a ratio

    for idx, (pip, tip) in enumerate([(6, 8), (10, 12), (14, 16), (18, 20)]):
        base_x = 0.56 - idx * 0.04
        put(pip, base_x, 0.34)
        put(tip, base_x, 0.24 if fingers[idx] else 0.36)

    if left:
        pts = [Point3(1.0 - p.x, p.y, p.z) for p in pts]

    return HandFrame(points=tuple(pts), t=t, present=True,
                     handedness="Left" if left else "Right")


def test_absent_frame_yields_absent_features():
    f = extract(HandFrame(points=(), t=1.0, present=False, handedness=""))
    assert f.present is False
    assert f.t == 1.0


def test_hand_scale_is_wrist_to_middle_knuckle():
    f = extract(make_hand())
    assert math.isclose(f.hand_scale, 0.20, abs_tol=1e-6)


def test_pinch_ratio_is_invariant_to_hand_scale():
    near = extract(make_hand(scale=1.0, pinch=0.30))
    far = extract(make_hand(scale=0.5, pinch=0.30))
    assert math.isclose(near.pinch_ratio, far.pinch_ratio, abs_tol=1e-6)


def test_pinch_ratio_tracks_thumb_distance():
    """Higher `pinch` means more pinched, so it must yield a LOWER ratio."""
    open_hand = extract(make_hand(pinch=0.10))
    closed = extract(make_hand(pinch=0.90))
    assert open_hand.pinch_ratio > closed.pinch_ratio


def test_finger_extension_detected_per_finger():
    f = extract(make_hand(fingers=(True, True, False, False)))
    assert f.fingers_up == (True, True, False, False)


def test_mirroring_applied_exactly_once():
    """Raw index MCP at x=0.56 must surface as 1 - 0.56 = 0.44."""
    f = extract(make_hand())
    assert math.isclose(f.cursor_ref.x, 0.44, abs_tol=1e-6)


def test_cursor_ref_is_index_knuckle_not_fingertip():
    """Closing the pinch must barely move cursor_ref."""
    a = extract(make_hand(pinch=0.90))
    b = extract(make_hand(pinch=0.05))
    moved = math.dist(a.cursor_ref, b.cursor_ref)
    assert moved < 1e-9


def test_palm_facing_true_for_right_hand_toward_camera():
    assert extract(make_hand()).palm_facing is True


def test_palm_facing_true_for_left_hand_toward_camera():
    assert extract(make_hand(left=True)).palm_facing is True


def test_cursor_ref_translates_with_the_hand():
    a = extract(make_hand())
    b = extract(make_hand(offset=(0.10, 0.0)))
    assert b.cursor_ref.x < a.cursor_ref.x  # mirrored: raw +x is user -x
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_features.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.features'`

- [ ] **Step 3: Write `src/gesture_control/features.py`**

```python
from __future__ import annotations

import math

from . import config
from .types import Features, HandFrame, Point2, Point3

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
PINKY_MCP = 17

FINGER_JOINTS = ((6, 8), (10, 12), (14, 16), (18, 20))

_ABSENT = Features(
    pinch_ratio=1.0,
    fingers_up=(False, False, False, False),
    palm_facing=False,
    hand_scale=0.0,
    cursor_ref=Point2(0.5, 0.5),
    t=0.0,
    present=False,
)


def _mirror(p: Point3) -> Point3:
    return Point3(1.0 - p.x, p.y, p.z)


def _dist(a: Point3, b: Point3) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _palm_facing(pts: tuple[Point3, ...], handedness: str) -> bool:
    wrist = pts[WRIST]
    v1x, v1y = pts[INDEX_MCP].x - wrist.x, pts[INDEX_MCP].y - wrist.y
    v2x, v2y = pts[PINKY_MCP].x - wrist.x, pts[PINKY_MCP].y - wrist.y
    cross_z = v1x * v2y - v1y * v2x
    return cross_z > 0.0 if handedness == "Right" else cross_z < 0.0


def extract(frame: HandFrame) -> Features:
    if not frame.present or len(frame.points) < 21:
        return Features(**{**_ABSENT.__dict__, "t": frame.t})

    pts = tuple(_mirror(p) for p in frame.points)
    scale = _dist(pts[WRIST], pts[MIDDLE_MCP])
    if scale <= 0.0:
        return Features(**{**_ABSENT.__dict__, "t": frame.t})

    pinch = _dist(pts[THUMB_TIP], pts[INDEX_TIP]) / scale

    fingers = tuple(
        _dist(pts[WRIST], pts[tip]) > config.FINGER_EXT_RATIO * _dist(pts[WRIST], pts[pip])
        for pip, tip in FINGER_JOINTS
    )

    return Features(
        pinch_ratio=pinch,
        fingers_up=fingers,
        palm_facing=_palm_facing(pts, frame.handedness),
        hand_scale=scale,
        cursor_ref=Point2(pts[INDEX_MCP].x, pts[INDEX_MCP].y),
        t=frame.t,
        present=True,
    )
```

Note on finger extension: comparing distance-from-wrist for tip versus PIP is deliberately rotation-invariant. Comparing y coordinates instead would break the moment the hand tilts.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_features.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/gesture_control/features.py tests/test_features.py
git commit -m "feat: extract scale-invariant hand features from landmarks"
```

---

### Task 3: Posture gate

**Files:**
- Create: `src/gesture_control/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `Features` from `types`; `ARM_DWELL_S`, `DISARM_S`, `HAND_SCALE_MIN`, `HAND_SCALE_MAX`, `ARM_FINGERS_MIN` from `config`
- Produces: `class Gate` with `update(f: Features) -> bool` and read-only property `armed: bool`

**The critical asymmetry.** Arming requires at least three extended fingers. *Staying* armed must not, because pinching curls the index finger — a symmetric condition would disarm the system the instant the user tried to click. Arming is strict, sustaining is loose. The test below (`test_stays_armed_when_fingers_curl_to_pinch`) is the regression guard for exactly this.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gate.py
from gesture_control.gate import Gate
from gesture_control.types import Features, Point2


def feat(t, fingers=(True, True, True, True), palm=True, scale=0.20, present=True):
    return Features(
        pinch_ratio=0.9, fingers_up=fingers, palm_facing=palm,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.gate'`

- [ ] **Step 3: Write `src/gesture_control/gate.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_gate.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/gesture_control/gate.py tests/test_gate.py
git commit -m "feat: add posture gate with asymmetric arm and disarm dwells"
```

---

### Task 4: One Euro filter and pointer gain

**Files:**
- Create: `src/gesture_control/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `Point2` from `types`; `EURO_MIN_CUTOFF`, `EURO_BETA`, `EURO_D_CUTOFF`, `BASE_GAIN_PX`, `ACCEL_MIN`, `ACCEL_MAX`, `ACCEL_VREF` from `config`
- Produces: `class OneEuroFilter` with `filter(x: float, t: float) -> float`; `class Point2Filter` with `filter(p: Point2, t: float) -> Point2`; `accel(speed: float) -> float`; `apply_gain(dx: float, dy: float, dt: float) -> tuple[float, float]`

**Why One Euro rather than a moving average.** A fixed-window average forces one choice for all speeds: enough smoothing to kill hand tremor also adds lag you feel on fast movements. One Euro adapts its cutoff to the observed speed — heavy smoothing when nearly still, light when moving. The algorithm: low-pass the derivative, use its magnitude to raise the cutoff, then low-pass the signal at that cutoff.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filters.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.filters'`

- [ ] **Step 3: Write `src/gesture_control/filters.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_filters.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/gesture_control/filters.py tests/test_filters.py
git commit -m "feat: add one euro filter and adaptive pointer gain"
```

---

### Task 5: State machine core — disarmed, armed idle, tracking

**Files:**
- Create: `src/gesture_control/state_machine.py`
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Consumes: `Gate` from `gate`; `Point2Filter`, `apply_gain` from `filters`; `Features`, `Move`, `DragEnd`, `Intent` from `types`; `PINCH_CLOSE`, `PINCH_OPEN` from `config`
- Produces: `class State(Enum)` with members `DISARMED`, `ARMED_IDLE`, `TRACKING`, `DRAG`, `SCROLL`; `class StateMachine` with `update(f: Features) -> list[Intent]`, property `state: State`, and property `virtual_pos: Point2` (accumulated screen-space cursor position, used for double-click proximity in Task 6)

**Scope of this task.** Only `DISARMED`, `ARMED_IDLE`, and `TRACKING` with `Move` emission. `DRAG` and `SCROLL` are declared in the enum so later tasks do not have to modify it, but nothing transitions into them yet. Clicks arrive in Task 6, scroll and swipe in Task 7.

**Why a virtual cursor position.** Double-click proximity is specified in screen pixels, but the state machine must stay pure and cannot query the real cursor. It therefore accumulates its own position starting at `(0, 0)`. Because both use the same gain, distances in virtual space equal distances on screen.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state_machine.py
from gesture_control.state_machine import State, StateMachine
from gesture_control.types import Features, Move, Point2


def feat(t, pinch=0.9, fingers=(True, True, True, True), palm=True,
         ref=(0.5, 0.5), scale=0.20, present=True):
    return Features(
        pinch_ratio=pinch, fingers_up=fingers, palm_facing=palm,
        hand_scale=scale, cursor_ref=Point2(*ref), t=t, present=present,
    )


def arm(sm, t0=0.0):
    """Drive the machine through the arming dwell. Returns the next timestamp."""
    sm.update(feat(t0))
    sm.update(feat(t0 + 0.4))
    assert sm.state is State.ARMED_IDLE
    return t0 + 0.5


def test_starts_disarmed():
    assert StateMachine().state is State.DISARMED


def test_disarmed_emits_nothing():
    sm = StateMachine()
    assert sm.update(feat(0.0)) == []


def test_arms_after_dwell():
    sm = StateMachine()
    sm.update(feat(0.0))
    assert sm.state is State.DISARMED
    sm.update(feat(0.4))
    assert sm.state is State.ARMED_IDLE


def test_armed_idle_does_not_move_the_cursor():
    """This is what makes the clutch a clutch."""
    sm = StateMachine()
    t = arm(sm)
    out = sm.update(feat(t, ref=(0.9, 0.9)))
    assert out == []
    assert sm.state is State.ARMED_IDLE


def test_pinch_enters_tracking():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.state is State.TRACKING


def test_tracking_emits_move_on_hand_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.1, pinch=0.2, ref=(0.6, 0.5)))
    moves = [i for i in out if isinstance(i, Move)]
    assert len(moves) == 1
    assert moves[0].dx > 0.0


def test_pinch_uses_hysteresis():
    """Between the two thresholds the pinch state must not change."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.1, pinch=0.40))
    assert sm.state is State.TRACKING
    sm.update(feat(t + 0.2, pinch=0.50))
    assert sm.state is State.ARMED_IDLE


def test_release_returns_to_armed_idle():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.5, pinch=0.9))
    assert sm.state is State.ARMED_IDLE


def test_losing_posture_disarms():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, present=False))
    sm.update(feat(t + 0.6, present=False))
    assert sm.state is State.DISARMED


def test_virtual_position_accumulates_moves():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.1, pinch=0.2, ref=(0.6, 0.5)))
    assert sm.virtual_pos.x > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.state_machine'`

- [ ] **Step 3: Write `src/gesture_control/state_machine.py`**

```python
from __future__ import annotations

from enum import Enum, auto

from . import config
from .filters import Point2Filter, apply_gain
from .gate import Gate
from .types import DragEnd, Features, Intent, Move, Point2


class State(Enum):
    DISARMED = auto()
    ARMED_IDLE = auto()
    TRACKING = auto()
    DRAG = auto()
    SCROLL = auto()


class StateMachine:
    """Pure gesture logic. Consumes Features, produces Intents. No I/O."""

    def __init__(self) -> None:
        self._gate = Gate()
        self._filter = Point2Filter()
        self._state = State.DISARMED
        self._ref: Point2 | None = None
        self._t: float | None = None
        self._pinch_closed = False
        self._virtual = Point2(0.0, 0.0)

    @property
    def state(self) -> State:
        return self._state

    @property
    def virtual_pos(self) -> Point2:
        return self._virtual

    def _reset_transient(self) -> None:
        self._pinch_closed = False
        self._ref = None
        self._t = None

    def _update_pinch(self, f: Features) -> tuple[bool, bool]:
        """Returns (pressed_this_frame, released_this_frame)."""
        if self._pinch_closed:
            if f.pinch_ratio > config.PINCH_OPEN:
                self._pinch_closed = False
                return False, True
        else:
            if f.pinch_ratio < config.PINCH_CLOSE:
                self._pinch_closed = True
                return True, False
        return False, False

    def update(self, f: Features) -> list[Intent]:
        intents: list[Intent] = []
        armed = self._gate.update(f)

        if not armed:
            if self._state is State.DRAG:
                intents.append(DragEnd())
            self._state = State.DISARMED
            self._reset_transient()
            return intents

        ref = self._filter.filter(f.cursor_ref, f.t)

        if self._state is State.DISARMED:
            self._state = State.ARMED_IDLE
            self._ref, self._t = ref, f.t
            return intents

        dt = f.t - self._t if self._t is not None else 0.0
        dxn = ref.x - self._ref.x if self._ref is not None else 0.0
        dyn = ref.y - self._ref.y if self._ref is not None else 0.0
        self._ref, self._t = ref, f.t

        pressed, released = self._update_pinch(f)

        if self._state is State.ARMED_IDLE:
            if pressed:
                self._state = State.TRACKING
            return intents

        if self._state is State.TRACKING:
            if released:
                self._state = State.ARMED_IDLE
                return intents
            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                intents.append(Move(dxp, dyp))
            return intents

        return intents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/gesture_control/state_machine.py tests/test_state_machine.py
git commit -m "feat: add state machine core with clutch cursor tracking"
```

---

### Task 6: Click, double-click, and drag

**Files:**
- Modify: `src/gesture_control/state_machine.py`
- Test: `tests/test_state_machine.py` (append)

**Interfaces:**
- Consumes: everything from Task 5; `Click`, `DragStart` from `types`; `TAP_MAX_S`, `TAP_MAX_PX`, `DOUBLE_MAX_S`, `DOUBLE_MAX_PX`, `DRAG_DWELL_S` from `config`
- Produces: no new public names. `StateMachine.update` now emits `Click(1)`, `Click(2)`, `DragStart()`, `DragEnd()` and can reach `State.DRAG`.

**The disambiguation rule.** All three pinch outcomes begin identically, so the machine records time and virtual position at pinch-down and decides from what follows. **All distances are cursor screen pixels after gain**, accumulated since pinch-down — never raw hand displacement. Measuring post-gain keeps the click tolerance constant in the space the user perceives, instead of varying with distance from the camera.

Double-click is emitted as a single `Click(2)`, not two `Click(1)`s. The actuator sets the Quartz click-state field on one event pair; posting two separate clicks and hoping macOS coalesces them is unreliable.

- [ ] **Step 1: Write the failing tests (append to `tests/test_state_machine.py`)**

```python
from gesture_control.types import Click, DragEnd, DragStart


def test_quick_pinch_release_emits_single_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.10, pinch=0.9))
    assert out == [Click(1)]


def test_slow_release_is_not_a_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.30, pinch=0.9))
    assert out == []


def test_release_after_moving_far_is_not_a_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.05, pinch=0.2, ref=(0.75, 0.5)))
    out = sm.update(feat(t + 0.10, pinch=0.9))
    assert not any(isinstance(i, Click) for i in out)


def test_two_quick_taps_emit_click_two():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.update(feat(t + 0.08, pinch=0.9)) == [Click(1)]
    sm.update(feat(t + 0.20, pinch=0.2))
    assert sm.update(feat(t + 0.28, pinch=0.9)) == [Click(2)]


def test_slow_second_tap_is_a_fresh_single_click():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    assert sm.update(feat(t + 0.08, pinch=0.9)) == [Click(1)]
    sm.update(feat(t + 1.00, pinch=0.2))
    assert sm.update(feat(t + 1.08, pinch=0.9)) == [Click(1)]


def test_triple_tap_does_not_emit_click_three():
    sm = StateMachine()
    t = arm(sm)
    for i in range(3):
        sm.update(feat(t + i * 0.20, pinch=0.2))
        out = sm.update(feat(t + i * 0.20 + 0.08, pinch=0.9))
        assert out[0].n in (1, 2)


def test_holding_pinch_still_starts_a_drag():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = sm.update(feat(t + 0.45, pinch=0.2))
    assert DragStart() in out
    assert sm.state is State.DRAG


def test_drag_emits_moves_then_one_drag_end():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.45, pinch=0.2))
    mid = sm.update(feat(t + 0.55, pinch=0.2, ref=(0.6, 0.5)))
    assert any(isinstance(i, Move) for i in mid)
    end = sm.update(feat(t + 0.70, pinch=0.9))
    assert end == [DragEnd()]
    assert sm.state is State.ARMED_IDLE


def test_moving_before_the_dwell_prevents_a_drag():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.10, pinch=0.2, ref=(0.80, 0.5)))
    out = sm.update(feat(t + 0.50, pinch=0.2))
    assert not any(isinstance(i, DragStart) for i in out)
    assert sm.state is State.TRACKING


def test_hand_vanishing_mid_drag_releases_the_button():
    """The stuck-button guard. Without this macOS keeps the button held.

    The absent frames must keep the pinch CLOSED. If they carried an open
    pinch, the ordinary release path would end the drag and the watchdog
    would never be exercised.
    """
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    sm.update(feat(t + 0.45, pinch=0.2))
    assert sm.state is State.DRAG
    sm.update(feat(t + 0.60, pinch=0.2, present=False))
    assert sm.state is State.DRAG  # still held, within DISARM_S
    out = sm.update(feat(t + 1.20, pinch=0.2, present=False))
    assert DragEnd() in out
    assert sm.state is State.DISARMED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: the 10 new tests FAIL; the 10 from Task 5 still pass

- [ ] **Step 3: Extend `__init__` and `_reset_transient`**

Add to `StateMachine.__init__`:

```python
        self._pinch_t0: float | None = None
        self._pinch_travel = 0.0
        self._last_click_t: float | None = None
        self._last_click_pos: Point2 | None = None
```

Replace `_reset_transient` with:

```python
    def _reset_transient(self) -> None:
        self._pinch_closed = False
        self._ref = None
        self._t = None
        self._pinch_t0 = None
        self._pinch_travel = 0.0
```

Note that `_last_click_t` and `_last_click_pos` are deliberately *not* cleared: a double-click straddling a momentary disarm is still the user's intent.

- [ ] **Step 4: Record the anchor on pinch-down**

In `update`, replace the `ARMED_IDLE` branch:

```python
        if self._state is State.ARMED_IDLE:
            if pressed:
                self._state = State.TRACKING
                self._pinch_t0 = f.t
                self._pinch_travel = 0.0
            return intents
```

- [ ] **Step 5: Add a click-classification helper**

```python
    def _classify_release(self, f: Features) -> list[Intent]:
        held = f.t - self._pinch_t0 if self._pinch_t0 is not None else 0.0
        if held > config.TAP_MAX_S or self._pinch_travel >= config.TAP_MAX_PX:
            return []

        n = 1
        if self._last_click_t is not None and self._last_click_pos is not None:
            gap = f.t - self._last_click_t
            near = math.dist(self._virtual, self._last_click_pos)
            if gap <= config.DOUBLE_MAX_S and near <= config.DOUBLE_MAX_PX:
                n = 2

        self._last_click_t = f.t
        self._last_click_pos = self._virtual if n == 1 else None
        return [Click(n)]
```

Setting `_last_click_pos` to `None` after a double-click is what stops a third tap becoming `Click(3)`: the proximity check then fails and the sequence restarts at `Click(1)`.

Add `import math` at the top of the module, and extend the `types` import to include `Click` and `DragStart`.

- [ ] **Step 6: Replace the `TRACKING` branch and add `DRAG`**

```python
        if self._state is State.TRACKING:
            if released:
                self._state = State.ARMED_IDLE
                return self._classify_release(f)

            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                self._pinch_travel += math.hypot(dxp, dyp)
                intents.append(Move(dxp, dyp))

            held = f.t - self._pinch_t0 if self._pinch_t0 is not None else 0.0
            if held > config.DRAG_DWELL_S and self._pinch_travel < config.TAP_MAX_PX:
                self._state = State.DRAG
                intents.append(DragStart())
            return intents

        if self._state is State.DRAG:
            if released:
                self._state = State.ARMED_IDLE
                intents.append(DragEnd())
                return intents
            dxp, dyp = apply_gain(dxn, dyn, dt)
            if dxp or dyp:
                self._virtual = Point2(self._virtual.x + dxp, self._virtual.y + dyp)
                intents.append(Move(dxp, dyp))
            return intents
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: 20 passed

- [ ] **Step 8: Commit**

```bash
git add src/gesture_control/state_machine.py tests/test_state_machine.py
git commit -m "feat: add click, double-click, and drag disambiguation"
```

---

### Task 7: Scroll and Space switching

**Files:**
- Modify: `src/gesture_control/state_machine.py`
- Test: `tests/test_state_machine.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 5–6; `Scroll`, `Space` from `types`; `SCROLL_GAIN`, `SCROLL_DWELL_S`, `SWIPE_VEL`, `SWIPE_DIST`, `SWIPE_HOLD_S`, `SWIPE_WINDOW_S`, `SWIPE_COOLDOWN_S` from `config`
- Produces: no new public names. `update` now emits `Scroll(dy)` and `Space("left" | "right")`, and can reach `State.SCROLL`.

**Two rules that prevent misfires.** Swipe is evaluated **only in `ARMED_IDLE`**, so a fast drag can never be read as a Space switch. And every emitted swipe starts an 800 ms cooldown — one physical sweep produces many frames above the velocity threshold, so without a lockout a single sweep skips three Spaces.

**Swipe reads the raw `f.cursor_ref`, not the filtered `ref`.** A sweep is a gross, high-amplitude gesture; smoothing only eats the displacement the detector is trying to measure. Reading raw also decouples swipe sensitivity from cursor-filter tuning, so a later change to `EURO_BETA` cannot silently break Space switching.

- [ ] **Step 1: Write the failing tests (append to `tests/test_state_machine.py`)**

```python
from gesture_control.types import Scroll, Space

TWO = (True, True, False, False)


def test_two_finger_posture_enters_scroll_after_dwell():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    assert sm.state is State.SCROLL


def test_brief_two_finger_flash_does_not_enter_scroll():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.10, fingers=TWO))
    assert sm.state is State.ARMED_IDLE


def test_scroll_emits_on_vertical_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    out = sm.update(feat(t + 0.35, fingers=TWO, ref=(0.5, 0.6)))
    scrolls = [i for i in out if isinstance(i, Scroll)]
    assert len(scrolls) == 1
    assert scrolls[0].dy != 0.0


def test_scroll_ignores_horizontal_motion():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    out = sm.update(feat(t + 0.35, fingers=TWO, ref=(0.9, 0.5)))
    assert not any(isinstance(i, Scroll) for i in out)


def test_losing_two_finger_posture_leaves_scroll():
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, fingers=TWO))
    sm.update(feat(t + 0.25, fingers=TWO))
    sm.update(feat(t + 0.40))
    assert sm.state is State.ARMED_IDLE


def _sweep(sm, t, x_from, x_to, steps=8, span=0.20):
    """Drive a smooth horizontal sweep. Returns all intents emitted."""
    out = []
    for i in range(steps + 1):
        x = x_from + (x_to - x_from) * i / steps
        out += sm.update(feat(t + span * i / steps, ref=(x, 0.5)))
    return out


def test_fast_sweep_right_emits_space_right():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80)
    assert Space("right") in out


def test_fast_sweep_left_emits_space_left():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.80, 0.20)
    assert Space("left") in out


def test_one_sweep_emits_exactly_one_space():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80)
    assert len([i for i in out if isinstance(i, Space)]) == 1


def test_slow_drift_does_not_emit_space():
    sm = StateMachine()
    t = arm(sm)
    out = _sweep(sm, t, 0.20, 0.80, steps=40, span=4.0)
    assert not any(isinstance(i, Space) for i in out)


def test_sweep_while_pinched_does_not_emit_space():
    """A fast drag must never be read as a Space switch."""
    sm = StateMachine()
    t = arm(sm)
    sm.update(feat(t, pinch=0.2))
    out = []
    for i in range(9):
        out += sm.update(feat(t + 0.02 * i, pinch=0.2, ref=(0.2 + 0.075 * i, 0.5)))
    assert not any(isinstance(i, Space) for i in out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: the 10 new tests FAIL; the 20 from Tasks 5–6 still pass

- [ ] **Step 3: Extend `__init__`**

```python
        self._scroll_since: float | None = None
        self._swipe_hist: deque[tuple[float, float]] = deque()
        self._swipe_last: float | None = None
```

Add `from collections import deque` at the top, and extend the `types` import with `Scroll` and `Space`.

- [ ] **Step 4: Add the swipe detector**

```python
    def _detect_swipe(self, f: Features) -> list[Intent]:
        self._swipe_hist.append((f.t, f.cursor_ref.x))
        while self._swipe_hist and f.t - self._swipe_hist[0][0] > config.SWIPE_WINDOW_S:
            self._swipe_hist.popleft()

        if self._swipe_last is not None and f.t - self._swipe_last < config.SWIPE_COOLDOWN_S:
            return []
        if sum(f.fingers_up) < config.ARM_FINGERS_MIN or len(self._swipe_hist) < 2:
            return []

        t0, x0 = self._swipe_hist[0]
        elapsed = f.t - t0
        disp = f.cursor_ref.x - x0
        if elapsed < config.SWIPE_HOLD_S:
            return []
        if abs(disp) < config.SWIPE_DIST or abs(disp) / elapsed < config.SWIPE_VEL:
            return []

        self._swipe_last = f.t
        self._swipe_hist.clear()
        return [Space("right" if disp > 0.0 else "left")]
```

- [ ] **Step 5: Replace the `ARMED_IDLE` branch and add `SCROLL`**

```python
        if self._state is State.ARMED_IDLE:
            if pressed:
                self._state = State.TRACKING
                self._pinch_t0 = f.t
                self._pinch_travel = 0.0
                self._scroll_since = None
                self._swipe_hist.clear()
                return intents

            if f.fingers_up == (True, True, False, False):
                if self._scroll_since is None:
                    self._scroll_since = f.t
                elif f.t - self._scroll_since >= config.SCROLL_DWELL_S:
                    self._state = State.SCROLL
                    self._scroll_since = None
                return intents

            self._scroll_since = None
            return intents + self._detect_swipe(f)

        if self._state is State.SCROLL:
            if f.fingers_up != (True, True, False, False):
                self._state = State.ARMED_IDLE
                return intents
            px = dyn * config.SCROLL_GAIN
            if abs(px) >= config.SCROLL_MIN_PX:
                intents.append(Scroll(px))
            return intents
```

The `SCROLL` branch must be placed before the `TRACKING` branch in `update`, and the swipe history must be cleared on entering `TRACKING` so a pinch cannot inherit pre-pinch velocity.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state_machine.py -v`
Expected: 30 passed

- [ ] **Step 7: Commit**

```bash
git add src/gesture_control/state_machine.py tests/test_state_machine.py
git commit -m "feat: add two-finger scroll and swipe-to-switch-space"
```

---

### Task 8: Camera capture and MediaPipe landmarks

**Files:**
- Create: `src/gesture_control/capture.py`
- Create: `src/gesture_control/landmarks.py`
- Create: `models/.gitkeep`
- Modify: `.gitignore`
- Test: `tests/test_landmarks.py`

**Interfaces:**
- Consumes: `HandFrame`, `Point3` from `types`; `CAMERA_INDEX`, `FRAME_WIDTH`, `FRAME_HEIGHT`, `FRAME_FPS` from `config`
- Produces: `class Camera` with `open()`, `read() -> tuple[bool, Any]`, `close()`, and context-manager support; `class HandTracker(model_path: str)` with `detect(bgr, t: float) -> HandFrame` and `close()`; `MODEL_URL`; `DEFAULT_MODEL_PATH`

**This is the first task that touches hardware,** so its tests cover only the pure conversion from MediaPipe's result object to a `HandFrame`. Camera behaviour is verified in the manual smoke check at the end.

MediaPipe runs in **VIDEO mode**, which is synchronous and takes an explicit millisecond timestamp. LIVE_STREAM mode uses an async callback with no ordering guarantee, which would make the replay tests in Task 9 non-deterministic.

- [ ] **Step 1: Download the model**

```bash
mkdir -p models
curl -sL -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
ls -lh models/hand_landmarker.task
```

Expected: a file of roughly 7 MB. Add `models/*.task` to `.gitignore` — it is a downloadable artefact, not source. Commit `models/.gitkeep` so the directory exists.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_landmarks.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_landmarks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.landmarks'`

- [ ] **Step 4: Write `src/gesture_control/capture.py`**

```python
from __future__ import annotations

from typing import Any

import cv2

from . import config


class Camera:
    """Webcam frames via AVFoundation."""

    def __init__(
        self,
        index: int = config.CAMERA_INDEX,
        width: int = config.FRAME_WIDTH,
        height: int = config.FRAME_HEIGHT,
        fps: int = config.FRAME_FPS,
    ) -> None:
        self._index, self._width, self._height, self._fps = index, width, height, fps
        self._cap: Any = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self._index, cv2.CAP_AVFOUNDATION)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera {self._index}. Grant camera access to your "
                "terminal in System Settings, Privacy and Security, Camera."
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

    def read(self) -> tuple[bool, Any]:
        if self._cap is None:
            return False, None
        return self._cap.read()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
```

- [ ] **Step 5: Write `src/gesture_control/landmarks.py`**

```python
from __future__ import annotations

from typing import Any

from .types import HandFrame, Point3

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
DEFAULT_MODEL_PATH = "models/hand_landmarker.task"


def to_hand_frame(result: Any, t: float) -> HandFrame:
    """Convert a MediaPipe HandLandmarkerResult to our HandFrame. Pure."""
    hands = getattr(result, "hand_landmarks", None) if result is not None else None
    if not hands:
        return HandFrame(points=(), t=t, present=False, handedness="")

    pts = tuple(Point3(lm.x, lm.y, lm.z) for lm in hands[0])

    handed = "Right"
    categories = getattr(result, "handedness", None) or []
    if categories and categories[0]:
        handed = categories[0][0].category_name

    return HandFrame(points=pts, t=t, present=True, handedness=handed)


class HandTracker:
    """MediaPipe HandLandmarker in VIDEO mode: synchronous and deterministic."""

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._last_ms = -1

    def _next_ms(self, t: float) -> int:
        """Strictly increasing millisecond stamps.

        VIDEO mode rejects a timestamp that is not greater than its
        predecessor, and flooring float seconds to milliseconds can repeat a
        value when two frames land inside the same millisecond. Forcing the
        increase keeps both live capture and replay deterministic.
        """
        ms = max(int(t * 1000), self._last_ms + 1)
        self._last_ms = ms
        return ms

    def detect(self, bgr: Any, t: float) -> HandFrame:
        import cv2

        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, self._next_ms(t))
        return to_hand_frame(result, t)

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_landmarks.py -v`
Expected: 4 passed

- [ ] **Step 7: Manual smoke check that the camera and model actually work**

```bash
PYTHONPATH=src .venv/bin/python -c "
import time
from gesture_control.capture import Camera
from gesture_control.landmarks import HandTracker
from gesture_control.features import extract
tr = HandTracker()
try:
    with Camera() as cam:
        t0 = time.monotonic()
        for _ in range(60):
            ok, frame = cam.read()
            if not ok: continue
            f = extract(tr.detect(frame, time.monotonic() - t0))
            if f.present:
                print(f'pinch={f.pinch_ratio:.2f} fingers={f.fingers_up} palm={f.palm_facing}')
finally:
    tr.close()
"
```

`PYTHONPATH=src` is required: the project is not installed into the venv, so
`gesture_control` is importable only via that path. The `finally` guarantees the
MediaPipe landmarker is closed even if the camera raises.

Hold your hand up, palm to camera. Expected: lines printing a pinch ratio that drops below 0.35 when you pinch and rises above 0.45 when you open. If macOS has not yet prompted for camera access, this is the call that triggers it.

- [ ] **Step 8: Commit**

```bash
git add src/gesture_control/capture.py src/gesture_control/landmarks.py tests/test_landmarks.py models/.gitkeep .gitignore
git commit -m "feat: add camera capture and mediapipe hand tracking"
```

---

### Task 9: Session recorder and replay tests

**Files:**
- Create: `src/gesture_control/recorder.py`
- Create: `tests/test_replay.py`
- Create: `recordings/.gitkeep`

**Interfaces:**
- Consumes: `HandFrame`, `Point3` from `types`; `extract` from `features`; `StateMachine` from `state_machine`
- Produces: `write_session(path: str, frames: Iterable[HandFrame]) -> None`; `read_session(path: str) -> list[HandFrame]`; `replay(path: str) -> list[Intent]`

**Why this task matters most.** Everything up to here is tested against synthetic inputs the implementer invented. Replay tests run *real recorded hand motion* through the pure core and assert exact intent sequences. They are the regression net that makes retuning thresholds safe: change `TAP_MAX_S`, run the suite, and immediately see whether the "reaching for coffee" recording started producing clicks.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_replay.py
import json

from gesture_control.recorder import read_session, replay, write_session
from gesture_control.types import HandFrame, Point3


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_replay.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.recorder'`

- [ ] **Step 3: Write `src/gesture_control/recorder.py`**

```python
from __future__ import annotations

import json
from typing import Iterable

from .features import extract
from .state_machine import StateMachine
from .types import HandFrame, Intent, Point3


def write_session(path: str, frames: Iterable[HandFrame]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for f in frames:
            fh.write(json.dumps({
                "t": f.t,
                "present": f.present,
                "handedness": f.handedness,
                "points": [[p.x, p.y, p.z] for p in f.points],
            }) + "\n")


def read_session(path: str) -> list[HandFrame]:
    out: list[HandFrame] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(HandFrame(
                points=tuple(Point3(*p) for p in d["points"]),
                t=d["t"],
                present=d["present"],
                handedness=d["handedness"],
            ))
    return out


def replay(path: str) -> list[Intent]:
    """Run a recorded session through the pure core. No camera, no OS."""
    sm = StateMachine()
    intents: list[Intent] = []
    for frame in read_session(path):
        intents.extend(sm.update(extract(frame)))
    return intents
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_replay.py -v`
Expected: 3 passed

- [ ] **Step 5: Add a recording entry point to `recorder.py`**

```python
def record_to(path: str, seconds: float = 10.0, model_path: str | None = None) -> None:
    """Capture a live session to disk. Used to build replay fixtures."""
    import time

    from .capture import Camera
    from .landmarks import DEFAULT_MODEL_PATH, HandTracker

    tracker = HandTracker(model_path or DEFAULT_MODEL_PATH)
    frames: list[HandFrame] = []
    try:
        with Camera() as cam:
            t0 = time.monotonic()
            while time.monotonic() - t0 < seconds:
                ok, image = cam.read()
                if not ok:
                    continue
                frames.append(tracker.detect(image, time.monotonic() - t0))
    finally:
        tracker.close()
    write_session(path, frames)
    print(f"wrote {len(frames)} frames to {path}")
```

- [ ] **Step 6: Create the fixture-recording script**

The recordings themselves are run by the user, not by an implementer: they need a
person gesturing at the camera, and on this machine they must run from a process
started after camera access was granted. Create the script; do not run it.

Create `scripts/record_fixtures.sh`, executable:

```bash
#!/usr/bin/env bash
# Record the six replay fixtures. Run from the repo root in Terminal.app.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p recordings

record() {
  local name="$1" prompt="$2"
  echo
  echo "=== $name ==="
  echo "$prompt"
  read -r -p "press return to start a 10 second recording..."
  PYTHONPATH=src .venv/bin/python -c "
from gesture_control.recorder import record_to
record_to('recordings/$name.jsonl', seconds=10)
"
}

record five_clicks      "Arm with an open palm, then five deliberate, separated pinch taps."
record one_double_click "Arm, then one quick pair of taps."
record drag_a_to_b      "Arm, pinch, hold still for a beat, move, then release."
record reaching_past    "Reach past the camera for a cup. Do NOT address the system."
record talking_hands    "Talk with your hands in frame. Do NOT address the system."
record one_sweep        "Arm, then one brisk horizontal sweep."

echo
echo "done. now run: .venv/bin/pytest tests/test_replay.py -v"
```

| Fixture | What the user does during the ten seconds |
|---|---|
| `five_clicks` | Arm, then five deliberate separated pinch taps |
| `one_double_click` | Arm, then one quick pair of taps |
| `drag_a_to_b` | Arm, pinch, hold still for a beat, move, release |
| `reaching_past` | Reach past the camera for a cup. Do not address the system |
| `talking_hands` | Talk with hands in frame. Do not address the system |
| `one_sweep` | Arm, then one brisk horizontal sweep |

- [ ] **Step 7: Write the replay assertions**

```python
# append to tests/test_replay.py
import pytest

from gesture_control.types import Click, DragEnd, DragStart, Space

FIXTURES = "recordings"


def _replay(name):
    path = f"{FIXTURES}/{name}.jsonl"
    try:
        return replay(path)
    except FileNotFoundError:
        pytest.skip(f"fixture {path} not recorded yet")


def test_five_clicks_yields_exactly_five_single_clicks():
    clicks = [i for i in _replay("five_clicks") if isinstance(i, Click)]
    assert clicks == [Click(1)] * 5


def test_double_click_yields_one_click_two():
    clicks = [i for i in _replay("one_double_click") if isinstance(i, Click)]
    assert Click(2) in clicks
    assert len(clicks) == 2


def test_drag_yields_one_start_and_one_end():
    out = _replay("drag_a_to_b")
    assert len([i for i in out if isinstance(i, DragStart)]) == 1
    assert len([i for i in out if isinstance(i, DragEnd)]) == 1


def test_reaching_past_camera_yields_nothing():
    out = _replay("reaching_past")
    assert [i for i in out if isinstance(i, (Click, DragStart, Space))] == []


def test_talking_with_hands_yields_nothing():
    out = _replay("talking_hands")
    assert [i for i in out if isinstance(i, (Click, DragStart, Space))] == []


def test_one_sweep_yields_exactly_one_space():
    spaces = [i for i in _replay("one_sweep") if isinstance(i, Space)]
    assert len(spaces) == 1
```

The last three are the false-positive net. `pytest.skip` on a missing fixture keeps the suite green for anyone who clones the repo without recordings.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all pass, with the six replay-fixture tests reported as SKIPPED — the
fixtures are recorded by the user separately, and `pytest.skip` on a missing
fixture is deliberate so the suite stays green for a fresh clone.

Once the user has recorded them, a failing replay test is real signal: adjust the
constant in `config.py` it implicates, rerun, and note the change. Do not edit the
assertion to match the behaviour.

- [ ] **Step 9: Commit**

```bash
git add src/gesture_control/recorder.py tests/test_replay.py recordings/.gitkeep
git commit -m "feat: add session recorder and replay regression tests"
```

---

### Task 10: Actuator

**Files:**
- Create: `src/gesture_control/actuator.py`
- Test: `tests/test_actuator.py`

**Interfaces:**
- Consumes: all intent types from `types`
- Produces: `class DryRunActuator` with `apply(intents: list[Intent]) -> None`, `release_all() -> None`, and attributes `log: list[str]` and `button_down: bool`; `class QuartzActuator` with the same two methods and `button_down`; `accessibility_granted() -> bool`; `request_accessibility() -> bool`

**This is the only module that can cause harm,** so it gets the strictest structure. `QuartzActuator` holds exactly one piece of mutable state — whether the left button is down — and `release_all()` is idempotent. The unit tests cover `DryRunActuator` and the shared intent dispatch; the Quartz calls are verified in the manual check.

Coordinate note: Quartz uses a **top-left origin**. `NSEvent.mouseLocation` uses bottom-left and would silently invert every vertical movement.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actuator.py
from gesture_control.actuator import DryRunActuator
from gesture_control.types import Click, DragEnd, DragStart, Move, Scroll, Space


def test_dry_run_logs_each_intent():
    a = DryRunActuator()
    a.apply([Move(1.0, 2.0), Click(1)])
    assert len(a.log) == 2
    assert "move" in a.log[0]
    assert "click" in a.log[1]


def test_dry_run_distinguishes_single_and_double_click():
    a = DryRunActuator()
    a.apply([Click(1), Click(2)])
    assert a.log[0] != a.log[1]


def test_dry_run_tracks_button_state():
    a = DryRunActuator()
    a.apply([DragStart()])
    assert a.button_down is True
    a.apply([DragEnd()])
    assert a.button_down is False


def test_release_all_is_idempotent():
    a = DryRunActuator()
    a.apply([DragStart()])
    a.release_all()
    a.release_all()
    assert a.button_down is False
    assert a.log.count("release-all") == 1


def test_release_all_does_nothing_when_button_is_up():
    a = DryRunActuator()
    a.release_all()
    assert a.log == []


def test_all_intent_types_are_handled():
    a = DryRunActuator()
    a.apply([Move(0, 0), Click(1), DragStart(), Move(1, 1), DragEnd(),
             Scroll(5.0), Space("right"), Space("left")])
    assert len(a.log) == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actuator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.actuator'`

- [ ] **Step 3: Write `src/gesture_control/actuator.py`**

```python
from __future__ import annotations

from .types import Click, DragEnd, DragStart, Intent, Move, Scroll, Space

KEY_LEFT_ARROW = 123
KEY_RIGHT_ARROW = 124


class DryRunActuator:
    """Logs what would happen. Used by --dry-run and by the unit tests."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.button_down = False

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self.log.append(f"move {dx:.1f} {dy:.1f}")
                case Click(n):
                    self.log.append(f"click x{n}")
                case DragStart():
                    self.button_down = True
                    self.log.append("drag-start")
                case DragEnd():
                    self.button_down = False
                    self.log.append("drag-end")
                case Scroll(dy):
                    self.log.append(f"scroll {dy:.1f}")
                case Space(d):
                    self.log.append(f"space {d}")

    def release_all(self) -> None:
        if self.button_down:
            self.button_down = False
            self.log.append("release-all")


def accessibility_granted() -> bool:
    """Whether this process may post synthetic events.

    Uses `CGPreflightPostEventAccess` rather than `AXIsProcessTrusted`: it asks
    the precise question this app needs answered, and it lives in Quartz, which
    is already a dependency. `AXIsProcessTrusted` would require the separate
    `pyobjc-framework-ApplicationServices` package.
    """
    import Quartz

    return bool(Quartz.CGPreflightPostEventAccess())


def request_accessibility() -> bool:
    """Ask macOS for event-posting access, returning whether it is now granted.

    Calling this is what makes the app appear in the Accessibility list at all —
    the toggle does not exist until a process has asked. Used by the startup
    preflight so the user has something to switch on.
    """
    import Quartz

    return bool(Quartz.CGRequestPostEventAccess())


class QuartzActuator:
    """Posts real events. The only module that can affect the user's machine."""

    def __init__(self) -> None:
        import Quartz

        self._q = Quartz
        self.button_down = False
        bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        self._w = float(bounds.size.width)
        self._h = float(bounds.size.height)

    def _cursor(self) -> tuple[float, float]:
        loc = self._q.CGEventGetLocation(self._q.CGEventCreate(None))
        return float(loc.x), float(loc.y)

    def _post_mouse(self, kind: int, x: float, y: float, clicks: int = 0) -> None:
        ev = self._q.CGEventCreateMouseEvent(
            None, kind, (x, y), self._q.kCGMouseButtonLeft
        )
        if clicks:
            self._q.CGEventSetIntegerValueField(
                ev, self._q.kCGMouseEventClickState, clicks
            )
        self._q.CGEventPost(self._q.kCGHIDEventTap, ev)

    def _move_by(self, dx: float, dy: float) -> None:
        x, y = self._cursor()
        nx = min(max(x + dx, 0.0), self._w - 1.0)
        ny = min(max(y + dy, 0.0), self._h - 1.0)
        kind = (
            self._q.kCGEventLeftMouseDragged
            if self.button_down
            else self._q.kCGEventMouseMoved
        )
        self._post_mouse(kind, nx, ny)

    def _key(self, code: int) -> None:
        for down in (True, False):
            ev = self._q.CGEventCreateKeyboardEvent(None, code, down)
            self._q.CGEventSetFlags(ev, self._q.kCGEventFlagMaskControl)
            self._q.CGEventPost(self._q.kCGHIDEventTap, ev)

    def apply(self, intents: list[Intent]) -> None:
        for i in intents:
            match i:
                case Move(dx, dy):
                    self._move_by(dx, dy)
                case Click(n):
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=n)
                    self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=n)
                case DragStart():
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseDown, x, y, clicks=1)
                    self.button_down = True
                case DragEnd():
                    x, y = self._cursor()
                    self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=1)
                    self.button_down = False
                case Scroll(dy):
                    ev = self._q.CGEventCreateScrollWheelEvent(
                        None, self._q.kCGScrollEventUnitPixel, 1, int(dy)
                    )
                    self._q.CGEventPost(self._q.kCGHIDEventTap, ev)
                case Space(d):
                    self._key(KEY_RIGHT_ARROW if d == "right" else KEY_LEFT_ARROW)

    def release_all(self) -> None:
        if self.button_down:
            x, y = self._cursor()
            self._post_mouse(self._q.kCGEventLeftMouseUp, x, y, clicks=1)
            self.button_down = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_actuator.py -v`
Expected: 6 passed

- [ ] **Step 5: Manual smoke check of the real actuator**

Open TextEdit with a few words of text first, so a stray drag is harmless.

```bash
PYTHONPATH=src .venv/bin/python -c "
import time
from gesture_control.actuator import (
    QuartzActuator, accessibility_granted, request_accessibility,
)
from gesture_control.types import Move

print('accessibility granted:', accessibility_granted())
if not accessibility_granted():
    print('requesting access:', request_accessibility())
    print('enable the app under privacy and security, accessibility, then re-run')
    raise SystemExit(1)

a = QuartzActuator()
time.sleep(2)
for _ in range(20):
    a.apply([Move(5, 0)])
    time.sleep(0.02)
a.release_all()
print('cursor should have drifted right by about 100 pixels')
"
```

Expected: `accessibility granted: True` and the cursor drifting right. If it prints
`False`, the script requests access, which is what makes the app appear in the
Accessibility list at all — the toggle does not exist until something has asked.
Enable it there, then re-run.

- [ ] **Step 6: Commit**

```bash
git add src/gesture_control/actuator.py tests/test_actuator.py
git commit -m "feat: add quartz actuator and dry-run logger"
```

---

### Task 11: HUD

**Files:**
- Create: `src/gesture_control/hud.py`
- Test: `tests/test_hud.py`

**Interfaces:**
- Consumes: `State` from `state_machine`
- Produces: `state_label(state: State, present: bool) -> str`; `class Hud` with `__init__(on_tick: Callable[[], None], tick_ms: int = 10)`, `set_state(state: State, present: bool) -> None`, `run() -> None`, `stop() -> None`

**Why the HUD owns the main loop.** Tkinter must run on the main thread on macOS. Rather than adding threads and a queue, `Hud` takes the pipeline step as a callback and drives it from `root.after`. One thread, no synchronisation, and the window stays responsive.

The HUD is a requirement, not decoration: gesture input gives no physical confirmation, so without a visible state the user cannot tell a missed pinch from a mis-tuned threshold.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hud.py
from gesture_control.hud import Hud, state_label
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


class _FakeLabel:
    def __init__(self):
        self.cfg = {}

    def config(self, **kw):
        self.cfg.update(kw)


class _FakeRoot:
    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn):
        self.scheduled.append((ms, fn))


def _bare_hud(on_tick):
    """A Hud with its Tk plumbing faked out, so these run without a display."""
    h = Hud.__new__(Hud)
    h._on_tick = on_tick
    h._tick_ms = 10
    h._running = True
    h._root = _FakeRoot()
    h._label = _FakeLabel()
    return h


def test_tick_reschedules_while_running():
    h = _bare_hud(lambda: None)
    h._tick()
    assert len(h._root.scheduled) == 1


def test_tick_does_not_reschedule_after_on_tick_stops_it():
    """A pipeline step that stops the hud must not leave a pending callback.

    Rescheduling after stop() has destroyed the root raises TclError.
    """
    holder = {}
    holder["h"] = None

    def stopper():
        holder["h"]._running = False

    h = _bare_hud(stopper)
    holder["h"] = h
    h._tick()
    assert h._root.scheduled == []


def test_on_tick_exception_stops_the_loop_and_shows_the_error():
    """A dead pipeline must not leave a healthy-looking hud."""

    def boom():
        raise RuntimeError("pipeline exploded")

    h = _bare_hud(boom)
    h._tick()
    assert h._running is False
    assert h._root.scheduled == []
    assert "error" in h._label.cfg["text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_hud.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.hud'`

- [ ] **Step 3: Write `src/gesture_control/hud.py`**

```python
from __future__ import annotations

import tkinter as tk
import traceback
from typing import Callable

from .state_machine import State

_ERROR_COLOR = "#993C1D"

_LABELS = {
    State.DISARMED: "disarmed",
    State.ARMED_IDLE: "armed",
    State.TRACKING: "tracking",
    State.DRAG: "drag",
    State.SCROLL: "scroll",
}

_COLORS = {
    State.DISARMED: "#5F5E5A",
    State.ARMED_IDLE: "#185FA5",
    State.TRACKING: "#0F6E56",
    State.DRAG: "#993C1D",
    State.SCROLL: "#534AB7",
}


def state_label(state: State, present: bool) -> str:
    label = _LABELS[state]
    if state is not State.DISARMED and not present:
        return f"{label} (no hand)"
    return label


class Hud:
    """Always-on-top state pill that also drives the pipeline via after()."""

    def __init__(self, on_tick: Callable[[], None], tick_ms: int = 10) -> None:
        self._on_tick = on_tick
        self._tick_ms = tick_ms
        self._running = False

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.88)
        self._root.geometry("+40+40")
        self._label = tk.Label(
            self._root, text="disarmed", fg="white", bg="#5F5E5A",
            font=("Helvetica", 13), padx=14, pady=6,
        )
        self._label.pack()
        self._root.bind_all("<Escape>", lambda _e: self.stop())

    def set_state(self, state: State, present: bool) -> None:
        self._label.config(text=state_label(state, present), bg=_COLORS[state])

    def _fail(self, message: str) -> None:
        """Stop the loop and leave the failure visible on screen.

        Deliberately does NOT destroy the window. A hud that vanishes on error
        looks the same as one the user closed; one that stays and says what
        went wrong is the whole reason this module exists.
        """
        self._running = False
        try:
            self._label.config(text=message, bg=_ERROR_COLOR)
        except tk.TclError:
            pass

    def _tick(self) -> None:
        if not self._running:
            return
        try:
            self._on_tick()
        except Exception:
            traceback.print_exc()
            self._fail("pipeline error, see terminal")
            return
        if self._running:
            self._root.after(self._tick_ms, self._tick)

    def run(self) -> None:
        self._running = True
        self._root.after(self._tick_ms, self._tick)
        self._root.mainloop()

    def stop(self) -> None:
        self._running = False
        try:
            self._root.destroy()
        except tk.TclError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_hud.py -v`
Expected: 4 passed

- [ ] **Step 5: Manual smoke check**

```bash
PYTHONPATH=src .venv/bin/python -c "
import itertools
from gesture_control.hud import Hud
from gesture_control.state_machine import State

states = list(State)
cycle = itertools.cycle(states)
seen = []
h = Hud(on_tick=lambda: None, tick_ms=500)

def step():
    s = next(cycle)
    seen.append(s.name)
    h.set_state(s, True)
    if len(seen) >= len(states):
        h.stop()
    else:
        h._root.after(400, step)

h._root.after(400, step)
h.run()
print('cycled through:', seen)
"
```

Expected: a small pill appears in the top-left corner, steps through all five
states with changing colours, then closes itself, printing
`cycled through: ['DISARMED', 'ARMED_IDLE', 'TRACKING', 'DRAG', 'SCROLL']`.

The check must terminate on its own. An earlier version ended with a bare
`h.run()` and told the operator to press `Esc`, which blocks forever when run
non-interactively.

- [ ] **Step 6: Commit**

```bash
git add src/gesture_control/hud.py tests/test_hud.py
git commit -m "feat: add always-on-top state hud that drives the pipeline"
```

---

### Task 12: Wiring, permission preflight, and README

**Files:**
- Create: `src/gesture_control/main.py`
- Create: `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1–11
- Produces: `parse_args(argv: list[str]) -> argparse.Namespace`; `preflight(dry_run: bool) -> list[str]` returning a list of human-readable problems (empty means ready); `main(argv: list[str] | None = None) -> int`

**The three stuck-button guards.** The watchdog lives in the state machine (Task 6, `test_hand_vanishing_mid_drag_releases_the_button`). This task adds the other two: `atexit` and signal handlers calling `release_all()`, and `Esc` as a hard kill switch. A `SIGKILL` can still defeat all three, which is why the README documents the recovery — click once anywhere.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from gesture_control.main import parse_args


def test_defaults_are_live_mode():
    args = parse_args([])
    assert args.dry_run is False
    assert args.record is None


def test_dry_run_flag():
    assert parse_args(["--dry-run"]).dry_run is True


def test_record_takes_a_path():
    args = parse_args(["--record", "recordings/x.jsonl"])
    assert args.record == "recordings/x.jsonl"


def test_camera_index_is_an_int():
    assert parse_args(["--camera", "2"]).camera == 2


def test_model_path_override():
    assert parse_args(["--model", "m.task"]).model == "m.task"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gesture_control.main'`

- [ ] **Step 3: Write `src/gesture_control/main.py`**

```python
from __future__ import annotations

import argparse
import atexit
import os
import signal
import time

from . import config
from .actuator import DryRunActuator, QuartzActuator, accessibility_granted
from .capture import Camera
from .features import extract
from .hud import Hud
from .landmarks import DEFAULT_MODEL_PATH, HandTracker
from .recorder import write_session
from .state_machine import StateMachine


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="gesture-control")
    p.add_argument("--dry-run", action="store_true",
                   help="run the full pipeline but post no real events")
    p.add_argument("--record", default=None, metavar="PATH",
                   help="also write the session to a jsonl file")
    p.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    p.add_argument("--model", default=DEFAULT_MODEL_PATH)
    return p.parse_args(argv)


def preflight(dry_run: bool, model: str = DEFAULT_MODEL_PATH) -> list[str]:
    problems: list[str] = []
    if not os.path.exists(model):
        problems.append(
            f"Model file not found at {model}. Download it with:\n"
            "  curl -sL -o models/hand_landmarker.task \\\n"
            "    https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
            "hand_landmarker/float16/1/hand_landmarker.task"
        )
    if not dry_run and not accessibility_granted():
        problems.append(
            "Accessibility permission is not granted. Add your terminal under "
            "System Settings, Privacy and Security, Accessibility, then restart it."
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else [])

    problems = preflight(args.dry_run, args.model)
    if problems:
        for p in problems:
            print(f"error: {p}")
        return 1

    print("Space switching requires the Mission Control shortcuts "
          "ctrl-left and ctrl-right to be enabled in System Settings, Keyboard.")

    actuator = DryRunActuator() if args.dry_run else QuartzActuator()
    tracker = HandTracker(args.model)
    machine = StateMachine()
    camera = Camera(index=args.camera)
    camera.open()
    recorded: list = []
    t0 = time.monotonic()

    def shutdown(*_args: object) -> None:
        actuator.release_all()

    atexit.register(shutdown)
    signal.signal(signal.SIGINT, lambda *_a: (shutdown(), hud.stop()))
    signal.signal(signal.SIGTERM, lambda *_a: (shutdown(), hud.stop()))

    def tick() -> None:
        ok, image = camera.read()
        if not ok:
            return
        frame = tracker.detect(image, time.monotonic() - t0)
        if args.record is not None:
            recorded.append(frame)
        features = extract(frame)
        actuator.apply(machine.update(features))
        hud.set_state(machine.state, features.present)

    hud = Hud(on_tick=tick, tick_ms=1)
    try:
        hud.run()
    finally:
        shutdown()
        camera.close()
        tracker.close()
        if args.record is not None:
            write_session(args.record, recorded)
            print(f"wrote {len(recorded)} frames to {args.record}")
    return 0
```

Note that `hud` is referenced inside the signal handlers before its assignment. That is fine — the handlers only run after `hud.run()` has started, by which point the name is bound.

- [ ] **Step 4: Add the console entry point to `pyproject.toml`**

```toml
[project.scripts]
gesture-control = "gesture_control.main:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: 5 passed

- [ ] **Step 6: Write `README.md`**

````markdown
# Gesture control

Hands-free pointer control for macOS using the built-in webcam. Move the cursor,
click, double-click, drag, scroll, and switch between fullscreen Spaces without
touching the trackpad.

## Gestures

The vocabulary mirrors the macOS trackpad, so there is no new mental model.

| Gesture | Action |
|---|---|
| Open palm to camera, hold briefly | Arm the system |
| Pinch and move | Move the cursor |
| Pinch and release quickly | Click |
| Two quick pinches | Double-click |
| Pinch, hold still, then move | Drag |
| Index and middle finger up, move vertically | Scroll |
| Open palm, sweep sideways | Previous or next fullscreen Space |
| `Esc` | Stop immediately |

Think of the pinch as your fingertip on the trackpad glass. Releasing it lifts
off, which is how you reposition your hand without moving the cursor.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
mkdir -p models
curl -sL -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

### Permissions

Two are required, both granted to the terminal you run from, in
System Settings → Privacy & Security:

- **Camera** — macOS prompts on first run
- **Accessibility** — add your terminal manually, then restart it

Space switching also needs the Mission Control shortcuts `Ctrl+←` and `Ctrl+→`
enabled in System Settings → Keyboard → Shortcuts. They are on by default.

## Running

```bash
.venv/bin/python -m gesture_control.main --dry-run   # no real events, watch the HUD
.venv/bin/python -m gesture_control.main             # live
```

Always start with `--dry-run` after changing anything in `config.py`.

## Tuning

Every threshold lives in `src/gesture_control/config.py`. Change one, then run
the replay suite to see what it broke:

```bash
.venv/bin/pytest tests/test_replay.py -v
```

Record a new fixture with `--record`:

```bash
.venv/bin/python -m gesture_control.main --dry-run --record recordings/my_case.jsonl
```

## If the mouse button gets stuck

A hard crash during a drag can leave macOS with the left button held. Click once
anywhere to release it. The watchdog, exit handlers, and `Esc` cover every other
case.

## Known limitations

- Precision is below a trackpad's; targets under about 20 px are harder to hit
- Detection degrades in dim or strongly backlit rooms
- Sustained use is tiring; the clutch lets your hand rest between movements
- Primary display only
````

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass across all eight test files.

- [ ] **Step 8: End-to-end dry run**

```bash
.venv/bin/python -m gesture_control.main --dry-run
```

Hold your palm up. Expected: the HUD moves from `disarmed` to `armed` after a beat; pinching shows `tracking`; holding a pinch shows `drag`; two fingers shows `scroll`. No real clicks occur.

- [ ] **Step 9: End-to-end live run**

```bash
.venv/bin/python -m gesture_control.main
```

Expected: the cursor follows a pinched hand, taps click, and a sweep switches Space.

- [ ] **Step 10: Commit**

```bash
git add src/gesture_control/main.py README.md tests/test_main.py pyproject.toml
git commit -m "feat: wire pipeline with permission preflight and safety handlers"
```

---

## Self-review

**Spec coverage.** Every spec section maps to a task: architecture and modules → the file structure table; permissions → Task 12 `preflight`; feature extraction → Task 2; posture gate including the arm/sustain asymmetry → Task 3; state machine transitions, pinch disambiguation, hysteresis → Tasks 5–7; filtering and gain → Task 4; actuator mapping → Task 10; safety's three guards → Task 6 (watchdog) and Task 12 (exit handlers, `Esc`); HUD → Task 11; all three testing layers → Tasks 2–8 (unit), 9 (replay), 8/10/11/12 (manual smoke); tuning parameters → Task 1 `config.py`; repo layout → the file structure table. Known limitations are carried into the README in Task 12.

**Type consistency.** `Features`, `HandFrame`, and every intent are defined once in Task 1 and imported unchanged thereafter. `StateMachine.update` returns `list[Intent]` in Tasks 5, 6, and 7. `apply(intents)` and `release_all()` are identical on both actuators. `virtual_pos` is introduced in Task 5 and consumed in Task 6.

**Two gaps found and closed during review.** Task 1's tests originally omitted intent value equality, which every replay assertion depends on — added. Task 7's `ARMED_IDLE` branch originally left the swipe history intact when entering `TRACKING`, letting a pinch inherit pre-pinch velocity and fire a spurious Space — the branch now clears it, and `test_sweep_while_pinched_does_not_emit_space` covers it.
