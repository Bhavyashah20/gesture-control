# Gesture Control — Design

Date: 2026-08-10
Status: Approved and implemented; amended 2026-08-11 (direct-manipulation redesign)

## Amendment (2026-08-11): direct manipulation replaces trackpad mimicry

The original model (below, largely unchanged) mapped a pinch to two
different meanings at once: "move the cursor" while the pinch was held, and
"start a drag" if the pinch was held *still enough, for long enough*. Those
two meanings share the same physical gesture, so the system had to guess
the user's intent from timing and travel alone.

That guess cannot be made reliable. The user reports the cursor "shows drag
when I am just moving the cursor" — and this is not a tuning miss. The user
is pinched while aiming the cursor at a target, so any natural pause during
aiming is indistinguishable, from travel and dwell alone, from the start of
a deliberate drag. Raising `DRAG_DWELL_S` bought headroom, not a fix: at
1.5 s the user's own genuine drag stopped registering at all, which means no
dwell value in between separates "pausing while aiming" from "starting a
drag" for this user. The two distributions overlap the same way the
double-click timing windows did in the original double-click redesign
(see "Double-click is a gesture, not a timing window" below) — the fix is
the same shape: stop trying to infer intent from timing, and remove the
ambiguity structurally instead.

The new model is direct manipulation, proposed by the user:

- **Point** the index finger and the cursor follows the hand, continuously,
  with no pinch required.
- **Pinch** (index + thumb) is a plain mouse button: down on close, up on
  release. Nothing else. The cursor keeps following the hand while the
  button is down, so a down/move/up sequence is a drag and a down/up
  sequence in place is a click — decided by macOS, exactly as it would be
  for a physical mouse, not by this codebase.
- **Clutch:** because the cursor now tracks continuously, the user needs a
  way to reposition their hand without moving the cursor (a physical mouse
  gets this by lifting off the mat). Curling the index finger toward the
  palm freezes the cursor; uncurling resumes tracking from wherever the
  hand now is.

The user is never pinched while merely aiming, so aiming can never be
misread as a drag — the ambiguity is removed by construction, not tuned
around. This also deletes the machinery that existed only to perform that
classification: `TAP_MAX_S`, `TAP_MAX_PX`, `TAP2_MAX_PX`, `DRAG_DWELL_S`,
and `DRAG_MAX_PX`, along with the release-classification code that read
them. `Click(1)` is retired along with it — an index pinch no longer
produces a `Click` intent of any kind. `Click(2)` (the middle-finger
double-click gesture) is unaffected: it remains a single, independent
pinch channel, resolved by the same closer-finger-at-pinch-down rule
described below, because that rule's job — keeping a deliberate
double-click from also registering as a spurious index button-down — is
unrelated to the click/drag ambiguity that motivated this change.

States, transitions, and the actuator's intent names were renamed to match:
`DragStart`/`DragEnd` (which already mapped to `LeftMouseDown`/
`LeftMouseUp`) are renamed `ButtonDown`/`ButtonUp` throughout, because that
is what they now mean unconditionally rather than only during a
dwell-classified drag. The rest of this document has been updated in place
to describe the new model; sections that did not change (the posture gate,
scroll, Space switching, filtering and gain, the actuator's non-button
events, safety guards) are left as originally written.

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
    pinch2_ratio: float          # scale-invariant thumb-middle distance
    index_curl_ratio: float      # scale-invariant index-tip-to-wrist distance
    fingers_up: tuple[bool, ...] # index, middle, ring, pinky
    palm_facing: bool            # palm oriented toward camera
    hand_scale: float            # wrist → middle MCP, in frame widths
    cursor_ref: Point2           # index MCP, mirrored x
    t: float

