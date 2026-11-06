"""What the 2026-11-06 ship round trip on arm_b needed: a wrist roll that holds in free air refuses the plan before any
motion, a fold held on the strain of the stop is retried, new table sites share the arm's map, a shallow grip keeps the
box level at the release, and a person's weight bound stays apart from a reading."""
import json
from pathlib import Path
import sys
import types

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_auto_pick as auto
    import cell_jaw_axis
    import cell_objects
    import cell_pipeline_io as cio
    import cell_pivot
    import cell_reach
    import cell_scale
    import cell_scene_guard
finally:
    sys.path.remove(str(OMX))

ROLL = "wrist_roll.pos"
ENTRY = {"id": "container-v2-3", "length_mm": 90, "width_mm": 30, "top_height_mm": 32.4,
         "grasp": {"jaw_axis_deg_from_long": 0}}
OBJECT = {"raw_m": [0.12, 0.015], "long_axis_deg": 89.0}
WIDE = {"gripper.open_max": 62.0}  # the default 56 refuses a 90 mm gap


def planner_with_roll(monkeypatch, roll):
    library = {"names": ["shoulder_pan.pos", ROLL], "chunks": {"above_pick": [[0.0, 54.0]], "descend_place": [[0.0, roll]]}}
    planner = types.SimpleNamespace(Planner=lambda plan: types.SimpleNamespace(library=lambda: library))
    monkeypatch.setitem(sys.modules, "grasp_planner", planner)


def test_a_plan_under_the_arms_joint_min_is_refused_before_any_file_exists(tmp_path, monkeypatch):
    planner_with_roll(monkeypatch, -29.4)  # yaw -120 folds to the twin +60: through the stall at 9.89
    path = tmp_path / "lib.json"
    with pytest.raises(SystemExit, match="wrist_roll.pos target -29.4 is under"):
        cio.write_library({"plan": {}, "joint_min": {ROLL: 15.0}}, {}, {}, path)
    assert not path.exists()


def test_a_plan_above_joint_min_and_an_arm_without_one_are_written(tmp_path, monkeypatch):
    planner_with_roll(monkeypatch, 19.9)
    assert cio.write_library({"plan": {}, "joint_min": {ROLL: 15.0}}, {}, {}, tmp_path / "a.json").exists()
    planner_with_roll(monkeypatch, -29.4)
    assert cio.write_library({"plan": {}}, {}, {}, tmp_path / "b.json").exists()


def test_plan_pick_takes_the_yaw_twin_when_the_first_yaw_breaks_joint_min(tmp_path, monkeypatch):
    config = {"plan": {"approach_m": 0.04}, "params": WIDE,
              "sites": {"ship": {"surface_z": -0.0167, "yaw_deg": 0.0}, "table": {"surface_z": -0.0197, "yaw_deg": -90.0}}}
    tried = []

    def write(cfg, pick, place, path):
        tried.append(pick["yaw_deg"])
        if len(tried) == 1:
            raise SystemExit("wrist_roll.pos target -29.4 is under this arm's joint_min 15.0")
        return path

    monkeypatch.setattr(auto.cp, "write_library", write)
    planned = auto.plan_pick(config, "ship", "table", (0.068, -0.112), OBJECT, ENTRY, 0, (0, 0), tmp_path)
    assert not isinstance(planned, str) and tried == [89.0, 269.0] and planned[4] == 269.0


class Parks:
    def __init__(self, *replies):
        self.replies, self.commands = list(replies), []

    def act(self, command):
        self.commands.append(command)
        return self.replies.pop(0)


def test_a_fold_held_on_a_contact_is_tried_once_more_after_a_pause():
    pauses, cell = [], Parks({"ok": False, "contact": True}, {"ok": True, "settled": True})
    assert cio.fold(cell, pauses.append)["ok"] and cell.commands == ["park", "park"] and pauses == [2.0]


def test_a_fold_is_not_repeated_after_it_worked_or_on_a_fault():
    done, broken = Parks({"ok": True}), Parks({"ok": False, "fault": "overload"})
    assert cio.fold(done, pytest.fail)["ok"] and done.commands == ["park"]
    assert not cio.fold(broken, pytest.fail)["ok"] and broken.commands == ["park"]


def test_a_second_held_fold_reports_failure():
    cell = Parks({"ok": False, "contact": True}, {"ok": False, "contact": True})
    assert not cio.fold(cell, lambda s: None)["ok"] and cell.commands == ["park", "park"]


