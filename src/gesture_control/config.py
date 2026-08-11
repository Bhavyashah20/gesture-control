"""Every constant that governs behaviour. Tuning happens here and nowhere else."""

PINCH_CLOSE = 0.35
PINCH_OPEN = 0.45

# Which finger opened the pinch (index -> Click(1), middle -> Click(2)) is
# decided by comparing pinch_ratio to pinch2_ratio at the moment either one
# first crosses its own CLOSE threshold below -- NOT by a fixed priority
# ("index always wins if closed"). That fixed-priority rule was the original
# design and was wrong: anatomically, pinching the middle fingertip to the
# thumb drags the index tip along with it, so the index channel often also
# reads closed during a genuine middle pinch. In the user's
# recordings/middle_pinch.jsonl (15 s, 8 deliberate middle-pinches), 43 of
# 417 present frames read pinch_ratio < PINCH_CLOSE even though the user
# never pinched their index finger -- under fixed priority that silently
# turned several intended double-clicks into single clicks. Closeness at
# pinch-down was validated against all three recordings on 2026-08-11 and
# correctly resolves every case, with no dead-band needed: the margin
# between the two ratios is 0.32-0.66 during genuine index clicks and
# 0.09-0.41 during genuine middle pinches, so the two never come close to
# tying. Do not reintroduce fixed priority.

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

# Calibrated against real recordings, not estimated. Observed on a live hand:
# deliberate taps hold 0.37-0.47 s (the original 0.250 rejected every one of
# them), and tap travel reaches 16.7 px (the original 15.0 sat mid-distribution).
TAP_MAX_S = 0.550
# TAP_MAX_PX history: first calibration (above) set this to 25.0. A later
# pass across live_clicks.jsonl and five_clicks.jsonl (17 real index taps)
# found 25 px rejects one of them (16/17 register); 60 px is where all 17
# register. Raised to 60.0. Safe only because DRAG_MAX_PX now gives the drag
# trigger its own, separate stillness budget -- before that split, loosening
# this constant would have silently made drags easier to start too.
TAP_MAX_PX = 60.0

# The middle-pinch double-click gesture disturbs the hand about twice as
# much as an index pinch (median reference motion 5.31 vs 2.66 in
# normalized units x1000, measured across real recordings), so it needs a
# looser travel allowance than TAP_MAX_PX. Measured: at 60 px, 6 of 8 real
# middle-pinch attempts register, against 3 of 8 at 25 px; raising it
# further gains nothing, because the two remaining failures are a
# deliberate 2.6 s hold (correctly a drag) and one that genuinely moved
# 283 px.
TAP2_MAX_PX = 60.0

# The drag trigger's own stillness budget. Deliberately separate from
# TAP_MAX_PX: how far a tap may drift and how still the hand must be to
# begin a drag are unrelated decisions, and coupling them means tuning
# clicks silently retunes drag. Measured: the user's real drag has travelled
# between 15 and 25 px by the time the dwell elapses, so budgets below 20 px
# stop genuine drags from starting at all.
DRAG_MAX_PX = 25.0

# Ceiling measured against the user's real drag: at 1.0 s it still fires; at
# 1.5 s it stops firing entirely. Do not raise this further without
# re-measuring. Must stay strictly greater than TAP_MAX_S (0.550), or a tap
# would be reclassified as a drag before it can ever release as a click.
DRAG_DWELL_S = 1.0

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
