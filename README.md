# Gesture control

Hands-free pointer control for macOS using the built-in webcam. Move the cursor,
click, double-click, drag, scroll, and switch between fullscreen Spaces without
touching the trackpad.

## Gestures

Direct manipulation, not trackpad mimicry: point to move, pinch to grab, exactly
like picking up a file and moving your hand.

| Gesture | Action |
|---|---|
| Open palm to camera, hold briefly | Arm the system |
| Point your index finger and move your hand | Move the cursor |
| Curl your index finger toward your palm | Freeze the cursor (clutch), so you can reposition your hand |
| Uncurl your index finger | Resume tracking, from wherever your hand now is |
| Pinch (index finger) | Press the mouse button down |
| Move while pinched | Drag |
| Release the pinch | Release the mouse button |
| Pinch (middle finger) | Double-click |
| Index and middle extended, ring curled, thumb tucked to the palm, then hold your hand above or below where you started the gesture | Scroll |
| Index, middle and ring extended, pinky curled, swept sideways | Previous or next fullscreen Space -- macOS natural-scrolling convention: sweep your hand LEFT to switch to the Space on the RIGHT, and vice versa (content follows your hand, exactly like a three-finger trackpad swipe with natural scrolling) |
| `Esc` | Stop immediately |

The cursor follows your hand continuously while armed — no pinch required to
move it. Pinching index-to-thumb is a plain mouse button: it goes down when
you pinch and up when you release, nothing else. macOS decides click versus
drag from that down/move/up sequence on its own, exactly as it would for a
physical mouse, so there is no separate "hold still to drag" gesture to learn
or mistune.

**Turning your palm away does not stop the system (2026-08-21).** Arming
still requires an open palm facing the camera, but once armed, staying
armed only requires your hand to be visible — not facing the camera. This
is deliberate: gestures rotate the hand (a three-finger swipe to the right
rotates the palm edge-on to the camera for part of the motion — see
"Tuning" below), and a system that disarms every time a gesture turns the
hand away fights the gestures it exists to recognize. To stop the system,
drop your hand out of frame (it disarms after 500 ms absent) or press
`Esc`.

**Stability (2026-08-11).** Three changes address "cursor too unstable for
small targets" and "scroll does nothing," all measured against real
recordings rather than guessed:

- The cursor reference point (`cursor_ref`) is now the centroid of your four
  MCP knuckles (index, middle, ring, pinky) instead of the index knuckle
  alone. Averaging four points cancels each one's independent tracking
  noise — measured 16-21% steadier on three of the user's four recordings.
- Small, jittery hand motion no longer moves the cursor at all: sub-pixel
  deltas accumulate instead of being applied or dropped, so tremor in
  alternating directions cancels out while slow, deliberate motion (aiming
  at a small target) still arrives, just in coarser steps. This is what
  makes small targets like window close buttons hittable.
- Scroll gain was raised roughly 5.5x — the posture detection and dwell
  timing were already correct, but the pixel output per gesture was about
  ten times too small to notice.

**Scroll acceleration (2026-08-19).** Raising `SCROLL_GAIN` fixed "scroll does
nothing" but left "the amount of scroll is hard to control": with a flat gain,
every hand speed scrolled at the same rate, so there was no way to get both a
small precise scroll and a long fast one, and even gentle hand tremor while
holding the scroll posture nudged the page. Scroll now has its own
acceleration curve (`scroll_accel`, mirroring the cursor's `accel` but with
its own constants — see "Tuning" below), so slow hand movement gives fine
control, fast movement gives reach, and tremor near the resting speed
collapses to below the scroll deadband instead of drifting the page.

**Scroll is rate-based, not displacement-based (2026-08-20 redesign).** The
scroll amount used to follow how far the hand physically moved, the same way
the cursor does: `scroll_px = dy × SCROLL_GAIN × scroll_accel(speed)`. That
model had a hard failure the user reported directly: when their hand reached
the top or bottom of its comfortable range, there was nowhere left to move,
so scrolling simply stopped, stranding them mid-page. Measured from
`recordings/scroll_attempt.jsonl`, the usable vertical span during the scroll
gesture is only 0.22 of frame height — enough for roughly 4400 px of
displacement scroll in one stroke and no more, regardless of gain.