Intent = Move(dx, dy) | Click(n) | ButtonDown | ButtonUp | Scroll(dy) | Space(dir)
```

## Feature extraction

MediaPipe landmark indices used: 0 wrist, 4 thumb tip, 5 index MCP, 8 index tip,
9 middle MCP, 12 middle tip, 17 pinky MCP.

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

**`pinch2_ratio`** = ‖landmark[4] − landmark[12]‖ / `hand_scale`, the same
normalization applied to thumb-to-middle-fingertip distance. This drives the
double-click gesture (see "Pinch disambiguation" below) — it is a second,
independent pinch channel, not a derivative of `pinch_ratio`.

**`index_curl_ratio`** = ‖landmark[8] − landmark[0]‖ / `hand_scale`, index
fingertip to wrist. Drives the clutch (see "The clutch: freezing the
cursor" below): curling the index finger toward the palm shrinks this
ratio. `INDEX_CURL_CLOSE` / `INDEX_CURL_OPEN` are calibrated against a
dedicated recording — see "Tuning parameters" for the numbers.

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

States: `Disarmed`, `Frozen`, `Tracking`, `Pressed`, `Scroll`.

`Tracking` is the resting armed state: cursor follows the hand, no button held.
`Frozen` is the clutch: armed, index curled, cursor does not move. `Pressed` is
the button-down state: the cursor still follows the hand, so movement here is a
drag. All states fall back to `Disarmed` when the gate drops; the gate itself
(arming and disarming) is unchanged from the section above.

### Transitions

| From | To | Trigger |
|---|---|---|
| `Disarmed` | `Tracking` | posture gate arms |
| `Tracking` | `Frozen` | index curls: `index_curl_ratio` < `INDEX_CURL_CLOSE`, no pinch was open |
| `Frozen` | `Tracking` | index uncurls: `index_curl_ratio` > `INDEX_CURL_OPEN` |
| `Tracking` | `Scroll` | index + middle extended, ring + pinky curled, 200 ms |
| `Tracking` | `Tracking` | horizontal sweep → emit `Space` |
| `Tracking` or `Frozen` | `Pressed` | index not curled, pinch closes (`pinch_ratio` < 0.35 OR `pinch2_ratio` < 0.30, either finger) **and** the index channel is the closer one at that instant; emit `ButtonDown` |
| `Tracking` or `Frozen` | (unchanged) | index not curled, pinch closes and the **middle** channel is the closer one; emit `Click(2)`, no state change |
| `Pressed` | `Tracking` | the pinch releases: `pinch_ratio` > 0.45 AND `pinch2_ratio` > 0.40 (both fingers clear); emit `ButtonUp` |
| `Pressed` | `Frozen` | index curls while a pinch is open: `index_curl_ratio` < `INDEX_CURL_CLOSE`; emit `ButtonUp` first (see "The clutch: freezing the cursor" below) |
| `Scroll` | `Tracking` | scroll posture lost |
| any | `Disarmed` | posture gate disarms; releases the button first if held (see Safety) |

**Curl and pinch are mutually exclusive.** Curl is evaluated before pinch on
every frame, and while curled the pinch channels are not consulted at all —
see "The clutch: freezing the cursor" below for why (a curled index reads as
a pinch geometrically) and "The button: press and release, nothing else" for
how this interacts with the closer-finger rule. Releasing the pinch while
`Frozen` (the ordinary `Pressed` → `Tracking` path, reached only when curl
did not cause the release) returns to `Tracking`, not back to `Frozen`; if
the index is still curled on the next frame, the ordinary curl transition
freezes it again from there.

### Continuous emissions

Beyond transitions, three states emit on every frame they are active:

| State | Emits each frame |
|---|---|
| `Tracking` | `Move(dx, dy)` from the filtered `cursor_ref` delta |
| `Pressed` | `Move(dx, dy)`, actuated as `LeftMouseDragged` |
| `Scroll` | `Scroll(dy)` when vertical movement exceeds one pixel |

`Frozen` and `Disarmed` emit nothing. This is the whole mechanism: the cursor
does not move in `Frozen` — that is what makes the clutch a clutch — and
`Tracking` is the only state where a bare hand movement (no pinch) produces a
`Move`.

### The button: press and release, nothing else

An index pinch is a plain mouse button. It does not classify click versus
drag — that ambiguity does not exist in this model, because the cursor never
moves from a pinch alone; it only ever moves because the hand moved, pinched
or not. `ButtonDown` fires the instant the pinch closes; `ButtonUp` fires the
instant it releases. macOS reads whatever happened to `Move` events in
between: none means a click, any means a drag — the same interpretation it
would apply to a physical mouse. There is no dwell timer, no travel budget,
and no release-time classification left in this codebase to get wrong.

**Closer-finger disambiguation still applies, and still matters.** There is a
single combined pinch state, not two independent trackers: it closes the
instant *either* `pinch_ratio` or `pinch2_ratio` crosses its own CLOSE
threshold, and does not reopen until *both* ratios clear their OPEN
thresholds. At the moment it closes, whichever finger's ratio is numerically
smaller — physically closer to the thumb on that frame — decides the
outcome: index closer → `ButtonDown` (may become a drag); middle closer →
`Click(2)`, no state change. This is the one piece of the pre-redesign
click/drag machinery that survives, and it survives for an unrelated reason:
anatomically, pinching the middle fingertip to the thumb drags the index tip
along with it, so the index channel often also reads closed during a
deliberate middle pinch. Without the closer-finger check, that cross-talk
would make a deliberate double-click also fire a spurious `ButtonDown` —
which, if the hand moves at all before release, macOS reads as an accidental
drag. In `recordings/middle_pinch.jsonl` (15 s, 8 deliberate middle-pinches),
43 of the 417 present frames read `pinch_ratio` < `PINCH_CLOSE` even though
the user was never pinching their index finger — that is the cross-talk this
rule exists to filter. Validated against all three original recordings: the
margin between the two ratios never approaches a tie (0.32–0.66 during
genuine index clicks, 0.09–0.41 during genuine middle pinches). **Do not
reintroduce fixed priority between the two channels** (e.g. "index always
wins if closed") — that was the original rule and live data proved it wrong.

#### Double-click is a gesture, not a timing window

(Unchanged from the original diagnosis, restated for the current model.)

Double-click was originally a Click whose predecessor had ended less than
450 ms and 50 px away — the same index pinch, tapped twice quickly. Diagnosis
against the user's real recordings on 2026-08-10 showed this is undetectable
for them:

- Their one **deliberate** double-click had a release-to-release gap of
  **0.399 s**.
- Their **accidental** doubles — two separate, intended single clicks that
  the old rule misread as one double — had gaps of **0.400 s, 0.300 s, and
  0.201 s**.

Those two distributions fully overlap; no single timing threshold sits
between "deliberate" and "accidental" gaps in this data. Space did not
separate them either — the accidental pairs were 0.7–3.8 px apart, the
deliberate one 4.7 px, so the accidental doubles were *closer* together,
meaning a tighter distance window would have made the false-positive rate
worse, not better. Only a 0.20 s window eliminated the false doubles in this
data, which is faster than the user can deliberately double-tap — i.e. no
timing window exists that admits the deliberate case and excludes the
accidental ones. (This is the same shape of finding that motivated the
2026-08-11 direct-manipulation redesign above: when two distributions
genuinely overlap, no threshold fixes it, and the only sound move is to stop
inferring intent from timing and remove the ambiguity structurally.)

Given design principle 1 ("a wrong action is worse than no action") and that
a false double-click opens a file instead of selecting it, the fix is to stop
using timing at all. Double-click is a **second, independent pinch
channel** — middle-tip-to-thumb instead of index-tip-to-thumb — with its own
hysteresis (`PINCH2_CLOSE` / `PINCH2_OPEN`) and no relationship to any
previous click's timestamp or position:

- index-tip-to-thumb pinch → `ButtonDown` / `ButtonUp` (click or drag,
  decided by macOS — see above)
- middle-tip-to-thumb pinch → `Click(2)`

Thresholds are measured, not guessed: while genuinely index-pinching, the
user's middle-to-thumb ratio (`pinch2_ratio`) ran 0.43–0.90 across their
recordings (median 0.64), and across 1060 recorded frames only one dipped
below 0.35. `PINCH2_CLOSE = 0.30` / `PINCH2_OPEN = 0.40` sit safely under
that floor with hysteresis room to spare, so an ordinary index pinch does not
misread as a double.

**Do not reintroduce timing-based double-click detection.** The overlap
above is not a tuning problem to be solved with a different constant — the
deliberate and accidental distributions genuinely overlap for this user, so
no threshold on gap or distance can separate them.

`Click(2)` is emitted the instant the pinch closes (not at release): unlike
the old model, there is nothing left to wait for — no travel or dwell budget
that a held middle pinch could still fail on. `Click(n)` remains a single
intent (rather than two separate presses) so the actuator can set the Quartz
click-state field directly, rather than posting two clicks and hoping macOS
coalesces them.

### The clutch: freezing the cursor

Because the cursor now tracks the hand continuously, the user needs a way to
lift off — reposition their hand in the air without dragging the cursor with
it, the way lifting a physical mouse off the mat does. Curling the index
finger toward the palm is that gesture: `index_curl_ratio` (index-tip-to-wrist
distance, scale-normalized — see "Feature extraction") drops below
`INDEX_CURL_CLOSE` and the machine enters `Frozen`, in which no `Move` is
emitted regardless of how the hand moves. Uncurling past `INDEX_CURL_OPEN`
resumes `Tracking`. Internally, the filtered reference point keeps updating
every frame even while `Frozen` — only the *emission* of `Move` is
suppressed — so resuming tracking never replays the frozen-period
displacement as a jump.

**Curl and pinch are mutually exclusive (2026-08-11 fix), and the clutch
releases the button rather than holding through a curl.** An earlier version
of this spec said the opposite — "the clutch must never release the button,"
with curl not even consulted while `Pressed` — on the reasoning that freezing
mid-drag should not silently drop whatever was being dragged. That reasoning
assumed curl and pinch were independent signals. They are not: curling the
index finger toward the palm brings the fingertip onto the thumb, which is
geometrically indistinguishable from a pinch. Measured directly against
`recordings/clutch.jsonl` (a recording where the user only points and
curls, never pinches): every one of the 124 frames classified as curled
also reads `pinch_ratio` below `PINCH_CLOSE`, bottoming out at 0.01, and 56
of those also cross `PINCH2_CLOSE`. So a pinch reading during a curl is
always spurious, and the old rule meant trusting exactly that spurious
reading to hold the button down indefinitely — before this fix, replaying
`recordings/clutch.jsonl` left the state machine stuck in `Pressed`, an
unreleased `ButtonDown`, the one failure mode this project guards against
everywhere else.

The fix: curl is evaluated before pinch on every frame. While curled, both
pinch channels are ignored outright — no new `Pressed` transition, no
`Click(2)` — and if a pinch was already open (`Pressed`) when the curl
engages, it is released (`ButtonUp`) in that same frame, landing in `Frozen`
rather than holding through the freeze. This is safe against every genuine
pinch on record: the lowest `index_curl_ratio` measured during any of the
374 genuine pinch frames across the five pinch-containing fixtures is 1.03,
comfortably above `INDEX_CURL_CLOSE` — no real pinch is ever misclassified
as a curl, so no real pinch is ever suppressed by this rule.

`index_curl_ratio` thresholds are calibrated against
`recordings/clutch.jsonl`, a dedicated 15 s recording that alternates
between pointing and curling while moving the hand throughout. Its
`index_curl_ratio` distribution is cleanly bimodal — a curled cluster at
0.56-0.9 (124 frames) and a pointing cluster at 1.6-2.04 (313 frames), with
a wide, nearly empty gap between — so `INDEX_CURL_CLOSE = 0.95` sits in that
gap, detecting every curled frame. The upper bound is still set by pinching,
not pointing: the lowest `index_curl_ratio` observed during any pinch,
across all five pinch-containing fixtures, is 1.03, so `INDEX_CURL_OPEN =
1.20` stays below the pointing cluster (for prompt uncurl detection) while
never approaching the pinch floor (so a pinch is never misread as a curl).
See "Tuning parameters" below.

**Known gap, unrelated to curl:** `recordings/clutch.jsonl` still replays
with one spurious `Click(2)`, at t=1.628s, where `index_curl_ratio` reads
1.936 — deep in the pointing cluster, nowhere near `INDEX_CURL_CLOSE`. It is
a transient `pinch2_ratio` dip during ordinary pointing motion with no
connection to curling, so "ignore pinch while curled" cannot and does not
address it; it is the same class of gap flagged in
`.superpowers/sdd/2026-08-10-gesture-control/curl-calibration-report.md`
("Blocking finding"), now narrowed from two spurious events (one of them a
stuck button) to this one, non-stuck-button case. Fixing it would mean
recalibrating `PINCH_CLOSE`/`PINCH2_CLOSE` against sustained hand motion —
out of scope here; see the README's "Known limitations".

### Hysteresis

Every threshold with a boundary gets two values, never one:

- index pinch closes at 0.35, reopens at 0.45
- middle pinch (double-click) closes at 0.30, reopens at 0.40
- index curl closes at 0.95, reopens at 1.20
- gate arms in 300 ms, disarms in 500 ms
- scroll posture engages in 200 ms, releases immediately

Single-valued thresholds chatter when the measurement sits near the boundary. That
chatter surfaces as phantom clicks and flickering state, which is the most
confusing possible failure for the user.

### Scroll

While in `Scroll`, vertical movement of `cursor_ref` maps to pixel-unit scroll
events: `scroll_px = dy_normalized × SCROLL_GAIN`, with `SCROLL_GAIN = 900`. Natural
scrolling direction is matched to the system setting by reading
`com.apple.swipescrolldirection`; if unavailable, defaults to natural.

### Space switching

Evaluated only in `Tracking`, so a fast drag (`Pressed`) can never be read as
a swipe.

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
| `ButtonDown` | `LeftMouseDown` |
| `Move` during `Pressed` | `kCGEventLeftMouseDragged` |
| `ButtonUp` | `LeftMouseUp` |
| `Scroll` | `CGEventCreateScrollWheelEvent`, `kCGScrollEventUnitPixel` |
| `Space(left/right)` | keycode 123 / 124 with `kCGEventFlagMaskControl` |

`ButtonDown` / `ButtonUp` are a rename of what this table originally called
`DragStart` / `DragEnd` — the Quartz calls were always exactly this (a plain
mouse-down and mouse-up), and the 2026-08-11 redesign made that literal
meaning the *only* meaning, so the names were changed to match rather than
continuing to describe a classification (drag) the code no longer performs.

## Safety

The failure that can actually cause damage is a stuck mouse button: if the process
dies mid-drag, macOS is left with the left button held, and the user's next trackpad
movement rubber-bands a selection or drags a file somewhere unintended.

Three independent guards, because any one of them can be bypassed by a different
failure mode:

1. **Watchdog** — in `Pressed`, if the hand is absent for > 500 ms, emit
   `ButtonUp`. Covers detection dropout and the user simply walking away.
2. **Exit handlers** — button release registered in `atexit` and in `SIGINT` /
   `SIGTERM` handlers. Covers Ctrl-C and ordinary termination.
3. **Kill switch** — `Esc` immediately disarms and releases everything. Covers the
   case where the system is misbehaving and the user needs it to stop now.

A hard crash (SIGKILL, segfault) can defeat all three. The README documents the
recovery: click once anywhere.

## Feedback: the HUD

A small always-on-top pill in a screen corner showing the current state, one of
`disarmed / frozen / tracking / pressed / scroll`.

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

- `features`: pinch ratio is invariant to hand scale and to rotation; `pinch2_ratio`
  is likewise scale-invariant and independent of the index pinch; `index_curl_ratio`
  is likewise scale-invariant and independent of the pinch; finger
  extension is correct for known hand poses; mirroring is applied exactly once
- `gate`: arms only after the full dwell; does not disarm when fingers curl to
  pinch (the asymmetry above); rejects out-of-range `hand_scale`
- `state_machine`: each row of the transition table, including the
  closer-finger disambiguation, the clutch (curl freezes and does not jump on
  resume; curl and pinch are mutually exclusive -- curl is evaluated before
  pinch every frame, the pinch channels are ignored while curled, and an
  already-open button is released, not held, the instant a curl engages),
  and the stuck-button watchdog
- `filters`: One Euro converges on constant input; gain curve is monotonic and
  respects its clamps

**Replay tests.** `recorder.py` writes real sessions as `.jsonl` (landmarks +
timestamps). Replaying a recording through the state machine must yield an exact
intent sequence. The six behavioural fixtures below were all recorded under the
OLD trackpad-mimicry model; replaying them against the new state machine changes
what they demonstrate but not their purpose:

- `five_clicks.jsonl` (five deliberate index taps) → five `ButtonDown`/`ButtonUp`
  pairs, no `Click`
- `drag_a_to_b.jsonl` → exactly one `ButtonDown`, then `Move`s, then one
  `ButtonUp` — no dwell classification left to demonstrate, just the raw
  press/move/release sequence
- a hand reaching past the camera for a coffee cup → zero intents,
  **non-negotiable** (see below)
- talking with hands in frame for 30 s → zero intents, **non-negotiable**
- `one_sweep.jsonl` → exactly one `Space`
- `middle_pinch.jsonl` (8 deliberate middle-pinches) → `Click(2)`s, proving the
  closer-finger disambiguation fires from real motion rather than only in
  synthetic unit tests

`one_double_click.jsonl` and `live_clicks.jsonl` predate the middle-pinch
gesture — both were recorded as rapid index taps under the old timing-based
design, and both used to contain false `Click(2)`s (`live_clicks.jsonl` had
three). They are kept as the regression test for exactly that misfire: under
the current design both must yield `ButtonDown`/`ButtonUp` pairs only and
never a `Click(2)`.

`recordings/middle_pinch.jsonl` (added 2026-08-11) is the fixture that
disproved the original "index wins" fixed-priority rule — see "The button:
press and release, nothing else" above. Under the new model, with no
travel or dwell budget left to lose registrations to, its replay yields more
`Click(2)`s than it did under any prior rule (see the redesign report for
the exact count) — the closer-finger check is still what keeps those closures
from also firing a spurious `ButtonDown`.

The false-positive fixtures (reaching past, talking hands) are the
regression net that lets thresholds be retuned later without silently
reintroducing stray output. They matter more under the new model than the
old one: because `Tracking` now emits a `Move` on nearly every frame, a gate
that mis-arms during either recording would produce a stream of stray
cursor movement, not just an occasional stray click. If either fixture
starts emitting anything, the fix is to tune the gate — not to weaken the
assertion.

**Manual smoke checklist** for `actuator` and `hud`, the two modules that must
touch the real OS. Run with `--dry-run` first, then live.

**Dry-run mode.** `--dry-run` substitutes a logging actuator: the full pipeline
runs, the HUD is live, and no real events are posted. All threshold tuning happens
here. `main.py` coalesces consecutive `move` log lines into a single `move xN`
summary — `move` fires roughly once per camera frame (~30/s), and now fires
throughout `Tracking` as well as `Pressed`, so printed one-per-line it
drowns out the discrete events (clicks, button down/up, scrolls, spaces)
that tuning actually needs to see; those still print immediately, one line
each. This is display-only bookkeeping in `main.py`, not a change to what
the actuator logs or to `DryRunActuator.log`.

## Tuning parameters

As of the 2026-08-11 direct-manipulation redesign, five parameters that
existed purely to classify click versus drag are gone: `TAP_MAX_S`,
`TAP_MAX_PX`, `TAP2_MAX_PX`, `DRAG_DWELL_S`, `DRAG_MAX_PX`. They were
calibrated carefully (the history is preserved in git for anyone who needs
it) and still produced the reported bug — because the problem was never
mistuning, it was that the classification they performed cannot be made
reliable from timing and travel alone. Removing them is the fix, not a
simplification made at the cost of losing that calibration work.

`PINCH_CLOSE` / `PINCH_OPEN` and `PINCH2_CLOSE` / `PINCH2_OPEN` are
unchanged and still calibrated against the same real recordings described
below their original entries. `INDEX_CURL_CLOSE` / `INDEX_CURL_OPEN` are
calibrated against a dedicated recording, `recordings/clutch.jsonl` — see
"The clutch: freezing the cursor" above. All other parameters (gate, gain,
scroll, swipe, filter) are unchanged by this redesign.

| Parameter | Start | Governs |
|---|---|---|
| `PINCH_CLOSE` / `PINCH_OPEN` | 0.35 / 0.45 | index pinch detection (button down/up), with hysteresis |
| `PINCH2_CLOSE` / `PINCH2_OPEN` | 0.30 / 0.40 | middle pinch (double-click) detection, with hysteresis |
| `INDEX_CURL_CLOSE` / `INDEX_CURL_OPEN` | 0.95 / 1.20 | Clutch (freeze/resume) detection, with hysteresis. Calibrated against `recordings/clutch.jsonl`: `index_curl_ratio` is cleanly bimodal (curled 0.56-0.9, pointing 1.6-2.04), and 0.95 sits in the wide gap between. The upper bound is set by the pinch floor (1.03, across all pinch-containing fixtures), not by pointing, so a pinch is never misread as a curl |
| `ARM_DWELL_MS` / `DISARM_MS` | 300 / 500 | gate responsiveness vs. stability |
| `BASE_GAIN_PX` | 1600 | cursor travel per hand movement |
| `ACCEL_MIN` / `ACCEL_MAX` | 0.35 / 2.5 | precision floor vs. reach ceiling |
| `SCROLL_GAIN` | 900 | scroll speed |
| `SCROLL_MIN_PX` | 1.0 | deadband below which no scroll is emitted |
| `SWIPE_VEL` / `SWIPE_DIST` | 0.8 / 0.20 | Space-switch sensitivity |
| `SWIPE_COOLDOWN_MS` | 800 | prevents multi-Space skips |
| `DRY_RUN_FLUSH_S` | 1000 | max age of a coalesced `move` run in `--dry-run` output before it flushes |
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
- **Arm fatigue.** Sustained use is tiring regardless of design. The clutch
  (curl to freeze, uncurl to resume) helps by letting the hand rest or
  reposition without the cursor following it, but this is a real ceiling on
  session length.
- **Single display only.** Cursor is clamped to the primary display.
