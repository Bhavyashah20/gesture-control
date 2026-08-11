# Gesture control

Hands-free pointer control for macOS using the built-in webcam. Move the cursor,
click, double-click, drag, scroll, and switch between fullscreen Spaces without
touching the trackpad.

## Gestures

The vocabulary mirrors the macOS trackpad, so there is no new mental model.

| Gesture | Action |
|---|---|
| Open palm to camera, hold briefly | Arm the system |
| Pinch (index finger) and move | Move the cursor |
| Pinch (index finger) and release quickly | Click |
| Pinch (middle finger) and release quickly | Double-click |
| Pinch, hold still, then move | Drag |
| Index and middle finger up, move vertically | Scroll |
| Open palm, sweep sideways | Previous or next fullscreen Space |
| `Esc` | Stop immediately |

Think of the pinch as your fingertip on the trackpad glass. Releasing it lifts
off, which is how you reposition your hand without moving the cursor.

Double-click is a distinct gesture, not two fast clicks: pinch your middle
finger to your thumb instead of your index finger. Whichever fingertip is
actually closer to your thumb when the pinch closes decides which one it is
— not which finger you technically moved first. This matters because
pinching your middle finger to your thumb naturally drags your index
fingertip part of the way in too, so both can read as "closed" at once; an
earlier version of this rule let the index finger win by default whenever
that happened, which silently turned real double-clicks into single clicks.

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
summary instead of scrolling every click off screen; every click, drag, scroll,
or space event still prints immediately, on its own line.

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
- the current state (`disarmed` / `armed` / `tracking` / `drag` / `scroll`)
  as a large, colour-coded banner
- the live `pinch_ratio` and whether the pinch currently reads as closed
- the last click, drag, or space-switch, held on screen for about a second
  so it doesn't scroll past unnoticed

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

`TAP2_MAX_PX` is the middle-pinch double-click's own travel budget, separate
from `TAP_MAX_PX` (which governs the index tap; the drag rule has its own
budget too — see `DRAG_MAX_PX` below). Closing the middle finger to the
thumb disturbs the whole hand about twice as much as an index pinch —
median frame-to-frame reference motion of 5.31 vs. 2.66 (normalized units
x1000), measured across real recordings — so the *original* `TAP_MAX_PX`
(25 px), calibrated against index pinches, rejected most genuine
double-clicks on TRAVEL. At 60 px, 6 of 8 real middle-pinch attempts
register, against 3 of 8 at 25 px; the two that still don't are a deliberate
2.6 s hold (correctly a drag) and one that genuinely moved 283 px, so
raising the budget further would not help.

`TAP_MAX_PX` was itself raised from 25 px to 60 px after a wider pass across
the user's real taps (`live_clicks.jsonl` and `five_clicks.jsonl`, 17 taps
total): at 25 px one genuine tap was rejected on travel alone (16/17
registered); at 60 px all 17 register. `TAP2_MAX_PX` happens to land on the
same 60 px value as a result, but the two remain independent constants,
tuned for different gestures.

That change is only safe because of `DRAG_MAX_PX`: the drag trigger's own
stillness budget, deliberately decoupled from `TAP_MAX_PX`. Before the
split, the drag trigger reused `TAP_MAX_PX` directly, so loosening the click
budget would have silently made drags easier to start too — two unrelated
tuning decisions sharing one knob. Measured against the user's real drag
(15-25 px of travel by the time the dwell elapses), `DRAG_MAX_PX` stays at
25 px; budgets below 20 px would stop genuine drags from starting.

`DRAG_DWELL_S` was raised from 700 ms to 1000 ms in the same pass: the
user's genuine drag still fires at 1.0 s but stops firing entirely at 1.5 s,
so 1.0 s is a measured ceiling — don't raise it further without
re-measuring. It must also stay strictly greater than `TAP_MAX_S` (550 ms),
or a quick tap could be reclassified as a drag before it ever gets the
chance to release as a click.

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