Scroll now works like a joystick. Entering `Scroll` records the hand's
current vertical position as a `neutral` point. Each frame, `offset` is the
hand's current position relative to that neutral, not a frame-to-frame
delta. Inside `SCROLL_NEUTRAL_DEADZONE` nothing happens, which is what lets
you stop scrolling by returning to centre. Outside it, `offset` sets a
continuous scroll *speed* — `sign(offset) × (|offset| − SCROLL_NEUTRAL_DEADZONE)
× SCROLL_RATE_GAIN` px/sec — so holding your hand off-centre keeps the page
scrolling for as long as you hold it, and the per-frame scroll amount is that
speed times the frame's `dt`. Hand range stops mattering: you hold a position
instead of sweeping through one, so you can never run out of room. `SCROLL_GAIN`
and the `scroll_accel` curve (2026-08-19, above) existed only to shape
displacement-based scrolling and are removed along with it — see "Tuning"
below for the replacement constants.

Curling and pinching are mutually exclusive, on purpose: curling your index
finger toward your palm brings the fingertip onto the thumb, which reads as
a pinch geometrically — there is no way to tell the two apart from the
landmark data alone. Measured directly: in `recordings/clutch.jsonl` (a
recording of pointing and curling only, no pinching), every one of the 124
curled frames also reads as a pinch, with `pinch_ratio` bottoming out at
0.01. So while your index is curled, both pinch channels are ignored
outright — a pinch reading during a curl is always spurious — and if a
pinch was already open when the curl engages, the button is released, not
held through the freeze. This used to be the opposite rule ("the clutch
must never release the button"); it changed once it was clear the two
signals aren't independent, because holding through a spurious pinch
reading is exactly the stuck-button failure this project guards against
everywhere else.

**A pinch requires an extended finger, not just tip proximity (2026-08-19
follow-up).** Users reported that bringing a finger "just a little closer to
the palm" pressed the button even when it never touched the thumb. The cause:
a pinch was detected purely from `dist(thumb_tip, finger_tip) / hand_scale`
crossing a threshold. Curling a finger brings its tip toward the palm, where
the thumb also rests, so that distance shrinks without the two ever
touching — the general case of the same geometry that made curl and pinch
mutually exclusive for the clutch above, just without a full clutch-level
curl to trigger that gate. Tip-to-thumb distance alone cannot tell a genuine
pinch from a partial curl; finger *shape* can. Measured as fingertip-to-wrist
distance over `hand_scale` (the same quantity as `index_curl_ratio`, plus the
new `middle_curl_ratio` for the middle finger) across frames the code reads
as pinched: genuine pinches never fall below 1.25 index / 1.22 middle
extension, while curling reaches as low as 0.69 index / 0.54 middle. A pinch
may now only *close* when its finger clears `PINCH_MIN_EXTENSION` (index) or
`PINCH2_MIN_EXTENSION` (middle) — see "Tuning" below for the exact values and
margins. This gates closing only: a pinch already held never releases just
because the finger flexes slightly, so a genuine drag can't drop the button
mid-motion. Against the recordings: `live_clicks.jsonl` and
`middle_pinch.jsonl` keep every genuine press unchanged, and
`recordings/clutch.jsonl` — which used to leave 2 `ButtonDown`/`ButtonUp`
pairs and 2 spurious `Click(2)`s even after the curl-gate fix — now replays
to zero button or click events of any kind.

**Scroll thumb gate (2026-08-19).** The user reported spurious scrolling
when they meant to double-click: opening the middle finger to pinch it to
the thumb passes through the scroll finger posture (index and middle
extended, ring not) on its way there, since the index finger stays extended
for tracking the whole time. Scroll now additionally requires the thumb
tucked toward the palm — `thumb_tuck_ratio` (thumb tip to pinky knuckle,
scale-normalized) below `THUMB_TUCK_MAX` — because a middle-pinch extends
the thumb out to meet the middle fingertip, making the two gestures mutually
exclusive by construction. Measured thumb-tuck medians: scroll 0.55,
middle-pinch 0.86, index clicks 0.90. At `THUMB_TUCK_MAX = 0.70`, the gate
keeps 195 of 260 genuine scroll frames from `recordings/scroll_attempt.jsonl`
and rejects every colliding frame from `middle_pinch.jsonl` and
`live_clicks.jsonl`. That 75% retention is measured on a recording where the
thumb was not deliberately tucked; now that the tuck is part of the
gesture, real retention should be higher.

**Scroll thumb gate is asymmetric (2026-08-19 follow-up).** The gate above,
using one shared threshold for both entering and leaving scroll, had a side
effect: replaying `recordings/scroll_attempt.jsonl` showed 65 of 260
scroll-posture frames with the thumb drifting back above `THUMB_TUCK_MAX`
mid-gesture without the user meaning to double-click. Each such frame
dropped `SCROLL` straight to `TRACKING`, which — unlike `SCROLL` — processes
pinches, so a stray pinch reading during that momentary window could fire a
click the user never intended. The fix mirrors the gate's own arm/sustain
asymmetry (see "Gestures" above): entering scroll stays strict
(`thumb_tuck_ratio < THUMB_TUCK_MAX`), but staying in scroll is loose — the
thumb must clear a separate, higher `THUMB_TUCK_RELEASE = 0.95` before
scroll is left. A brief un-tuck is absorbed; a genuine, deliberate untuck on
the way to a real middle-pinch still ejects the user, since it clears 0.95.
Measured against `recordings/scroll_attempt.jsonl`: the specific transition
this was built to fix (the thumb drifting from ~0.71 to ~0.84 while
scroll-posture fingers hold steady) now correctly stays inside `SCROLL`
instead of dropping out, and total scroll output on that fixture went up
slightly (96 → 102 events, 9232 → 9341 px) rather than down. However, the 4
`ButtonDown`/`ButtonUp` pairs originally reported are **still present**
after this fix, unchanged in count and timestamp. Tracing them showed they
occur in a different part of the recording (~10.4-11.9 s) where the thumb
never drops below `THUMB_TUCK_MAX` in the first place — the machine never
enters `SCROLL` there at all, so the exit-side asymmetry has nothing to
absorb. Before the original thumb-tuck gate existed, that same segment
stayed in `SCROLL` because the *entry* check was pure finger-shape with no
thumb condition; adding the thumb condition to entry (not touched by this
follow-up) is what stopped `SCROLL` from picking that segment up. This is a
different mechanism than the one diagnosed, and out of scope for this fix —
see the follow-up report for the full trace.

**Scroll is reluctant to leave (2026-08-20 follow-up).** The user recorded
`recordings/scroll_hold.jsonl`, 15 s of correctly performed rate-scroll
holding, and it produced only 10 `Scroll` events totalling 47 px — next to
nothing. The gesture was not the problem: `(True, True, False, False)` is
the dominant finger pattern at 224 of 361 present frames, exactly the
intended shape. The problem was that the scroll gate flickered — over
those 15 s there were 16 unbroken runs of a satisfied gate, the longest
only 1.73 s, from single-frame landmark noise dropping the finger or thumb
condition. Every break exited `Scroll`, and every re-entry re-recorded the
rate neutral at the hand's then-current position, so the offset driving
scroll speed was continuously reset to zero and never accumulated.

The fix mirrors the posture gate's own arm/disarm asymmetry (see
`ARM_DWELL_S`/`DISARM_S` above) one level further in: `Scroll` now requires
the posture to be absent **continuously** for `SCROLL_EXIT_S` (0.35 s)
before it is actually left, not just absent on a single frame. While that
debounce timer is running, scroll behaves exactly as if the posture were
still satisfied — offset, speed, and the resulting `Scroll` output are
computed from the frame's real hand position regardless, so a single
flickered frame produces no visible stutter, the same way the posture
gate's own `DISARM_S` grace window doesn't pause cursor tracking while its
sustain check is momentarily false. The neutral is only cleared, and only
re-recorded, on an actual exit-then-re-entry — a fragment that recovers
within the debounce window keeps scrolling at the same rate it was
already at, never resetting to zero. This debounce sits on top of the
*whole* posture predicate, covering the finger conditions too, which
previously had no hysteresis at all (only the thumb had
`THUMB_TUCK_RELEASE`).

