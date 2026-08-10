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

If the project is not installed (`pip install -e ".[dev]"` was skipped), run
with `PYTHONPATH=src` instead:

```bash
PYTHONPATH=src .venv/bin/python -m gesture_control.main --dry-run
```

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
