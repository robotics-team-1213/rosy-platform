"""cell_calibrate remap: visit order, the stop reason, and the folded arm's own body in the scene check (2026-11-26)."""
import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate as cc  # noqa: E402

GRID = [(0.10, 0.10), (0.12, 0.12), (0.10, 0.14), (0.14, 0.10), (0.15, 0.15), (0.17, 0.12), (0.13, 0.17), (0.18, 0.09)]


def to_px(p):  # 1 px per mm, arm (0, 0.2) at pixel (200, 200)
    return (200 + p[0] * 1000, 200 + (p[1] - 0.2) * 1000)


def test_remap_visits_neighbours_instead_of_crossing_the_grid():
    """2026-11-26 arm_a: by distance from the base alone, 6 of 18 moves crossed the grid at 80-105 s each."""
    arm_a = [[0.11, 0.04], [0.11, 0.06], [0.11, 0.08], [0.13, 0.02], [0.13, 0.04], [0.13, 0.06], [0.13, 0.08],
             [0.15, 0.02], [0.15, 0.04], [0.15, 0.06], [0.15, 0.08], [0.17, 0.02], [0.17, 0.04], [0.17, 0.06],
             [0.09, 0.12], [0.06, 0.14], [0.07, 0.16], [0.04, 0.17]]
    order = cc.rp.visit_order(arm_a)

    def path(seq):
        return sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))

    assert sorted(order) == sorted(arm_a) and order[0] == min(arm_a, key=lambda q: math.hypot(*q))
    assert cc.rp.visit_order([[0.1, 0.1], [0.1, 0.1], (0.2, 0.0)]) == [[0.1, 0.1], [0.1, 0.1], (0.2, 0.0)]
    assert cc.rp.visit_order([]) == []
    assert path(order) < 0.6 * path(sorted(arm_a, key=lambda q: math.hypot(*q)))


def test_a_stop_before_enough_marks_names_the_stop(tmp_path, monkeypatch):
    """2026-11-26 arm_a: a contact stop at the first point was reported only as "only 0 marks agree of 0"."""
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))

    class Cell:
        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            if command == "goto above_pick":
                return {"ok": False, "error": "contact in goto above_pick: shoulder_lift lag rose to 2.2 units"}
            return {"ok": True}

    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    with pytest.raises(SystemExit, match=r"remap stopped at goto above_pick for \[0\.1, 0\.1\]: contact in goto "
                                         r"above_pick: shoulder_lift lag.*marks agree of 0"):
        cc.remap(Cell(), config, [list(p) for p in GRID], tmp_path, log=lambda row: None)


def test_remap_scene_check_skips_the_folded_arms_own_body(tmp_path, monkeypatch):
    """2026-11-24..26 arm_s: the parked arm's cables moved a few px and 4 of 9 remaps saved nothing."""
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = cc.rp.visit_order(GRID)

    class Cell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            view = np.zeros((480, 640, 3), np.uint8)
            if self.i >= 0:  # the folded arm's cable, a few px off after the last park
                view[342:352, 314:344] = (200, 200, 200)
            return view

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(points[cell.i]))
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    with pytest.raises(SystemExit, match="scene changed"):
        cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)
    config["calibrate"]["scene_ignore_px"] = [[285, 40, 375, 385]]
    record = cc.remap(Cell(), config, [list(p) for p in points], tmp_path / "again", log=lambda row: None)
    assert len(record["points"]) == len(points)