Replayed against `recordings/scroll_hold.jsonl`: 10 events / 47 px before →
36 events / ~820 px after, roughly 17x. `recordings/scroll_attempt.jsonl`
also benefits (22 → 33 events, ~2097 → ~4011 px) since the same flicker
affected it, though less severely. `reaching_past.jsonl` and
`talking_hands.jsonl` still replay to zero intents, and
`middle_pinch.jsonl` still produces zero `Scroll` events — the debounce
only extends how long an already-active `Scroll` survives a flicker, it
cannot cause `Scroll` to be entered in the first place, so the strict
entry-side thumb-tuck bar (`THUMB_TUCK_MAX`) is untouched. See "Tuning"
below for `SCROLL_EXIT_S`.

This replaces an earlier design where a pinch meant both "move the cursor"
and, if held still, "start a drag" — which meant any pause while aiming a
pinch could be misread as the start of a drag. No dwell threshold separated
the two: raising it enough to stop the false drags also stopped genuine
drags from firing at all. The clutch (curl to freeze) is what pinch-to-move
used to provide implicitly, now split out as its own gesture, structurally
unable to be confused with a drag.

Double-click is a distinct gesture, not two fast clicks: pinch your middle
finger to your thumb instead of your index finger. Whichever fingertip is
actually closer to your thumb when the pinch closes decides which one it is
— not which finger you technically moved first. This matters because
pinching your middle finger to your thumb naturally drags your index
fingertip part of the way in too, so both can read as "closed" at once; a
fixed-priority rule that let the index finger win by default whenever that
happened would silently turn real double-clicks into spurious button-downs.

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
- **Accessibility** — the app requests access on startup, which is what makes
  it appear in the Accessibility list. Switch it on there, then restart the
  app. Until it is granted, the app refuses to start in live mode and prints
  this instruction instead.

