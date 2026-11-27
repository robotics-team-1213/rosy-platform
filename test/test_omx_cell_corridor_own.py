"""The fold corridor's own-arm mask and reference-frame gap (cell_corridor_own), from arm_a's stop on 2026-11-27:
extended over the belt's edge, torque OFF, every fold candidate ALL_PATHS_BLOCKED."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_corridor as cc  # noqa: E402
import cell_corridor_own as own  # noqa: E402
import cell_pivot  # noqa: E402
import cell_place_fit  # noqa: E402
import cell_recovery_plan as crp  # noqa: E402

ROI = (0, 0, 400, 400)
SHAPE = (400, 400)
START = [-20.59, 15.07, 7.11, 40.76, 29.91, 57.19]  # arm_a's measured joints at the stop
HOME = [0.8, -62.2, 53.1, 51.6, 45.2, 49.0]
LIFT = [START[0], START[1] - 40.0, *START[2:]]  # straight up past clear_z before the fold, as park_path does
TCP_X = 0.074
BELT = [[255, 40], [335, 40], [335, 150], [255, 150]]  # the TCP (325, 96) rests 10 px inside its right edge
PALLET = [[210, 250], [390, 250], [390, 350], [210, 350]]
FAR = [[40, 150], [120, 150], [120, 250], [40, 250]]
SHIP = [[360, 30], [395, 30], [395, 80], [360, 80]]


def _to_px(p):  # 1 px per mm, the arm's base at pixel (200, 200)
    return (200.0 + p[0] * 1000.0, 200.0 + p[1] * 1000.0)


class _Cell:
    def __init__(self, img):
        self.img = img

    def frame(self, _camera):
        return self.img


def _config(reference: Path | None) -> dict:
    site = lambda poly: {"z": 0.0, "surface_z": 0.0, "surface_px": poly, "surface_lab": [240, 128, 128]}  # noqa: E731
    config = {"sites": {"belt": site(BELT), "pallet": site(PALLET), "far": site(FAR), "ship": site(SHIP)},
              "cameras": {"top": {"height_m": 0.6, "center_px": [300, 370]}}}
    if reference is not None:
        config["preflight"] = {"reference_top": str(reference)}
    return cell_place_fit.with_tiers(config)[0]


def _furniture() -> np.ndarray:
    """White mats on a dark base plate beside a bright table: the gap has no single colour."""
    img = np.full((400, 400, 3), 50, np.uint8)
    img[:, 150:260] = 200
    for poly in (BELT, PALLET, FAR, SHIP):
        cv2.fillPoly(img, [np.asarray(poly, np.int32)], (240, 240, 240))
    return img


def _look(img, reference: Path | None, state=START, bound: str | None = None):
    """The fold's look: the reference bound by its sha256 (or `bound`), the arm's links from `state` (None: not asked)."""
    calibration = {}
    if reference is not None:
        calibration["reference_top_sha256"] = bound or hashlib.sha256(reference.read_bytes()).hexdigest()
    return crp.build_multi_site_look(_Cell(img), _config(reference), calibration, "belt", ROI, None, _to_px, TCP_X,
                                     allow_ascending_departure=True,
                                     own_state=None if state is None else (lambda: state))


def _arm(pose) -> np.ndarray:
    return own.own_mask(_config(None), "belt", _to_px, [pose], SHAPE, ROI, TCP_X, half_mm=25.0) > 0


def test_check_own_links_are_neither_obstacle_nor_unseen():
    site = [[240, 60], [360, 60], [360, 340], [240, 340]]
    tcp = [(0.12, y, 0.14) for y in np.linspace(-0.10, 0.10, 20)]  # a high lane along pixel x = 320
    mask = np.zeros(SHAPE, np.uint8)
    mask[180:220, 310:330] = 1
    assert cc.check(tcp, mask, ROI, _to_px, surface_px=site)["high"]
    links = np.zeros(SHAPE, np.uint8)
    links[170:230, 300:340] = 1
    assert cc.check(tcp, mask, ROI, _to_px, surface_px=site, own=links)["clear"]
    mask[120:140, 310:330] = 1  # a blob beside the links still blocks
    assert cc.check(tcp, mask, ROI, _to_px, surface_px=site, own=links)["high"]
    narrow = [[310, 60], [330, 60], [330, 340], [310, 340]]
    empty = np.zeros(SHAPE, np.uint8)
    assert cc.check(tcp, empty, ROI, _to_px, surface_px=narrow, own=links)["off_surface"] > 0  # unseen beside the links
    assert cc.check(tcp, empty, ROI, _to_px, surface_px=narrow, own=np.ones(SHAPE, np.uint8))["clear"]


def test_own_mask_is_empty_without_a_site_height_or_a_top_camera():
    config = _config(None)
    assert own.own_mask(config, "belt", _to_px, [START], SHAPE, ROI, TCP_X).any()
    assert not own.own_mask({**config, "cameras": {}}, "belt", _to_px, [START], SHAPE, ROI, TCP_X).any()
    assert not own.own_mask(config, "nowhere", _to_px, [START], SHAPE, ROI, TCP_X).any()
    assert not own.own_mask(config, "belt", lambda _p: None, [START], SHAPE, ROI, TCP_X).any()


def test_measured_joints_come_only_from_an_ok_state():
    class _Runner:
        def __init__(self, status):
            self.status = status

        def act(self, _command):
            return self.status

    assert own.measured_joints(_Runner({"ok": True, "state": START})) == START
    assert own.measured_joints(_Runner({"ok": False, "state": START})) is None
    assert own.measured_joints(_Runner({"ok": True, "state": [0.0, float("nan"), 0.0, 0.0, 0.0, 0.0]})) is None
    assert own.measured_joints(_Runner(None)) is None


def test_fold_from_the_belt_edge_clears_against_the_reference_and_still_sees_an_object(tmp_path):
    config = _config(None)
    frames = [START, *crp.interpolate_pose(START, LIFT, max_step=2.0), *crp.interpolate_pose(LIFT, HOME, max_step=2.0)]
    reference = tmp_path / "reference-top.png"
    folded = _furniture()
    folded[_arm(HOME)] = 20  # the reference shows the arm folded at home
    cv2.imwrite(str(reference), folded)
    img = _furniture()
    img[_arm(START)] = 20  # now it lies extended over the belt's edge

    # the colour rule alone: the furniture makes the whole gap an object, as on the real cell
    old = _look(img, None)(frames)
    assert not old["clear"] and (old["low"] or old["high"])
    # against the bound reference only the arm changed, and the arm is its own
    assert _look(img, reference)(frames)["clear"] is True
    # a caller that does not ask (the placement check) still meets the arm as an obstacle, and keeps the colour rule
    # for the gap even where nothing differs from the reference
    assert not _look(img, reference, state=None)(frames)["clear"]
    cv2.imwrite(str(tmp_path / "same.png"), _furniture())
    across = crp.interpolate_pose(LIFT, HOME, max_step=2.0)  # high over the gap only
    assert not _look(_furniture(), tmp_path / "same.png", state=None)(across)["clear"]
    assert _look(_furniture(), tmp_path / "same.png")(across)["clear"] is True
    # the links are excused where they are measured, not where the path says they start
    elsewhere = [START[0] + 60.0, *START[1:]]
    assert not _look(img, reference, state=elsewhere)(frames)["clear"]
    # a reference the calibration is not bound to, or of another size, is no reference
    assert not _look(img, reference, bound="0" * 64)(frames)["clear"]
    small = tmp_path / "small.png"
    cv2.imwrite(str(small), _furniture()[:200])
    assert not _look(img, small)(frames)["clear"]

    # an object in the lane, beside the arm, still refuses the fold: darker, and of the table's own brightness
    low, high = cc.runs([cell_pivot.joints_tcp(f, tcp_x_m=TCP_X)[:3] for f in frames])
    lane = cc.corridor(low + high, _to_px, SHAPE, ROI) > 0
    links = own.own_mask(config, "belt", _to_px, (START, HOME), SHAPE, ROI, TCP_X) > 0
    polys = cc.calibrated_surface_polygons(config, "belt")
    hull = cc.transit_hull_polygon(polys, extra_pts=[_to_px((0.0, 0.0))])
    gap = (cc._fill_surfaces(SHAPE, ROI, hull) > 0) & ~(cc._fill_surfaces(SHAPE, ROI, polys) > 0)
    depth = cv2.distanceTransform((lane & ~links & gap).astype(np.uint8), cv2.DIST_L2, 3)
    row, col = np.unravel_index(int(depth.argmax()), depth.shape)
    assert depth[row, col] >= 7, "the fixture needs lane pixels beside the arm"
    for colour in ((125, 125, 125), tuple(int(v) + d for v, d in zip(img[row, col], (70, 0, -70)))):
        seen_img = img.copy()
        seen_img[row - 6:row + 7, col - 6:col + 7] = np.clip(colour, 0, 255)
        seen = _look(seen_img, reference)(frames)
        assert not seen["clear"] and (seen["low"] or seen["high"]), colour
