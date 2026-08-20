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

# A pinch requires the pinching finger to be reasonably EXTENDED, not
# merely to have its tip near the thumb. Curling a finger brings its tip
# toward the palm, where the thumb rests, so tip proximity alone reads a
# partial curl as a press even when the fingers never touch. Finger shape
# separates them cleanly: measured over frames read as pinched, genuine
# pinches never fall below 1.25 index extension (min across all three
# pinch recordings) while deliberate curling reaches 0.69. At these
# values all 253 genuine pinch frames are kept and 126 curl-induced false
# frames are rejected -- the discriminator costs nothing.
#
# The middle-finger figures are the same measurement on the same
# recordings: 1.22 is the lowest middle extension seen on any genuine
# middle-channel close (in recordings/middle_pinch.jsonl; the other two
# recordings never close the middle channel at all). Both thresholds below
# sit slightly under their respective measured genuine minima (1.25 index,
# 1.22 middle) to leave margin for hand orientations not represented in
# the recordings, while both remain far above the curled values (0.69
# index, 0.54 middle) they exist to reject.
#
# Applies to the CLOSE transition only (see state_machine.py's
# _update_pinch): a pinch already held must not release just because the
# finger flexes slightly below these values, which would drop a button
# the user is still actively holding -- the open thresholds above
# (PINCH_OPEN / PINCH2_OPEN) are unaffected by this pair.
#
# PINCH_MIN_EXTENSION == INDEX_CURL_OPEN (1.20) is not a coincidence: see
# INDEX_CURL_CLOSE's comment below for why this makes the curl-gate
# fully redundant for suppressing new index-channel closes specifically,
# while still leaving it load-bearing for two other things it does that
# this gate does not.
PINCH_MIN_EXTENSION = 1.20
PINCH2_MIN_EXTENSION = 1.10

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
#
# Partially redundant with PINCH_MIN_EXTENSION above (2026-08-19 follow-up).
# This rule only ever suppressed a FULL clutch curl (index_curl_ratio below
# 0.95, hysteresis-latched up to 1.20); a partial curl -- one that never
# drops that low -- was not caught, and the user's "even a little closer
# and it presses" report was exactly that gap. PINCH_MIN_EXTENSION,
# calibrated to 1.20 == INDEX_CURL_OPEN, closes it: whenever `_curled` is
# latched True, index_curl_ratio is by definition at or below
# INDEX_CURL_OPEN, so it also fails PINCH_MIN_EXTENSION's `> 1.20` check --
# meaning the extension gate now blocks every NEW index-channel close this
# rule used to block, plus the partial-curl cases it never could. So this
# rule is redundant for that one purpose (gating new index-channel closes)
# and could be dropped for it alone.
#
# It is NOT redundant overall, and must stay, because it does two things
# PINCH_MIN_EXTENSION does not:
#   1. It also blocks the MIDDLE channel while the index is curled. The
#      extension gate checks each channel against its own finger's curl
#      ratio only -- an index curl (self._curled True) does not, by
#      itself, fail PINCH2_MIN_EXTENSION, so a genuine middle-finger click
#      performed while the index happens to be curled would otherwise
#      pass. This rule still suppresses it.
#   2. It force-releases an already-open button the instant curl engages
#      (see state_machine.py's PRESSED handling). PINCH_MIN_EXTENSION
#      applies to the CLOSE transition only, by design (an ordinary press
#      must not drop just because the finger flexes) -- it has no opinion
#      on release, so this rule is the only thing that still safety-releases
#      a held pinch when a curl begins mid-press.
# Both are exercised by tests -- see test_curling_while_pressed_releases_
# the_button_and_freezes and test_curling_ignores_a_spurious_pinch_reading
# in test_state_machine.py -- so do not remove this rule.

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