Space switching also needs the Mission Control shortcuts `Ctrl+←` and `Ctrl+→`
enabled in System Settings → Keyboard → Shortcuts. They are on by default.

Space switching is implemented via AppleScript (`osascript` driving System
Events — see "Space switching goes through AppleScript, not CGEvent" below),
so it separately needs **Automation** access for your terminal to control
"System Events", under System Settings → Privacy & Security → Automation.
macOS prompts for this the first time a Space-switch gesture actually fires,
not at startup — if you dismiss or deny that prompt, Space gestures will
silently do nothing until you grant it there.

## Running

```bash
.venv/bin/python -m gesture_control.main --dry-run   # no real events, watch the HUD
.venv/bin/python -m gesture_control.main             # live
```

Always start with `--dry-run` after changing anything in `config.py`.

`--dry-run` prints one line per action. `move` fires roughly 30 times a
second, so consecutive moves are folded into a single `move x34`-style
summary instead of scrolling every click off screen; every click, button
down/up, scroll, or space event still prints immediately, on its own line.

If the project is not installed (`pip install -e ".[dev]"` was skipped), run
with `PYTHONPATH=src` instead:

```bash
PYTHONPATH=src .venv/bin/python -m gesture_control.main --dry-run
```

### Seeing what the system sees

```bash
.venv/bin/python -m gesture_control.main --dry-run --preview
```

`--preview` is the recommended way to see what the system is doing, and a
much better starting point than the HUD pill. It opens an OpenCV window,
mirrored like a selfie camera, showing the live feed with:

- the 21 hand landmarks and finger skeleton drawn on your hand
- the current state (`disarmed` / `frozen` / `tracking` / `pressed` / `scroll`)
  as a large, colour-coded banner
- the live `pinch_ratio` and whether the pinch currently reads as closed
- the last click, button-down/up, or space-switch, held on screen for about a
  second so it doesn't scroll past unnoticed

Press `Esc` or `q` to quit; this releases any held button the same way the
HUD path does. `--preview` replaces the Tk HUD for that run — the two never
run together — but drives the exact same pipeline, so it combines with
`--dry-run` and `--record` normally.

## Tuning

Every threshold lives in `src/gesture_control/config.py`. Change one, then run
the replay suite to see what it broke:

