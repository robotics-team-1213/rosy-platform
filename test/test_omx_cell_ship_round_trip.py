"""What the 2026-11-06 ship round trip on arm_b needed: a wrist roll that holds in free air refuses the plan before any
motion, a fold held on the strain of the stop is retried, new table sites share the arm's map, a shallow grip keeps the
box level at the release, and a person's weight bound stays apart from a reading."""
import json
import math
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
    import cell_auto_setup
    import cell_choices
    import cell_jaw_axis
    import cell_objects
    import cell_pipeline_io as cio
    import cell_pivot
    import cell_reach
    import cell_scale
    import cell_scene_guard
    import grasp_planner as gp
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
    cell, config = Stalled(), {"plan": {"approach_m": 0.04}, "sites": {"s": {"z": 0.1}}, "coarse": {"z_view": 0.1}}
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


@pytest.mark.parametrize("bias", [[29.6, 0.0], [float("nan"), 0.0], [0.0, float("inf")], [True, 0.0], [1.0]])
def test_invalid_saved_and_in_memory_bias_is_refused_instead_of_using_zero(tmp_path, bias):
    region = {"site": "ship", "point_m": [0.12, 0.015], "bias_mm": bias}
    data = {"schema": cell_pivot.SCHEMA, "regions": [region]}
    path = tmp_path / "map.bias.json"
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    with pytest.raises(ValueError, match="bias refused"):
        cell_pivot.load_bias(path)
    with pytest.raises(ValueError, match="bias refused"):
        cell_pivot.bias_at(data, "ship", OBJECT["raw_m"])
    with pytest.raises(ValueError, match="bias refused"):
        auto.self_calibrate(None, {}, {}, tmp_path / "map.json", "ship", OBJECT["raw_m"], [], tmp_path,
                            data, None, None)
    with pytest.raises(ValueError, match="bias refused"):
        cell_pivot.save_bias(path, region)
    assert path.read_bytes() == original


def test_bias_boundary_and_the_active_bound_apply_to_read_write_and_lookup(tmp_path):
    path = tmp_path / "map.bias.json"
    region = {"site": "ship", "point_m": OBJECT["raw_m"], "bias_mm": [15.0, 20.0]}
    cell_pivot.save_bias(path, region)
    assert cell_pivot.bias_at(cell_pivot.load_bias(path), "ship", OBJECT["raw_m"]) == region
    tight = {"pivot.max_bias_mm": 24.9}
    with pytest.raises(ValueError, match="pivot.max_bias_mm"):
        cell_pivot.load_bias(path, tight)
    region["bias_mm"] = [29.6, 0.0]
    measured = {"pivot.max_bias_mm": 30.0}
    cell_pivot.save_bias(path, region, measured)
    assert cell_pivot.bias_at(cell_pivot.load_bias(path, measured), "ship", OBJECT["raw_m"], params=measured) == region


