# Gesture Control — Design

Date: 2026-08-10
Status: Approved, ready for implementation planning

## Goal

Replace trackpad pointer input with one-handed webcam gestures on a MacBook Air (M5,
macOS 26), for hands-free use at normal laptop working distance (30–70 cm from the
camera).

Six actions must work reliably:

1. Move the cursor
2. Click
3. Double-click
4. Drag and drop
5. Scroll up/down
6. Switch to the next/previous fullscreen window (Space)

## Non-goals

Explicitly out of scope for this version. All are addable later; none are needed to
prove the concept.

- Text entry or dictation
- Right-click / secondary click
- Multi-monitor cursor mapping (primary display only)
- Pinch-to-zoom, rotate, or any other multi-touch gesture
- User-recordable custom gestures
- Menu-bar app packaging, launch-at-login, or distribution

## Design principles

The order of priority, which resolves every trade-off below:

1. **A wrong action is worse than no action.** A stray click can send an email or
   delete a file. A missed gesture costs one repeat. Thresholds bias toward
   silence.
2. **Precision beats reach.** Landing on a small target matters more than crossing
   the screen quickly.
3. **The user must always know the current state.** Gesture input has no physical
   feedback; the system supplies it visually.

## Platform assumptions

- macOS 26, Apple Silicon (arm64)
- Python 3.13; `mediapipe` 1.0.0 ships a `py3-none-macosx_11_0_arm64` wheel that
  installs cleanly on 3.13 — no interpreter pinning needed
- Only Command Line Tools are installed (no full Xcode). The Python stack avoids
  any need for an app bundle or code signing.

### Required permissions

| Permission | Granted to | Needed for |
|---|---|---|
| Camera | the terminal running Python | reading webcam frames |
| Accessibility | the terminal running Python | synthesizing mouse/key events |

Both are granted once to the terminal application (System Settings → Privacy &
Security). Startup performs a preflight check and exits with actionable instructions
if either is missing:

- Accessibility: verify with `AXIsProcessTrusted()`
- Camera: verify by opening the capture device and reading one frame
- Mission Control shortcuts: `Ctrl+←` / `Ctrl+→` must be enabled (on by default) for
  Space switching. Cannot be read programmatically without extra entitlements, so
  the startup banner states the requirement rather than asserting it.

## Architecture

One-way pipeline, camera to screen. The governing rule: **only the actuator touches
the OS.** Everything upstream is pure and testable.

```
camera frame → landmarks → features → gate → state machine → filter → actuator
   30 fps        21 pts      scalars   armed?    intents      smooth    CGEvent
```

### Modules

| Module | Responsibility | Pure? | Depends on |
|---|---|---|---|
| `capture.py` | Yields frames from the webcam, 640×480 @ 30 fps | no | OpenCV |
| `landmarks.py` | Wraps MediaPipe HandLandmarker (live-stream, 1 hand) → `HandFrame` | no | MediaPipe |
| `features.py` | 21 landmarks → `Features` | yes | — |
| `gate.py` | `Features` → armed / disarmed, with hysteresis | yes | — |
| `state_machine.py` | `(Features, t, State) → (State, [Intent])` | yes | — |
| `filters.py` | One Euro filter; pointer gain curve | yes | — |
| `actuator.py` | `Intent` → CGEvent. The only OS-touching module | no | pyobjc/Quartz |
| `hud.py` | Always-on-top state indicator | no | Tk |
| `recorder.py` | Writes/replays landmark sessions as `.jsonl` | no | — |
| `main.py` | Wires the pipeline; CLI flags | no | all |

`features`, `gate`, `state_machine`, and `filters` contain all the behaviour worth
testing and none of the I/O. This is what makes threshold tuning measurable rather
than a matter of waving at the laptop and guessing.

### Data types

```python
@dataclass(frozen=True)
class HandFrame:
    points: tuple[Point3, ...]   # 21 landmarks, normalized [0,1] image coords
    t: float                     # monotonic seconds
    present: bool                # False when no hand detected

@dataclass(frozen=True)
class Features:
    pinch_ratio: float           # scale-invariant thumb-index distance
    fingers_up: tuple[bool, ...] # index, middle, ring, pinky
    palm_facing: bool            # palm oriented toward camera
    hand_scale: float            # wrist → middle MCP, in frame widths
    cursor_ref: Point2           # index MCP, mirrored x
    t: float

Intent = Move(dx, dy) | Click(n) | DragStart | DragEnd | Scroll(dy) | Space(dir)
```

## Feature extraction

MediaPipe landmark indices used: 0 wrist, 4 thumb tip, 5 index MCP, 8 index tip,
9 middle MCP, 17 pinky MCP.

