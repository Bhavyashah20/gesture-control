"""Every constant that governs behaviour. Tuning happens here and nowhere else."""

PINCH_CLOSE = 0.35
PINCH_OPEN = 0.45

ARM_DWELL_S = 0.300
DISARM_S = 0.500
HAND_SCALE_MIN = 0.08
HAND_SCALE_MAX = 0.45
FINGER_EXT_RATIO = 1.15
ARM_FINGERS_MIN = 3

# Calibrated against real recordings, not estimated. Observed on a live hand:
# deliberate taps hold 0.37-0.47 s (the original 0.250 rejected every one of
# them), tap travel reaches 16.7 px (the original 15.0 sat mid-distribution),
# and a real double-click gap was 0.399 s (the original 0.350 just missed it).
TAP_MAX_S = 0.550
TAP_MAX_PX = 25.0
DOUBLE_MAX_S = 0.450
DOUBLE_MAX_PX = 50.0
DRAG_DWELL_S = 0.700

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
EURO_BETA = 0.7
EURO_D_CUTOFF = 1.0

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FRAME_FPS = 30