def test_invalid_bias_cannot_reach_the_pick_coordinate_planner(tmp_path, monkeypatch):
    monkeypatch.setattr(auto.cp, "write_library", lambda *a: pytest.fail("invalid bias reached the planner"))
    with pytest.raises(ValueError, match="pivot.max_bias_mm"):
        auto.plan_pick({}, "ship", "table", (0.0, 0.0), OBJECT, ENTRY, 0, (29.6, 0.0), tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("seen", [[29.6, 0.0], [float("nan"), 0.0]])
def test_a_nearby_place_does_not_teach_an_invalid_absolute_bias(tmp_path, seen):
    path = tmp_path / "map.json"
    # Both pass the old distance-only rule against the last 24 mm correction.
    verify = {"found": True, "seen_bias_mm": seen, "used_bias_mm": [24.0, 0.0]}
    assert auto.learn_bias({}, path, "ship", OBJECT["raw_m"], verify) is None
    assert not cell_pivot.bias_path(path).exists()


def test_nonfinite_region_position_cannot_hide_a_bias_from_lookup():
    data = {"regions": [{"site": "ship", "point_m": [float("nan"), 0.0], "bias_mm": [1.0, 0.0]}]}
    with pytest.raises(ValueError, match="point_m"):
        cell_pivot.bias_at(data, "ship", OBJECT["raw_m"])


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


def test_a_box_pushed_past_the_target_stops_the_hover():
    pushed = view()
    cv2.rectangle(pushed, (380, 200), (410, 300), (170, 170, 170), -1)  # the far box left its place
    cv2.rectangle(pushed, (415, 200), (424, 300), (30, 90, 220), -1)
    answer = cell_scene_guard.hook(types.SimpleNamespace(frame=lambda name: pushed), {}, view(), ROI, BASE_PX, TARGET_PX)()
    assert answer["verdict"] == "refuse" and answer["moved"] and "scene changed" in answer["why"]


def test_the_arm_short_of_the_target_side_and_a_brightness_shift_pass():
    frame = np.clip(view().astype(int) + 25, 0, 255).astype(np.uint8)
    cv2.circle(frame, TARGET_PX, 60, (20, 20, 20), -1)  # the wrist over the target
    cv2.line(frame, BASE_PX, TARGET_PX, (20, 20, 20), 40)  # the link
    answer = cell_scene_guard.hook(types.SimpleNamespace(frame=lambda name: frame), {}, view(), ROI, BASE_PX, TARGET_PX)()
    assert answer["verdict"] == "pass" and answer["total_mm"] == 0.0


def test_a_guard_without_a_base_pixel_does_not_let_the_carry_go_on():
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


def test_the_jaw_axis_tool_refuses_without_a_person_and_hands_load_config_a_path(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="D-911"):
        cell_jaw_axis.main(["--config", "x.json", "--site", "s", "--point", "0,0", "--yaw", "-40"])
    config = {"calibration_path": str(tmp_path / "cal.json"), "io": str(tmp_path), "cameras": {}, "work_dir": str(tmp_path), "sites": {}}
    (tmp_path / "cal.json").write_text(json.dumps({"schema": "rosy.omx-cell-calibration.v1", "sites": {}}))
    path = tmp_path / "cell.json"
    path.write_text("{}")
    monkeypatch.setattr(cell_auto_setup,
                        "load_config", lambda p: (p.read_text(), config)[1])
    monkeypatch.setattr(cell_jaw_axis, "measure", lambda *a, **k: {"result": "measured"})
    argv = ["--config", str(path), "--site", "s", "--point", "0.07,-0.06", "--yaw", "-40", "-80", "--commissioning", "--person-at-switch"]
    assert cell_jaw_axis.main(argv) == 0


class Jaws:
    """A runner with jaws that open along tool yaw + `true_offset`, seen from above with arm mm = image px."""

    def __init__(self, true_offset):
        self.true_offset, self.grip, self.yaw, self.commands = true_offset, 50.0, 0.0, []

    def act(self, command):
        self.commands.append(command)
        if command.startswith("load "):
            self.yaw = json.loads(Path(command.split(" ", 1)[1]).read_text())["yaw"]
        if command.startswith("grip "):
            self.grip = float(command.split()[1])
        return {"ok": True, "state": [self.yaw, 0, 0, 0, 0, self.grip]}

    def frame(self, camera):
        img = np.full((480, 640, 3), 200, np.uint8)
        u, gap = np.radians(self.yaw + self.true_offset), 10 + 3 * (self.grip - 50)
        for side in (-1, 1):
            cv2.circle(img, (int(320 + side * gap * np.cos(u)), int(240 + side * gap * np.sin(u))), 9, (20, 20, 20), -1)
        return img


@pytest.mark.parametrize("true_offset", [90.0, 0.0])
def test_measure_finds_the_real_axis_at_every_yaw_and_folds(tmp_path, monkeypatch, true_offset):
    def write(config, pick, place, path):
        path.write_text(json.dumps({"yaw": pick["yaw_deg"]}))
        return path

    monkeypatch.setattr(auto.cp, "write_library", write)
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda state: (0.1, 0.0, 0.1, state[0]))
    monkeypatch.setattr(cell_pivot, "mark_pixel", lambda *a: (320, 240))
    monkeypatch.setattr(cell_pivot, "mark_to_arm", lambda record, config, site, p, z: (p[0] / 1000, p[1] / 1000))
    cell = Jaws(true_offset)
    config = {"plan": {"approach_m": 0.04, "grip_open": 62.0}, "coarse": {"z_view": 0.1}, "sites": {"s": {"z": 0.1}}}
    result = cell_jaw_axis.measure(cell, config, {"sites": {"s": {"homography": []}}}, "s", (0.1, 0.0), [-90.0, -75.0], tmp_path,
                                   lambda s: None, lambda row: None)
    assert result["result"] == "measured", result
    assert abs(cell_jaw_axis.wrap90(result["closing_axis_offset_deg"] - true_offset)) < 6
    assert cell.commands[-1] == "park"


