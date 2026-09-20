# Gesture control

Hands-free pointer control for macOS using the built-in webcam. Point to move the
cursor, pinch to grab, curl to reposition. Built for use without touching the
trackpad.

Point your index finger and the cursor follows your hand. Pinching index-to-thumb
is a plain mouse button — down when you pinch, up when you release — so macOS
decides click versus drag exactly as it would for a physical mouse.

## Demo

[![Ten seconds of talking with your hands produces nothing, then a real pinch-drag](docs/demo/demo.gif)](docs/demo/demo.mp4)

▶️ [Watch the full video with sound](docs/demo/demo.mp4) (22 s). Every hand pose, state
change and count in it is replayed from the fixtures in `recordings/` through the same
pure core the tests use — it is not live capture, and nothing is staged. Each shot names
the fixture it came from.

## Gestures

| Gesture | Action |
|---|---|
| Open palm to the camera, hold briefly | Arm the system |
| Point your index finger, move your hand | Move the cursor |
| Curl your index finger toward your palm | Freeze the cursor so you can reposition your hand |
| Pinch index finger to thumb | Mouse button down; move to drag, release to drop |
| Pinch **middle** finger to thumb | Double-click |
| Index and middle up, ring curled, **thumb tucked into your palm**, then hold above or below where you started | Scroll |
| Three fingers up (index, middle, ring), pinky folded, sweep sideways | Switch fullscreen Space |
| Drop your hand out of frame, or press `Esc` | Stop |

Two gestures need explaining because they are not what you would guess.

**Scroll works like a joystick, not a swipe.** Forming the hand shape records
wherever your hand is as a neutral point. Holding your hand above or below that
point scrolls continuously at a speed set by how far off centre you are, and
returning to it stops. Sweeping does almost nothing, because it crosses back
through the stop point on every pass. The tucked thumb is what distinguishes it
from a middle-finger double-click, which passes through the same finger shape.

**The swipe pushes the desktop.** Sweep your hand left to move to the Space on
the right, matching the three-finger trackpad gesture with natural scrolling.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
mkdir -p models
curl -sL -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

Two macOS permissions are required, both granted to whatever terminal or app you
run from, in System Settings → Privacy & Security:

- **Camera** — macOS prompts on first run
- **Accessibility** — needed to synthesize mouse events; the app requests it on
  startup, which is what makes it appear in the list

Space switching goes through AppleScript rather than synthesized key events,
because Mission Control ignores synthetic `Ctrl+arrow`. macOS may prompt once for
permission to control System Events.

Note that permissions attach to the *process*, and macOS caches the decision at
launch. If you grant access while the app is running, restart it.

## Running

```bash
PYTHONPATH=src .venv/bin/python -m gesture_control.main --preview
```

`--preview` opens a window showing the camera, your hand drawn as a skeleton, the
current state, and the last action taken. It is the fastest way to see why a
gesture is not registering.

`--dry-run` runs the whole pipeline and posts no real events, printing what it
would have done instead. Use it after changing anything in `config.py`.

`--record PATH` writes the session to a `.jsonl` file, which can be replayed
through the pure core without a camera. This is how every threshold in the project
was calibrated.

## Tuning

Every constant lives in `src/gesture_control/config.py`, annotated with the
measurement that produced it. Edit and re-run; there is nothing to rebuild.

The ones most worth changing:

| Constant | Default | Effect |
|---|---|---|
| `BASE_GAIN_PX` | 2000 | Cursor speed |
| `MOVE_DEADZONE_PX` | 2.0 | How still your hand must be before the cursor stops |
| `SCROLL_RATE_GAIN` | 60000 | Scroll speed |
| `SCROLL_NEUTRAL_DEADZONE` | 0.008 | How far off centre before scrolling starts |
| `SWIPE_DIST` | 0.10 | How far you must sweep to switch Space |
| `THUMB_TUCK_MAX` | 0.70 | How tucked your thumb must be to start scrolling |

If a change breaks something, the replay tests will say so:

```bash
.venv/bin/pytest tests/test_replay.py -v
```

## Tests

```bash
.venv/bin/pytest
```

The pipeline is one-way — camera, landmarks, features, gate, state machine,
filter, actuator — and only the actuator touches the OS. Everything upstream is
pure, so recorded sessions replay through it and assert exact intent sequences
without a camera.

Two of those recordings matter more than the rest. `reaching_past.jsonl` and
`talking_hands.jsonl` capture a hand doing ordinary things near the camera while
*not* addressing the system, and both must replay to zero intents of any kind.
That assertion is the reason the system can be left running.

To record your own fixtures:

```bash
./scripts/record_fixtures.sh
```

## If the mouse button gets stuck

A hard crash mid-drag can leave macOS with the button held. Click once anywhere to
release it. Three guards cover every other case: a watchdog releases the button if
your hand disappears, exit and signal handlers release it on shutdown, and `Esc`
releases it immediately.

## Known limitations

- Precision is below a trackpad's; very small targets are harder to hit
- Detection degrades in dim or strongly backlit rooms
- Sustained use is tiring; the clutch lets your hand rest between movements
- Primary display only
- Scroll direction is fixed to natural and does not read the system preference
- No right-click, text entry, or zoom

## Design

`docs/superpowers/specs/` holds the design document, including why each threshold
has the value it does and which recording produced it. Several designs in there
were replaced rather than tuned — timing-based double-click, displacement
scrolling, pinch-to-move — and the reasoning is recorded alongside the
measurements that forced each change.

## License

Apache License 2.0. See [LICENSE](LICENSE).