def test_planned_hovers_pick_the_order_without_raised_transits():
    """2026-11-26 arm_a: one 87 s transit (close, rise, turn, descend, open) between the grid's two clusters."""
    direct_move = cc.rp.direct_move
    points = [(0.10, 0.0), (0.11, 0.0), (0.14, 0.0), (0.16, 0.0)]  # S, A, B, C; A is S's nearest neighbour
    hovers = [[pan, -20.0, 10.0, 50.0, 0.0] for pan in (10.0, 40.0, 20.0, 30.0)]  # but A is 30 deg of pan away

    def transits(order):
        h = [hovers[points.index(p)] for p in order]
        return sum(not direct_move(a, b) for a, b in zip(h, h[1:]))

    plain = cc.rp.visit_order(points)
    assert plain == [points[0], points[1], points[2], points[3]] and transits(plain) == 2
    planned = cc.rp.visit_order(points, hovers)
    assert planned == [points[0], points[2], points[3], points[1]] and transits(planned) == 0
    assert cc.rp.visit_indices(points, hovers, budget=0) == [0, 1, 2, 3]  # no search: the nearest chain
    assert cc.rp.visit_order(points, [*hovers[:3], None]) == plain  # a point without a plan: the nearest chain


def test_direct_move_matches_transit_path():
    """The order's straight-move test must stay the one transit_path uses."""
    import itertools

    from omx_adapter.chunk_library import PARK_SPEED, RISE_SPEED, transit_path
    from omx_adapter.motion_profile import flow

    base = [20.0, -20.0, 10.0, 50.0, 0.0, 62.0]
    steps = {0: (0, 14, 16), 1: (0, -14, -16, 23, 26), 2: (0, 23, 25), 3: (0, 23, 25), 4: (0, 44, 46)}
    seen = set()
    for start in (base, [20.0, -34.0, 10.0, 50.0, 0.0, 62.0], [20.0, -36.0, 10.0, 50.0, 0.0, 62.0]):
        for i, deltas in steps.items():
            for d in deltas:
                goal = list(base)
                goal[i] += d
                straight = flow([list(start), goal], 30, 0.85 * PARK_SPEED, blend=[False, False], blend_s=0.25,
                                rise_speed=RISE_SPEED)
                same = transit_path(start, goal, 50.5, 30, None, 0.85) == straight
                assert cc.rp.direct_move(start, goal) == same, (start[1], i, d)
                seen.add(same)
    assert seen == {True, False}


def test_a_moved_camera_carries_the_regions_before_the_depth_check(tmp_path):
    """2026-11-27 arm_a: the depth check read the pallet through its pre-move ROI and refused the remap."""
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(5)
    ref = np.full((480, 640), 90, np.uint8)
    for _ in range(160):
        x, y = int(rng.integers(0, 620)), int(rng.integers(0, 460))
        cv2.rectangle(ref, (x, y), (x + int(rng.integers(6, 40)), y + int(rng.integers(6, 40))), int(rng.integers(0, 255)), -1)
    cv2.imwrite(str(tmp_path / "ref.png"), ref)
    now = cv2.warpAffine(ref, np.float32([[1, 0, 30], [0, 1, 0]]), (640, 480), borderValue=90)
    config = {"preflight": {"reference_top": str(tmp_path / "ref.png")}, "sites": {"pallet": {"auto_roi": [200, 100, 300, 300]}}}
    found = {"camera_moved": True, "camera_shift": {"ok": True, "inliers": 500}}
    moved = cc.rp.regions_now(config, found, now)
    assert moved["sites"]["pallet"]["auto_roi"][0] == pytest.approx(230, abs=3) and config["sites"]["pallet"]["auto_roi"][0] == 200
    assert cc.rp.regions_now(config, {"camera_moved": False}, now) is config
    for weak in ({"ok": False}, {"ok": True, "inliers": 40}, None):
        assert cc.rp.regions_now(config, {"camera_moved": True, "camera_shift": weak}, now) is config
    assert cc.rp.regions_now(config, found, np.zeros((480, 640), np.uint8)) is config  # no homography: as before
    seen = {}
    monkey_depth = lambda cfg, depth, colour: seen.setdefault("roi", cfg["sites"]["pallet"]["auto_roi"]) and {"obstacle_mm": 0.0, "sites_mm": {}, "edge_px": 0.0}  # noqa: E731
    import cell_cal_eval
    orig = (cc.rp.site_obstacle_mm, cell_cal_eval.top_has_depth)
    cc.rp.site_obstacle_mm, cell_cal_eval.top_has_depth = monkey_depth, lambda c: True
    try:
        view, _ = cc.rp.remap_view({**config, "coarse": {"z_view": 0.14}}, now, None, lambda: object(), depth_config=moved)
    finally:
        cc.rp.site_obstacle_mm, cell_cal_eval.top_has_depth = orig
    assert seen["roi"][0] == moved["sites"]["pallet"]["auto_roi"][0] and view["sites"] is config["sites"]  # only the depth moved