def test_a_pivot_folds_again_when_the_stop_also_held_the_first_fold(tmp_path, monkeypatch):
    class Stalled:
        def __init__(self):
            self.commands, self.parks = [], 0

        def act(self, command):
            self.commands.append(command)
            if command == "goto above_pick":
                return {"ok": False, "contact": True}
            if command == "park":
                self.parks += 1
                return {"ok": self.parks == 2, "contact": self.parks == 1}
            return {"ok": True}

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, a, b, path: path))
    cell, config = Stalled(), {"plan": {"approach_m": 0.04}, "sites": {"s": {"z": 0.1}}, "coarse": {"z": 0.1}}
    result = cell_pivot.pivot_calibrate(cell, config, (0.1, 0.0), [-40], {"sites": {"s": {"homography": [], "z_view": 0.1}}},
                                        "s", tmp_path, lambda s: None, lambda row: None)
    assert result["result"] == "stopped" and cell.commands[-2:] == ["park", "park"]


def test_a_site_with_map_from_shares_the_arms_map_and_a_fitted_map_is_kept():
    pallet, own = {"homography": "pallet"}, {"homography": "own"}
    config = {"sites": {"pallet": {}, "strip": {"map_from": "pallet"}, "kept": {"map_from": "pallet"}}}
    calibration = {"schema": "x", "sites": {"pallet": pallet, "kept": own}}
    shared = cell_pivot.with_site_maps(config, calibration)
    assert shared["sites"]["strip"] is pallet and shared["sites"]["kept"] is own and shared["schema"] == "x"
    assert "strip" not in calibration["sites"]  # the file's own map record is not touched


def test_map_from_a_site_without_a_map_is_refused():
    with pytest.raises(SystemExit, match="no map"):
        cell_pivot.with_site_maps({"sites": {"strip": {"map_from": "pallet"}}}, {"sites": {}})


def test_a_shallow_grip_stated_by_the_site_sets_both_the_pick_and_the_release_height(tmp_path, monkeypatch):
    config = {"plan": {"approach_m": 0.04}, "params": WIDE,
              "sites": {"ship": {"surface_z": -0.0167, "yaw_deg": 0.0, "grasp_depth_m": 0.0083},
                        "table": {"surface_z": -0.0197, "yaw_deg": -90.0, "place_dz": 0.002}}}
    monkeypatch.setattr(auto.cp, "write_library", lambda cfg, pick, place, path: path)
    _, pick, place, *_ = auto.plan_pick(config, "ship", "table", (0.068, -0.112), OBJECT, ENTRY, 0, (0, 0), tmp_path)
    assert pick["z"] == pytest.approx(0.0074)  # reachable at r 0.12: the default 15 mm grip is under the arm's floor
    assert place["z"] == pytest.approx(0.0064)  # 24.1 mm grip over the box's bottom, table -19.7, 2 mm drop


def test_a_site_without_its_own_depth_keeps_the_default_grip(tmp_path, monkeypatch):
    config = {"plan": {"approach_m": 0.04}, "params": WIDE, "sites": {"s": {"surface_z": -0.01, "yaw_deg": 0.0}}}
    monkeypatch.setattr(auto.cp, "write_library", lambda cfg, pick, place, path: path)
    _, pick, *_ = auto.plan_pick(config, "s", "s", (0.1, 0.0), OBJECT, ENTRY, 0, (0, 0), tmp_path)
    assert pick["z"] == pytest.approx(-0.01 + 0.0324 - 0.015)


def view():
    """A packed row of three boxes on a plain deck, as the top camera shows it."""
    frame = np.full((480, 640, 3), 170, np.uint8)
    for x in (300, 340, 380):
        cv2.rectangle(frame, (x, 200), (x + 30, 300), (30, 90, 220), -1)
    return frame


ROI, BASE_PX, TARGET_PX = (285, 185, 425, 420), (200, 230), (315, 250)


def test_a_box_pushed_outside_the_arms_corridor_stops_the_hover():
    pushed = view()
    cv2.rectangle(pushed, (380, 200), (410, 300), (170, 170, 170), -1)  # the far box left its place
    cv2.rectangle(pushed, (415, 200), (424, 300), (30, 90, 220), -1)
    answer = cell_scene_guard.hook(types.SimpleNamespace(frame=lambda name: pushed), {}, view(), ROI, BASE_PX, TARGET_PX)()
    assert answer["verdict"] == "refuse" and answer["moved"] and "scene changed" in answer["why"]


def test_the_arm_in_its_corridor_and_a_brightness_shift_pass():
    frame = np.clip(view().astype(int) + 25, 0, 255).astype(np.uint8)
    cv2.circle(frame, TARGET_PX, 60, (20, 20, 20), -1)  # the wrist over the target
    cv2.line(frame, BASE_PX, TARGET_PX, (20, 20, 20), 40)  # the link
    answer = cell_scene_guard.hook(types.SimpleNamespace(frame=lambda name: frame), {}, view(), ROI, BASE_PX, TARGET_PX)()
    assert answer["verdict"] == "pass" and answer["total_mm"] == 0.0