**Mirroring.** The webcam image is mirrored relative to the user, so all x
coordinates are transformed `x → 1 - x` at feature-extraction time. Everything
downstream then works in user-facing orientation, and the sign flip cannot be
forgotten in one code path and not another.

**`hand_scale`** = ‖landmark[9] − landmark[0]‖ (wrist to middle-finger knuckle).
This is the normalizer for every distance measure.

**`pinch_ratio`** = ‖landmark[4] − landmark[8]‖ / `hand_scale`. Dividing by hand
scale makes the pinch read identically at 30 cm and 70 cm from the camera. Without
this normalization every threshold silently breaks whenever the user shifts in
their chair.

**`fingers_up[f]`** = ‖tip − wrist‖ > 1.15 × ‖pip − wrist‖ for each of index,
middle, ring, pinky. Comparing distances from the wrist rather than comparing y
coordinates keeps this correct when the hand is rotated.

**`palm_facing`** = sign of the z-component of
(landmark[5] − landmark[0]) × (landmark[17] − landmark[0]). Toward the camera is
palm-facing.

**`cursor_ref`** = landmark[5], the index MCP knuckle.

> This choice is load-bearing. The knuckle at the base of the index finger barely
> moves when the thumb and index close, whereas a fingertip translates several
> millimetres. Tracking a fingertip makes the cursor jump at the exact instant of a
> pinch — the most common failure mode in webcam pointers, and the one that makes
> small targets unhittable.

## Posture gate

Arming is strict; staying armed is loose. These are deliberately different
conditions.

| Transition | Condition | Dwell |
|---|---|---|
| Disarmed → Armed | ≥3 of 4 fingers extended, `palm_facing`, `hand_scale` ∈ [0.08, 0.45] | 300 ms |
| Armed → Disarmed | hand absent, or not `palm_facing` | 500 ms |

The asymmetry is required, not incidental: pinching closes the index finger, so a
sustain condition that demanded extended fingers would disarm the system the moment
the user tried to click. The `hand_scale` bound rejects hands that are implausibly
near or far — usually a second person in frame or a hand reaching past the camera.

## State machine

States: `Disarmed`, `ArmedIdle`, `Tracking`, `Drag`, `Scroll`.

All states fall back to `ArmedIdle` when their triggering posture ends, and to
`Disarmed` when the gate drops.

### Transitions

| From | To | Trigger |
|---|---|---|
| `Disarmed` | `ArmedIdle` | posture gate arms |
| `ArmedIdle` | `Tracking` | `pinch_ratio` < 0.35; record anchor position and time |
| `ArmedIdle` | `Scroll` | index + middle extended, ring + pinky curled, 200 ms |
| `ArmedIdle` | `ArmedIdle` | horizontal sweep → emit `Space` |
| `Tracking` | `ArmedIdle` | `pinch_ratio` > 0.45 (release); may emit `Click` |
| `Tracking` | `Drag` | pinch held > 400 ms with total movement < 15 px; emit `DragStart` |
| `Drag` | `ArmedIdle` | `pinch_ratio` > 0.45; emit `DragEnd` |
| `Scroll` | `ArmedIdle` | scroll posture lost |
| any | `Disarmed` | posture gate disarms; releases any held button first |

### Continuous emissions

Beyond transitions, three states emit on every frame they are active:

| State | Emits each frame |
|---|---|
| `Tracking` | `Move(dx, dy)` from the filtered `cursor_ref` delta |
| `Drag` | `Move(dx, dy)`, actuated as `LeftMouseDragged` |
| `Scroll` | `Scroll(dy)` when vertical movement exceeds one pixel |

`ArmedIdle` and `Disarmed` emit nothing. In particular, the cursor does not move in
`ArmedIdle` — that is what makes the clutch a clutch.

### Pinch disambiguation

All three pinch outcomes begin identically. The machine records position and time
at pinch-down and decides from what follows:

| Outcome | Rule |
|---|---|
| Click | released within 250 ms, having moved < 15 px |
| Double-click | a Click whose predecessor ended < 350 ms ago and < 30 px away |
| Cursor move | moved > 15 px before release — no button event ever fires |
| Drag | held > 400 ms while staying under 15 px, then movement drags |

All distances here are **cursor screen pixels after gain is applied**, accumulated
since pinch-down — not raw hand displacement. Measuring post-gain means the click
tolerance stays constant in the space the user actually perceives it, rather than
varying with how far the hand happens to be from the camera.

Double-click is emitted as a single `Click(2)` intent so the actuator can set the
Quartz click-state field, rather than posting two separate clicks and hoping macOS
coalesces them.

### Hysteresis

Every threshold with a boundary gets two values, never one:

- pinch closes at 0.35, reopens at 0.45
- gate arms in 300 ms, disarms in 500 ms
- scroll posture engages in 200 ms, releases immediately

Single-valued thresholds chatter when the measurement sits near the boundary. That
chatter surfaces as phantom double-clicks and flickering state, which is the most
confusing possible failure for the user.

### Scroll

While in `Scroll`, vertical movement of `cursor_ref` maps to pixel-unit scroll
events: `scroll_px = dy_normalized × SCROLL_GAIN`, with `SCROLL_GAIN = 900`. Natural
scrolling direction is matched to the system setting by reading
`com.apple.swipescrolldirection`; if unavailable, defaults to natural.

### Space switching

Evaluated only in `ArmedIdle`, so a fast drag can never be read as a swipe.

Fires when, with the open-palm posture held: horizontal velocity of `cursor_ref`
exceeds 0.8 frame-widths/sec sustained for ≥ 100 ms, and net horizontal displacement
exceeds 0.20 frame widths. Rightward sweep emits `Space(right)` → `Ctrl+→`.

Swipe reads the **raw** `cursor_ref`, not the filtered value the cursor uses. A sweep
is a gross, high-amplitude gesture, so smoothing only eats the displacement being
measured; reading raw also decouples swipe sensitivity from cursor-filter tuning.

An 800 ms cooldown follows every emission. Without it, a single physical sweep
produces many frames above threshold and skips three Spaces instead of one.

## Filtering and pointer gain

**One Euro filter** on `cursor_ref` before any delta is computed. Parameters:
`min_cutoff = 1.0`, `beta = 0.7`, `d_cutoff = 1.0`. This filter is chosen over a
moving average because it adapts: heavy smoothing when the hand is nearly still
(killing tremor), light smoothing when moving fast (avoiding lag). A fixed-window
average forces a choice between a jittery cursor and a laggy one.

**`beta` is scale-dependent, and 0.7 is the value for *this* coordinate space.**
The 0.007 quoted throughout the literature assumes pixel-domain input where speeds
run to hundreds of units per second. Our input is normalized to `[0, 1]`, where
speeds are roughly 1–5 per second, making the adaptive term `beta × speed` about
0.02 — inert. At that value the filter silently degenerates into a fixed 1 Hz
low-pass with full lag at every speed, which discards the entire reason for
choosing it. Any future change to the coordinate normalization must revisit `beta`.

**Adaptive gain**, mirroring macOS pointer acceleration:

```
speed  = ‖delta‖ / dt                        # frame widths per second
accel  = clamp(0.35 + speed / 1.2, 0.35, 2.5)
px     = delta × 1600 × accel                # 1600 px per frame width, base
```

Low gain at low speed buys precision on small targets; high gain at high speed
avoids repeated re-clutching to cross the display. The cursor is clamped to the
primary display bounds.

## Actuator

All events posted to `kCGHIDEventTap`. Cursor position is read via
`CGEventGetLocation(CGEventCreate(None))` to stay in Quartz's top-left origin
coordinate system throughout (`NSEvent.mouseLocation` uses bottom-left and would
introduce a sign error).

| Intent | Implementation |
|---|---|
| `Move` | `kCGEventMouseMoved` at the new absolute position |
| `Click(n)` | `LeftMouseDown` + `LeftMouseUp`, with `kCGMouseEventClickState = n` |
| `DragStart` | `LeftMouseDown` |
| `Move` during `Drag` | `kCGEventLeftMouseDragged` |
| `DragEnd` | `LeftMouseUp` |
| `Scroll` | `CGEventCreateScrollWheelEvent`, `kCGScrollEventUnitPixel` |
| `Space(left/right)` | keycode 123 / 124 with `kCGEventFlagMaskControl` |

## Safety

The failure that can actually cause damage is a stuck mouse button: if the process
dies mid-drag, macOS is left with the left button held, and the user's next trackpad
movement rubber-bands a selection or drags a file somewhere unintended.

Three independent guards, because any one of them can be bypassed by a different
failure mode:

1. **Watchdog** — in `Drag`, if the hand is absent for > 500 ms, emit `DragEnd`.
   Covers detection dropout and the user simply walking away.
2. **Exit handlers** — button release registered in `atexit` and in `SIGINT` /
   `SIGTERM` handlers. Covers Ctrl-C and ordinary termination.
3. **Kill switch** — `Esc` immediately disarms and releases everything. Covers the
   case where the system is misbehaving and the user needs it to stop now.

A hard crash (SIGKILL, segfault) can defeat all three. The README documents the
recovery: click once anywhere.

## Feedback: the HUD

A small always-on-top pill in a screen corner showing the current state, one of
`disarmed / armed / tracking / drag / scroll`.

