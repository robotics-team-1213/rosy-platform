"""Subject: the capture layer owns its sensor. One adaptive loop, not three.

The Pi ISP runs its own Bayesian AWB (frame_period 10, IIR speed 0.05) and its
own AGC/AEC. At 8 fps that re-decides roughly every 1.25 s and then creeps
toward the answer, so a floor-colour reference tracked on top of it is chasing a
moving target. The camera tuning guide names the AWB weakness outright -- "large
objects of a uniform but non-grey colour" -- and a floor filling the lower frame
is exactly that object, so the floor drags the gains that the floor reference is
measured in.

Measured on artifacts/pinky-real-20260907/camera-current.jpg with the reference
frozen: a 1.3x gain step on that one unchanged frame flips blocked False -> True
(1.5x puts near-centre obst at 0.94), and a per-channel white-balance shift
drives near-floor 1.00 -> 0.00 with near-obst 0.00 -> 1.00. Nothing downstream
survives that, so the lock comes before any classifier work.

Setting ExposureTime + AnalogueGain implicitly disables AE, and setting
ColourGains implicitly disables AWB. Passing AeEnable/AwbEnable explicitly has
reported sequencing bugs in picamera2, so this module never emits them.

Values are plain ints/floats/tuples: no picamera2 import, so the tests run off
the robot.
"""

# picamera2 documented control ranges (Appendix C of the manual).
COLOUR_GAIN_MAX = 32.0
# libcamera draft NoiseReductionModeEnum.Fast. HighQuality is documented to cost
# framerate, and denoising is not what makes a floor separable from an obstacle.
NOISE_REDUCTION_FAST = 1
# Sharpening invents halo edges along every floor/obstacle boundary, which is
# indistinguishable from a real edge once the mask is thresholded.
SHARPNESS_OFF = 0.0

LOCKED_KEYS = ('ExposureTime', 'AnalogueGain', 'ColourGains')


def static_controls(fps):
    """Controls that never depend on the scene. Apply after configure(), before start().

    configure() discards previously-set controls, so these cannot be set earlier.
    Pinning FrameDurationLimits to the requested period stops the AE from buying
    brightness with frame time, which would silently drop the detection rate.
    """
    try:
        rate = float(fps)
    except (TypeError, ValueError):
        return None
    if not rate > 0 or rate != rate or rate == float('inf'):
        return None
    period = int(round(1e6 / rate))
    return {
        'NoiseReductionMode': NOISE_REDUCTION_FAST,
        'Sharpness': SHARPNESS_OFF,
        'FrameDurationLimits': (period, period),
    }


def lock_controls(metadata):
    """Convert settled capture metadata into the controls that freeze it.

    Returns None when the metadata cannot justify a lock. Staying in auto is the
    honest failure: a fabricated exposure would be worse than a drifting one,
    because the drift is at least tracking the real scene.
    """
    try:
        exposure = metadata['ExposureTime']
        gain = metadata['AnalogueGain']
        red, blue = metadata['ColourGains']
    except (KeyError, TypeError, ValueError):
        return None
    # bools survive float(), so True would become a silent unity red gain. Any
    # bool here is a metadata read gone wrong, not a measurement.
    if any(isinstance(v, bool) for v in (exposure, gain, red, blue)):
        return None
    # int(float('inf')) raises OverflowError, which is neither TypeError nor
    # ValueError; without it here an unreadable exposure escapes as an exception
    # instead of as "stay in auto". Check finiteness before narrowing to int.
    if not _finite(exposure, gain, red, blue):
        return None
    try:
        exposure, gain = int(exposure), float(gain)
        red, blue = float(red), float(blue)
    except (TypeError, ValueError, OverflowError):
        return None
    # picamera2 reports ExposureTime in microseconds; a frame cannot outlast the
    # sensor's own limits, so a value past an hour is a bad metadata read.
    if exposure <= 0 or exposure > 3_600_000_000 or gain <= 0:
        return None
    # A zero colour gain would zero a channel outright; the documented ceiling is
    # 32.0 and a value past it is a metadata read gone wrong, not a dim room.
    if not 0 < red <= COLOUR_GAIN_MAX or not 0 < blue <= COLOUR_GAIN_MAX:
        return None
    return {'ExposureTime': exposure, 'AnalogueGain': gain, 'ColourGains': (red, blue)}