def _profiles(tmp_path, roi):
    import json
    cal = tmp_path / "arm-b" / "stack-calibration.json"
    cal.parent.mkdir()
    cal.write_text("{}", encoding="utf-8")
    sites = {"pallet": {"auto_roi": list(roi), "surface_px": [[1, 1], [9, 1], [9, 9]], "z": 0.0},
             "pallet_t1": {"tier_of": "pallet", "auto_roi": [0, 0, 1, 1]}}
    stack = {"arm_id": "arm_b", "calibration_path": str(cal), "sites": sites}
    policy = {**json.loads(json.dumps(stack)), "payload": {"kg": 0.05}, "zone_rois": {"ship": [1, 2, 3, 4]}}
    for name, cfg in (("cell-arm-b-stack.json", stack), ("cell-arm-b-policy.json", policy)):
        (tmp_path / name).write_text(json.dumps(cfg), encoding="utf-8")
    return cal, stack


def test_a_remap_through_one_profile_carries_the_moved_geometry_to_the_other(tmp_path):
    """2026-11-27: stack and policy share one map; a remap through one left the other held on 'site geometry changed'."""
    import hashlib
    import json
    import cell_attempts
    import cell_calibrate_bound as cb
    from cell_auto_evidence import bound_map_error

    cal, stack = _profiles(tmp_path, (10, 10, 50, 50))
    old = cb.geometry_sha(stack)
    stack["sites"]["pallet"]["auto_roi"] = [40, 12, 80, 52]  # move_regions after the camera moved
    out = cb.sync_siblings(tmp_path / "cell-arm-b-stack.json", stack, cal, old)
    policy = json.loads((tmp_path / "cell-arm-b-policy.json").read_text(encoding="utf-8"))
    assert out == {"synced": ["cell-arm-b-policy.json"], "held": []}
    assert policy["sites"]["pallet"]["auto_roi"] == [40, 12, 80, 52] and policy["payload"] == {"kg": 0.05}
    assert cb.geometry_sha(policy) == cb.geometry_sha(stack)
    bound = {"reference_top_sha256": hashlib.sha256(b"jpg").hexdigest(), "reference_map_sha": cell_attempts.digest(None),
             "reference_geometry_sha": cb.geometry_sha(stack)}
    assert bound_map_error(bound, policy, b"jpg") is None
    assert list(tmp_path.glob("cell-arm-b-policy.json.bak-*"))  # the previous file is kept


def test_a_sibling_that_had_drifted_from_the_old_binding_stays_held(tmp_path):
    import json
    import cell_calibrate_bound as cb

    cal, stack = _profiles(tmp_path, (10, 10, 50, 50))
    old = cb.geometry_sha(stack)
    policy_path = tmp_path / "cell-arm-b-policy.json"
    drifted = json.loads(policy_path.read_text(encoding="utf-8"))
    drifted["sites"]["pallet"]["auto_roi"] = [11, 10, 50, 50]  # hand-edited: not what the replaced map was measured with
    policy_path.write_text(json.dumps(drifted), encoding="utf-8")
    stack["sites"]["pallet"]["auto_roi"] = [40, 12, 80, 52]
    assert cb.sync_siblings(tmp_path / "cell-arm-b-stack.json", stack, cal, old) == {"synced": [], "held": ["cell-arm-b-policy.json"]}
    assert json.loads(policy_path.read_text(encoding="utf-8")) == drifted
    assert cb.sync_siblings(tmp_path / "cell-arm-b-stack.json", stack, cal, "") == {"synced": [], "held": ["cell-arm-b-policy.json"]}
