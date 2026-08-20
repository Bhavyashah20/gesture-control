# Gesture Control — Design

Date: 2026-08-10
Status: Approved and implemented; amended 2026-08-11 (direct-manipulation
redesign; stability fixes); amended 2026-08-19 (scroll acceleration; scroll
thumb gate; scroll thumb gate made asymmetric; pinch requires an extended
finger); amended 2026-08-20 (rate-based scrolling replaces displacement;
absent frames must not reach the movement path; scroll exit debounce;
Space switch requires an exact three-finger posture); amended 2026-08-21
(posture gate sustain no longer requires palm_facing)

## Amendment (2026-08-21): sustain no longer requires palm_facing

**The three-finger swipe worked leftward but was lost rightward, and the
cause was the posture gate, not the swipe detector.** The previous
amendment ("Space switch requires an exact three-finger posture" below)
diagnosed this and left it out of scope: every rightward swipe in
`recordings/three_finger.jsonl` rotates the palm edge-on to the camera for
roughly 0.3-0.4 s, tripping `Gate._can_sustain`'s `palm_facing`
requirement and, via `DISARM_S`, dropping the state machine out of
`Tracking` mid-swipe.

**The cause is physical, not a detection artifact.** Handedness is stable
across all 448 frames in the recording ("Right", zero label changes), and
only 4% of frames sit in the genuinely ambiguous edge-on band — but the
normalized palm normal reaches -0.46 at p05 while the median is +0.39.
Swiping right genuinely rotates the palm past facing the camera; this
isn't landmark noise being misread.

**The fix drops `palm_facing` from the sustain condition:**

```python
def _can_sustain(self, f: Features) -> bool:
    return f.present
```

`_can_arm` is unchanged — arming still requires `palm_facing`, at least
`ARM_FINGERS_MIN` extended fingers, `hand_scale` in range, and the full
`ARM_DWELL_S` dwell. This extends the gate's existing asymmetry (arming
strict, sustaining loose — see "Posture gate" below) rather than replacing
it: the conditions that prove intent at the start are conditions ordinary
use then violates, and that was already true of the finger-extension
requirement (pinching closes the index finger) before it was true of
`palm_facing`. The general lesson: gestures rotate the hand, so any
sustain condition on orientation fights every gesture, not only the one
that happened to expose it first.

**Measured effect on `recordings/three_finger.jsonl`:** before the fix,
the gate disarmed 3 times over the recording, for stretches up to 41
frames (1.4 s), with 62 of 267 three-finger frames caught disarmed; full
pipeline replay produced only 2 `Space` intents, both `Space("left")`.
After the fix: zero disarms, all 267 three-finger frames armed, and replay
produces 5 `Space` intents — 3 `Space("right")` and 2 `Space("left")` —
matching the 5 raw posture/velocity crossings the previous amendment
measured independently of the gate. Both directions now work.

**Verified against the non-negotiable fixtures.** `reaching_past.jsonl`
and `talking_hands.jsonl` still replay to zero intents of any kind —
arming is untouched, so neither fixture, which never satisfies the strict
arm condition, ever arms in the first place. A stickier sustain condition
only changes behaviour once armed, so this had to be checked, not assumed.

**Effect on `recordings/scroll_hold.jsonl`.** Also stickier, and measurably
better, though not the recording this fix targets: before, 88 `Scroll`
events totalling ~3270 px; after, 111 events totalling ~4162 px (roughly
27% more of both). The mechanism is the same one-level-out effect as
above — when the gate disarmed mid-hold on a palm-orientation blip, the
state machine fell all the way back to `Disarmed`, dropping `Scroll`'s
rate neutral entirely (a strictly worse loss than the fragmentation
`SCROLL_EXIT_S` already absorbs within an armed session). This was
measured, not assumed, to confirm it moved in the right direction rather
than being an untested side effect.

**Tests.** `tests/test_gate.py` pins the change directly:
`test_stays_armed_when_palm_turns_away` holds `palm_facing=False` for
several seconds past `DISARM_S` with the hand present throughout and
asserts the gate never disarms — verified to fail against the pre-fix
`_can_sustain`. `test_requires_palm_facing_to_arm` pins that arming is
unaffected. `test_disarms_when_hand_absent_even_with_palm_turned_away`
pins that presence, not orientation, is what still disarms.
`test_disarms_when_palm_turns_away` — the previous test, which asserted
disarming on palm orientation alone — encoded the now-obsolete behaviour
and was replaced by `test_stays_armed_when_palm_turns_away` rather than
kept passing by coincidence.
`tests/test_replay.py`'s `test_three_finger_recording_yields_multiple_spaces`
is updated to the new, higher, both-directions figure.

**Consequence: turning the palm away no longer stops the system.** This is
worth stating plainly because it is a behaviour change to something safety
lives near. The system now stops the same two ways it always could stop
regardless of orientation: drop the hand out of frame (disarms after
`DISARM_S` with the hand absent) or press `Esc` (the kill switch — see
"Safety" below). See the README's "Gestures" section for the user-facing
version of this note.

## Amendment (2026-08-20 second follow-up): Space switch requires an exact three-finger posture

**Space switching fired on any posture with three or more fingers up, not
specifically a three-finger swipe.** `_detect_swipe`'s finger gate was
`sum(f.fingers_up) >= config.ARM_FINGERS_MIN` — the same "three or more"
threshold the posture gate uses to arm the whole system. An open palm (four
fingers up) satisfies that easily, and open palm is the *resting* hand
shape while armed, so ordinary armed hand movement — reaching across the
frame, repositioning between clicks — could cross `SWIPE_DIST`/`SWIPE_VEL`
and switch Spaces without the user making anything resembling a deliberate
swipe gesture. The user asked for a three-finger swipe specifically,
matching the macOS trackpad convention, which also closes this
false-positive source.

**Finger detection needed no change.** An earlier assumption held that
detecting the three-finger posture reliably would require new work on the
finger-extension logic. The user's recording,
`recordings/three_finger.jsonl` (15 s of deliberate three-finger swipes),
disproved that: `(True, True, True, False)` — index, middle, ring extended,
pinky down — is already the dominant pattern at 267 of 448 present frames,
using the existing `fingers_up` extraction unmodified. The fix is purely a
gate change:

```python
def _swipe_finger_shape(f: Features) -> bool:
    return f.fingers_up == (True, True, True, False)
```

replacing the `sum(...) >= ARM_FINGERS_MIN` check in `_detect_swipe`, and
distinguishable from the scroll posture (`_scroll_finger_shape`) by the
ring finger: scroll needs it down, swipe needs it up. Simulated against
every existing fixture, the old `>= 3` rule produced spurious swipes in
`one_sweep`, `live_clicks`, `middle_pinch` and `reaching_past`; the exact
posture produces none in any of them.

**`SWIPE_VEL` needed retuning — by one hundredth.** With the posture fixed,
the user's real three-finger swipes still didn't fire. Measured from the
recording: displacement comfortably clears `SWIPE_DIST` (0.268 frame-widths
over roughly 0.34 s), but peak velocity is 0.79 frame-widths/sec against
`SWIPE_VEL = 0.8` — every swipe in the recording missed the threshold by a
hundredth of a frame-width per second. Lowered to:

```python
SWIPE_VEL = 0.6
```

0.7 was tried first and only recovered 4 of the recording's swipes, with
less clean direction separation; 0.6 recovers all 5 raw crossings (measured
by evaluating `_detect_swipe`'s posture/displacement/velocity condition
directly against every present frame, independent of the arm/disarm gate)
and introduces zero false positives across the other eleven recordings.

**`SWIPE_WINDOW_S` was tested wider and made things worse — left alone.**
Widening the 0.35 s window to capture more of a slow swipe seems like an
obvious companion move, but was tested and rejected: a longer window starts
including the hand's *return* motion after the swipe, which cancels net
displacement against `SWIPE_DIST` and drops `three_finger.jsonl`'s raw
detection count from 5 to 2. `SWIPE_WINDOW_S` stays at 0.350 — do not widen
it on the assumption that it will help.

**Full-pipeline replay tells a different story than the raw crossing
count, and that gap is real, not a bug.** The 5 raw crossings above (3
right, 2 left) are measured by calling `_detect_swipe` directly against
every present frame — finger posture and displacement/velocity alone,
bypassing the arm/disarm `Gate` and the curl/pinch state machine entirely.
That is not how the shipped system, or any other fixture test in this
codebase, is verified: every other regression test in `test_replay.py`
replays fixtures through a fresh `StateMachine` via `replay()`, gate and
all. Doing the same for `three_finger.jsonl` yields only 2 `Space`
intents, both `Space("left")` — the 3 rightward crossings are lost.

The mechanism: every rightward swipe in this recording is preceded by
roughly 0.3-0.4 s where `palm_facing` reads `False` — rotating the hand
sideways to swipe right also rotates it edge-on to the camera, at least for
this user's swipe technique. That is long enough to trip the Gate's
`DISARM_S` (0.5 s sustain-loss window) and drop the state machine out of
`Tracking` for part of the swipe, so `_detect_swipe` either never sees the
fast phase of the motion or resumes with too little of the `SWIPE_WINDOW_S`
history left to clear `SWIPE_DIST`/`SWIPE_VEL`. Leftward swipes in this
recording never trip `palm_facing` the same way, and both register
cleanly.