LOCK_MAX_ATTEMPTS = 3


def lock_action(enabled, now, deadline, attempts, max_attempts=LOCK_MAX_ATTEMPTS):
    """Decide whether to freeze the sensor now. Pure: no camera, no clock, no ROS.

    'disabled'  operator turned the lock off; run in auto and say so.
    'wait'      the ISP has not settled yet, or there is nothing to settle.
    'attempt'   read metadata and try to freeze.
    'exhausted' repeated attempts failed; stay in auto rather than freeze on a
                value we do not trust. A fabricated exposure is worse than a
                drifting one, because the drift at least tracks the real scene.
    """
    if not enabled:
        return 'disabled'
    if deadline is None or attempts >= max_attempts:
        return 'exhausted' if attempts >= max_attempts else 'wait'
    try:
        if not (float(now) >= float(deadline)):
            return 'wait'
    except (TypeError, ValueError):
        return 'wait'
    return 'attempt'


RELOCK_REASONS = ('overexposed', 'low_light')
# Defaults for the clipping trigger (config/camera.yaml carries the same values).
RELOCK_CLIP_FRACTION = 0.30
RELOCK_BRIGHT_MEDIAN = 235.0


class RelockWatch:
    """Decide when a frozen exposure no longer fits the scene. Pure: caller owns the clock.

    The lock is taken once, so a camera that froze in dim light stays frozen at
    that gain when the room brightens (rosy_26, 2026-10-06: exposure=66640us
    gain=8.0 locked at night, 47-71 % of the road clipped in daylight). A bad
    reason must persist for dwell_s before it counts, so one glare frame never
    re-locks, and re-locks are at least min_interval_s apart so a genuinely dark
    room costs one short settle per interval, not a blackout loop.
    The node has no motion signal; CORE already holds the robot while the
    quality is low_light/overexposed, so the settle blackout costs nothing extra.
    dwell_s <= 0 disables the watch.

    The visibility verdict alone misses the real incident: it calls the road
    overexposed only above 95 % clipped, but rosy_26 broke the lane model at
    47-71 % (median 225-253). So a frame is also bad when the road band's clipped
    fraction reaches clip_fraction or its median reaches bright_median.
    """

    def __init__(self, dwell_s, min_interval_s, clip_fraction=RELOCK_CLIP_FRACTION,
                 bright_median=RELOCK_BRIGHT_MEDIAN):
        self._dwell = float(dwell_s)
        self._interval = float(min_interval_s)
        self._clip = float(clip_fraction)
        self._median = float(bright_median)
        self._since = None
        self._last = None

    def update(self, reason, now, clip=0.0, median=0.0):
        """True when the caller should re-run settle -> lock now."""
        bad = reason in RELOCK_REASONS or clip >= self._clip or median >= self._median
        if self._dwell <= 0 or not bad:
            self._since = None
            return False
        if self._since is None:
            self._since = now
        if now - self._since < self._dwell:
            return False
        if self._last is not None and now - self._last < self._interval:
            return False
        self._since, self._last = None, now
        return True


def lock_summary(controls):
    """One-line record of what the camera was frozen at, for the log and the bag."""
    if not controls:
        return 'auto'
    red, blue = controls['ColourGains']
    return (f'exposure={controls["ExposureTime"]}us gain={controls["AnalogueGain"]:.3f} '
            f'colour_gains={red:.3f},{blue:.3f}')


def _finite(*values):
    """Same contract as camera_ground._finite: ints fine, NaN and infinities not."""
    try:
        return all(float(v) == float(v) and
                   float(v) not in (float('inf'), float('-inf')) for v in values)
    except (TypeError, ValueError, OverflowError):
        return False