def test_measure_stops_and_folds_when_the_arm_refuses_to_go():
    class Refuses(Jaws):
        def act(self, command):
            status = super().act(command)
            return {"ok": False, "contact": True} if command == "goto above_pick" else status

    def write(config, pick, place, path):
        path.write_text(json.dumps({"yaw": pick["yaw_deg"]}))
        return path

    cell, pause = Refuses(90.0), []
    original, auto.cp.write_library = auto.cp.write_library, write
    try:
        config = {"plan": {"approach_m": 0.04}, "coarse": {"z_view": 0.1}, "sites": {"s": {"z": 0.1}}}
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            result = cell_jaw_axis.measure(cell, config, {"sites": {"s": {"homography": []}}}, "s", (0.1, 0.0), [-90.0], Path(folder), pause.append)
    finally:
        auto.cp.write_library = original
    assert result["result"] == "not agreed" and result["rows"] == [{"yaw": -90.0, "stopped": "goto above_pick"}]
    assert cell.commands[-1] == "park"


GEOMETRY = {"radius_mm": 16.7, "phase_deg": -86.1, "measured": "2026-11-06"}


def marks_at(centre, yaws, geometry=GEOMETRY):
    r, phase = geometry["radius_mm"] / 1000, geometry["phase_deg"]
    return [(centre[0] + r * math.cos(math.radians(y + phase)), centre[1] + r * math.sin(math.radians(y + phase))) for y in yaws]


def test_a_known_geometry_finds_the_centre_over_a_narrow_arc():
    yaws = [-105.0, -95.0, -85.0]
    tcps = [(0.07, -0.1, 0.1, y) for y in yaws]
    result = cell_pivot.known_geometry_bias(marks_at((0.08, -0.09), yaws), tcps, GEOMETRY, "s", {"homography": []})
    assert result["result"] == "calibrated" and result["bias"]["bias_mm"] == pytest.approx([10.0, 10.0], abs=0.1)
    assert result["bias"]["n"] == 3 and result["bias"]["geometry_from"] == "2026-11-06"


def test_marks_that_disagree_are_refused_not_averaged():
    yaws = [-105.0, -85.0]
    marks = marks_at((0.08, -0.09), yaws)
    marks[1] = (marks[1][0] + 0.03, marks[1][1])
    result = cell_pivot.known_geometry_bias(marks, [(0.07, -0.1, 0.1, y) for y in yaws], GEOMETRY, "s", {"homography": []})
    assert result["result"].startswith("marks disagree")


def test_one_mark_or_a_bias_past_the_cap_is_refused_with_a_known_geometry():
    tcp = [(0.07, -0.1, 0.1, -90.0)]
    assert "need 2" in cell_pivot.known_geometry_bias(marks_at((0.08, -0.09), [-90.0]), tcp, GEOMETRY, "s", {})["result"]
    yaws = [-95.0, -85.0]
    far = cell_pivot.known_geometry_bias(marks_at((0.12, -0.09), yaws), [(0.07, -0.1, 0.1, y) for y in yaws], GEOMETRY, "s", {"homography": []})
    assert far["result"].startswith("bias refused")


def jaw_frames(sides):
    closed, opened = np.full((480, 640, 3), 200, np.uint8), np.full((480, 640, 3), 200, np.uint8)
    for x, y in sides:
        cv2.rectangle(opened, (x - 8, y - 12), (x + 8, y + 12), (20, 20, 20), -1)
    return closed, opened


def test_the_mark_is_the_middle_of_both_sides_of_the_jaws():
    (cx, cy, _), = cell_pivot.jaw_centre(*jaw_frames([(243, 322), (321, 316)]))
    assert (cx, cy) == pytest.approx((282, 319), abs=1)


def test_one_side_or_two_blobs_too_far_apart_give_no_mark():
    assert cell_pivot.jaw_centre(*jaw_frames([(297, 267)])) == []
    assert cell_pivot.jaw_centre(*jaw_frames([(200, 300), (420, 300)])) == []


def test_the_centre_mark_does_not_flip_with_the_larger_side(tmp_path):
    big = jaw_frames([(243, 322), (321, 316)])
    cv2.rectangle(big[1], (230, 300), (256, 340), (20, 20, 20), -1)
    (cx, _, _), = cell_pivot.jaw_centre(*big)
    assert abs(cx - 282) < 4


def test_mark_jaws_uses_the_centre_only_when_the_config_asks(monkeypatch):
    frames = iter(jaw_frames([(243, 322), (321, 316)]) * 6)
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(grip_to=lambda cell, value: True))
    monkeypatch.setattr(cell_pivot, "settled_frame", lambda *a, **k: next(frames))
    config = {"plan": {}, "jaw_mark": {"centre": True}}
    assert cell_pivot.mark_jaws(None, config, lambda s: None) == pytest.approx((282, 319), abs=1)


