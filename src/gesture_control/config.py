"""Every constant that governs behaviour. Tuning happens here and nowhere else."""

PINCH_CLOSE = 0.35
PINCH_OPEN = 0.45

# Which finger closed the pinch (index -> ButtonDown, middle -> Click(2)) is
# decided by comparing pinch_ratio to pinch2_ratio at the moment either one
# first crosses its own CLOSE threshold below -- NOT by a fixed priority
# ("index always wins if closed"). That fixed-priority rule was an earlier
# design and was wrong: anatomically, pinching the middle fingertip to the
# thumb drags the index tip along with it, so the index channel often also
# reads closed during a genuine middle pinch. In the user's
# recordings/middle_pinch.jsonl (15 s, 8 deliberate middle-pinches), 43 of
# 417 present frames read pinch_ratio < PINCH_CLOSE even though the user
# never pinched their index finger -- under fixed priority that would
# silently turn several intended double-clicks into spurious button-downs.
# Closeness at pinch-down was validated against all three recordings on
# 2026-08-11 and correctly resolves every case, with no dead-band needed:
# the margin between the two ratios is 0.32-0.66 during genuine index
# clicks and 0.09-0.41 during genuine middle pinches, so the two never come
# close to tying. Do not reintroduce fixed priority.
#
# Under the direct-manipulation model (2026-08-11 redesign), the index
# channel no longer classifies click vs. drag -- it is a plain
# button-down/button-up pair, exactly like a physical mouse button. Only
# the closer-finger disambiguation above survives from the old design,
# because it is what keeps a deliberate middle-pinch double-click from also
# registering as a spurious ButtonDown on the index channel.

# Double-click is its own gesture (middle-tip-to-thumb), not a timing window.
# Diagnosed against real recordings 2026-08-10: the user's deliberate
# double-click had a release-to-release gap of 0.399 s; three ACCIDENTAL
# doubles (consecutive single clicks read as one) had gaps of 0.400, 0.300,
# 0.201 s. Those distributions fully overlap, so no timing threshold can
# separate them. While index-pinching, the user's middle-to-thumb ratio runs
# 0.43-0.90 (median 0.64); across 1060 recorded frames only one dips below
# 0.35. 0.30/0.40 sit safely under that floor with hysteresis room to spare.
PINCH2_CLOSE = 0.30
PINCH2_OPEN = 0.40

ARM_DWELL_S = 0.300
DISARM_S = 0.500
HAND_SCALE_MIN = 0.08
HAND_SCALE_MAX = 0.45
FINGER_EXT_RATIO = 1.15
ARM_FINGERS_MIN = 3

# PROVISIONAL - not yet calibrated against a real curl recording.
# Measured on existing fixtures: index-tip-to-wrist ratio is ~1.71 with the
# hand open and ~1.39 while pinching, so the curl threshold must sit below
# 1.39 or pinching would freeze the cursor. A dedicated clutch recording is
# being made; recalibrate against it before trusting these.
INDEX_CURL_CLOSE = 1.15
INDEX_CURL_OPEN = 1.30

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
# Deliberately 0.7, NOT the canonical One Euro paper value of 0.007. That
# constant is calibrated for pixel-scale coordinates; this project feeds the
# filter normalized [0,1] landmark coordinates, where speeds are three orders
# of magnitude smaller. At 0.007 the adaptive term stays inert across the
# whole range of real hand motion, degenerating the filter to a fixed 1 Hz
# low-pass, which also blunts the velocity swipes need to fire.
EURO_BETA = 0.7
EURO_D_CUTOFF = 1.0

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_FPS = 30

HUD_TICK_MS = 1

# --dry-run posts a `move` roughly every camera tick (~30/s); printed one at
# a time, clicks and other discrete events scroll off screen instantly. This
# is the max age of a pending run of coalesced `move` lines before it flushes
# on its own, so a still hand doesn't leave a summary line hanging forever.
DRY_RUN_FLUSH_S = 1.0
