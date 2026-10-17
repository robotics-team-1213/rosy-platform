"""D-792 camera setup reference and setup check; a verdict never admits a recording by itself."""
import math

from .artifacts import _base, _fields, _hash, _text

MOUNT = ("height_cm", "distance_cm", "tilt_deg", "pan_deg", "roll_deg")
VERDICTS = ("ok", "adjust", "unmeasurable")
MODES = ("shadow", "enforce")
MIN_MARKERS = 3
# shortcut: D-792 starting thresholds without field evidence; S5 replaces them from shadow records.
PX_MEAN, PX_MAX, DEG, CM = 3.0, 6.0, 1.0, 0.5
# Tape and inclinometer against marker estimate; a larger gap means the layout or the tape is wrong.
AGREE_CM, AGREE_DEG = 2.0, 3.0
_DIAGONAL = math.hypot(640, 480)


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


def validate_reference(doc):
    """Verify one sealed ``rosy.camera-setup-reference/1`` and return it."""
    value = _base(doc, "rosy.camera-setup-reference/1",
                  "camera_role camera_identity width height fps intrinsics marker_dictionary "
                  "markers mount reference_still guides created_at created_by")
    for key in ("camera_role", "camera_identity", "marker_dictionary", "created_at", "created_by"):
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
    markers = value["markers"]
    if not isinstance(markers, list) or len(markers) < MIN_MARKERS:
        raise ValueError(f"at least {MIN_MARKERS} reference markers required")
    ids = []
    for marker in markers:
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
    mount = value["mount"]
    _fields(mount, "measured estimated")
    _mount(mount["measured"], nullable=True)
    _mount(mount["estimated"], nullable=False)
    for key in MOUNT:
        measured = mount["measured"][key]
        limit = AGREE_CM if key.endswith("_cm") else AGREE_DEG
        if measured is not None and abs(measured - mount["estimated"][key]) > limit:
            raise ValueError(f"measured {key} disagrees with the marker estimate")
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
    """Verdict for one measured comparison; ``None`` metrics mean the frame could not be measured."""
    if metrics is None:
        return "unmeasurable"
    scale = _DIAGONAL / math.hypot(width, height)
    if metrics["marker_px_mean"] * scale > PX_MEAN or metrics["marker_px_max"] * scale > PX_MAX:
        return "adjust"
    for key in MOUNT:
        if abs(metrics["d_" + key]) > (CM if key.endswith("_cm") else DEG):
            return "adjust"
    return "ok"


def _check(value):
    fields = "markers_seen marker_px_mean marker_px_max verdict " + " ".join("d_" + k for k in MOUNT)
    _fields(value, fields)
    if type(value["markers_seen"]) is not int or value["markers_seen"] < 0:
        raise ValueError("markers_seen must be a nonnegative integer")
    if value["verdict"] not in VERDICTS:
        raise ValueError("unknown setup verdict")
    numbers = [value[k] for k in fields.split() if k not in ("markers_seen", "verdict")]
    if value["verdict"] == "unmeasurable":
        if any(v is not None for v in numbers):
            raise ValueError("an unmeasurable check carries no measurements")
        return
    for v in numbers:
        _num(v)


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