def test_a_known_geometry_bias_passes_the_check_that_guards_its_saving(tmp_path):
    yaws = [-105.0, -95.0]
    result = cell_pivot.known_geometry_bias(marks_at((0.08, -0.09), yaws), [(0.07, -0.1, 0.1, y) for y in yaws], GEOMETRY, "s", {"homography": []})
    path = tmp_path / "x.bias.json"
    cell_pivot.save_bias(path, result["bias"], None)
    assert cell_pivot.load_bias(path, None)["regions"][0]["bias_mm"] == pytest.approx([10.0, 10.0], abs=0.1)


def test_an_outcome_on_the_measured_axis_is_recorded_not_raised(tmp_path):
    choices = cell_choices.Choices(tmp_path / "choices.json")
    cell_jaw_axis.offer_measured({"closing_axis_offset_deg": 85.5}, choices, auto.CLOSING)
    cell_jaw_axis.offer_measured({}, choices, auto.CLOSING)
    choices.outcome(auto.CLOSING, 85.5, False, "contact")
    assert [c["value"] for c in choices.data["values"][auto.CLOSING]] == [85.5]


def test_descend_guard_frac_really_slows_the_descent_and_only_it():
    cfg = {"plan": json.loads((OMX / "grasp-plan.example.json").read_text())}
    point = dict(x=0.12, y=0.02, z=0.03, yaw_deg=0.0)

    def library(plan):
        return gp.Planner(dict(plan, pick=point, place=point, keep_out=None)).library()["chunks"]

    # 0.30, not 0.42: 90ba3fd74f floors slow-motion acceleration (eased 0.75), so 0.42 now slows only 1.48x
    normal, slow = library(cfg["plan"]), library(dict(cfg["plan"], descend_guard_frac=0.30))
    assert len(slow["descend_pick"]) > 1.5 * len(normal["descend_pick"])
    assert slow["descend_pick"][-1][:5] == pytest.approx(normal["descend_pick"][-1][:5], abs=0.01)
    assert len(slow["lift_pick"]) == len(normal["lift_pick"])


def test_lift_guard_frac_really_slows_the_lift_and_only_it():
    plan = json.loads((OMX / "grasp-plan.example.json").read_text())
    point = dict(x=0.12, y=0.02, z=0.03, yaw_deg=0.0)

    def library(p):
        return gp.Planner(dict(p, pick=point, place=point, keep_out=None)).library()["chunks"]

    normal, slow = library(plan), library(dict(plan, lift_guard_frac=0.42))
    assert len(slow["lift_pick"]) > 1.5 * len(normal["lift_pick"])
    assert slow["lift_pick"][-1][:5] == pytest.approx(normal["lift_pick"][-1][:5], abs=0.01)
    assert len(slow["descend_pick"]) == len(normal["descend_pick"])


def test_what_the_finger_mask_does_not_cover_is_not_room():
    px = lambda p: (100 + p[0] * 1000, 100 + p[1] * 1000)  # 1 px per mm
    box = {"raw_m": [0.0, 0.0], "long_axis_deg": 0.0, "width_mm": 30.0, "length_mm": 90.0}
    wide = np.zeros((200, 200), np.uint8)
    assert auto.finger_room(wide, (0, 0, 200, 200), px, box)["margin_mm"] is not None
    tight = np.zeros((40, 200), np.uint8)  # the roi stops 5 mm past the box on both sides: nothing is known beyond it
    assert auto.finger_room(tight, (0, 80, 200, 120), px, box)["margin_mm"] is None


def test_a_site_can_grip_a_box_off_its_centre(monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    cell = types.SimpleNamespace(frame=lambda name: frame)
    box = {"centre_mm": [60.0, -140.0], "matched": True}
    monkeypatch.setattr(auto.cell_objects, "detect", lambda *a: [dict(box)])
    monkeypatch.setattr(auto.cell_objects, "foreground", lambda *a, **k: np.zeros((10, 10), np.uint8))
    monkeypatch.setattr(auto.cell_objects, "colour_mask", lambda *a: np.zeros((10, 10), np.uint8))
    monkeypatch.setattr(auto.cell_pivot, "map_record", lambda c, s: {"homography": []})
    monkeypatch.setattr(auto.cd, "see", lambda *a: None)
    monkeypatch.setattr(auto, "keep", lambda *a: None)
    config = {"cameras": {"top": {}}, "sites": {"s": {"surface_z": 0.0, "grip_offset_m": [0.0, -0.033]}}}
    _, _, objects, _ = auto.observe(cell, config, {}, "s", (0, 0, 10, 10), [])
    assert objects[0]["raw_m"] == pytest.approx([0.06, -0.173])
    del config["sites"]["s"]["grip_offset_m"]
    assert auto.observe(cell, config, {}, "s", (0, 0, 10, 10), [])[2][0]["raw_m"] == pytest.approx([0.06, -0.14])
