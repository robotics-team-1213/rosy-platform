"""D-792 camera setup reference and setup check; a verdict never admits a recording by itself.

Two methods: ``features`` (default, no markers: static scene features of the reference still)
and ``markers`` (optional DICT_4X4_50 work-surface markers, adds height and distance in cm).
An arm-mounted camera (the OMX wrist camera) moves with the arm, so its reference carries a
``check_pose`` and a check is measured only with the arm back at that pose.
"""
import math

from .artifacts import _base, _fields, _hash, _text

MOUNT = ("height_cm", "distance_cm", "tilt_deg", "pan_deg", "roll_deg")
ANGLES = ("pan_deg", "tilt_deg", "roll_deg")
METHODS = ("features", "markers")
VERDICTS = ("ok", "adjust", "unmeasurable")
MODES = ("shadow", "enforce")
MIN_MARKERS = 3
# Real ceiling-camera frames kept >= 295 inliers down to 10% light; near-dark (5%) fell to 38.
MIN_MATCHES = 150
# shortcut: D-792 starting thresholds without field evidence; S5 replaces them from shadow records.
PX_MEAN, PX_MAX, DEG, CM, SCALE_PCT = 3.0, 6.0, 1.0, 0.5, 1.0
# Tape and inclinometer against marker estimate; a larger gap means the layout or the tape is wrong.
AGREE_CM, AGREE_DEG = 2.0, 3.0
_DIAGONAL = math.hypot(640, 480)
CHECK = ("method", "matches", "pose_error_rad", "px_mean", "px_max", "d_pan_deg", "d_tilt_deg", "d_roll_deg",
         "d_scale_pct", "d_height_cm", "d_distance_cm", "verdict")
# 0.01 rad at a 0.2 m lever is 2 mm at the wrist, below the 3 px screen-shift limit at wrist range.
POSE_TOLERANCE = (0.001, 0.05)


def _num(value, low=-math.inf, high=math.inf):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("finite number required")


def _point(value, width, height):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("pixel point [x, y] required")
    _num(value[0], 0, width)
    _num(value[1], 0, height)


def _mount(value, nullable):
    _fields(value, " ".join(MOUNT))
    for key in MOUNT:
        if value[key] is None and nullable:
            continue
        _num(value[key], 0 if key.endswith("_cm") else -180, 1000 if key.endswith("_cm") else 180)


def _markers(value, width, height):
    ids = []
    for marker in value:
        _fields(marker, "id size_cm center_cm corners_px")
        if type(marker["id"]) is not int or marker["id"] < 0:
            raise ValueError("marker id must be a nonnegative integer")
        ids.append(marker["id"])
        _num(marker["size_cm"], 0.5, 100)
        if not isinstance(marker["center_cm"], list) or len(marker["center_cm"]) != 2:
            raise ValueError("marker center_cm [x, y] required")
        for v in marker["center_cm"]:
            _num(v, -1000, 1000)
        if not isinstance(marker["corners_px"], list) or len(marker["corners_px"]) != 4:
            raise ValueError("four marker corners required")
        for corner in marker["corners_px"]:
            _point(corner, width, height)
    if len(ids) != len(set(ids)):
        raise ValueError("unique marker ids required")


