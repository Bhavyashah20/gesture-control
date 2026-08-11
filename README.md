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
| Index and middle finger up, move vertically | Scroll |
| Open palm, sweep sideways | Previous or next fullscreen Space |
| `Esc` | Stop immediately |

The cursor follows your hand continuously while armed — no pinch required to
move it. Pinching index-to-thumb is a plain mouse button: it goes down when
you pinch and up when you release, nothing else. macOS decides click versus
drag from that down/move/up sequence on its own, exactly as it would for a
physical mouse, so there is no separate "hold still to drag" gesture to learn
or mistune.

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
  scrolling turned off, scroll will feel inverted; negate `SCROLL_GAIN` in
  `config.py` as a workaround
- If a right-click ever appears (this app posts no right-clicks of its own),
  it indicates a modifier-flag leak: `_key` posts Control-flagged key events
  for the Space switch gesture, and on macOS a plain left mouse-down created
  without explicit flags inherits whatever modifier state is currently
  active, so Control+click reads as a right-click. `QuartzActuator._post_mouse`
  now explicitly clears flags (`CGEventSetFlags(ev, 0)`) on every mouse event
  it posts to prevent this
- `recordings/clutch.jsonl` (point/curl only, no pinching) still replays to
  one spurious `Click(2)`, at t=1.628s, where `index_curl_ratio` reads 1.936
  — deep in the pointing cluster, nowhere near a curl. It is a transient
  `pinch2_ratio` dip during ordinary pointing motion, unconnected to
  curling, so the curl/pinch mutual-exclusivity fix (see "Gestures" above)
  cannot address it. `PINCH_CLOSE`/`PINCH2_CLOSE` were never calibrated
  against sustained hand motion of the kind in this recording; needs its own
  investigation. The previously-reported stuck button from this same
  recording (an unreleased `ButtonDown` at t=14.208s, where the pinch
  reading was spurious *because* the index was curled) is fixed by the
  mutual-exclusivity change and no longer occurs
