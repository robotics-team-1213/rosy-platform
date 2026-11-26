"""D-1057: slot occupancy and tier from the D435 depth map, on real frames of the cell (2026-11-20 read-only capture)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_area_zones as zones  # noqa: E402
import cell_depth_slots as slots  # noqa: E402
import cell_z_profile as zp  # noqa: E402
import cell_zone_verification as czv  # noqa: E402

FIX = Path(__file__).parent / "fixtures/omx_zone_cal_1120"
_FIXTURE = json.loads((FIX / "zone_rois.json").read_text(encoding="utf-8"))
ROIS = _FIXTURE["zone_rois"]
FLOOR_BY_FRAME = _FIXTURE["floor_depth_mm_by_frame"]  # the floor depth recorded for each captured pose
OCCUPIED, EMPTY = ("c1r2", "c2r2", "c3r2"), ("c1r1", "c2r1", "c3r1")  # black, red, black container; the empty row


class Frames(tuple):
    n = 0


def _frames(n):
    out = Frames((cv2.imread(str(FIX / f"top-{n}.jpg")), cv2.imread(str(FIX / f"side-{n}.jpg")), np.load(FIX / f"depth-{n}.npz")["depth"]))
    out.n = n
    return out


# The local RGB-depth edge error inside the slot ROI is 11-12 px at the right-hand slots of pose 2 (the whole-frame error is 5.9):
# those slots are refused, which is the point of the local check.
LOCAL_BAD = {(2, "c3r2"), (2, "c3r1")}


def refused_locally(frames, key) -> bool:
    if (frames.n, key) not in LOCAL_BAD:
        return False
    ref = _ref(frames, key)
    assert ref["ok"] is False and any("edge error" in r for r in ref["reasons"]) and ref["local_edge_px"] > slots.LOCAL_EDGE_MAX_PX
    return True


def rois_for(frames):
    return {**ROIS, "floor_depth_mm": FLOOR_BY_FRAME[str(frames.n)]}


@pytest.fixture(autouse=True, scope="module")
def _cached_alignment():
    """align_edges is a brute-force search (about 1 s); the same frame pairs recur, so memoise it for this module only."""
    import cell_depth

    real, seen = cell_depth.align_edges, {}

    def cached(colour, heights, *args, **kwargs):
        key = (hash(colour.tobytes()), hash(np.nan_to_num(heights).tobytes()), args, tuple(sorted(kwargs)))
        if key not in seen:
            seen[key] = real(colour, heights, *args, **kwargs)
        return seen[key]

    cell_depth.align_edges = cached
    yield
    cell_depth.align_edges = real


@pytest.fixture(params=[0, 2])
def frames(request):
    return _frames(request.param)


def _ref(frames, key, tier=1):
    top, _, depth = frames
    return slots.depth_reference(depth, top, ROIS["top"][key], ROIS["floor"], tier, floor_depth_mm=FLOOR_BY_FRAME[str(frames.n)])


@pytest.mark.parametrize("key", OCCUPIED)
def test_the_three_placed_containers_are_occupied_tier_1(frames, key):
    if refused_locally(frames, key):
        return
    ref = _ref(frames, key)
    assert ref["ok"] and ref["occupied"] and ref["tier_ok"], ref
    assert abs(ref["median_rel_mm"] - 30.0) <= slots.TOL_MM and ref["valid_depth_ratio"] >= 0.8
    # +-7 mm identified the tier; seating and height anomalies are judged by the unchanged band on the same residual
    from omx_adapter.z_profile import evaluate_signed_tier_residual_mm

    gate, old = slots.tier_gate(ref, 1), evaluate_signed_tier_residual_mm(ref["median_rel_mm"], 1, valid_depth_ratio=ref["valid_depth_ratio"])
    assert gate["verdict"] == old["verdict"] and gate["failure_code"] == old["failure_code"]


@pytest.mark.parametrize("key", EMPTY)
def test_empty_slots_read_absent(frames, key):
    if refused_locally(frames, key):
        return
    ref = _ref(frames, key)
    assert ref["ok"] and ref["occupied"] is False and ref["tier_ok"] is False
    assert slots.tier_gate(ref, 1)["verdict"] == "FAIL"


@pytest.mark.parametrize("key", OCCUPIED)
def test_a_tier_2_requirement_on_a_tier_1_container_fails(frames, key):
    if refused_locally(frames, key):
        return
    ref = _ref(frames, key, tier=2)
    assert ref["ok"] and ref["tier_ok"] is False
    gate = slots.tier_gate(ref, 2)
    assert gate["verdict"] == "FAIL" and gate["r_k_mm"] < -slots.TOL_MM


def test_the_depth_reference_makes_the_calibration_check_ok_and_without_it_nothing_changed(frames):
    top, side, depth = frames
    ref = _ref(frames, "c2r2")
    assert zp._current_frame_calibration_checks(side, top, depth, None, None, 0.9, ref)["ok"] is True
    assert zp._current_frame_calibration_checks(side, top, depth, None, None, 0.9)["ok"] is False  # the original path
    slot = zp.perceive_slot_z_mm(side, top, depth, col=2, row=2, tier=1)  # no floor ROIs: the old absolute gate
    assert slot["spec_gate"]["verdict"] == "UNKNOWN" and slot["measurement_calibrated"] is False


def test_an_unusable_reference_is_reported_not_guessed(frames):
    top, _, depth = frames
    assert slots.depth_reference(None, top, ROIS["top"]["c2r2"], ROIS["floor"], 1)["ok"] is False
    assert slots.depth_reference(depth * 0, top, ROIS["top"]["c2r2"], ROIS["floor"], 1)["ok"] is False  # no valid depth
    assert slots.depth_reference(depth, top, ROIS["top"]["c2r2"], ROIS["floor"], 1, to_depth=np.eye(3)[:2],
                                 align_edge_px=slots.ALIGN_EDGE_MAX_PX + 1)["ok"] is False
    ref = slots.depth_reference(depth, top, ROIS["top"]["c2r2"], [[0, 0, 40, 40]], 1)  # a "floor" that is not flat/valid
    assert ref["ok"] is False or ref["plane_rms_mm"] > 0
    assert slots.tier_gate({"ok": False, "reasons": ["x"]}, 1)["verdict"] == "UNKNOWN"


def _verify(frames, key, tier=1, rois=None):
    rois = rois or rois_for(frames)
    top, side, depth = frames
    col, row = int(key[1]), int(key[3])
    blank = np.zeros_like(top)
    return zones.verify_stack_outcome_z_mm(before_side=blank, after_side=side, before_top=blank, after_top=top, after_depth=depth,
                                           pick={"area": "belt"}, place={"area": "pallet", "col": col, "row": row, "tier": tier},
                                           strict_target=True, zone_rois=rois)


@pytest.mark.parametrize("key", OCCUPIED)
def test_the_real_measurement_function_follows_the_depth_gate_for_each_placed_container(frames, key):
    if refused_locally(frames, key):
        assert _verify(frames, key)["verified"] is False
        return
    out = _verify(frames, key)
    ref = out["depth_reference"]
    assert ref["tier_ok"] is True and ref["change"]["changed"] is True and ref["change"]["orientation_ok"] is True
    # verified exactly when the unchanged seating band passes (r_k in (-4, 1)); depth noise decides which of the slots do
    assert out["verified"] is (out["z_gate"]["verdict"] == "PASS" and not 1.0 <= out["z_gate"]["r_k_mm"] <= 3.0), out.get("reason")
    if key != "c2r2":  # the colour model alone would miss the black ones: auxiliary only
        assert out["place_slot"]["top_zone"]["within_zone"] is False


def test_at_least_some_real_slots_pass_the_unchanged_band(frames):
    verdicts = [_verify(frames, key)["verified"] for key in OCCUPIED if not refused_locally(frames, key)]
    assert any(verdicts), "depth noise should not keep every real slot out of the seating band"


def test_the_same_frame_as_before_and_after_is_refused(frames):
    top, side, depth = frames
    out = zones.verify_stack_outcome_z_mm(before_side=side, after_side=side, before_top=top, after_top=top, after_depth=depth,
                                          pick={"area": "belt"}, place={"area": "pallet", "col": 2, "row": 2, "tier": 1},
                                          strict_target=True, zone_rois=rois_for(frames))
    assert out["verified"] is False and out["depth_reference"]["change"]["changed"] is False
    assert out["depth_reference"]["tier_ok"] is True  # the depth alone looked fine: the missing change is what refuses it


def test_a_horizontal_change_is_not_an_upright_container(frames):
    top, _, _ = frames
    before = np.zeros_like(top)
    after = before.copy()
    x0, y0, x1, y1 = ROIS["top"]["c2r2"]
    after[y0 + 40:y0 + 60, x0 - 20:x1 + 20] = 255  # a wide, flat blob
    assert slots.change_evidence(before, after, [x0 - 20, y0, x1 + 20, y1])["orientation_ok"] is False
    assert slots.change_evidence(None, after, ROIS["top"]["c2r2"])["changed"] is False
    assert slots.change_evidence(before, before, ROIS["top"]["c2r2"])["changed"] is False


def test_contaminated_floor_patches_are_refused(frames):
    top, _, depth = frames
    ok = slots.depth_reference(depth, top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=FLOOR_BY_FRAME[str(frames.n)])
    assert ok["ok"]
    import cell_depth

    plane = cell_depth.table_plane(depth.astype(np.uint16))
    to_depth, _ = cell_depth.align_edges(top, cell_depth.height_map(depth.astype(np.uint16), plane))
    fake = depth.copy()
    for roi in ROIS["floor"]:  # a flat 568 mm surface laid over both floor patches (a flat sheet is not the floor)
        a, b = to_depth @ [roi[0] - 10, roi[1] - 10, 1.0], to_depth @ [roi[2] + 10, roi[3] + 10, 1.0]
        fake[int(a[1]):int(b[1]), int(a[0]):int(b[0])] = 568
    bad = slots.depth_reference(fake, top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=FLOOR_BY_FRAME[str(frames.n)])
    assert bad["ok"] is False and any("recorded floor" in r for r in bad["reasons"])
    covered = depth.copy()
    a, b = to_depth @ [ROIS["floor"][0][0] - 10, ROIS["floor"][0][1] - 10, 1.0], to_depth @ [ROIS["floor"][0][2] + 10, ROIS["floor"][0][3] + 10, 1.0]
    covered[int(a[1]):int(b[1]), int(a[0]):int(b[0])] = 0  # occluded: no depth there
    assert slots.depth_reference(covered, top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=FLOOR_BY_FRAME[str(frames.n)])["ok"] is False
    assert slots.depth_reference(depth, top, ROIS["top"]["c2r2"], ROIS["floor"], 1)["ok"] is False  # no recorded floor depths
    assert slots.depth_reference(depth, top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=[630.0])["ok"] is False


def test_a_same_direction_floor_offset_beyond_the_noise_is_refused(frames):
    top, _, depth = frames
    import cell_depth

    to_depth, _ = cell_depth.align_edges(top, cell_depth.height_map(depth.astype(np.uint16), cell_depth.table_plane(depth.astype(np.uint16))))
    recorded = FLOOR_BY_FRAME[str(frames.n)]

    def lowered(mm):  # every floor patch and its surroundings read mm nearer to the camera (e.g. a sheet laid over the pallet)
        fake = depth.astype(np.int32).copy()
        for roi in ROIS["floor"]:
            a, b = to_depth @ [roi[0] - 20, roi[1] - 20, 1.0], to_depth @ [roi[2] + 20, roi[3] + 20, 1.0]
            part = fake[int(a[1]):int(b[1]), int(a[0]):int(b[0])]
            part[part > 0] -= mm  # valid pixels only (0 means no depth)
        return fake.astype(np.uint16)

    near = slots.depth_reference(lowered(2), top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=recorded)
    assert near["ok"] is True  # inside the 4 mm noise margin
    far = slots.depth_reference(lowered(12), top, ROIS["top"]["c2r2"], ROIS["floor"], 1, floor_depth_mm=recorded)
    assert far["ok"] is False and any("recorded floor" in r or "calibration plane" in r for r in far["reasons"])
    assert slots.FLOOR_DEPTH_TOL_MM == 4.0


def test_the_local_alignment_inside_the_slot_roi_is_measured(frames):
    top, _, depth = frames
    import cell_depth

    M, _ = cell_depth.align_edges(top, cell_depth.height_map(depth.astype(np.uint16), cell_depth.table_plane(depth.astype(np.uint16))))
    good = slots.local_edge_error(top, depth, M, ROIS["top"]["c2r2"])
    shifted = np.array(M, dtype=float)
    shifted[:, 2] += 12.0
    assert good is not None and good <= slots.LOCAL_EDGE_MAX_PX
    assert slots.local_edge_error(top, depth, shifted, ROIS["top"]["c2r2"]) > 2.5 * good  # edges that no longer meet
    assert slots.local_edge_error(None, depth, M, ROIS["top"]["c2r2"]) is None


def test_a_light_change_alone_is_not_a_placed_object(frames):
    top, side, depth = frames
    if refused_locally(frames, "c2r2"):
        return
    darker = np.clip(top.astype(np.float32) * 0.55 + 12, 0, 255).astype(np.uint8)  # same scene, other light
    out = zones.verify_stack_outcome_z_mm(before_side=side, after_side=side, before_top=darker, after_top=top, after_depth=depth,
                                          pick={"area": "belt"}, place={"area": "pallet", "col": 2, "row": 2, "tier": 1},
                                          strict_target=True, zone_rois=rois_for(frames))
    change = out["depth_reference"]["change"]
    assert out["verified"] is False and change["changed"] is False and change["changed_fraction"] < 0.1
    assert out["depth_reference"]["tier_ok"] is True  # the container is really there: only the missing object change refuses it


def test_the_object_change_needs_the_depth_rise_and_the_direction_comes_from_the_depth_blob(frames):
    top, _, depth = frames
    ref = _ref(frames, "c1r2") if not refused_locally(frames, "c1r2") else None
    if ref is None:
        return
    blank = np.zeros_like(top)
    ok = slots.change_evidence(blank, top, ROIS["top"]["c1r2"], ref)
    assert ok["changed"] and ok["depth_raised"] and ok["orientation_ok"] and ok["orientation_class"] == "vertical_ns"
    assert slots.change_evidence(blank, top, ROIS["top"]["c1r2"], None)["changed"] is False  # the picture alone is not enough
    flat = {**ref, "orientation": {"ok": False, "elongation": 1.1, "angle_from_vertical_deg": 70.0}}
    assert slots.change_evidence(blank, top, ROIS["top"]["c1r2"], flat)["orientation_ok"] is False  # a container lying across


def test_a_depth_reference_without_the_cells_own_slot_roi_is_not_verified(frames):
    top, side, depth = frames
    rois = {**rois_for(frames), "top": {k: v for k, v in ROIS["top"].items() if k != "c2r2"}}
    blank = np.zeros_like(top)
    out = zones.verify_stack_outcome_z_mm(before_side=blank, after_side=side, before_top=blank, after_top=top, after_depth=depth,
                                          pick={"area": "belt"}, place={"area": "pallet", "col": 2, "row": 2, "tier": 1},
                                          strict_target=True, zone_rois=rois)
    assert out["verified"] is False and out["depth_reference"]["ok"] is False  # no fallback to the shared top table


@pytest.mark.parametrize("key", EMPTY)
def test_the_real_measurement_function_refuses_an_empty_slot(frames, key):
    assert _verify(frames, key)["verified"] is False


def test_the_real_measurement_function_refuses_tier_2_on_a_tier_1_container(frames):
    out = _verify(frames, "c1r2", tier=2)
    assert out["verified"] is False and out["z_gate"]["verdict"] == "FAIL"


def test_floor_rois_without_a_depth_frame_are_not_verified(frames):
    top, side, _ = frames
    out = zones.verify_stack_outcome_z_mm(before_side=None, after_side=side, before_top=None, after_top=top, after_depth=None,
                                          pick={"area": "belt"}, place={"area": "pallet", "col": 2, "row": 2, "tier": 1},
                                          strict_target=True, zone_rois=rois_for(frames))
    assert out["verified"] is False


def test_without_floor_rois_the_existing_calls_are_unchanged(frames):
    top, side, depth = frames
    rois = {k: v for k, v in rois_for(frames).items() if k != "floor"}
    out = zones.verify_stack_outcome_z_mm(before_side=None, after_side=side, before_top=None, after_top=top, after_depth=depth,
                                          pick={"area": "belt"}, place={"area": "pallet", "col": 2, "row": 2, "tier": 1},
                                          strict_target=True, zone_rois=rois)
    assert out["z_gate"]["verdict"] == "UNKNOWN" and out["verified"] is False and out["depth_reference"] is None


class Cell:
    cameras = {"top": "u", "side": "u"}

    def __init__(self, frames):
        self.top, self.side, _ = frames

    def frame_receipt(self, camera, *, previous=None, max_age_s=2.0, timeout_s=10.0):
        now = time.time()
        return {"image": self.top if camera == "top" else self.side, "camera": camera, "source_seq": 1, "source_stamp": now,
                "captured_at": now, "jpeg_sha256": "x"}


@pytest.mark.parametrize("col, row, expected", [(1, 2, True), (3, 2, True), (2, 1, False)])
def test_the_placement_record_for_a_real_pallet_slot(monkeypatch, frames, col, row, expected):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: (frames[2], {"source_seq": 1, "exposure_wall_estimate_s": time.time()}, None))
    config = {"sites": {"pallet-l0": {"layer": 0, "col": col, "row": row}}, "zone_rois": rois_for(frames)}
    blank = np.zeros_like(frames[0])
    out = czv.measure(Cell(frames), {"image": blank, "before_side": {"image": blank}}, config, "pallet-l0", "belt", None)
    assert out["basis"] == czv.BASIS and out["target"]["tier"] == 1
    if not expected:
        assert out["verified"] is False
    else:  # verified follows the unchanged seating band on this slot's residual
        gate = out["z_gate"]
        assert out["verified"] is (gate["verdict"] == "PASS" and not 1.0 <= gate["r_k_mm"] <= 3.0)


def test_a_floor_table_must_be_a_list_of_valid_rois(monkeypatch, frames):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: (frames[2], {"source_seq": 1, "exposure_wall_estimate_s": time.time()}, None))
    for bad in ([], [[1, 2, 3]], "x", [[0, 0, 900, 40]]):
        config = {"sites": {"pallet-l0": {"layer": 0, "col": 1, "row": 2}}, "zone_rois": {"floor": bad}}
        out = czv.measure(Cell(frames), {"image": frames[0], "before_side": {"image": frames[1]}}, config, "pallet-l0", "belt", None)
        assert out["verified"] is False and "zone_rois" in out["basis"]


def test_depth_is_captured_only_when_the_cell_config_has_floor_rois(monkeypatch, frames):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    calls = []
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: calls.append(1) or (frames[2], {"exposure_wall_estimate_s": time.time()}, None))
    blank = np.zeros_like(frames[0])
    before = {"image": blank, "before_side": {"image": blank}}
    sites = {"pallet-l0": {"layer": 0, "col": 1, "row": 2}}
    czv.measure(Cell(frames), before, {"sites": sites}, "pallet-l0", "belt", None)
    czv.measure(Cell(frames), before, {"sites": sites, "zone_rois": {k: v for k, v in rois_for(frames).items() if k not in ("floor", "floor_depth_mm")}},
                "pallet-l0", "belt", None)
    assert calls == []
    czv.measure(Cell(frames), before, {"sites": sites, "zone_rois": rois_for(frames)}, "pallet-l0", "belt", None)
    assert calls == [1]


def test_floor_rois_need_recorded_depths_and_the_target_slots_own_roi(monkeypatch, frames):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: (frames[2], {"exposure_wall_estimate_s": time.time()}, None))
    blank = np.zeros_like(frames[0])
    before = {"image": blank, "before_side": {"image": blank}}
    sites = {"pallet-l0": {"layer": 0, "col": 3, "row": 2}}
    no_depths = {k: v for k, v in rois_for(frames).items() if k != "floor_depth_mm"}
    assert "floor_depth_mm" in czv.measure(Cell(frames), before, {"sites": sites, "zone_rois": no_depths}, "pallet-l0", "belt", None)["basis"]
    no_slot = {**rois_for(frames), "top": {k: v for k, v in ROIS["top"].items() if k != "c3r2"}}
    out = czv.measure(Cell(frames), before, {"sites": sites, "zone_rois": no_slot}, "pallet-l0", "belt", None)
    assert out["verified"] is False and "no cell-specific ROI for c3r2" in out["basis"]


def test_a_read_that_returns_after_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)

    class Slow:
        cameras = {"top": "u"}

        def frame_receipt(self, camera, **kw):
            time.sleep(0.5)
            now = time.time()
            return {"image": np.zeros((4, 4, 3), np.uint8), "camera": camera, "source_seq": 1, "source_stamp": now, "captured_at": now}

    receipt, why = czv._frame(Slow(), "top", None, 0.0)
    assert receipt is None and "longer than" in why


def test_depth_reference_with_factory_and_subzone_3d_alignment():
    import cell_subzone_3d as csz

    factory = {
        "K": [[600.0, 0.0, 320.0], [0.0, 600.0, 240.0], [0.0, 0.0, 1.0]],
        "depth": {"size": [640, 480], "K": [[600.0, 0.0, 320.0], [0.0, 600.0, 240.0], [0.0, 0.0, 1.0]]},
        "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0.0, 0.0, 0.0]},
    }
    depth = np.full((480, 640), 600, np.uint16)
    depth[200:260, 280:320] = 570  # +30 mm tier-1 container at colour pixels
    ref = slots.depth_reference(depth, None, [280, 200, 320, 260], [[60, 200, 120, 260], [500, 200, 560, 260]],
                                1, floor_depth_mm=[600.0, 600.0], factory=factory)
    assert ref["ok"] is True and ref["align_edge_px"] == 0.0 and ref["occupied"] is True and ref["tier_ok"] is True
    assert ref["median_rel_mm"] == pytest.approx(30.0, abs=1.0)

    # cell_subzone_3d: raw unaligned top_depth without factory/height_map_mm must NOT read hardcoded 588.0 -> None
    raw_obs = csz.observe_subzones_2d(top_depth=depth, col=2, row=1, tier=1)
    assert all(s["top_depth_z_mm"] is None for s in raw_obs["subzones"])

    hm = np.full((480, 640), 30.0, float)  # 30 mm above pallet when pallet_surface_mm=0.0
    aligned_obs = csz.observe_subzones_2d(height_map_mm=hm, col=2, row=1, tier=1)
    assert all(s["top_depth_z_mm"] == pytest.approx(30.0, abs=0.5) for s in aligned_obs["subzones"])

@pytest.mark.parametrize("remove,ok", [(False, True), (True, False)])
def test_factory_depth_ratio_counts_native_rays_and_retains_missing_rays(remove, ok):
    factory = {
        "K": [[619., 0., 320.], [0., 619., 240.], [0., 0., 1.]],
        "depth": {"K": [[388., 0., 320.], [0., 388., 240.], [0., 0., 1.]]},
        "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0., 0., 0.]},
    }
    depth = np.full((480, 640), 600, np.uint16)
    if remove:
        depth[200:280:2, 280:360] = 0
    ref = slots.depth_reference(depth, None, [280, 200, 360, 280], [[60, 200, 120, 260]], 1,
                                floor_depth_mm=[600.], factory=factory)
    support = ref["native_ray_support"]["slot"]
    assert support["expected"] == 48**2
    assert ref["ok"] is ok
    assert ref["valid_depth_ratio"] == pytest.approx(0.5 if remove else 1.0, abs=0.02)


def test_factory_support_rejects_edge_rays_that_move_out_of_patch():
    import cell_depth_pose as pose
    import cell_shared_markers as markers

    k = [[100., 0., 50.], [0., 100., 50.], [0., 0., 1.]]
    factory = {"K": k, "depth": {"K": k}, "depth_to_colour": {"R": np.eye(3).tolist(), "t_m": [0.05, 0., 0.]}}
    depth = np.full((100, 100), 500, np.uint16)
    # The foreground projects 10 pixels farther right. It hides some expected
    # floor rays and brings other foreground samples into the ROI.
    depth[:, 40:50] = 250
    grid = 500 - markers.depth_in_colour(depth, factory, (100, 100))
    plane = {"normal": [0., 0., -1.], "height_mm": 500.}
    seen, total = pose.patch_ray_coverage(depth, grid, (50, 40, 70, 60), 0., plane, factory)
    assert (seen, total) == (200, 400)