def validate_reference(doc):
    """Verify one sealed ``rosy.camera-setup-reference/1`` and return it."""
    value = _base(doc, "rosy.camera-setup-reference/1",
                  "camera_role camera_identity width height fps intrinsics method marker_dictionary "
                  "markers mount check_pose reference_still guides created_at created_by")
    for key in ("camera_role", "camera_identity", "created_at", "created_by"):
        _text(value[key])
    width, height = value["width"], value["height"]
    if any(type(v) is not int or not 1 <= v <= 1920 for v in (width, height)):
        raise ValueError("invalid camera dimensions")
    if type(value["fps"]) is not int or not 1 <= value["fps"] <= 30:
        raise ValueError("invalid sampling fps")
    intrinsics = value["intrinsics"]
    _fields(intrinsics, "camera_info_sha256 revision k dist")
    _hash(intrinsics["camera_info_sha256"])
    _text(intrinsics["revision"])
    if not isinstance(intrinsics["k"], list) or len(intrinsics["k"]) != 4:
        raise ValueError("intrinsics k must be [fx, fy, cx, cy]")
    for v in intrinsics["k"]:
        _num(v, 0)
    if not isinstance(intrinsics["dist"], list) or len(intrinsics["dist"]) not in (4, 5, 8):
        raise ValueError("distortion must have 4, 5 or 8 coefficients")
    for v in intrinsics["dist"]:
        _num(v)
    method, markers = value["method"], value["markers"]
    if method not in METHODS:
        raise ValueError("setup method must be features or markers")
    if not isinstance(markers, list):
        raise ValueError("markers must be a list")
    mount = value["mount"]
    _fields(mount, "measured estimated")
    _mount(mount["measured"], nullable=True)
    if method == "markers":
        _text(value["marker_dictionary"])
        if len(markers) < MIN_MARKERS:
            raise ValueError(f"at least {MIN_MARKERS} reference markers required")
        _markers(markers, width, height)
        _mount(mount["estimated"], nullable=False)
        for key in MOUNT:
            measured = mount["measured"][key]
            limit = AGREE_CM if key.endswith("_cm") else AGREE_DEG
            if measured is not None and abs(measured - mount["estimated"][key]) > limit:
                raise ValueError(f"measured {key} disagrees with the marker estimate")
    elif value["marker_dictionary"] is not None or markers or mount["estimated"] is not None:
        raise ValueError("a features reference carries no markers and no estimated mount")
    pose = value["check_pose"]
    if pose is not None:
        _fields(pose, "joint_names positions_rad tolerance_rad")
        names, positions = pose["joint_names"], pose["positions_rad"]
        if not isinstance(names, list) or not names or len(names) != len(set(names)):
            raise ValueError("check pose needs unique joint names")
        for name in names:
            _text(name)
        if not isinstance(positions, list) or len(positions) != len(names):
            raise ValueError("check pose needs one position per joint")
        for v in positions:
            _num(v, -2 * math.pi, 2 * math.pi)
        _num(pose["tolerance_rad"], *POSE_TOLERANCE)
    _hash(value["reference_still"])
    if not isinstance(value["guides"], list):
        raise ValueError("guides must be a list")
    for guide in value["guides"]:
        _fields(guide, "kind label points closed")
        if guide["kind"] not in ("edge", "zone", "object"):
            raise ValueError("guide kind must be edge, zone or object")
        _text(guide["label"])
        if type(guide["closed"]) is not bool:
            raise ValueError("guide closed must be a boolean")
        if not isinstance(guide["points"], list) or len(guide["points"]) < (3 if guide["closed"] else 2):
            raise ValueError("guide needs at least two points, three when closed")
        for point in guide["points"]:
            _point(point, width, height)
    return value


def judge(metrics, width, height):
    """Verdict for one measured comparison; ``None`` metrics mean the frame could not be measured.

    Pixel limits are for 640x480 and scale with the image diagonal. ``None`` deltas are not
    measured by the method (cm without markers) and do not count."""
    if metrics is None:
        return "unmeasurable"
    scale = _DIAGONAL / math.hypot(width, height)
    if metrics["px_mean"] * scale > PX_MEAN or metrics["px_max"] * scale > PX_MAX:
        return "adjust"
    limits = {"d_pan_deg": DEG, "d_tilt_deg": DEG, "d_roll_deg": DEG, "d_scale_pct": SCALE_PCT,
              "d_height_cm": CM, "d_distance_cm": CM}
    if any(metrics[key] is not None and abs(metrics[key]) > limit for key, limit in limits.items()):
        return "adjust"
    return "ok"


def _check(value):
    _fields(value, " ".join(CHECK))
    if value["method"] not in METHODS:
        raise ValueError("setup method must be features or markers")
    if type(value["matches"]) is not int or value["matches"] < 0:
        raise ValueError("matches must be a nonnegative integer")
    if value["verdict"] not in VERDICTS:
        raise ValueError("unknown setup verdict")
    if value["pose_error_rad"] is not None:
        _num(value["pose_error_rad"], 0)
    numbers = [key for key in CHECK if key not in ("method", "matches", "pose_error_rad", "verdict")]
    if value["verdict"] == "unmeasurable":
        if any(value[key] is not None for key in numbers):
            raise ValueError("an unmeasurable check carries no measurements")
        return
    for key in numbers:
        unmeasured = ("d_height_cm", "d_distance_cm") if value["method"] == "features" else ("d_scale_pct",)
        if key in unmeasured:
            if value[key] is not None:
                raise ValueError(f"a {value['method']} check does not measure {key}")
            continue
        _num(value[key])


def validate_setup(value):
    """Verify the ``provenance.camera.setup`` record of one Episode."""
    _fields(value, "reference_revision before after mode")
    _hash(value["reference_revision"])
    if value["mode"] not in MODES:
        raise ValueError("setup mode must be shadow or enforce")
    _check(value["before"])
    if value["after"] is not None:
        _check(value["after"])
    if value["mode"] == "enforce" and value["before"]["verdict"] != "ok":
        raise ValueError("enforce mode cannot record an Episode started without an ok check")
    return value


def pose_error(reference, joints):
    """Largest joint difference from the reference check pose in rad; None for a fixed camera.

    ``joints`` maps joint name to the current readback in rad. A missing joint raises: an
    arm-mounted check without the arm's own readback cannot say where the camera looked."""
    pose = reference["check_pose"]
    if pose is None:
        return None
    if not isinstance(joints, dict) or any(name not in joints for name in pose["joint_names"]):
        raise ValueError("arm-mounted camera check needs the current joint readback")
    for name in pose["joint_names"]:
        _num(joints[name])
    return max(abs(joints[n] - p) for n, p in zip(pose["joint_names"], pose["positions_rad"]))