`ARM_DWELL_S` / `DISARM_S` (posture gate, `gate.py`) govern arming and
disarming. Arming is strict — open palm, `hand_scale` in range, held for
`ARM_DWELL_S` — and unchanged by the 2026-08-21 sustain change below.
Disarming used to require either the hand absent or `palm_facing` false,
continuously, for `DISARM_S`; sustaining now only requires the hand
present. Measured against `recordings/three_finger.jsonl`: a rightward
three-finger swipe rotates the palm edge-on to the camera for part of the
motion (normalized palm normal reaching -0.46 at p05 against a +0.39
median), which used to trip the old palm-facing sustain condition and
disarm the system mid-swipe — the gate disarmed 3 times over the
recording, for stretches up to 41 frames (1.4 s), with 62 of 267
three-finger frames caught disarmed. Dropping `palm_facing` from the
sustain condition (`Gate._can_sustain`, now just `f.present`) fixes this:
replaying the same recording now shows zero disarms and all 267
three-finger frames armed. This is a general fix, not a swipe-specific
one — gestures rotate the hand by nature, so a sustain condition that
fights that rotation works against every gesture, not just this one. See
`gate.py`'s `Gate` docstring for the full measurement and
`tests/test_gate.py`'s `test_stays_armed_when_palm_turns_away` for the
pinned regression test.

`PINCH2_CLOSE` / `PINCH2_OPEN` govern the double-click (middle-tip-to-thumb)
gesture, with the same hysteresis pattern as `PINCH_CLOSE` / `PINCH_OPEN`.
They are set well below the middle-to-thumb ratio observed while genuinely
index-pinching, so an ordinary click does not misread as a double.

The index pinch (`PINCH_CLOSE` / `PINCH_OPEN`) no longer classifies click
versus drag — it is a plain button down/up pair, and macOS reads a
down/move/up sequence as a click or a drag on its own, the same way it would
for a physical mouse. That removed five constants that used to exist purely
to make that classification (`TAP_MAX_S`, `TAP_MAX_PX`, `TAP2_MAX_PX`,
`DRAG_DWELL_S`, `DRAG_MAX_PX`) and the code that tuned them; they are gone,
not just unused.

