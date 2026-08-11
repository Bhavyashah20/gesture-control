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

# Calibrated against recordings/clutch.jsonl, not estimated. That recording's
# index_curl_ratio is cleanly bimodal: a curled cluster at 0.56-0.9 and a
# pointing cluster at 1.6-2.04, with a wide empty gap between. 0.95 sits in
# that gap. The upper bound is set by pinching, not by pointing: the lowest
# ratio observed during any pinch across all fixtures is 1.03, and a pinch
# misread as a curl would freeze the cursor mid-drag. At 0.95 all 124 genuine
# curl frames are detected and zero pinched frames freeze; the previous
# provisional 1.15 would have frozen 6.
INDEX_CURL_CLOSE = 0.95
INDEX_CURL_OPEN = 1.20

# Curl and pinch are mutually exclusive by construction (2026-08-11 fix).
# Curling the index finger brings the fingertip onto the thumb, which is
# geometrically indistinguishable from a pinch: in recordings/clutch.jsonl
# (index-only curling, the user never pinches) every one of the 124 frames
# classified as curled by INDEX_CURL_CLOSE above also trips PINCH_CLOSE,
# with pinch_ratio bottoming out at 0.01; 56 of those 124 also trip
# PINCH2_CLOSE. A pinch reading during a curl is therefore always spurious.
# state_machine.py evaluates curl before pinch each frame and ignores both
# pinch channels while curled, releasing an already-open button first if
# one was held when the curl engaged (never silently dropping it). This is
# safe against every genuine pinch on record: across the five
# pinch-containing fixtures (374 genuine pinch frames total), the lowest
# index_curl_ratio seen during any real pinch is 1.03 -- comfortably above
# INDEX_CURL_CLOSE -- so no genuine pinch is ever suppressed by this rule.

# Slow-movement reach: hand-sweep pixels = BASE_GAIN_PX * ACCEL_MIN.
# Previous tuning (1600 * 0.35 = 560 px) was insufficient for 1470 px display:
# before reaching the edge, hand left the camera frame. Raised to 2000 * 0.5 =
# 1000 px per hand-sweep; index-curl clutch covers the remaining 470 px.
# Cost: hand tremor is amplified by the same factor, so small targets get
# harder. Deliberate trade-off requested after measuring reach as the bigger
# problem in practice.
BASE_GAIN_PX = 2000.0
ACCEL_MIN = 0.5
ACCEL_MAX = 2.5
ACCEL_VREF = 1.2

# Raised from 900 (2026-08-11): the user reported "scroll does nothing."
# recordings/scroll_attempt.jsonl (15 s, deliberate scrolling) proved the
# posture detection and state machine were fine -- 260 of 444 present frames
# match the scroll posture and the machine emits 53 Scroll intents -- the
# problem was purely magnitude. At the old gain the whole 15 s gesture
# produced 220 px of total scroll (median event 2.4 px), roughly two lines.
#
# Measured total vertical hand travel while the scroll posture holds
# (filtered cursor_ref, summed frame-to-frame, over every posture-matching
# frame regardless of dwell) is 0.429 frame-heights. Naively scaling that
# raw travel by the gain projects 386 px at 900 and ~2145 px at 5000. That
# naive projection is optimistic, though: the real pipeline only scrolls
# once SCROLL_DWELL_S has elapsed and drops any single event under
# SCROLL_MIN_PX, so actual replay output runs below it at both gains --
# 220 px actual vs. 386 px projected at the old GAIN=900. Replayed for
# real at GAIN=5000 through the full pipeline (this fix plus the palm-
# centroid cursor_ref and the jitter deadzone, both below): 118 Scroll
# intents totaling 1362 px (median 3.9 px) -- about 6.2x more scroll for
# the same gesture, comfortably past "does nothing."
SCROLL_GAIN = 5000.0
SCROLL_DWELL_S = 0.200
SCROLL_MIN_PX = 1.0

SWIPE_VEL = 0.8
SWIPE_DIST = 0.20
SWIPE_HOLD_S = 0.100
SWIPE_WINDOW_S = 0.350
SWIPE_COOLDOWN_S = 0.800

# Added 2026-08-11: the user cannot hold the cursor still enough to land on
# small targets like window close buttons. A plain deadzone that discards
# sub-threshold motion outright would also swallow slow, deliberate
# movement -- precision movement IS slow movement -- so state_machine.py
# instead accumulates sub-threshold pixel deltas in a residual and only
# emits Move once the residual's magnitude crosses this threshold, resetting
# to zero on emission. Random tremor is directionless and cancels within the
# residual (cursor sits genuinely still); consistent slow movement is
# directional and keeps accumulating (still reaches its target, just in
# slightly coarser steps once every few frames instead of every frame).
# 2.0 px was chosen as comfortably above single-pixel sensor/filter noise
# but small enough not to be felt as added lag during deliberate movement.
MOVE_DEADZONE_PX = 2.0

EURO_MIN_CUTOFF = 0.4
# Lowered from 1.0 (2026-08-11): 1.0 was fine at the old gain, but at
# BASE_GAIN_PX = 2000 and ACCEL_MIN = 0.5 (raised from 1600 / 0.35 for
# display-edge reach -- see BASE_GAIN_PX's comment) the same hand tremor now
# produces roughly twice the cursor movement it used to, so the
# resting-state smoothing had to increase to compensate -- the user's
# reported symptom was "cursor too jumpy to hit small targets like window
# close buttons." A lower min_cutoff smooths harder specifically when the
# hand is nearly still (small |dx_hat|, so the adaptive cutoff term
# EURO_BETA * |dx_hat| stays near zero and min_cutoff dominates); it does
# NOT add lag when the hand moves fast, because at high speed the same
# adaptive term raises the cutoff back up regardless of min_cutoff. This
# trades a little responsiveness at very low speeds -- the cursor settles
# fractionally slower right as the hand stops -- for the ability to land on
# small targets, which is the trade the user asked for.
#
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