This is a requirement, not decoration. Gesture input provides no physical
confirmation — nothing tells the user whether a pinch registered or was ignored.
Without a visible state, diagnosing "why did nothing happen?" means guessing among
the gate, the threshold, and the actuator. With it, the answer is on screen.

The HUD also displays a landmark-confidence dot, so low-light detection failures are
distinguishable from threshold problems.

## Testing

Three layers, matching the module purity boundary.

**Unit tests (pure modules).** Synthetic landmark arrays, no camera, millisecond
runtime.

- `features`: pinch ratio is invariant to hand scale and to rotation; finger
  extension is correct for known hand poses; mirroring is applied exactly once
- `gate`: arms only after the full dwell; does not disarm when fingers curl to
  pinch (the asymmetry above); rejects out-of-range `hand_scale`
- `state_machine`: each row of the transition and disambiguation tables, including
  the boundaries — a 249 ms release clicks, a 251 ms release does not
- `filters`: One Euro converges on constant input; gain curve is monotonic and
  respects its clamps

**Replay tests.** `recorder.py` writes real sessions as `.jsonl` (landmarks +
timestamps). Replaying a recording through the state machine must yield an exact
intent sequence. Seed recordings to capture:

- five deliberate clicks → exactly `[Click(1)] × 5`
- one double-click → exactly `[Click(2)]`, never two `Click(1)`
- a drag from A to B → exactly one `DragStart`, then `Move`s, then one `DragEnd`
- a hand reaching past the camera for a coffee cup → zero intents
- talking with hands in frame for 30 s → zero intents
- one sweep → exactly one `Space`

The last three are the false-positive regression net. They are what allow
thresholds to be retuned later without silently reintroducing stray clicks.

**Manual smoke checklist** for `actuator` and `hud`, the two modules that must
touch the real OS. Run with `--dry-run` first, then live.

**Dry-run mode.** `--dry-run` substitutes a logging actuator: the full pipeline
runs, the HUD is live, and no real events are posted. All threshold tuning happens
here.

## Tuning parameters

Every value below is a starting estimate to be refined against recordings, not a
derived constant. They live in one `config.py` so tuning never means hunting
through logic.

| Parameter | Start | Governs |
|---|---|---|
| `PINCH_CLOSE` / `PINCH_OPEN` | 0.35 / 0.45 | pinch detection, with hysteresis |
| `ARM_DWELL_MS` / `DISARM_MS` | 300 / 500 | gate responsiveness vs. stability |
| `TAP_MAX_MS` | 250 | click vs. cursor move |
| `TAP_MAX_PX` | 15 | click vs. cursor move |
| `DOUBLE_MS` / `DOUBLE_PX` | 350 / 30 | double-click recognition |
| `DRAG_DWELL_MS` | 400 | drag vs. move |
| `BASE_GAIN_PX` | 1600 | cursor travel per hand movement |
| `ACCEL_MIN` / `ACCEL_MAX` | 0.35 / 2.5 | precision floor vs. reach ceiling |
| `SCROLL_GAIN` | 900 | scroll speed |
| `SCROLL_MIN_PX` | 1.0 | deadband below which no scroll is emitted |
| `SWIPE_VEL` / `SWIPE_DIST` | 0.8 / 0.20 | Space-switch sensitivity |
| `SWIPE_COOLDOWN_MS` | 800 | prevents multi-Space skips |
| `EURO_MIN_CUTOFF` / `EURO_BETA` | 1.0 / 0.7 | jitter vs. lag |

## Repository layout

```
gesture_control/
  src/gesture_control/
    capture.py  landmarks.py  features.py  gate.py
    state_machine.py  filters.py  actuator.py  hud.py
    recorder.py  config.py  main.py
  tests/
    test_features.py  test_gate.py  test_state_machine.py
    test_filters.py  test_replay.py
  recordings/          # .jsonl fixtures for replay tests
  docs/superpowers/specs/
  pyproject.toml
  README.md
```

## Known limitations

Accepted for this version, documented so they are not rediscovered as bugs.

- **Precision ceiling.** Webcam hand tracking carries a few millimetres of
  irreducible noise. Even filtered, targets smaller than roughly 20 px will be
  harder to hit than with a trackpad. The design mitigates this (knuckle tracking,
  One Euro, low-speed gain) but cannot eliminate it.
- **Lighting dependence.** Detection degrades in dim or strongly backlit
  conditions. The HUD confidence dot makes this visible rather than mysterious.
- **Arm fatigue.** Sustained use is tiring regardless of design. The clutch model
  helps by allowing the hand to rest between movements, but this is a real ceiling
  on session length.
- **Single display only.** Cursor is clamped to the primary display.