Which finger's pinch a closing gesture belongs to is still decided by
comparing `pinch_ratio` to `pinch2_ratio` at the moment either crosses its
own CLOSE threshold — whichever is numerically smaller (physically closer to
the thumb) wins. This is the one piece of the old click/drag-disambiguation
machinery that survives, because it is what keeps a deliberate middle-pinch
double-click from also registering as a spurious index button-down (see
`config.py`'s `PINCH_CLOSE` comment for the measured margins).

`INDEX_CURL_CLOSE` / `INDEX_CURL_OPEN` govern the clutch: curling the index
finger toward the palm freezes the cursor so you can reposition your hand
without moving it. Curl and pinch are mutually exclusive (see "Gestures"
above): while curled, both pinch channels are ignored, and an already-open
button is released rather than held through the freeze. These are
calibrated against `recordings/clutch.jsonl`, a
dedicated 15 s recording that alternates between pointing and curling while
moving the hand throughout. Its `index_curl_ratio` distribution is cleanly
bimodal — curled at 0.56-0.9, pointing at 1.6-2.04, with a wide empty gap
between — and `INDEX_CURL_CLOSE = 0.95` sits in that gap. The upper bound is
set by pinching, not pointing: `index_curl_ratio` runs 1.03-1.39 while
genuinely pinching (see `PINCH_CLOSE`/`PINCH2_CLOSE` above), and a pinch
misread as a curl would freeze the cursor mid-drag, so `INDEX_CURL_OPEN =
1.20` stays below the pointing cluster while never touching the pinch floor.

`PINCH_MIN_EXTENSION` / `PINCH2_MIN_EXTENSION` (2026-08-19 follow-up) require
the pinching finger to be reasonably extended before a pinch may *close* —
tip-to-thumb proximity alone reads a partial curl as a press (see "Gestures"
above). Calibrated against frames read as pinched across `live_clicks.jsonl`,
`five_clicks.jsonl`, and `middle_pinch.jsonl`: the lowest index extension on
any genuine index-channel close is 1.25, and the lowest middle extension on
any genuine middle-channel close is 1.22. Both thresholds (`1.20` and `1.10`)
sit slightly below those measured floors, leaving margin for hand
orientations not in the recordings, while staying far above the curled
values (0.69 index, 0.54 middle) they exist to reject. `PINCH_MIN_EXTENSION`
is deliberately set equal to `INDEX_CURL_OPEN` (both `1.20`): this makes it
strictly subsume `INDEX_CURL_CLOSE`/`INDEX_CURL_OPEN` for the one purpose of
blocking a *new* index-channel pinch close, since the index curl-latch can
only be active at or below `INDEX_CURL_OPEN`. The curl-gate is not fully
redundant, though, and was kept: it also blocks the *middle* channel while
the index is curled (the extension gate only checks each channel against its
own finger), and it force-releases an already-open button the instant a curl
begins mid-press (the extension gate only governs closing, never releasing,
so a genuine drag can't be dropped by a finger flexing slightly).

`THUMB_TUCK_MAX` (2026-08-19) governs *entering* the scroll thumb gate:
scroll requires `thumb_tuck_ratio` (thumb tip to pinky knuckle,
scale-normalized) below this value, in addition to the finger posture, so
that opening the middle finger to pinch it to the thumb — which passes
through the scroll finger posture on the way there — cannot be misread as
scroll. Measured medians: scroll 0.55, middle-pinch 0.86, index clicks 0.90.
`0.70` keeps 195 of 260 genuine scroll frames in
`recordings/scroll_attempt.jsonl` while rejecting every colliding frame in
`middle_pinch.jsonl` and `live_clicks.jsonl`. Lowering it trades scroll
retention for a wider safety margin against the collision; raising it does
the opposite.

`THUMB_TUCK_RELEASE` (2026-08-19 follow-up) governs *leaving* scroll, and is
deliberately looser than `THUMB_TUCK_MAX` — the same asymmetry as
`ARM_DWELL_S`/`DISARM_S`: strict to enter, reluctant to leave. With a single
shared threshold, a momentary thumb drift above `THUMB_TUCK_MAX` mid-scroll
dropped straight to `TRACKING`, which processes pinches — letting a stray
pinch reading fire an unintended click during that window. The thumb must
now clear `THUMB_TUCK_RELEASE = 0.95`, not just `THUMB_TUCK_MAX`, before
scroll is left, so a brief un-tuck is absorbed while a genuine, deliberate
untuck (on the way to a real middle-pinch) still ejects the user. Raising it
further trades a wider absorption margin for a slower reaction to a genuine
exit; it must stay above `THUMB_TUCK_MAX` (enforced by
`test_thumb_tuck_thresholds_have_hysteresis_gap`). See the "Scroll thumb
gate is asymmetric" paragraph above for what this fix did and did not fix
against `recordings/scroll_attempt.jsonl`.

`SCROLL_EXIT_S` (2026-08-20 follow-up) governs how long the *whole* scroll
posture (finger shape and thumb together, via `_can_stay_in_scroll`) must
be continuously absent before `Scroll` is actually left — see "Scroll is
reluctant to leave" above. Diagnosed on `recordings/scroll_hold.jsonl`:
single-frame landmark noise broke a 15 s correctly-performed hold into 16
fragments, the longest only 1.73 s, and each fragment re-entered `Scroll`
and re-recorded the neutral, producing 47 px total instead of a real
scroll. At `0.35` s the fix raised that to ~820 px (36 events) on the same
recording. Raising it further trades a slower reaction to a genuine exit
for more flicker absorption; lowering it does the opposite and moves back
toward the original bug.

`MOVE_DEADZONE_PX` (2026-08-11) governs the jitter deadzone: sub-threshold
per-frame `Move` deltas accumulate in a residual instead of being emitted or
dropped, so random tremor (which cancels within the residual) is filtered
out while slow deliberate movement (which keeps accumulating in one
direction) still gets through — just in coarser steps. Raising it trades
more tremor rejection for coarser slow-movement steps; lowering it does the
opposite. It applies identically whether you're just moving the cursor or
dragging.

Scroll is rate-based (2026-08-20), not displacement-based — see "Scroll is
rate-based, not displacement-based" above for why. `SCROLL_NEUTRAL_DEADZONE`
sets how far your hand must move from the neutral point (recorded when you
enter `Scroll`) before scrolling starts at all — inside it you are
considered "centred" and nothing scrolls, which is both how you stop
scrolling and what absorbs hand tremor while holding still. `SCROLL_RATE_GAIN`
converts the remaining offset into a scroll speed in px/sec — this is the
constant you are most likely to want to adjust if scrolling feels too fast
or too slow across the board. Both are sized from real measurements on
`recordings/scroll_hold.jsonl`, where the user's actual deflections from
neutral run to a maximum of 0.041 frame-heights with a median of 0.012. The
deadzone is set to 0.008 (roughly three times the hand tremor noise floor of
0.0026), sitting well below the median to register normal holds while
absorbing jitter. The gain is calibrated for a maximum useful deflection of
about 0.04: at `SCROLL_NEUTRAL_DEADZONE = 0.008` and `SCROLL_RATE_GAIN = 60000`,
a 0.012 offset (the median real deflection) scrolls at roughly 240 px/sec, 0.023
(p75) at roughly 900 px/sec, 0.034 (p90) at roughly 1560 px/sec, and 0.041 (max)
at roughly 1980 px/sec. If you change other constants and scroll stops working,
replay `recordings/scroll_attempt.jsonl` and check the event count and total
pixel output before retuning.

```bash
.venv/bin/pytest tests/test_replay.py -v
```

Record a new fixture with `--record`:

```bash
.venv/bin/python -m gesture_control.main --dry-run --record recordings/my_case.jsonl
```

## If the mouse button gets stuck

A hard crash during a drag can leave macOS with the left button held. Click once
anywhere to release it. The watchdog, exit handlers, and a pipeline-error
callback cover the ordinary failure modes (camera stalls, a bad frame, an
uncaught exception). `Esc` is the backstop for anything else. A hard `SIGKILL`
is the one case nothing can cover — the process is gone before any of the
above gets a chance to run.

## Known limitations

- Precision is below a trackpad's; targets under about 20 px are harder to hit
- Detection degrades in dim or strongly backlit rooms
- Sustained use is tiring; the clutch lets your hand rest between movements
- Primary display only
- Scroll direction is fixed to natural scrolling and does not read the
  system's `com.apple.swipescrolldirection` preference. If you have natural
  scrolling turned off, scroll will feel inverted; negate `SCROLL_RATE_GAIN`
  in `config.py` as a workaround
- If a right-click ever appears (this app posts no right-clicks of its own),
  it indicates a modifier-flag leak: on macOS a plain left mouse-down created
  without explicit flags inherits whatever modifier state is currently
  active (e.g. a physically-held Control key), so Control+click reads as a
  right-click. `QuartzActuator._post_mouse` explicitly clears flags
  (`CGEventSetFlags(ev, 0)`) on every mouse event it posts to prevent this.
  (Space switching itself can no longer be the source of this leak — see
  below, it no longer posts a CGEvent at all)
- `recordings/clutch.jsonl` (point/curl only, no pinching) now replays to
  zero button or click events of any kind, as of the 2026-08-19
  extension-gate follow-up (see "Gestures" and "Tuning" above). It
  previously left 2 `ButtonDown`/`ButtonUp` pairs and 2 spurious `Click(2)`s
  even after the original curl/pinch mutual-exclusivity fix, including one
  at t=1.628s that had been diagnosed as "unconnected to curling" — that
  diagnosis was wrong: at that frame `middle_curl_ratio` was 0.966, i.e. the
  middle finger itself was genuinely curled, just not the index finger the
  original curl-gate watches. The previously-reported stuck button from this
  same recording (an unreleased `ButtonDown` at t=14.208s) was fixed earlier
  by the mutual-exclusivity change and remains fixed
- Space switching (2026-08-20) requires the exact three-finger posture.
  Originally it fired reliably only for leftward swipes: a rightward
  three-finger swipe rotates the hand edge-on to the camera for roughly
  0.3-0.4 s, tripping `palm_facing` false and, via the old `_can_sustain`,
  disarming the system mid-swipe. Fixed 2026-08-21 by dropping
  `palm_facing` from the gate's sustain condition — see "Turning your palm
  away does not stop the system" above and the `Gate` docstring in
  `gate.py`. `recordings/three_finger.jsonl` now replays to 5 genuine
  `Space` switches (up from 2, both one direction) — see
  `tests/test_replay.py`'s `test_three_finger_recording_yields_multiple_spaces`.
  Direction labels below reflect the hand-pushes-the-desktop convention
  fixed the same day — see the swipe-usability bullet below
- **Space switching goes through AppleScript, not CGEvent (2026-08-21).**
  Every other intent in this app posts a synthetic CGEvent to
  `kCGHIDEventTap`, and that mechanism reliably worked end-to-end — except
  for Space switching, which never actually worked in real use even though
  the gesture fired correctly and the CGEvents posted without error.
  Confirmed live: the real keyboard's `Ctrl+←`/`Ctrl+→` switches Spaces
  fine, Accessibility is granted, mouse CGEvents work, no Secure Input
  holder was present, and a synthetic `Cmd+Space` posted the same way DID
  open Spotlight — so synthetic keystrokes reach the system fine in
  general. Four different CGEvent constructions for the Space key combo
  (HID source + session tap, HID source + HID tap, combined source +
  session tap, and a real Control keydown held around the arrow key) all
  failed to move the desktop. `osascript -e 'tell application "System
  Events" to key code 124 using control down'` DID switch it. Conclusion:
  Mission Control's Space shortcuts are consumed by WindowServer before the
  event tap `CGEventPost` delivers to, while AppleScript's System Events
  path reaches them by a different route. `QuartzActuator._space_switch`
  now shells out to `osascript` instead of using `CGEvent` — this is
  deliberate, not an oversight, and it needs the separate Automation
  permission described under "Permissions" above. The call runs
  synchronously (`subprocess.run`, ~tens of ms, at most once per
  `SWIPE_COOLDOWN_S` = 800 ms) and never raises: a failed or slow Space
  switch prints an actionable message to stderr instead of taking down the
  pipeline mid-gesture.
- **Three-finger swipe usability fixes (2026-08-21).** Live use surfaced
  three problems with the swipe once it was firing reliably:
  - *Direction was backwards.* The old mapping fired `Space("right")` for a
    rightward hand movement — the opposite of the macOS convention, where
    content follows the hand (a three-finger trackpad swipe with natural
    scrolling). `state_machine.py`'s `_detect_swipe` now maps hand-left to
    `Space("right")` and hand-right to `Space("left")`; see the "Gestures"
    table above.
  - *The required sweep was impractically long.* `SWIPE_DIST` was 0.20
    frame-widths — 51% of the user's measured usable hand width (0.39-0.79),
    forcing a sweep from one extreme of their reach to the other. Swept
    against all twelve recordings from 0.20 down to 0.06:
    `recordings/three_finger.jsonl` holds at exactly 5 swipes with the same
    direction sequence across the whole range, and false positives stay at
    zero across all eleven other recordings throughout that range too.
    Lowered to `SWIPE_DIST = 0.10` — about 26% of the user's hand range,
    still a wide margin above the false-positive floor found by the sweep.
  - *Forming or releasing the posture fired stray presses.* Replaying
    `recordings/three_finger.jsonl` emitted 2 `ButtonDown` and 1 `Click(2)`
    the user never intended, even though only 2 of its 267 three-finger
    frames actually read as pinched — the presses fired while the hand was
    forming or releasing the three-finger shape, passing through
    configurations that read as a pinch. A pinch-length debounce was tested
    and ruled out: spurious pinch episodes during the swipe run a median of
    7 consecutive frames, longer than genuine clicks in
    `recordings/live_clicks.jsonl` at a median of 2, so episode length
    cannot separate them. Fixed the same way as the existing curl-vs-pinch
    and scroll-vs-double-click mutual exclusions: while the three-finger
    posture is held, or within `SWIPE_PINCH_LOCKOUT_S` (0.4 s) of when it
    was last held, both pinch channels are ignored, and an already-open
    pinch is released (`ButtonUp`) rather than held through, the same
    stuck-button safety rule as the curl gate (commit `577b189`). After
    this fix, `recordings/three_finger.jsonl` replays to zero `ButtonDown`,
    `ButtonUp`, or `Click` events of any kind while still producing 5
    `Space` switches. Recordings that never hold the three-finger posture
    are structurally unaffected by this gate; confirmed by replaying all
    twelve fixtures, not assumed.
