"""cell_stack_check: orange tops stacked in one slot, read through the colour camera model at their depth-measured
height, come out at CAD size; a focal length 3 % off and a stack knocked out of line are caught."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_stack_check as sc  # noqa: E402

K = np.array([[618.5, 0, 322.3], [0, 618.7, 236.6], [0, 0, 1.0]])
FACTORY = {"K": K.tolist(), "depth": {"size": [640, 480], "K": [[388.7, 0, 321.0], [0, 388.7, 245.0], [0, 0, 1]]},
           "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0.0145, 0.0, 0.0]}}
N = cv2.Rodrigues(np.radians([11.0, 0, 0]))[0] @ [0, 0, -1.0]  # the deck's normal, toward the camera
D = 597.0  # mm from the camera to the deck plane
E1 = np.cross(N, [0, 1.0, 0])
E1 /= np.linalg.norm(E1)
E2 = np.cross(N, E1)
DECK, TOP, SIDE = (5, 235, 200), (10, 200, 230), (10, 200, 140)  # HSV: yellow deck, orange top, darker side


def bgr(hsv):
    return cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()


def tier(k, centre=(120.0, -100.0), size=(90.0, 30.0)):
    """(colour, depth mm) of the slot with k containers: the top face at k * 30 mm, its centre in the deck's frame."""
    height = k * 30.0
    foot = -D * N
    half = np.array(size) / 2

    def corners(h):
        return np.array([foot + (centre[0] + a * half[0]) * E1 + (centre[1] + b * half[1]) * E2 + h * N
                         for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])

    colour = np.full((480, 640, 3), bgr((21, 235, 200)), np.uint8)
    if k:
        top = corners(height)
        project = lambda pts: np.round((pts @ K.T)[:, :2] / (pts @ K.T)[:, 2:]).astype(np.int32)
        for i in range(4):  # side faces first, the top face over them
            quad = np.array([corners(0)[i], corners(0)[(i + 1) % 4], top[(i + 1) % 4], top[i]])
            cv2.fillPoly(colour, [project(quad)], bgr(SIDE))
        cv2.fillPoly(colour, [project(top)], bgr(TOP))
    dK = np.asarray(FACTORY["depth"]["K"])
    t = np.array(FACTORY["depth_to_colour"]["t_m"]) * 1000
    v, u = np.mgrid[0:480, 0:640]
    rays = np.dstack([(u - dK[0, 2]) / dK[0, 0], (v - dK[1, 2]) / dK[1, 1], np.ones((480, 640))])
    depth = (-D - N @ t) / (rays @ N)  # the deck
    if k:
        s = (height - D - N @ t) / (rays @ N)
        X = rays * s[..., None] + t
        a, b = (X - foot) @ E1 - centre[0], (X - foot) @ E2 - centre[1]
        inside = (np.abs(a) <= half[0]) & (np.abs(b) <= half[1])
        depth[inside] = s[inside]
    return colour, np.round(depth).astype(np.uint16).astype(float)


ROI = (330, 120, 560, 330)  # around the slot, ~150 mm off the optical axis


def test_a_true_stack_passes_and_a_wrong_focal_length_or_a_knocked_stack_fails():
    tiers = {k: tier(k) for k in range(4)}
    out = sc.check(tiers, FACTORY, ROI, (90, 30))
    assert out["accepted"] is True, out
    for k in "123":
        row = out["tiers"][k]
        assert abs(row["height_error_mm"]) < 2.0 and abs(row["long_error_mm"]) < 2.0 and abs(row["short_error_mm"]) < 2.0
    wrong = dict(FACTORY, K=(K * [[1.03], [1.03], [1]]).tolist())  # the model under test 3 % off
    bad = sc.check(tiers, wrong, ROI, (90, 30))
    assert bad["accepted"] is False and abs(bad["scale_signal_mm"]) > 1.0
    knocked = {**tiers, 3: tier(3, centre=(128.0, -100.0))}  # the top container 8 mm out of the slot line
    assert sc.check(knocked, FACTORY, ROI, (90, 30))["centre_spread_mm"] > 3.5


def test_jpeg_and_shading_still_pass_and_a_hidden_face_is_named():
    def camera(img):  # light falling off across the view, then the stream's JPEG
        shade = np.linspace(1.0, 0.9, img.shape[1])[None, :, None]
        ok, jpg = cv2.imencode(".jpg", np.clip(img * shade, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 85])
        return cv2.imdecode(jpg, cv2.IMREAD_COLOR)

    tiers = {k: (camera(c), d) for k, (c, d) in ((k, tier(k)) for k in range(4))}
    out = sc.check(tiers, FACTORY, ROI, (90, 30))
    assert out["accepted"] is True, out
    colour, depth = tier(2)
    colour[:, 445:] = bgr((100, 40, 120))  # a grey slot wall over half the top face
    hidden = sc.check({**tiers, 2: (colour, depth)}, FACTORY, ROI, (90, 30))
    assert hidden["tiers"]["2"]["reason"] == "top face partly hidden: its size says nothing"


def test_needs_the_empty_slot_and_says_when_no_face_is_found():
    with pytest.raises(ValueError, match="empty slot"):
        sc.check({1: tier(1)}, FACTORY, ROI, (90, 30))
    empty = {0: tier(0), 1: tier(0)}  # nothing was placed
    assert sc.check(empty, FACTORY, ROI, (90, 30))["tiers"]["1"]["ok"] is False