This is a genuine measurement, not a defect introduced by this change —
`Gate`, `DISARM_S`, and `palm_facing` are untouched by it, so the
interaction predates this work and would show up under the old finger gate
too, just masked by the fact that the old gate never fired on this
recording at all (three-or-more-fingers plus the old `SWIPE_VEL = 0.8`
rejected every crossing regardless). Fixing it was out of scope for this
change at the time: it was neither requested nor measured against
unrelated recordings, and would mean retuning the arm/disarm gate or
`palm_facing`, both shared by every other gesture. The regression test for
this change, `test_three_finger_recording_yields_multiple_spaces` in
`tests/test_replay.py`, pinned the true, lower, single-direction figure
(`>= 2`, all `Space("left")`) rather than the higher bypass count, so it
stayed honest about what the shipped system actually did at the time —
see that test's docstring for the full measurement.

**Superseded 2026-08-21.** This "out of scope" gap was the very next fix —
see "Amendment (2026-08-21): sustain no longer requires palm_facing" above.
`Gate._can_sustain` no longer requires `palm_facing`, so this recording now
replays to 5 `Space` intents, 3 right and 2 left, and the test above
asserts that instead. The measurement and mechanism described in this
section remain accurate as a historical record of the diagnosis; they are
no longer the shipped behaviour.

**Verified against every other fixture.** `reaching_past.jsonl` and
`talking_hands.jsonl` still replay to zero intents of any kind
(non-negotiable, unchanged). `one_sweep.jsonl` — the user's old open-palm
sweep, recorded before this change — now replays to zero `Space` intents;
this is the change working as intended, not a regression, since an open
palm is no longer the swipe posture. `live_clicks.jsonl` previously
contained one genuine `Space("left")` performed with an open palm; under
the exact posture gate it no longer registers, for the same reason.
`recordings/three_finger.jsonl` is committed as a fixture and is now the
regression test for the three-finger posture and `SWIPE_VEL` retuning.

## Amendment (2026-08-20 follow-up): scroll exit debounce

**A correctly performed gesture produced next to nothing.** The user
recorded `recordings/scroll_hold.jsonl`, 15 s of correctly performing the
rate-scroll gesture, and it produced 10 `Scroll` events totalling 47 px.
The gesture itself was not the problem: `(True, True, False, False)` is the
dominant finger pattern at 224 of 361 present frames, exactly the intended
shape.

The problem was that the scroll gate flickered. Over those 15 s there were
16 unbroken runs of a satisfied `_can_stay_in_scroll` predicate; the
longest was 52 frames (1.73 s), and many were 1-3 frames. The finger
condition dropped out 13 times and the thumb condition 16 times —
single-frame landmark detection noise, not the user changing their hand.
Each break exited `Scroll`, and each re-entry re-recorded the rate-scroll
neutral at the hand's then-current position (see the entry mechanism in
"Amendment (2026-08-20): rate-based scrolling replaces displacement"
above). So the offset that drives scroll speed was continuously reset to
zero and never accumulated — hence 47 px.

**The fix: `Scroll` is reluctant to leave, one level further than the
existing thumb hysteresis.** `THUMB_TUCK_RELEASE` (2026-08-19) already made
leaving `Scroll` reluctant with respect to the thumb specifically, but the
finger conditions (index/middle extended, ring not) had no hysteresis at
all, and thumb hysteresis alone was not wide enough to absorb frames where
the *finger* reading was the one that flickered. This follow-up sits on top
of the whole predicate, mirroring the posture gate's own arm/disarm
asymmetry (`ARM_DWELL_S`/`DISARM_S`) one level further in:

```python
SCROLL_EXIT_S = 0.35
```

While in `Scroll`, when `_can_stay_in_scroll(f)` fails, the state machine
starts (or continues) a debounce timer, `_scroll_exit_since`, instead of
leaving on the spot — the same pattern as `Gate._lost_since`. Only once
that timer has run continuously for `SCROLL_EXIT_S` does `Scroll` actually
transition to `Tracking`, and only then is `_scroll_neutral` cleared. If
the posture is satisfied again before the timer elapses, it is reset to
`None` and `Scroll` continues uninterrupted — critically, `_scroll_neutral`
is left exactly as it was, so a fragment that recovers within the debounce
window keeps scrolling at the same rate it was already at, rather than
starting over from zero.

**What happens to scroll output during the debounce window.** The frame's
`Scroll` computation (offset from `_scroll_neutral`, speed, `px = speed ×
dt`) runs exactly as it would with the posture satisfied, regardless of
whether `_can_stay_in_scroll` passed or failed that particular frame — the
debounce timer is bookkeeping for the eventual transition decision, not a
gate on this frame's output. Two choices were considered:

1. **Suppress `Scroll` on a posture-failing frame, keep the state and
   neutral.** Philosophically cleaner — the invariant "the posture holds
   this frame" would stay true of every frame that actually emits `Scroll`
   — but it introduces a real gap: a hand held at a sustained offset would
   visibly pause for up to `SCROLL_EXIT_S` on every flicker, even though
   nothing about the hand's actual position changed.
2. **Compute output normally regardless of this frame's posture reading
   (chosen).** Mirrors what the posture gate already does during its own
   `DISARM_S` grace window: when `_can_sustain` fails but the gate hasn't
   yet disarmed, the rest of the pipeline (cursor tracking, in that case)
   keeps running on that frame's real data unmodified — the grace window
   delays the *disarm decision*, it does not pause everything else in the
   meantime. Applying the same principle here means a single flickered
   frame produces zero visible effect: no stutter, no pause, no reset. The
   cost is that a frame whose finger or thumb reading currently fails
   `_can_stay_in_scroll` can still emit a `Scroll` intent, on the theory
   that the reading is what's noisy, not the underlying hand position (the
   One Euro filter already dampens single-frame position noise
   independently).

Option 2 was implemented, for consistency with the existing precedent in
this codebase and because it fully eliminates the stutter, not just
shrinks it.

**Verified against every fixture.** Replayed `recordings/scroll_hold.jsonl`:
10 events / 47 px before → 36 events / ~820 px after — roughly 17x, and
comfortably "dramatically more" than the pre-fix number, confirming the
flicker diagnosis rather than some other mechanism.
`recordings/scroll_attempt.jsonl` also increases (22 → 33 events, ~2097 →
~4011 px), since the same class of flicker affected it, just less
severely — its replay test asserts lower bounds, not exact figures, so this
is not a regression. `reaching_past.jsonl` and `talking_hands.jsonl` still
replay to zero intents of any kind (non-negotiable, unchanged).
`middle_pinch.jsonl` still produces zero `Scroll` events: the debounce only
extends how long an *already-active* `Scroll` survives a flicker on exit,
it has no effect on entry, so the strict entry-side thumb-tuck bar
(`THUMB_TUCK_MAX`) that keeps a middle-pinch double-click out of `Scroll`
in the first place is untouched.

`recordings/scroll_hold.jsonl` is committed as a fixture and is now the
regression test for this entire class of bug — see "Testing" below.

## Amendment (2026-08-20): absent frames must not reach the movement path

**An absent frame is not a hand at the centre of the frame.** Reported by
the user: "if it is disabled somehow the cursor stays in the same
position" — it did not; it jumped to the middle of the screen and back on
every brief detection dropout while armed.

`features.extract` returns the `_ABSENT` sentinel for any `present=False`
`HandFrame`, and that sentinel's `cursor_ref` is `Point2(0.5, 0.5)` —
frame-centre — by construction (see `features.py`). This is not a rare
edge case: the gate's `DISARM_S` sustain window (500 ms — see "Posture
gate" below) exists specifically so a *momentary* tracking loss doesn't
disarm the system, and `main.py` deliberately feeds an absent frame on
every failed camera read so the gate's timers keep advancing and the
stuck-button watchdog can still fire. So the state machine sees
`present=False` frames routinely while still armed, not just at the
instant of disarming.

Before this fix, `state_machine.update` had no guard on `f.present` in the
armed path: it filtered the sentinel's `cursor_ref` like any real position,
computed a delta from the last real hand position to frame-centre, emitted
a `Move` for it, and stored the sentinel as the new reference. The next
real frame then computed another large delta back from centre to the
hand's actual (undropped) position. Net effect: every dropout threw the
cursor at the screen centre and back, twice the size of the actual gap.

**The fix.** `StateMachine.update` now checks `f.present` immediately
after the `Disarmed → Tracking` re-seed (which cannot itself see the
sentinel — arming requires `f.present`, so that frame is always real) and
before any of the filter, delta, curl, or pinch logic runs:

```python
if not f.present:
    self._ref, self._t = None, None
    return intents
```

Nothing else touches state for this frame. Concretely, per active state:

- **`Tracking` / `Frozen`.** No `Move` is computed or emitted; the One
  Euro filter is never fed the sentinel (feeding it would have polluted
  its internal velocity estimate even without emitting a `Move`, biasing
  the *next* real frame's smoothing). Clearing `_ref`/`_t` to `None`
  reuses the exact re-seed mechanism the `Disarmed → Tracking` transition
  already relies on: every delta computation below is already guarded by
  `if self._ref is not None else 0.0`, so the next real frame naturally
  computes a zero delta and re-anchors from wherever the hand actually is
  — no jump replayed for the gap, and no separate re-seed path to
  maintain.
- **`Pressed`.** The button stays down through the dropout: `_pinch_closed`
  and `_curled` are untouched (the curl/pinch channels are not evaluated
  at all on an absent frame — evaluating them against sentinel values,
  even though the sentinel is shaped to read as "unpinched, uncurled" so
  it is not self-evidently dangerous, still risks a spurious transition
  for no benefit, so the frame is skipped outright rather than evaluated
  and discarded). Only the existing stuck-button watchdog — `Gate`'s own
  `DISARM_S` timer, orthogonal to this change — releases the button, and
  only if the hand never returns before it fires. On reappearance the
  drag resumes from the hand's real position with no jump, via the same
  `_ref = None` re-seed above.
- **`Scroll`.** Nothing is computed; no `Scroll` is emitted for the gap
  (running the rate-scroll formula against the sentinel's `cursor_ref`
  would produce a bogus offset from `_scroll_neutral` and scroll at a
  meaningless rate). `_scroll_neutral` is left exactly as recorded on
  entry — it is not re-derived from, or reset by, the sentinel — so
  scrolling resumes on reappearance relative to the same neutral as
  before the dropout, not a stale or corrupted one.

**Side effect worth recording.** The same contamination existed one level
up: `_detect_swipe` used to run on absent frames too, appending the
sentinel's raw (unfiltered) `cursor_ref` into the swipe history. A real
frame arriving immediately after an absent one then computed its
swipe displacement/velocity against that frame-centre point instead of
the hand's actual prior position, occasionally crossing `SWIPE_DIST` /
`SWIPE_VEL` and firing a `Space` the user never gestured. Skipping absent
frames entirely (they never reach `_detect_swipe` now, since it is only
called from the `Tracking` fall-through) removes this too.
`recordings/live_clicks.jsonl` demonstrates it directly: replayed before
this fix it produced two incidental `Space("right")` events, both
immediately following an absent frame (`t≈7.548` and `t≈8.58`-`8.647`);
replayed after, it produced exactly one `Space("left")`, corresponding to
the recording's one genuine sustained leftward sweep
(`cursor_ref.x` 0.927 → 0.457 between frames 232 and 249) — performed with
an open palm. The 2026-08-20 second follow-up (see "Amendment (2026-08-20
second follow-up)" above) then replaced the open-palm swipe posture with an
exact three-finger posture, so that one remaining genuine-but-open-palm
sweep no longer registers either: `live_clicks.jsonl` now replays to zero
`Space` events. See
`tests/test_replay.py::test_live_clicks_yields_no_space`.

Verified against every fixture in `recordings/`:
`reaching_past.jsonl` (9 of 300 frames present — heavily absent-dominated,
a good stress case for this exact change) and `talking_hands.jsonl` still
replay to zero intents of any kind, unchanged by this fix. See
`.superpowers/sdd/2026-08-10-gesture-control/absent-frame-report.md` for
the full before/after intent-count table across all fixtures.

## Amendment (2026-08-20): rate-based scrolling replaces displacement

Scroll was displacement-based from its introduction (2026-08-11) through the
acceleration-curve and thumb-gate amendments above: scroll distance followed
how far the hand physically moved, `scroll_px = dy × SCROLL_GAIN ×
scroll_accel(speed)`. The user reported a hard failure this model cannot
avoid by tuning: when their hand reached the top or bottom of its
comfortable range, there was nowhere left to move, so scrolling stopped and
they were stuck mid-page. Measured directly from
`recordings/scroll_attempt.jsonl`, the usable vertical span during the
scroll gesture is only 0.22 of frame height. At the tuned `SCROLL_GAIN =
20000` and `scroll_accel`'s ceiling (`SCROLL_ACCEL_MAX = 2.5`), that caps a
single displacement stroke at roughly 0.22 × 20000 × 2.5 ≈ 4400 px, at any
gain -- no amount of retuning `SCROLL_GAIN` or the acceleration curve fixes
a hand-range problem, because the problem is that distance is bounded by
displacement at all.

**The fix: scroll speed from hand offset, not scroll distance from hand
displacement.** Hand range stops mattering, because the user holds a
position rather than sweeping through one, so they can never run out.
Mechanically, entering `Scroll` records the hand's current vertical
position as `neutral` (re-recorded on every entry, so re-entering after
repositioning never inherits a stale neutral from a previous visit). Each
frame while in `Scroll`:

```
offset = current_y - neutral
if abs(offset) <= SCROLL_NEUTRAL_DEADZONE:
    # emit nothing -- lets the user stop by returning to centre, and
    # prevents drift from tremor while holding still
else:
    speed = sign(offset) * (abs(offset) - SCROLL_NEUTRAL_DEADZONE) * SCROLL_RATE_GAIN  # px/sec
    px = speed * dt
```

The existing `SCROLL_MIN_PX` per-event deadband is unchanged and still
applies to the resulting per-frame `px`. `SCROLL_DWELL_S` (entry dwell) and
the thumb-tuck entry/exit gates (`THUMB_TUCK_MAX` / `THUMB_TUCK_RELEASE`,
2026-08-19 above) are untouched -- this amendment only changes what happens
*while* the state machine is in `Scroll`, not how it enters or leaves.

Sign convention is preserved from the displacement model, not inverted: the
old code produced positive `px` when `dyn` (the frame-to-frame vertical
delta) was positive, i.e. the hand moving downward in frame coordinates.
The new code produces positive `px` when `offset` is positive, i.e. the hand
currently positioned below neutral -- the same physical direction maps to
the same output sign, just keyed off position rather than instantaneous
velocity.

`SCROLL_GAIN`, `SCROLL_ACCEL_MIN`, `SCROLL_ACCEL_MAX`, `SCROLL_ACCEL_VREF`,
and the `scroll_accel()` function existed only to shape displacement-based
scrolling and are removed along with it -- see "Amendment (2026-08-19):
scroll gets its own acceleration curve" below for the design they replace.
Two new constants take their place, both sized from the same 0.22
frame-height span measured above, so a comfortable maximum deflection is
roughly 0.041 at most, with a median of 0.012:

```
SCROLL_NEUTRAL_DEADZONE = 0.008   # frame-heights; inside this, no scrolling
SCROLL_RATE_GAIN = 60000.0        # px/sec per frame-height of offset
```

At these values (tuned from actual measurements on `recordings/scroll_hold.jsonl`):
a 0.008 offset (the deadzone boundary) gives 0 px/sec; 0.012 (median real deflection)
gives 240 px/sec; 0.023 (p75) gives 900 px/sec; 0.034 (p90) gives 1560 px/sec; 0.041
(max) gives 1980 px/sec -- verified directly against the running state
machine, not just the formula, and matching within filter-settling noise.

**Replayed against the fixtures.** `recordings/scroll_attempt.jsonl` was
recorded as a sweeping motion for the displacement model and was not
re-recorded for this change -- its numbers change substantially under the
rate model, as expected, and are not a regression: 22 `Scroll` events
totalling ~2097 px over the 15 s recording (previously 102 events, 9341 px
under the asymmetric-gate displacement model), across 7 separate entries
into `Scroll` and 155 frames spent in that state. Fewer, larger events than
before is the expected shape of the change: offset is measured from a
single neutral recorded once per entry, so a sweep that keeps passing back
near neutral only fires while held away from it, not on every frame of
motion the way displacement scrolling did. `reaching_past.jsonl` and
`talking_hands.jsonl` continue to replay to zero intents of any kind, and
`middle_pinch.jsonl` continues to produce zero `Scroll` events -- this
change is confined to the `Scroll` state's internals and does not touch
posture detection, entry/exit gating, or any other gesture.

## Amendment (2026-08-11): stability fixes — scroll magnitude, jitter, cursor reference

Three changes, each backed by measurement against the user's own recordings,
addressing two reports: "cursor is too unstable to hit small targets like
window close buttons" and "scroll does nothing."

1. **`SCROLL_GAIN` raised 900 → 5000 → 20000.** `recordings/scroll_attempt.jsonl`
   proved scroll's posture detection and dwell logic were already correct;
   the gain alone was insufficient. Further tuning showed 5000 was still too
   weak (~160 px/sec, trackpad flicks are 1000–2000 px/sec); raised to 20000
   targeting ~640 px/sec. See "Scroll" below.
2. **Jitter deadzone with accumulation, `MOVE_DEADZONE_PX = 2.0`.** Sub-
   threshold per-frame `Move` deltas accumulate in a residual instead of
   being emitted or dropped outright, so random tremor cancels (cursor sits
   still) while consistent slow movement still arrives (precision movement
   is slow movement, and a plain deadzone would have blocked it too). See
   "The jitter deadzone" under "State machine" below.
3. **`cursor_ref` changed from the index MCP knuckle to the palm centroid**
   (mean of the index, middle, ring, and pinky MCP knuckles). Measured 16-21%
   steadier on three of the user's four recordings, 3% worse on the fourth
   (`clutch.jsonl`, dominated by extreme finger articulation that moves the
   knuckles themselves). Net win, applied. See "Feature extraction" below.

## Amendment (2026-08-19): scroll gets its own acceleration curve

Raising `SCROLL_GAIN` (2026-08-11, above) fixed "scroll does nothing" but
left a related report: "the amount of scroll is hard to control." The cause
was that scroll had no acceleration curve while the cursor did — the cursor
scales its gain by `accel(speed)` so slow hand movement gives fine control
and fast movement gives reach, but scroll's output was flat
(`px = dyn × SCROLL_GAIN`), so every hand speed scrolled at the identical
rate. Measured vertical hand speed while holding the scroll posture in
`recordings/scroll_attempt.jsonl` spans two orders of magnitude (p10 0.001,
median 0.011, p75 0.040, p90 0.110 frame-heights/sec); at the flat gain
those map to roughly 29–2196 px/sec, so there was no way to get both a small
precise scroll and a long fast one, and because even the gentlest movement
scrolled, hand tremor while holding the posture made the page drift.

The fix mirrors the cursor's shape with scroll's own constants — scroll hand
speed runs roughly an order of magnitude slower than cursor hand speed, so
`ACCEL_VREF` (tuned for the cursor) is the wrong scale for it:

```
SCROLL_ACCEL_MIN = 0.2
SCROLL_ACCEL_MAX = 2.5
SCROLL_ACCEL_VREF = 0.05
```

`scroll_accel(speed) = clamp(SCROLL_ACCEL_MIN + speed / SCROLL_ACCEL_VREF,
SCROLL_ACCEL_MIN, SCROLL_ACCEL_MAX)`, the same clamp shape as `accel()`. The
`Scroll` branch of the state machine now computes the frame's vertical hand
speed (`abs(dyn) / dt`, guarded against `dt <= 0`) and scales by
`scroll_accel(speed)`: `px = dyn × SCROLL_GAIN × scroll_accel(speed)`. The
existing `SCROLL_MIN_PX` per-event deadband is unchanged and still applies to
the resulting `px`.

Replayed against `recordings/scroll_attempt.jsonl`: 128 `Scroll` events
totaling 11206 px over the 15 s gesture (previously 154 events, 5538 px under
the flat gain) — comfortably inside a usable range, not "does nothing" and
not an unusable firehose. Effective scroll rate at the user's measured
speeds: gentle (p10, 0.001) rounds to 0 px/sec — below `SCROLL_MIN_PX` every
frame, since scroll has no residual accumulator (see "The jitter deadzone"
below for why scroll deliberately doesn't get one), so tremor at that speed
no longer drifts the page at all; median (0.011) ≈ 92 px/sec, fine control;
p75 (0.040) ≈ 800 px/sec; p90/flick (0.110) ≈ 5280 px/sec, reach without
being clamped at `SCROLL_ACCEL_MAX` (raw value 2.4, ceiling is 2.5) — a
harder flick still has headroom to go faster. `reaching_past.jsonl` and
`talking_hands.jsonl` continue to replay to zero intents, unaffected by a
change confined to the `Scroll` state.

## Amendment (2026-08-19): scroll requires a tucked thumb

The user reported spurious scrolling when they meant to double-click:
"in scroll i dont want it to be activated unless my thumb is closed like
to my palm since i tend to double press by opening my middle finger and the
index is open for tracking so it mistakes for scrolling." Diagnosis: the
scroll posture is index extended, middle extended, ring not extended.
Double-click is a middle-fingertip-to-thumb pinch (see "Pinch
disambiguation" below). Opening the middle finger to perform that pinch
necessarily passes through the scroll finger posture on the way there,
since the index stays extended the whole time for tracking — the finger
shape alone cannot tell the two gestures apart mid-motion.

The user's own proposed fix is what shipped: require the thumb tucked
toward the palm for scroll. During a middle-pinch the thumb is extended out
to meet the middle fingertip, so the two gestures become mutually exclusive
by construction, the same structural trick already used to keep curl and
pinch apart (see "The clutch: freezing the cursor" below).

The signal is `thumb_tuck_ratio` = ‖landmark[4] − landmark[17]‖ /
`hand_scale` (thumb tip to pinky knuckle) — small means tucked. Measured
medians across the recordings: `scroll_attempt` 0.55, `clutch` 0.75,
`middle_pinch` 0.86, `live_clicks` 0.90, `five_clicks` 0.95. Combined with
the existing finger predicate, frames passing the full scroll gate at
various thresholds:

```
threshold   scroll_attempt   middle_pinch   live_clicks
  1.00        254 of 260       2 of 3         0 of 2
  0.80        229 of 260       0 of 3         0 of 2
  0.70        195 of 260       0 of 3         0 of 2
  0.60        173 of 260       0 of 3         0 of 2
```

`THUMB_TUCK_MAX = 0.70` was chosen: it retains 75% of the genuine scroll
gesture and rejects every colliding frame, and sits at the tighter end of
the safe range (0.60–0.80 all reject every collision) because the 75%
retention figure is measured on a recording where the user was NOT
deliberately tucking their thumb — now that the tuck is part of the
gesture, real retention should be higher, so there is no reason to spend
extra margin loosening the threshold.

The condition is added to `_is_scroll_posture()`, the single predicate
shared by both the entry and exit checks in `state_machine.py`, so the two
cannot drift apart — entering scroll and holding the same posture (fingers
and tuck both unchanged) does not immediately exit, and the thumb un-tucking
while the fingers stay in position (the natural way a user transitions into
a double-click) does exit scroll on its own, before the pinch closes.

Replayed against `recordings/scroll_attempt.jsonl` post-fix: 96 `Scroll`
events totaling 9232 px over the 15 s gesture (previously 128 events, 11206
px) — a real but modest reduction, comfortably more than half, consistent
with the fixture not having been recorded with the thumb deliberately
tucked. `middle_pinch.jsonl` and `live_clicks.jsonl` produce zero `Scroll`
events, before and after. `reaching_past.jsonl` and `talking_hands.jsonl`
continue to replay to zero intents.

## Amendment (2026-08-19): scroll thumb gate made asymmetric

The gate above used one shared predicate, `_is_scroll_posture()`, for both
entering and leaving `Scroll`, with a single threshold `THUMB_TUCK_MAX`.
That has a side effect: replaying `recordings/scroll_attempt.jsonl` showed
that of the 260 frames in scroll posture, 65 have `thumb_tuck_ratio` drift
back above `THUMB_TUCK_MAX` mid-gesture — a momentary, non-deliberate
un-tuck, not the user reaching for a double-click. Under the shared
threshold, each such frame dropped `Scroll` straight to `Tracking`, which
(unlike `Scroll`) processes pinches — so a pinch reading during that
momentary window could fire a click the user never intended. Measured: 4
complete `ButtonDown`/`ButtonUp` pairs on this recording that did not occur
before the original thumb-tuck gate existed.

The fix mirrors the posture gate's own arm/sustain asymmetry (see "The
posture gate" below): strict to enter, reluctant to leave. `_is_scroll_posture()`
is replaced by two predicates built from one shared finger-shape helper so
entry and exit cannot drift apart on the finger condition, only on the
thumb threshold:

- `_scroll_finger_shape(f)` — index extended, middle extended, ring not
  extended (pinky ignored). Unchanged, and shared by both checks.
- `_can_enter_scroll(f)` — finger shape **and**
  `thumb_tuck_ratio < THUMB_TUCK_MAX` (0.70, unchanged).
- `_can_stay_in_scroll(f)` — finger shape **and**
  `thumb_tuck_ratio < THUMB_TUCK_RELEASE` (0.95, new).

`Tracking → Scroll` still calls `_can_enter_scroll()` after the 200 ms
dwell; `Scroll → Tracking` now calls `_can_stay_in_scroll()` instead of
re-using the entry predicate. `THUMB_TUCK_RELEASE = 0.95` was supplied
directly rather than derived from a fresh measurement pass — 0.95 sits well
above every scroll-posture thumb-tuck reading observed while still leaving
room below the untucked values seen during a genuine middle-pinch approach.
A test (`test_thumb_tuck_thresholds_have_hysteresis_gap`) asserts
`THUMB_TUCK_MAX < THUMB_TUCK_RELEASE` so the two constants cannot be set
inconsistently.

**Verified working, for the mechanism it targets.** Tracing
`recordings/scroll_attempt.jsonl` frame-by-frame confirms the fix does what
it was built to do: at t=14.604-14.779s, `thumb_tuck_ratio` rises from 0.706
to 0.839 while the scroll-posture fingers hold steady. Under the single
shared threshold this dropped `Scroll` to `Tracking` on every one of those
frames; under the asymmetric fix, all of them correctly stay inside
`Scroll` (emitting `Scroll` intents) because none clears
`THUMB_TUCK_RELEASE`. Total scroll output on the fixture went up slightly as
a result (96 → 102 events, 9232 → 9341 px), not down — consistent with "not
losing scroll magnitude." `middle_pinch.jsonl` still produces zero `Scroll`
events; `reaching_past.jsonl` and `talking_hands.jsonl` still replay to zero
intents; every other fixture (`five_clicks`, `one_double_click`,
`live_clicks`, `drag_a_to_b`, `clutch`, `one_sweep`) is byte-for-byte
unaffected, since none of them ever reach `Scroll`.

**Not verified working, for the reported symptom.** The 4
`ButtonDown`/`ButtonUp` pairs that motivated this fix are still present
after it, unchanged in count and in timestamp (10.446s, 10.678s, 11.013s,
11.279s). Tracing them shows why: they occur in a region (~9.5-12.0s) where
`thumb_tuck_ratio` never drops below `THUMB_TUCK_MAX` (0.70) in the first
place — it ranges roughly 0.72-1.08 throughout, well above the entry bar. So
the state machine never enters `Scroll` in that region at all; it stays in
`Tracking`/`Frozen`/`Pressed` for what is actually a legitimate index-curl
clutch-and-pinch sequence, which is emitting real `ButtonDown`/`ButtonUp`
pairs by the ordinary curl/pinch rules, not a scroll-exit bug. Diffing this
fixture against the state machine as it existed before the original
thumb-tuck gate (commit `1aa1b6d`) shows the same underlying pinch closures
used to be silently absorbed there too — but by a different mechanism: the
pre-thumb-tuck `Scroll` entry check was pure finger-shape, so the raw
(True, True, False, False) finger flicker in that region was, by chance,
often enough to re-enter `Scroll` right as each pinch closed, absorbing it.
Adding a thumb condition to *entry* (not touched by this follow-up, and not
in scope for it — the brief specifically asked only for the exit-side
asymmetry) is what stopped that region from re-entering `Scroll`, exposing
the pinch closures to the ordinary click path. The exit-side fix in this
amendment has no mechanism to affect that, because the machine is never in
`Scroll` there to begin with. `THUMB_TUCK_RELEASE` was not raised further
in pursuit of removing these 4 pairs — see the follow-up task report for
the full frame-by-frame trace this conclusion is based on.

## Amendment (2026-08-19): a pinch requires an extended finger

The user reported: "even if i bring my index or middle finger just a little
closer to the palm it presses even if not touching the thumb." The cause is
the same geometry that motivated the curl/pinch mutual-exclusivity rule (see
"The clutch: freezing the cursor" below), in its more general form: a pinch
was detected purely from tip-to-thumb distance
(`pinch_ratio`/`pinch2_ratio`) crossing a threshold, and curling a finger
brings its tip toward the palm, where the thumb also rests, shrinking that
distance without the two ever touching. The curl-gate below only ever
caught the *full* clutch curl (`index_curl_ratio` below `INDEX_CURL_CLOSE`);
a partial curl that never dropped that low was not caught, and that gap is
exactly the reported symptom.

Two other discriminators were tried and rejected: thumb-tuck position
overlaps too much between genuine pinches and curls, and the ratio of
thumb-to-tip against palm-to-tip is actually *lower* during curling (0.26)
than during genuine clicks (0.35), because a curled fingertip really is
close to the thumb.

**The fix is finger shape, not tip proximity.** A pinch keeps the finger
relatively straight and meets the thumb at the tip; a curl folds the finger
at its joints — the same signal `index_curl_ratio` already measures
(fingertip-to-wrist distance over `hand_scale`), extended with a new,
identically-computed `middle_curl_ratio` for the middle finger (see "Feature
extraction" above). Measured across frames the code reads as pinched:

| fixture | index: min / p10 / median | middle: min / p10 / median |
|---|---|---|
| `live_clicks` | 1.32 / 1.35 / 1.42 | 1.60 / 1.68 / 1.76 |
| `five_clicks` | 1.31 / 1.35 / 1.40 | 1.76 / 1.79 / 1.81 |
| `middle_pinch` | 1.25 / 1.29 / 1.66 | 1.22 / 1.33 / 1.43 |
| `clutch` (curling) | 0.69 / 0.78 / 1.72 | 0.54 / 0.57 / 0.64 |

Genuine pinches never fall below 1.25 index / 1.22 middle extension (the
minimum across the three genuine-pinch recordings, on the channel that
actually closed); deliberate curling reaches as low as 0.69 index / 0.54
middle. `PINCH_MIN_EXTENSION = 1.20` and `PINCH2_MIN_EXTENSION = 1.10` sit
slightly below those measured floors, for margin on hand orientations not
represented in the recordings — see "Tuning parameters" below. A pinch may
now only *close* when the closing finger's curl ratio clears the
corresponding threshold; the transition table above reflects this. The gate
applies to closing only, never to releasing: a pinch already held does not
drop just because the finger flexes slightly below the threshold, which
would be a stuck-button-adjacent failure in reverse.

**Interaction with the curl-gate.** `PINCH_MIN_EXTENSION` is set equal to
`INDEX_CURL_OPEN` (both 1.20) on purpose: since the curl-latch (`_curled`)
can only be active at or below `INDEX_CURL_OPEN`, this makes the extension
gate strictly subsume the curl-gate for the one purpose of blocking a *new*
index-channel pinch close — every case the curl-gate blocked on that front,
the extension gate blocks too, plus the partial-curl cases the curl-gate
never could. The curl-gate is not fully redundant, though, and stays: it
also blocks the *middle* channel while the index is curled (the extension
gate checks each channel only against its own finger's ratio, so an index
curl alone does not fail `PINCH2_MIN_EXTENSION`), and it force-releases an
already-open button the instant a curl begins mid-press — a case the
extension gate structurally cannot cover, since it governs closing only.

**Verified against every fixture.** `live_clicks.jsonl` (12 presses) and
`middle_pinch.jsonl` (9 `Click(2)`s, 1 press) are unchanged. `clutch.jsonl`
— which previously left 2 `ButtonDown`/`ButtonUp` pairs and 2 spurious
`Click(2)`s even after the curl-gate fix, including one at t=1.628s
previously diagnosed as "unconnected to curling" (that diagnosis was wrong:
`middle_curl_ratio` at that frame is 0.966, well below
`PINCH2_MIN_EXTENSION` — the middle finger itself was curled) — now replays
to zero button or click events of any kind. `reaching_past.jsonl` and
`talking_hands.jsonl` remain at zero intents.

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
    middle_curl_ratio: float     # scale-invariant middle-tip-to-wrist distance
    thumb_tuck_ratio: float      # scale-invariant thumb-tip-to-pinky-MCP distance
    fingers_up: tuple[bool, ...] # index, middle, ring, pinky
    palm_facing: bool            # palm oriented toward camera
    hand_scale: float            # wrist → middle MCP, in frame widths
    cursor_ref: Point2           # palm centroid (mean of 4 MCP knuckles), mirrored x
    t: float

Intent = Move(dx, dy) | Click(n) | ButtonDown | ButtonUp | Scroll(dy) | Space(dir)
```

## Feature extraction

MediaPipe landmark indices used: 0 wrist, 4 thumb tip, 5 index MCP, 8 index tip,
9 middle MCP, 12 middle tip, 13 ring MCP, 17 pinky MCP.

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
dedicated recording — see "Tuning parameters" for the numbers. Also drives
the index side of the pinch-close extension gate — see "Amendment
(2026-08-19): a pinch requires an extended finger" below.

**`middle_curl_ratio`** = ‖landmark[12] − landmark[0]‖ / `hand_scale`,
middle fingertip to wrist — computed identically to `index_curl_ratio`,
just for the middle finger. Added 2026-08-19 alongside the extension gate
below; there is no middle-finger clutch, so this ratio exists solely to
drive the middle side of that gate.

**`thumb_tuck_ratio`** = ‖landmark[4] − landmark[17]‖ / `hand_scale`, thumb
tip to pinky knuckle. Small means the thumb is tucked across the palm.
Drives the scroll gate's thumb condition (see "Amendment (2026-08-19):
scroll requires a tucked thumb" below): required in addition to the finger
posture so that a middle-pinch double-click, which extends the thumb out to
meet the middle fingertip, cannot also read as scroll. Checked against two
different thresholds depending on direction (see "Amendment (2026-08-19):
scroll thumb gate made asymmetric" below) — `THUMB_TUCK_MAX` to enter
`Scroll`, the looser `THUMB_TUCK_RELEASE` to leave it.

**`fingers_up[f]`** = ‖tip − wrist‖ > 1.15 × ‖pip − wrist‖ for each of index,
middle, ring, pinky. Comparing distances from the wrist rather than comparing y
coordinates keeps this correct when the hand is rotated.

**`palm_facing`** = sign of the z-component of
(landmark[5] − landmark[0]) × (landmark[17] − landmark[0]). Toward the camera is
palm-facing.

**`cursor_ref`** = mean of landmarks [5, 9, 13, 17] — the index, middle, ring, and
pinky MCP knuckles — the palm centroid. Changed from a single knuckle
(landmark[5], the index MCP) on 2026-08-11.

> This choice is load-bearing. None of the four MCP knuckles moves much when the
> thumb and index close, whereas a fingertip translates several millimetres.
> Tracking a fingertip makes the cursor jump at the exact instant of a pinch — the
> most common failure mode in webcam pointers, and the one that makes small targets
> unhittable. A single knuckle already has this property; the centroid of four
> knuckles keeps it and improves on it, because each knuckle's tracking noise is
> largely independent of the others', so averaging four cancels noise that
> averaging one cannot.
>
> Measured directly against the user's own recordings (median frame-to-frame
> displacement of the reference point, normalized units × 1000 — a robust jitter
> metric, insensitive to the occasional large deliberate movement that a mean would
> be skewed by):
>
> | Recording | Index MCP alone | Palm centroid | Change |
> |---|---|---|---|
> | `live_clicks.jsonl` | 2.11 | 1.66 | 21% steadier |
> | `five_clicks.jsonl` | 0.99 | 0.83 | 16% steadier |
> | `scroll_attempt.jsonl` | 3.10 | 2.59 | 17% steadier |
> | `clutch.jsonl` | 4.13 | 4.26 | 3% worse |
>
> A net win across three of the four fixtures, so the centroid replaces the single
> knuckle everywhere `cursor_ref` is used (tracking, dragging, scrolling, swipe
> detection). `clutch.jsonl` is the one exception, and a small one: that recording
> is dominated by extreme index-finger articulation (deliberate curling to the
> point of touching the thumb), which moves the knuckles themselves more than
> ordinary pointing or clicking does — the same motion the centroid is measuring
> jitter against is, in this one fixture, real signal, not noise. Replaying every
> fixture through the full state machine after the change showed no behavioural
> regression from this 3% figure (see the replay report in
> `.superpowers/sdd/2026-08-10-gesture-control/`), so it was accepted rather than
> reverted.

## Posture gate

Arming is strict; staying armed is loose. These are deliberately different
conditions.

| Transition | Condition | Dwell |
|---|---|---|
| Disarmed → Armed | ≥3 of 4 fingers extended, `palm_facing`, `hand_scale` ∈ [0.08, 0.45] | 300 ms |
| Armed → Disarmed | hand absent | 500 ms |

The asymmetry is required, not incidental: pinching closes the index finger, so a
sustain condition that demanded extended fingers would disarm the system the moment
the user tried to click. The `hand_scale` bound rejects hands that are implausibly
near or far — usually a second person in frame or a hand reaching past the camera.

**Sustain dropped `palm_facing` on 2026-08-21** (see the amendment below,
"Sustain no longer requires palm_facing"). It used to read `hand absent, or
not palm_facing`, matching arming's orientation requirement; the row above
reflects the current, looser condition. The reasoning is the same as the
finger-extension asymmetry above, one level further out: gestures rotate
the hand as a matter of course, so a sustain condition that fights hand
rotation works against every gesture, not only the one that exposed it.
The consequence: turning the palm away no longer stops the system by
itself. Dropping the hand out of frame (disarms after `DISARM_S`) or `Esc`
are the ways to stop it now — see "Safety" below and the README.

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
| `Tracking` | `Scroll` | index extended, middle extended, ring not extended, thumb tucked (`thumb_tuck_ratio` < `THUMB_TUCK_MAX`), 200 ms (pinky ignored) — `_can_enter_scroll()` |
| `Tracking` | `Tracking` | horizontal sweep → emit `Space` |
| `Tracking` or `Frozen` | `Pressed` | index not curled, pinch closes (`pinch_ratio` < 0.35 with `index_curl_ratio` > `PINCH_MIN_EXTENSION`, OR `pinch2_ratio` < 0.30 with `middle_curl_ratio` > `PINCH2_MIN_EXTENSION`) **and** the index channel is the closer one at that instant; emit `ButtonDown` |
| `Tracking` or `Frozen` | (unchanged) | index not curled, pinch closes (same extension-gated condition) and the **middle** channel is the closer one; emit `Click(2)`, no state change |
| `Pressed` | `Tracking` | the pinch releases: `pinch_ratio` > 0.45 AND `pinch2_ratio` > 0.40 (both fingers clear); emit `ButtonUp` |
| `Pressed` | `Frozen` | index curls while a pinch is open: `index_curl_ratio` < `INDEX_CURL_CLOSE`; emit `ButtonUp` first (see "The clutch: freezing the cursor" below) |
| `Scroll` | `Tracking` | scroll posture (finger shape, or thumb past `THUMB_TUCK_RELEASE`) absent **continuously** for `SCROLL_EXIT_S` (0.35 s, added 2026-08-20 follow-up — see "Amendment (2026-08-20 follow-up): scroll exit debounce"); a posture failure shorter than that is absorbed and `Scroll` continues uninterrupted, with `_scroll_neutral` untouched |
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

Beyond transitions, three states are active on every frame:

| State | Active every frame |
|---|---|
| `Tracking` | computes a `Move(dx, dy)` candidate from the filtered `cursor_ref` delta, then runs it through the jitter deadzone below — most frames accumulate silently, and a `Move` is emitted only when the deadzone crosses |
| `Pressed` | same candidate-then-deadzone pipeline, actuated as `LeftMouseDragged` when it does emit |
| `Scroll` | rate-based (2026-08-20): emits `Scroll(dy)` every frame the hand's offset from the entry-recorded `neutral` clears `SCROLL_NEUTRAL_DEADZONE` and the resulting per-frame amount clears `SCROLL_MIN_PX` — no hand movement between frames is required, unlike `Move` above; see "Amendment (2026-08-20): rate-based scrolling replaces displacement" above. This computation runs identically whether or not the current frame's posture reading satisfies `_can_stay_in_scroll` — see "Amendment (2026-08-20 follow-up): scroll exit debounce" for why a posture-failing frame during the exit debounce still produces normal output |

`Frozen` and `Disarmed` emit nothing. This is the whole mechanism: the cursor
does not move in `Frozen` — that is what makes the clutch a clutch — and
`Tracking` and `Pressed` are the only states where hand movement can produce
a `Move`.

"Every frame" above means every *present* frame. An absent frame
(`f.present` False — the hand momentarily lost while still armed) emits
nothing from any state, `Scroll` and `Pressed` included: it is not treated
as "the hand at frame-centre" and does not feed the movement, scroll, or
swipe pipelines at all. See "Amendment (2026-08-20): absent frames must
not reach the movement path" above.

#### The jitter deadzone (2026-08-11)

The user reported the cursor was too unstable to hit small targets like
window close buttons. A plain deadzone — drop any per-frame delta smaller
than a threshold — would fix tremor but also break precision: aiming at a
small target means moving slowly, and slow, deliberate movement produces
small per-frame deltas too. A threshold that can't tell them apart either
lets tremor through (too low) or blocks deliberate aiming (too high). No
single threshold value resolves that trade-off, because the two cases are
identical at the single-frame level — the only thing that distinguishes them
is *direction over time*, which a per-frame check can't see.

The fix accumulates instead of discarding. Each frame's gained pixel delta
(`dxp, dyp`, the output of `apply_gain`) is added to a running residual. If
the residual's magnitude is below `MOVE_DEADZONE_PX`, no `Move` is emitted
and the residual carries into the next frame. Once it crosses the threshold,
a single `Move` is emitted for the *entire* accumulated residual, which then
resets to zero. Random tremor is random in direction, so its contributions
to the residual largely cancel and it rarely crosses the threshold — the
cursor sits still. Consistent slow movement is directional, so its
contributions add up and it always eventually crosses — the cursor still
gets there, just in coarser steps (one `Move` every few frames instead of
every frame) rather than being silently dropped.

The residual lives on the state machine, not the filter — it is per-frame
cursor state, the same category as `_virtual` and the tracking reference
point, not a property of the One Euro filter. It is shared between
`Tracking` and `Pressed` so a drag is exactly as steady as plain cursor
movement, and it is reset in two places: when the gate disarms, and on every
transition into `Frozen`. Both resets exist for the same reason — a residual
accumulated before one of these events must never combine with fresh motion
after it to fire an oversized jump the instant tracking resumes. Without the
disarm reset, walking away and coming back could replay stale sub-pixel
drift as a jump; without the `Frozen` reset, repositioning the hand during a
clutch and then uncurling could do the same.

`Scroll` does not go through this deadzone. It already has its own
independent threshold (`SCROLL_MIN_PX`, a plain per-event minimum, not an
accumulator) and scroll wheel input has no equivalent small-target precision
requirement — there is no "close button" to overshoot by a pixel when
scrolling.

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

**Former known gap, closed 2026-08-19:** `recordings/clutch.jsonl` used to
still replay with spurious presses even after this fix — 2 `ButtonDown`/
`ButtonUp` pairs and 2 `Click(2)`s, including one at t=1.628s
(`index_curl_ratio` = 1.948, deep in the pointing cluster) previously
diagnosed here as "a transient `pinch2_ratio` dip during ordinary pointing
motion with no connection to curling." That diagnosis was incomplete: at
that same frame `middle_curl_ratio` = 0.966 — the middle finger itself was
genuinely curled at that moment, just not the index finger this section's
gate watches. See "Amendment (2026-08-19): a pinch requires an extended
finger" above for the fix (`PINCH_MIN_EXTENSION` / `PINCH2_MIN_EXTENSION`),
which catches this and every other remaining spurious event in this
recording: it now replays to zero button or click events of any kind.

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

**Current model (2026-08-20; see "Amendment (2026-08-20): rate-based
scrolling replaces displacement" above for the full derivation).** While in
`Scroll`, the hand's vertical position sets a continuous scroll *speed*,
like a joystick, rather than the scroll distance following how far the hand
moved. Entering `Scroll` records the current vertical position as `neutral`
(re-recorded on every entry). Each frame, `offset = current_y - neutral`;
inside `SCROLL_NEUTRAL_DEADZONE` nothing is emitted, otherwise `speed =
sign(offset) × (|offset| − SCROLL_NEUTRAL_DEADZONE) × SCROLL_RATE_GAIN`
px/sec and the frame's scroll amount is `speed × dt`. The existing
`SCROLL_MIN_PX` per-event deadband still applies to that result. Natural
scrolling direction is matched to the system setting by reading
`com.apple.swipescrolldirection`; if unavailable, defaults to natural.

The rest of this section (below) describes the earlier, now-replaced
displacement model (`scroll_px = dy_normalized × SCROLL_GAIN ×
scroll_accel(speed)`) and the tuning history that led to it. It is kept as
a historical record of the reasoning already spent — `SCROLL_GAIN`,
`SCROLL_ACCEL_MIN`, `SCROLL_ACCEL_MAX`, `SCROLL_ACCEL_VREF`, and
`scroll_accel()` itself no longer exist in the code.

Entering `Scroll` additionally requires the thumb tucked toward the palm
(`thumb_tuck_ratio < THUMB_TUCK_MAX`, added 2026-08-19 — see "Amendment
(2026-08-19): scroll requires a tucked thumb" above for the full
derivation), so that opening the middle finger for a middle-pinch
double-click, which passes through the scroll finger posture and extends
the thumb out to meet the middle fingertip, cannot also read as scroll.
Leaving `Scroll` uses a separate, looser threshold, `THUMB_TUCK_RELEASE`
(`thumb_tuck_ratio >= THUMB_TUCK_RELEASE`, added 2026-08-19 — see
"Amendment (2026-08-19): scroll thumb gate made asymmetric" above), so a
momentary thumb un-tuck mid-scroll is absorbed rather than dropping the
user into `Tracking`, where a stray pinch reading could fire a click they
did not intend.

**`SCROLL_GAIN` raised 900 → 5000 → 20000 (2026-08-11): scroll magnitude undertuned.**
The user reported "scroll does nothing." `recordings/scroll_attempt.jsonl` (a
new, dedicated 15 s deliberate-scrolling recording) proved this was a
magnitude bug, not a posture or state-machine bug: 260 of 444 present frames
match the scroll posture and the machine emitted 53 `Scroll` intents at the
old gain — the posture detection and dwell logic were working. The problem
was that those 53 intents added up to only 220 px of total scroll (median
event 2.4 px) over the whole 15 s gesture — roughly two lines, imperceptible
as "scrolling happened" at all.

Measured total vertical hand travel while the scroll posture holds (filtered
`cursor_ref`, summed frame-to-frame over every posture-matching frame,
independent of the entry dwell) is 0.429 frame-heights. Naively multiplying
that raw travel by the gain projects 386 px at `GAIN=900` and ~2145 px at
`GAIN=5000` — but that projection is optimistic: the real pipeline only
scrolls once `SCROLL_DWELL_S` has elapsed and drops any single event under
`SCROLL_MIN_PX`, so actual replayed output runs below the naive number at
both gains (220 px actual vs. 386 px projected at the old gain). Replayed for
real at `GAIN=5000`, through the full pipeline including the palm-centroid
`cursor_ref` and jitter-deadzone changes below: 118 `Scroll` intents totaling
1362 px (median 3.9 px), about 160 px/sec — improved but still too slow for
practical use (trackpad flicks move 1000–2000 px/sec). Further raised to
`GAIN=20000`: 154 `Scroll` intents totaling 5538 px (median 9.1 px), about
650 px/sec — brisk but still controllable. `recordings/scroll_attempt.jsonl`
is a committed fixture and the regression test for scroll magnitude (see
"Testing" below).

### Space switching

Evaluated only in `Tracking`, so a fast drag (`Pressed`) can never be read as
a swipe.

Fires when, with the exact three-finger posture held (index, middle and ring
extended, pinky down — matching the macOS trackpad three-finger-swipe
convention; see "Amendment (2026-08-20 second follow-up)" above for why this
replaced the original open-palm posture): horizontal velocity of
`cursor_ref` exceeds 0.6 frame-widths/sec sustained for ≥ 100 ms, and net
horizontal displacement exceeds 0.20 frame widths. Rightward sweep emits
`Space(right)` → `Ctrl+→`.

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

**Jitter deadzone (2026-08-11), after gain.** The gained pixel delta above is
not emitted as a `Move` directly — it first passes through the accumulating
deadzone described in "The jitter deadzone" (under "State machine" above):
sub-`MOVE_DEADZONE_PX` deltas accumulate in a residual instead of being
emitted or dropped, so tremor cancels out while slow deliberate movement
still arrives, just in coarser steps. This lives in `state_machine.py`, not
here, because it is per-frame cursor state (the residual), not a property of
the filter or the gain curve.

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
  is likewise scale-invariant and independent of the pinch; `middle_curl_ratio`
  (added 2026-08-19) is the same three properties, for the middle finger; finger
  extension is correct for known hand poses; mirroring is applied exactly once
  (now: to each of the four MCP knuckles before they are averaged, not to a
  single landmark); `cursor_ref` is the mean of landmarks 5/9/13/17 and barely
  moves when the pinch closes, same as the single knuckle it replaced
- `gate`: arms only after the full dwell; does not disarm when fingers curl to
  pinch (the asymmetry above); rejects out-of-range `hand_scale`
- `state_machine`: each row of the transition table, including the
  closer-finger disambiguation, the clutch (curl freezes and does not jump on
  resume; curl and pinch are mutually exclusive -- curl is evaluated before
  pinch every frame, the pinch channels are ignored while curled, and an
  already-open button is released, not held, the instant a curl engages),
  the pinch-close extension gate (added 2026-08-19: a tip-close-to-thumb
  reading with the finger curled below `PINCH_MIN_EXTENSION` /
  `PINCH2_MIN_EXTENSION` does not press or click; the same tip distance with
  the finger extended does; a pinch already held does not release when the
  finger flexes slightly below the threshold), the stuck-button watchdog,
  and the jitter deadzone accumulator (consistent sub-threshold motion
  accumulates and eventually emits its full total; alternating sub-threshold
  motion cancels and emits nothing; the residual applies identically during
  a drag; it resets on disarm and on entering `Frozen`); the absent-frame
  dropout while armed (added 2026-08-20: an absent frame emits no `Move`;
  hand present, absent for several frames, then present at a distant
  position emits zero net movement across the whole gap; a held `Pressed`
  survives the dropout and the disarm watchdog still releases it if the
  gate eventually drops; `Scroll` emits nothing during a dropout and its
  `neutral` is not corrupted by it — see "Amendment (2026-08-20): absent
  frames must not reach the movement path"); the scroll exit debounce
  (added 2026-08-20 follow-up: the posture failing for less than
  `SCROLL_EXIT_S` does not leave `Scroll`; failing for longer than
  `SCROLL_EXIT_S` does; the neutral is not re-recorded when the posture
  recovers within the debounce window, so a sustained offset that briefly
  flickers keeps scrolling at the same rate rather than resetting to zero;
  re-entering `Scroll` after a genuine exit does record a fresh neutral —
  see "Amendment (2026-08-20 follow-up): scroll exit debounce")
- `filters`: One Euro converges on constant input; gain curve is monotonic and
  respects its clamps

**Replay tests.** `recorder.py` writes real sessions as `.jsonl` (landmarks +
timestamps). Replaying a recording through the state machine must yield an exact
intent sequence. The core behavioural fixtures below were all recorded under the
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
- `one_sweep.jsonl` → zero `Space` events as of the 2026-08-20 second
  follow-up (see "Amendment (2026-08-20 second follow-up)" above): this
  recording is the user's OLD open-palm sweep, and Space switching now
  requires the exact three-finger posture, which an open palm no longer
  satisfies. This is the change working as intended, not a regression.
  `recordings/three_finger.jsonl` (added 2026-08-20) is the current
  fixture for a genuine three-finger swipe, and replays to multiple
  `Space` events (see the amendment for the exact count and why full
  pipeline replay differs from a raw posture/velocity scan)
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
from also firing a spurious `ButtonDown`. It is also the regression fixture
for the scroll-entry thumb gate not being weakened by the 2026-08-20
follow-up exit debounce below: it must still replay to zero `Scroll` events.

`recordings/scroll_hold.jsonl` (added 2026-08-20 follow-up) is 15 s of a
correctly performed rate-scroll hold that exposed the scroll-exit-flicker
bug — see "Amendment (2026-08-20 follow-up): scroll exit debounce" above.
It is the regression fixture for that entire class of bug: replay must
produce substantially more than the pre-fix 47 px (lower bounds, ~820 px
measured, same non-exact-figure convention as `scroll_attempt.jsonl`'s
magnitude test above).

The false-positive fixtures (reaching past, talking hands) are the
regression net that lets thresholds be retuned later without silently
reintroducing stray output. They matter more under the new model than the
old one: because `Tracking` now emits a `Move` on nearly every frame, a gate
that mis-arms during either recording would produce a stream of stray
cursor movement, not just an occasional stray click. If either fixture
starts emitting anything, the fix is to tune the gate — not to weaken the
assertion.

`recordings/scroll_attempt.jsonl` (added 2026-08-11, a dedicated 15 s
deliberate-scrolling recording) is the regression fixture for scroll
magnitude generally — originally `SCROLL_GAIN`, now `SCROLL_RATE_GAIN` /
`SCROLL_NEUTRAL_DEADZONE` under the 2026-08-20 rate-based redesign (see
"Amendment (2026-08-20)" above). It was recorded as a sweeping motion for
the old displacement model and was never re-recorded for the rate model, so
its replayed event count and pixel total changed substantially under the
redesign (fewer, larger events — see the amendment for the measured
numbers) without that being a regression. Its replay test asserts a
meaningful total scroll distance and event count (lower bounds, not exact
figures, so both survive future retuning) rather than pinning the exact
numbers, which would just re-encode the tuning constants as a second set of
magic numbers in the test.

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
"The clutch: freezing the cursor" above. `PINCH_MIN_EXTENSION` /
`PINCH2_MIN_EXTENSION` (added 2026-08-19) additionally gate the CLOSE
transition on finger shape — see "Amendment (2026-08-19): a pinch requires
an extended finger" above. All other parameters (gate, gain, scroll, swipe,
filter) are unchanged by this redesign.

| Parameter | Start | Governs |
|---|---|---|
| `PINCH_CLOSE` / `PINCH_OPEN` | 0.35 / 0.45 | index pinch detection (button down/up), with hysteresis |
| `PINCH2_CLOSE` / `PINCH2_OPEN` | 0.30 / 0.40 | middle pinch (double-click) detection, with hysteresis |
| `INDEX_CURL_CLOSE` / `INDEX_CURL_OPEN` | 0.95 / 1.20 | Clutch (freeze/resume) detection, with hysteresis. Calibrated against `recordings/clutch.jsonl`: `index_curl_ratio` is cleanly bimodal (curled 0.56-0.9, pointing 1.6-2.04), and 0.95 sits in the wide gap between. The upper bound is set by the pinch floor (1.03, across all pinch-containing fixtures), not by pointing, so a pinch is never misread as a curl |
| `PINCH_MIN_EXTENSION` / `PINCH2_MIN_EXTENSION` | 1.20 / 1.10 | required finger extension (`index_curl_ratio` / `middle_curl_ratio`) for a pinch to *close* (added 2026-08-19) — see "Amendment (2026-08-19): a pinch requires an extended finger" above. Distinguishes a genuine pinch from a partial curl that merely brings the tip near the thumb without touching it. Measured floors across the three genuine-pinch recordings: 1.25 index, 1.22 middle; both thresholds sit slightly below for margin. `PINCH_MIN_EXTENSION` equals `INDEX_CURL_OPEN` on purpose, making it subsume the curl-gate for new index-channel closes specifically (see the amendment for what the curl-gate still does that this does not) |
| `ARM_DWELL_MS` / `DISARM_MS` | 300 / 500 | gate responsiveness vs. stability |
| `BASE_GAIN_PX` | 2000 | cursor travel per hand movement; raised from 1600 to increase reach from 560 px to 1000 px per hand-sweep, enabling edge access on 1470 px display with index-curl clutch covering the rest; cost: hand tremor amplified |
| `ACCEL_MIN` / `ACCEL_MAX` | 0.5 / 2.5 | precision floor vs. reach ceiling; ACCEL_MIN raised from 0.35 to 0.5 to increase slow-movement reach from 560 px to 1000 px per hand-sweep |
| `SCROLL_NEUTRAL_DEADZONE` | 0.008 | rate-based scrolling (added 2026-08-20, resized 2026-08-20 follow-up, replacing `SCROLL_GAIN`/`scroll_accel`) — see "Amendment (2026-08-20)" above. Frame-heights of hand offset from the entry-recorded neutral before scrolling starts at all; inside it nothing scrolls, which is both how the user stops scrolling and what absorbs tremor while holding still. Tuned from `recordings/scroll_hold.jsonl` measurements: user's actual deflections run to 0.041 max with median 0.012; deadzone at 0.008 sits well below median and roughly 3x above hand tremor noise floor |
| `SCROLL_RATE_GAIN` | 60000.0 | px/sec of scroll speed per frame-height of offset beyond `SCROLL_NEUTRAL_DEADZONE` (added 2026-08-20, resized 2026-08-20 follow-up). This is the constant most users will want to adjust for scroll feeling too fast or too slow across the board. Tuned from `recordings/scroll_hold.jsonl` measurements for maximum useful deflection ~0.04: 0.012 offset ≈ 240 px/sec, 0.023 ≈ 900 px/sec, 0.034 ≈ 1560 px/sec, 0.041 ≈ 1980 px/sec |
| `SCROLL_MIN_PX` | 1.0 | deadband below which no single scroll event is emitted; unchanged by the 2026-08-20 rate-based redesign, now applied to the per-frame `speed × dt` amount instead of a raw displacement |
| `THUMB_TUCK_MAX` | 0.70 | scroll entry additionally requires `thumb_tuck_ratio` below this (added 2026-08-19) — see "Amendment (2026-08-19): scroll requires a tucked thumb" above. Keeps a middle-pinch double-click, which extends the thumb to meet the middle fingertip, from being misread as scroll. Measured medians: scroll 0.55, middle-pinch 0.86, index clicks 0.90; 0.70 keeps 195 of 260 genuine scroll frames while rejecting every colliding frame |
| `THUMB_TUCK_RELEASE` | 0.95 | scroll exit uses this instead of `THUMB_TUCK_MAX` (added 2026-08-19 follow-up) — see "Amendment (2026-08-19): scroll thumb gate made asymmetric" above. Must stay above `THUMB_TUCK_MAX` (asserted by `test_thumb_tuck_thresholds_have_hysteresis_gap`). Absorbs a momentary thumb un-tuck mid-scroll that would otherwise drop into `Tracking` and let a stray pinch reading fire an unintended click; a genuine untuck past 0.95 still exits. Does not, on its own, remove every spurious click observed on `recordings/scroll_attempt.jsonl` — some come from a different mechanism (`Scroll` failing to *enter* during a curl/pinch sequence where the thumb never drops below `THUMB_TUCK_MAX`), which this constant cannot address |
| `SCROLL_EXIT_S` | 0.35 | how long the whole scroll posture must be absent continuously before `Scroll` is actually left (added 2026-08-20 follow-up) — see "Amendment (2026-08-20 follow-up): scroll exit debounce" above. Diagnosed on `recordings/scroll_hold.jsonl`: single-frame landmark noise broke a 15 s correctly-performed hold into 16 fragments (longest 1.73 s), each re-entering `Scroll` and re-recording the neutral, for a total of 47 px instead of a real scroll. At 0.35 s that recording replays to ~820 px (36 events) instead |
| `MOVE_DEADZONE_PX` | 2.0 | jitter deadzone for `Move` (added 2026-08-11) — see "The jitter deadzone" above. Sub-threshold pixel deltas accumulate in a residual instead of being emitted or dropped, so tremor cancels but slow deliberate movement still arrives |
| `SWIPE_VEL` / `SWIPE_DIST` | 0.6 / 0.20 | Space-switch sensitivity. `SWIPE_VEL` lowered from 0.8 to 0.6 (2026-08-20 second follow-up) — see the amendment above — after `recordings/three_finger.jsonl` measured real swipes peaking at 0.79 frame-widths/sec, missing 0.8 by a hundredth |
| Space-switch finger posture | exact `(True, True, True, False)` | replaced `sum(fingers_up) >= ARM_FINGERS_MIN` (2026-08-20 second follow-up); see the amendment above. An open palm satisfied the old rule and is the resting hand shape, so ordinary hand movement while armed could switch Spaces unintentionally |
| `SWIPE_COOLDOWN_MS` | 800 | prevents multi-Space skips |
| `DRY_RUN_FLUSH_S` | 1000 | max age of a coalesced `move` run in `--dry-run` output before it flushes |
| `EURO_MIN_CUTOFF` / `EURO_BETA` | 0.4 / 0.7 | jitter vs. lag |

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