def test_a_guard_without_a_corridor_does_not_let_the_carry_go_on():
    cell = types.SimpleNamespace(frame=lambda name: pytest.fail("nothing to compare"))
    assert cell_scene_guard.hook(cell, {}, view(), ROI, None, TARGET_PX)()["verdict"] == "refuse"


def test_a_guard_refusal_stops_the_chain_before_the_hook_that_reopens_the_jaws():
    later = types.SimpleNamespace(calls=0)

    def reach():
        later.calls += 1
        return {"verdict": "pass"}

    out = cell_reach.chain(lambda: {"verdict": "refuse", "why": "scene changed"}, reach)()
    assert out["verdict"] == "refuse" and later.calls == 0


@pytest.mark.parametrize("angle", [0.0, 90.0, 35.0])
def test_the_changed_pixels_give_the_axis_the_jaws_opened_along(angle):
    closed, opened = np.zeros((480, 640, 3), np.uint8), np.zeros((480, 640, 3), np.uint8)
    u = np.radians(angle)
    for side in (-1, 1):  # each finger moved 40 px out along the axis
        cv2.circle(opened, (int(320 + side * 40 * np.cos(u)), int(240 + side * 40 * np.sin(u))), 12, (255, 255, 255), -1)
    axis = cell_jaw_axis.changed_axis_px(closed, opened, (320, 240), 90, None)
    assert abs(cell_jaw_axis.wrap90(axis - angle)) < 3


def test_a_round_change_has_no_axis():
    closed, opened = np.zeros((480, 640, 3), np.uint8), np.zeros((480, 640, 3), np.uint8)
    cv2.circle(opened, (320, 240), 30, (255, 255, 255), -1)
    assert cell_jaw_axis.changed_axis_px(closed, opened, (320, 240), 90, None) is None


def test_image_axis_goes_through_the_map_so_a_mirrored_camera_is_right():
    mirrored = lambda p: (p[1] / 1000, -p[0] / 1000)  # image x = arm -y, as on this cell
    assert abs(cell_jaw_axis.wrap90(cell_jaw_axis.to_arm_axis(0.0, (320, 240), mirrored) - 90.0)) < 1e-6


def test_two_yaws_must_agree_on_the_offset():
    agree = [{"offset_deg": 88.0}, {"offset_deg": -89.0}]  # mod 180 these are 3 degrees apart
    assert abs(cell_jaw_axis.wrap90(cell_jaw_axis.agreed_offset(agree) - 89.5)) < 1.0
    assert cell_jaw_axis.agreed_offset([{"offset_deg": 90.0}]) is None
    assert cell_jaw_axis.agreed_offset([{"offset_deg": 0.0}, {"offset_deg": 90.0}]) is None


def test_a_grasp_by_the_ends_needs_the_measured_axis_and_others_keep_the_ledger():
    across_width = {"grasp": {"jaw_axis_deg_from_long": 90}}
    assert cell_jaw_axis.offset_for({}, across_width, 0) == (0, None)
    assert cell_jaw_axis.offset_for({}, ENTRY, 0)[0] is None and "measure" in cell_jaw_axis.offset_for({}, ENTRY, 0)[1]
    assert cell_jaw_axis.offset_for({"closing_axis_offset_deg": 90.0}, ENTRY, 0) == (90.0, None)


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"schema": "x", "objects": [dict(ENTRY)]}))
    return path


def test_a_declared_bound_is_a_payload_that_says_it_was_not_weighed(catalog):
    assert cell_scale.main(["declare", "--catalog", str(catalog), "--object", ENTRY["id"], "--kg", "0.016", "--by", "user"]) == 0
    objects = json.loads(catalog.read_text())["objects"]
    payload = cell_objects.payload(objects, ENTRY["id"])
    assert payload["kg"] == 0.016 and "not weighed" in payload["source"] and objects[0]["mass_declared"]["by"] == "user"


def test_a_reading_replaces_a_declaration_and_a_declaration_never_replaces_a_reading(catalog):
    cell_scale.declare(catalog, ENTRY["id"], 0.016, "user")
    cell_scale.enrol(catalog, ENTRY["id"], 0.0151, "15.1 g")
    objects = json.loads(catalog.read_text())["objects"]
    assert "mass_declared" not in objects[0] and "not weighed" not in cell_objects.payload(objects, ENTRY["id"])["source"]
    with pytest.raises(SystemExit, match="was weighed"):
        cell_scale.declare(catalog, ENTRY["id"], 0.016, "user")


@pytest.mark.parametrize("kg", [0, -0.1, 1.5])
def test_an_implausible_or_unknown_declaration_is_refused(catalog, kg):
    with pytest.raises(SystemExit):
        cell_scale.declare(catalog, ENTRY["id"], kg, "user")
    with pytest.raises(SystemExit, match="unknown object"):
        cell_scale.declare(catalog, "nothing", 0.016, "user")
