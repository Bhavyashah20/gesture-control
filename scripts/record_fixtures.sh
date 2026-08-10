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