# Rate-based scrolling (2026-08-20 redesign): hand OFFSET from a neutral
# point sets a continuous scroll SPEED, like a joystick, replacing the
# earlier displacement-based model (a since-removed SCROLL_GAIN and
# scroll_accel curve) where scroll distance followed how far the hand
# physically moved. That model had a hard failure: once the user's hand
# reached the top or bottom of its comfortable range there was nowhere
# left to move, and scrolling simply stopped. Measured from
# recordings/scroll_attempt.jsonl, the usable vertical span during the
# scroll gesture is only 0.22 of frame height, capping one displacement
# stroke at roughly 4400 px -- confirmed too little range for real use.
# Under the rate model hand range stops mattering, because the user holds
# a position rather than sweeping, so they can never run out.
#
# On entering SCROLL, the current vertical hand position is recorded as
# `neutral`. Each frame, offset = current_y - neutral; inside
# SCROLL_NEUTRAL_DEADZONE this emits nothing (lets the user stop by
# returning to centre, and prevents drift while holding still); outside it,
# speed (px/sec) = sign(offset) * (abs(offset) - SCROLL_NEUTRAL_DEADZONE) *
# SCROLL_RATE_GAIN, and the per-frame scroll amount is speed * dt.
#
# Measured from recordings/scroll_hold.jsonl (user performing the gesture
# correctly for 15 s), actual vertical deflections from neutral run to a
# maximum of 0.041 frame-heights, with a median of 0.012, p75 0.023, p90
# 0.034. Initial sizing assumed deflections up to 0.11 (roughly three times
# larger) and set SCROLL_NEUTRAL_DEADZONE=0.02 and SCROLL_RATE_GAIN=30000,
# which swallowed 66% of the gesture with no output. The deadzone must sit
# well below the median (0.012) to register normal holds, while still
# exceeding hand tremor (measured at ~0.0026 frame-height/frame jitter), so
# 0.008 is roughly three times the noise floor. The gain is scaled for a
# maximum useful deflection of 0.04 (vs the original assumption of 0.11),
# yielding expected scroll speeds of: median 240 px/sec, p75 900, p90 1560,
# max 1980.
SCROLL_NEUTRAL_DEADZONE = 0.008   # frame-heights; inside this, no scrolling
SCROLL_RATE_GAIN = 60000.0        # px/sec per frame-height of offset
SCROLL_DWELL_S = 0.200
SCROLL_MIN_PX = 1.0

# Scroll additionally requires the thumb tucked toward the palm, because
# opening the middle finger for a middle-pinch double-click passes
# through the scroll finger posture and caused spurious scrolling. A
# middle-pinch extends the thumb out to meet the middle fingertip, so the
# two gestures become mutually exclusive. Measured thumb-tuck medians:
# scroll 0.55, middle-pinch 0.86, index clicks 0.90. At 0.70 the gate
# keeps 195 of 260 genuine scroll frames and rejects every colliding
# frame in middle_pinch and live_clicks. That 75% retention is measured
# on a recording where the thumb was not deliberately tucked, so real
# retention should be higher.
#
# This threshold governs ENTRY only. See THUMB_TUCK_RELEASE below for why
# leaving scroll uses a separate, looser threshold.
THUMB_TUCK_MAX = 0.70

# Asymmetric on purpose, exactly like ARM_DWELL_S/DISARM_S above: entering
# scroll must be strict (THUMB_TUCK_MAX) so it can't be confused with the
# thumb opening out for a middle-pinch double-click, but leaving scroll
# must be reluctant. Diagnosed 2026-08-19: with a single shared threshold,
# 65 of 260 frames in recordings/scroll_attempt.jsonl have the thumb
# drift above THUMB_TUCK_MAX mid-gesture without the user intending to
# double-click. Each such frame dropped SCROLL straight to TRACKING,
# which -- unlike SCROLL -- processes pinches, so a pinch reading during
# that momentary window could fire a click the user never meant to make:
# 4 spurious ButtonDown/ButtonUp pairs in that one recording. Requiring
# the thumb to clear a much higher bar to leave scroll absorbs that
# momentary drift while still letting a genuine, deliberate untuck (on
# the way to a real middle-pinch) eject the user, same as before.
THUMB_TUCK_RELEASE = 0.95

# Scroll is reluctant to leave, mirroring the posture gate's arm/disarm
# asymmetry and for the same reason. Measured on recordings/scroll_hold.jsonl:
# a correctly performed 15 s gesture broke into 16 fragments, the longest only
# 1.73 s, because single frames of landmark noise dropped the finger or thumb
# condition 13 and 16 times respectively. Every fragment re-entered scroll and
# re-recorded the rate neutral, so the offset never accumulated and the whole
# gesture produced 47 px. The posture must be absent continuously for this
# long before scroll actually ends.
SCROLL_EXIT_S = 0.35

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
