"""Autonomous pick and place against a simulated cell: jaws drawn with a linkage offset that rotates with the
yaw (so the pivot circle is real), a map with a known bias, an object that is held only when the hidden
closing axis matches the candidate, side faces drawn the way the top camera sees them."""
import copy
import json
import math
from pathlib import Path
import sys
import time

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_attempts
    import cell_auto_pick as auto
    import cell_calibration as cal
    import cell_choices
    import cell_decisions
    import cell_knowledge
    import cell_objects
    import cell_perception
    import cell_pivot
    import grasp_planner as gp
    import judge_seat
finally:
    sys.path.remove(str(OMX))

CONFIG = json.loads((OMX / "cell-pipeline.example.json").read_text())
CONFIG["profiles"] = {name: cell_perception.load_profile(OMX / "cell-profile.example.json") for name in CONFIG["cameras"]}
CONFIG["plan"] = json.loads((OMX / "grasp-plan.example.json").read_text())
CONFIG["pivot"] = {"points": [[0.072, 0.055]]}
CONFIG["_commissioning"] = {"person_at_switch": True}  # simulated supervised trials (D-911), not field acceptance
CONFIG["operating_conditions"] = {"installation_revision": "sim-install-1", "object_revision": "sim-object-1",
    "payload_kg": 0.05, "object_dimensions_m": [0.03, 0.03, 0.03], "environment_revision": "sim-scene-1"}
SESSION = {"scope": "simulation", "sha256": "a" * 64, "session_id": "fixture-session"}
CATALOG = cell_objects.load_catalog(OMX / "object-catalog.example.json")
CAMERA = CONFIG["cameras"]["top"]
ROI = (40, 205, 300, 420)
BIAS = (-0.0133, 0.0029)  # the map reads true + BIAS
KIN = gp.load_kinematics(None)[0]
H_CAM = CAMERA["height_m"] - (CONFIG["sites"]["pinky"]["z"] - 0.015)


def tray_pixel(x, y):
    return 134.5 - 900 * (y - 0.106), 239.5 - 900 * (x - 0.072)


def corners(o):
    u = math.radians(o["long"])
    a, b = np.array([math.cos(u), math.sin(u)]), np.array([-math.sin(u), math.cos(u)])
    return [np.array([o["x"], o["y"]]) + sa * o["length"] / 2000 * a + sb * o["width"] / 2000 * b
            for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def draw(img, o, colour=(60, 160, 60)):
    """The top face where the map reads it, plus the side faces toward the principal point (hull with the base)."""
    top = np.array([tray_pixel(*c) for c in corners(o)])
    centre = np.array(CAMERA["center_px"], float)
    base = centre + (top - centre) * (H_CAM - 0.03) / H_CAM
    hull = cv2.convexHull(np.vstack([top, base]).astype(np.float32)).astype(np.int32)
    cv2.fillPoly(img, [hull], colour)


class Cell:
    def __init__(self, objects, true_closing=0.0, temp=40):
        self.objects, self.true_closing, self.temp = [dict(o) for o in objects], true_closing, temp
        self.q, self.grip, self.library, self.held, self.commands = None, 56.0, None, None, []
        self.q = list(CONFIG["plan"]["home"])

    def fk(self):
        pose = KIN.fk([gp.norm_to_rad(v) for v in self.q[:5]])
        return pose.x, pose.y, pose.z, math.degrees(pose.yaw)

    def act(self, command):
        if command.startswith("checked "):  # Gate's form (D-911): the runner checks session and library
            _, session, _, command = command.split(" ", 3)
            assert session == SESSION["session_id"]
        self.commands.append(command)
        if command.startswith("load "):
            self.library = json.loads(Path(command.split(" ", 1)[1]).read_text())
        elif command == "goto above_pick":
            self.q = list(self.library["chunks"]["above_pick"][0][:5])
        elif command.startswith("grip "):
            self.grip = max(48.5, float(command.split()[1]))
        elif command == "state":
            return {"command": "state", "ok": True, "state": self.q[:5] + [self.grip], "t": time.time(),
                    "operating_context": dict(SESSION),
                    "health": {"temp_c": [self.temp] * 6, "pwm": [10] * 6, "current_ma": [0] * 6}}
        elif command == "park":
            self.q = list(CONFIG["plan"]["home"])
        elif command == "run grasp_pick":
            x, y, _, yaw = self.fk()
            for o in self.objects:
                across = o["long"] + 90
                closes = abs((yaw + self.true_closing - across + 90) % 180 - 90) <= 20 or o["length"] == o["width"]
                if math.dist((o["x"], o["y"]), (x, y)) < 0.006 and closes:
                    self.held = o
            return {"command": command, "ok": True, "holding": self.held is not None}
        elif command == "run release_place" and self.held is not None:
            self.held["x"], self.held["y"] = self.library["source"]["place"]["x"], self.library["source"]["place"]["y"]
            self.held = None
        return {"command": command, "ok": True}

    def frame(self, camera):
        img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
        img[40:200, 150:510] = (90, 70, 55)
        for o in self.objects:
            if o is not self.held:
                draw(img, o)
        if self.grip >= 55 and self.q != list(CONFIG["plan"]["home"]):  # the linkage shows only with the jaws open: radius 18.8 mm, 53 degrees past the FK yaw
            x, y, z, yaw = self.fk()
            a = math.radians(yaw + 53)
            mark = (x + 0.0188 * math.cos(a), y + 0.0188 * math.sin(a))
            u, v = cal.parallax(tray_pixel(*mark), CONFIG["sites"]["pinky"]["z"], z, CAMERA)
            cv2.rectangle(img, (round(u) - 12, round(v) - 12), (round(u) + 12, round(v) + 12), (20, 20, 20), -1)
        return img


def biased_map(tmp_path):
    points = [(tray_pixel(x, y), (x + BIAS[0], y + BIAS[1])) for x in (0.05, 0.072, 0.094) for y in (0.08, 0.106, 0.132)]
    path = tmp_path / "cal.json"
    cal.save(path, "pinky", {"homography": cal.fit(points).tolist(), "loo_error_mm": {"max": 0.1, "mean": 0.1}, "points": []})
    return path


def no_sleep(_):
    pass


CONT2 = {"x": 0.072, "y": 0.120, "long": 30.0, "length": 60, "width": 30}


def test_pivot_circle_recovers_the_map_bias_and_the_linkage_geometry(tmp_path):
    path = biased_map(tmp_path)
    result = cell_pivot.pivot_calibrate(Cell([]), CONFIG, (0.072, 0.055), [-148, -108, -68, -28, 12, 52], cal.load(path),
                                        "pinky", tmp_path, no_sleep, lambda row: None)
    bias = result["bias"]
    assert result["result"] == "calibrated" and bias["n"] == 6
    assert bias["bias_mm"] == pytest.approx([1000 * BIAS[0], 1000 * BIAS[1]], abs=1.0)
    assert bias["radius_mm"] == pytest.approx(18.8, abs=1.0) and bias["phase_deg"] == pytest.approx(53, abs=3)
    cell_pivot.save_bias(cell_pivot.bias_path(path), bias)
    assert cell_pivot.bias_at(cell_pivot.load_bias(cell_pivot.bias_path(path)), "pinky", (0.072, 0.120))
    assert cell_pivot.bias_at(cell_pivot.load_bias(cell_pivot.bias_path(path)), "pinky", (0.2, 0.2)) is None


def test_a_circle_outside_the_linkage_radius_is_refused_not_saved(tmp_path):
    path = biased_map(tmp_path)  # beside the Pinky body the marks gave radius 70 mm, rms 13.6 mm (2026-10-28)
    tight = dict(CONFIG, params={"pivot.radius_hi_mm": 15.0})
    result = cell_pivot.pivot_calibrate(Cell([]), tight, (0.072, 0.055), [-148, -108, -68, -28, 12, 52], cal.load(path),
                                        "pinky", tmp_path, no_sleep, lambda row: None)
    assert result["result"].startswith("circle refused") and result["bias"]["radius_mm"] == pytest.approx(18.8, abs=1.0)


def test_hidden_closing_axis_candidates_compete_and_every_attempt_is_a_row(tmp_path, monkeypatch):
    path, cell = biased_map(tmp_path), Cell([CONT2])
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1")
    choices = cell_choices.Choices(tmp_path / "choices.json")
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path, choices,
                           sleep=no_sleep, log=lambda row: None)
    assert result["result"] == "placed", json.dumps(result, default=str)[:800]
    assert choices.best(auto.CLOSING) == 0  # theory (90) was tried first, came back empty, lost to the alternative
    assert [(c["value"], c["ok"], c["tries"]) for c in choices.data["values"][auto.CLOSING]] == [(90, 0, 1), (0, 1, 1)]
    assert math.dist((CONT2["x"], CONT2["y"]), (0.060, 0.090)) > 0.02 and cell.objects[0]["x"] == pytest.approx(0.060, abs=0.006)
    assert cell.objects[0]["y"] == pytest.approx(0.090, abs=0.006)
    rows = [json.loads(line) for line in (tmp_path / "attempts.jsonl").read_text().splitlines()]
    assert [(r["outcome"], r["fail_stage"]) for r in rows] == [("failed", "grasp"), ("placed", None)]
    assert [r["auto"]["closing_axis_offset_deg"] for r in rows] == [90, 0]
    assert rows[1]["auto"]["bias_mm"] == pytest.approx([1000 * BIAS[0], 1000 * BIAS[1]], abs=1.5)
    assert rows[1]["verify"]["basis"] == "map" and rows[1]["verify"]["inside"]
    assert cell_pivot.bias_path(path).exists() and cell.commands.count("park") >= 2 and cell.commands[-1] == "park"


def test_a_square_object_does_not_compete_and_is_picked_with_the_site_yaw(tmp_path):
    path, cell = biased_map(tmp_path), Cell([{"x": 0.072, "y": 0.120, "long": 3.0, "length": 30, "width": 30}])
    choices = cell_choices.Choices(tmp_path / "choices.json")
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path, choices,
                           sleep=no_sleep, log=lambda row: None)
    assert result["result"] == "placed" and auto.CLOSING not in choices.data["values"]
    assert abs(result["attempts"][0]["plan"]["pick"]["yaw_deg"] - CONFIG["sites"]["pinky"]["yaw_deg"]) <= 10.0


def test_dry_run_only_observes_chooses_and_plans(tmp_path):
    path, cell = biased_map(tmp_path), Cell([CONT2])
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), dry_run=True)
    assert result["result"] == "planned" and cell.commands == []
    row = result["attempts"][0]
    assert row["chosen"]["closing_axis_offset_deg"] == 90 and "needs a pivot" in row["pivot_needed"]
    assert row["plan"]["pick"]["z"] == pytest.approx(0.060, abs=1e-4) and json.dumps(result, default=str)
    lib = json.loads(next(tmp_path.glob("auto-pinky-90-*.json")).read_text())  # the library opens just past 30 mm, not wide
    grip = [f[5] for f in lib["chunks"]["above_pick"]]
    assert grip[0] == pytest.approx(auto.jaw_open_for(30), abs=0.01)


def test_a_hot_motor_aborts_by_parking_and_stopping(tmp_path):
    path, cell = biased_map(tmp_path), Cell([CONT2], temp=56)
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None)
    assert result["result"].startswith("aborted: motor temperature 56") and cell.commands[-1] == "park"
    assert not any(c.startswith("run ") for c in cell.commands)


def test_a_runner_that_does_not_answer_refuses_to_start(tmp_path):
    class Dead(Cell):
        def act(self, command):
            return {"ok": False, "error": "chunk_runner is not running", "fault": "no runner"}

    path = biased_map(tmp_path)
    result = auto.run_auto(Dead([CONT2]), CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "belt", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"))
    assert result["result"] == "refused"


REAL_CAPS = {"11": {"pwm": 300}, "12": {"pwm": 600}, "13": {"pwm": 600}, "14": {"pwm": 300}, "15": {"pwm": 300}, "16": {"pwm": 300}}


def test_pwm_is_judged_against_each_joints_own_cap_and_only_when_it_stops_moving(tmp_path):
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps(REAL_CAPS))
    config, now = {"record": {"caps": str(caps)}}, [0.0]
    cell, steady = Cell([]), [0.0] * 6
    monitor = auto.Monitor(cell, config, clock=lambda: now[0])
    assert monitor.caps == [300, 600, 600, 300, 300, 300]

    def check(pwm, pos):
        cell.act = lambda command: {"command": "state", "ok": True, "state": pos,
                                    "health": {"temp_c": [40], "pwm": pwm, "current_ma": [0] * 6}}
        return monitor.check()

    for t in (0, 1, 2, 3, 10):  # lifting the held container: shoulder_lift 325 of 600 (54 %) is not a load at its cap
        now[0] = t
        assert check([40, 325, 40, 40, 40, 40], steady) is None
    for t in (20, 21, 22, 23):  # elbow at 95 % of 600 while it moves: at the cap alone is normal
        now[0] = t
        assert check([40, 40, 570, 40, 40, 40], [0, 0, 5.0 * t, 0, 0, 0]) is None
    now[0] = 30
    assert check([40, 40, 40, 285, 40, 40], steady) is None  # wrist_flex at 95 % of 300, not yet for the window
    now[0] = 31.0
    assert check([40, 40, 40, 285, 40, 40], steady) is None
    now[0] = 32.0
    assert "joint 4 PWM 285 is 95% of its cap 300" in check([40, 40, 40, 285, 40, 40], steady)
    for t in (40, 42, 50):  # jaws squeezing a held box at their cap, still: the floor->belt abort of 2026-10-28
        now[0] = t
        assert check([40, 40, 40, 40, 40, -300], steady) is None
    stale = cell.act("state")
    cell.act = lambda command: dict(stale, t=1.0)
    assert monitor.check() == "stale live state"


def test_without_a_caps_file_the_session_default_cap_is_used():
    assert auto.Monitor(Cell([]), {}).caps is None and auto.Monitor(Cell([]), {}).fallback_cap == 300


def cube_image(x, y, long=0.0):
    img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
    draw(img, {"x": x, "y": y, "long": long, "length": 30, "width": 30})
    return img


def test_a_cube_near_the_image_edge_is_measured_by_its_top_face_not_its_side_faces(tmp_path):
    path = biased_map(tmp_path)
    record = cal.load(path)["sites"]["pinky"]
    x, y = 0.040, 0.150  # far from the principal point: ~44 mm wide with the side faces
    img = cube_image(x, y)
    raw = cell_objects.to_mm(np.column_stack(np.nonzero(cell_objects.foreground(img, (0, 0, 640, 480))))[:, ::-1].astype(float),
                             record, CAMERA, 0.045 + 0.03)
    assert cell_objects.measure(raw)["length_mm"] > 36  # the side faces are in the blob
    found = cell_objects.detect(img, (0, 0, 640, 480), record, CAMERA, CATALOG, surface_z=0.045)
    assert len(found) == 1 and found[0]["object"] == "container-1"
    assert (found[0]["length_mm"], found[0]["width_mm"]) == pytest.approx((30, 30), abs=3.5)
    assert found[0]["centre_mm"] == pytest.approx([1000 * (x + BIAS[0]), 1000 * (y + BIAS[1])], abs=3.0)


def blob_image(objects):
    img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
    for o in objects:
        draw(img, o)
    return img


def test_two_side_by_side_pieces_split_but_a_tangled_cluster_is_never_a_target(tmp_path):
    record = cal.load(biased_map(tmp_path))["sites"]["pinky"]
    pair = [{"x": 0.072, "y": 0.090, "long": 0.0, "length": 60, "width": 30},
            {"x": 0.072, "y": 0.120, "long": 0.0, "length": 60, "width": 30}]
    found = cell_objects.detect(blob_image(pair), (0, 0, 640, 480), record, CAMERA, CATALOG, 0.045)
    assert [f["object"] for f in found] == ["container-2", "container-2"] and all(f.get("split_from") == 2 for f in found)
    tangled = [{"x": 0.072, "y": 0.090, "long": 0.0, "length": 60, "width": 30},  # a third cube touching at an angle
               {"x": 0.072, "y": 0.1215, "long": 0.0, "length": 30, "width": 30},
               {"x": 0.050, "y": 0.1215, "long": 25.0, "length": 30, "width": 30}]
    cluster = cell_objects.detect(blob_image(tangled), (0, 0, 640, 480), record, CAMERA, CATALOG, 0.045)
    assert cluster and not any(f["matched"] or f["grasp"] for f in cluster)  # unmatched or flagged tangled, never a target


def run_started(tmp_path, monkeypatch, cell, knowledge=None):
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    monkeypatch.setattr(cell_decisions, "RUN", dict(cell_decisions.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "r1")
    cell_decisions.start(tmp_path / "decisions.jsonl", knowledge)
    monkeypatch.setitem(auto.cp.KEEP, "dir", tmp_path / "frames")
    path = biased_map(tmp_path)
    result = auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None)
    return result, cell_decisions.read(tmp_path / "decisions.jsonl"), cell_decisions.read(tmp_path / "attempts.jsonl")


def test_every_decision_point_writes_a_row_linked_to_its_attempt(tmp_path, monkeypatch):
    result, rows, attempts = run_started(tmp_path, monkeypatch, Cell([CONT2]), str(OMX / "cell-knowledge.example.json"))
    assert result["result"] == "placed"
    assert [(r["attempt_id"][-3:], r["stage"]) for r in rows] == [
        ("001", "target"), ("001", "bias"), ("001", "target"), ("001", "closing_axis"), ("001", "failure"), ("001", "retry"),
        ("002", "target"), ("002", "bias"), ("002", "closing_axis"), ("002", "verify")]
    assert {r["attempt_id"] for r in rows} == {a["attempt_id"] for a in attempts}
    target, bias, _, closing, failure, retry = rows[:6]
    assert failure["facts"]["result"] == "empty" and failure["chosen"] == "observe_again"
    assert target["facts"]["objects"][0]["catalogue"] == "container-2" and target["chosen"]["object"] == "container-2"
    assert bias["chosen"] == "pivot circle" and rows[7]["chosen"] == "reuse saved region" and rows[7]["facts"]["region_bias_mm"]
    assert (closing["chosen"], [c["value"] for c in closing["facts"]["ledger"]]) == (90, [90, 0]) and closing["by"] == "measurement"
    assert retry["chosen"] == {"retry_with": 0} and rows[8]["chosen"] == 0
    assert rows[9]["chosen"] is True and rows[9]["facts"]["basis"] == "map"
    assert all(r["schema"] == cell_decisions.SCHEMA and r["params_sha"] and r["code"] and r["t"] for r in rows)
    assert rows[0]["knowledge_sha"] and rows[0]["knowledge_ids"]  # the knowledge this stage selected
    assert len(rows[0]["frames"]) == 1


def test_a_safety_abort_row_names_the_rule_the_value_and_the_limit(tmp_path, monkeypatch):
    result, rows, attempts = run_started(tmp_path, monkeypatch, Cell([CONT2], temp=56))
    assert result["result"].startswith("aborted") and attempts == []
    safety = [r for r in rows if r["stage"] == "safety"]
    assert len(safety) == 1 and safety[0]["facts"]["rule"] == "motor temperature"
    assert (safety[0]["facts"]["value"], safety[0]["facts"]["limit"]) == (56, 55.0) and safety[0]["chosen"] == "park and stop"
    assert [e["outcome"] for e in cell_decisions.export(rows, attempts, None) if e["input"]["stage"] == "safety"] == ["aborted"]


def test_exported_labels_follow_the_outcome_and_a_person_correction_replaces_the_row(tmp_path, monkeypatch):
    _, rows, attempts = run_started(tmp_path, monkeypatch, Cell([CONT2]))
    path = tmp_path / "decisions.jsonl"
    first_closing = next(r for r in rows if r["stage"] == "closing_axis")
    labels = {(e["attempt_id"][-3:], e["input"]["stage"]): (e["label"], e["outcome"]) for e in cell_decisions.export(rows, attempts, None)}
    assert labels[("001", "closing_axis")] == ("unvalidated", "empty")  # the empty grasp does not validate candidate 90
    assert labels[("001", "retry")][0] == "validated_by_outcome"  # the next attempt held with candidate 0
    assert labels[("002", "closing_axis")][0] == labels[("002", "verify")][0] == "validated_by_outcome"
    cell_decisions.note(path, "closing_axis", "closing is along tool x here", chosen=0, supersedes=first_closing["decision_id"])
    cell_decisions.main(["note", "--decisions", str(path), "--stage", "target", "--text", "use the upper containers"])
    out = cell_decisions.export(cell_decisions.read(path), attempts, None)
    assert first_closing["decision_id"] not in [e["decision_id"] for e in out]
    fixed = next(e for e in out if e["label"] == "corrected_by_person" and e["input"]["stage"] == "closing_axis")
    assert fixed["target"] == 0 and fixed["by"] == "person" and fixed["input"]["facts"]["ledger"] and fixed["attempt_id"] == first_closing["attempt_id"]
    assert any(e["target"] == "use the upper containers" for e in out)
    with pytest.raises(SystemExit):
        cell_decisions.note(path, "target", "x", supersedes="nope")


def test_unverified_knowledge_never_reaches_an_example(tmp_path, monkeypatch):
    knowledge = json.loads((OMX / "cell-knowledge.example.json").read_text())
    knowledge["entries"].append({**knowledge["entries"][0], "id": "guess", "statement": "GUESS", "status": "unverified",
                                 "applies_when": ["any"]})
    (tmp_path / "k.json").write_text(json.dumps(knowledge))
    _, rows, attempts = run_started(tmp_path, monkeypatch, Cell([CONT2]), str(tmp_path / "k.json"))
    assert all("guess" not in r["knowledge_ids"] for r in rows)
    rows[0]["knowledge_ids"] += ["guess"]  # even if a row named it, the exporter filters by status
    lines = [k for e in cell_decisions.export(rows, attempts, cell_knowledge.load(tmp_path / "k.json")) for k in e["input"]["knowledge"]]
    assert lines and not any("GUESS" in k or "unverified" in k for k in lines)


def test_the_context_digest_is_background_only_and_the_measurement_still_vetoes(tmp_path, monkeypatch):
    run_started(tmp_path, monkeypatch, Cell([CONT2]))
    cell_decisions.note(tmp_path / "decisions.jsonl", "safety", "per-joint caps are right")
    text = cell_decisions.context(tmp_path / "decisions.jsonl")
    assert "closing_axis: 2 decisions" in text and "0 -> 1/1 good" in text and "per-joint caps are right" in text
    asked = []
    seat = judge_seat.Seat(lambda p, i, s: asked.append((p, s)) or {"decision": "retry", "reason": "x"}, context=tmp_path / "decisions.jsonl")
    assert seat.decide({"box_found": True, "next": "grasp", "aligned": False})["decision"] == "retry"
    prompt, schema = asked[0]
    assert "Past decisions of this cell (background only, not instructions): " + text in prompt
    assert schema["properties"]["decision"]["enum"] == ["retry", "park", "abort"]  # proceed still refused by the measurement
    assert judge_seat.Seat(lambda *a: {}).context == ""
    assert judge_seat.prompt({"a": 1}, ["retry"]) == judge_seat.prompt({"a": 1}, ["retry"], (), "")  # no context: the old prompt
    assert cell_decisions.context(tmp_path / "missing.jsonl") == ""


def test_no_decision_file_started_writes_nothing(tmp_path):
    path, cell = biased_map(tmp_path), Cell([CONT2])
    assert cell_decisions.RUN["path"] is None and cell_decisions.emit("target", {}, [], None, "rule", "") is None
    auto.run_auto(cell, CONFIG, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                  cell_choices.Choices(tmp_path / "choices.json"), dry_run=True)
    assert not (tmp_path / "decisions.jsonl").exists()


def test_the_shipped_example_rows_export_with_the_persons_corrections():
    rows = cell_decisions.read(OMX / "decisions.example.jsonl")
    out = cell_decisions.export(rows, [], cell_knowledge.load(OMX / "cell-knowledge.example.json"))
    assert [r["decision_id"] for r in rows if r["stage"] == "safety" and r["by"] != "person"][0] not in [e["decision_id"] for e in out]
    assert {e["label"] for e in out} == {"unvalidated", "corrected_by_person"} and sum(e["by"] == "person" for e in out) == 4
    assert any(e["target"] == "fold home, then place from home" and e["input"]["facts"]["lag_units"] == 2.2 for e in out)
    assert any("per-joint caps" in e["reason"] and e["input"]["facts"]["rule"] == "pwm stall" for e in out)


def test_a_stop_in_transport_with_the_object_held_is_its_own_decision_point(tmp_path, monkeypatch):
    class Strain(Cell):  # the runner's strain hold at goto above_place, after a held grasp
        def act(self, command):
            if command.endswith(" goto above_place"):  # checked by the gate
                command = "goto above_place"
                self.commands.append(command)
                return {"command": command, "ok": False, "contact": True, "state": [0, 20.0, 0, 0, 0, 50],
                        "target": [0, 22.2, 0, 0, 0, 50], "error": "contact in goto above_place: a joint lagged the command by 2.2 units"}
            return super().act(command)

    result, rows, attempts = run_started(tmp_path, monkeypatch, Strain([dict(CONT2)], true_closing=90.0))
    stop = next(r for r in rows if r["stage"] == "transport_stop")
    assert stop["facts"]["holding"] is True and stop["facts"]["joint"] == 2 and stop["facts"]["lag_units"] == 2.2
    assert stop["facts"]["at"] == "goto above_place" and stop["facts"]["pwm_last_checked"] == [10] * 6
    assert "fold home, then place from home" in stop["options"]
    assert stop["chosen"] == "re-observe and pick again" and not any(r["stage"] == "retry" and r["attempt_id"] == stop["attempt_id"] for r in rows)


class Scripted:
    """A runner that answers each command from a script; anything unscripted succeeds."""

    def __init__(self, answers=None):
        self.answers, self.commands = dict(answers or {}), []

    def act(self, command):
        self.commands.append(command)
        answer = self.answers.get(command, {})
        if isinstance(answer, list):  # one answer per call, then plain success
            answer = answer.pop(0) if answer else {}
        return {"command": command, "ok": True, **answer}


def test_transport_folds_home_between_lift_and_place():
    cell = Scripted({"run grasp_pick": {"holding": True, "gripper_current_ma": 215}})
    moved = auto.transfer_folded(cell, "lib.json")
    assert moved["result"] == "placed"
    assert cell.commands[1:] == list(auto.FOLDED)
    assert cell.commands.index("park") == cell.commands.index("run lift_pick") + 1  # folded before the place leg


def test_a_stop_while_carrying_backs_out_and_reports_contact_with_the_box_in_the_jaws():
    stop = {"ok": False, "contact": True, "error": "contact in goto above_place: shoulder_lift lag rose to 2.2 units"}
    cell = Scripted({"run grasp_pick": {"holding": True}, "goto above_place": stop})
    moved = auto.transfer_folded(cell, "lib.json")
    assert moved["result"] == "contact" and moved["at"] == "goto above_place"
    assert cell.commands[-2:] == ["retreat", "park"]
    assert any(s.get("command") == "run grasp_pick" and s.get("holding") for s in moved["steps"])


def test_an_empty_grasp_lifts_and_folds_without_the_place_leg():
    cell = Scripted({"run grasp_pick": {"holding": False}})
    assert auto.transfer_folded(cell, "lib.json")["result"] == "empty"
    assert "goto above_place" not in cell.commands and cell.commands[-1] == "park"


def test_a_fold_held_by_strain_backs_off_folds_again_and_goes_on_to_place():
    strain = {"ok": False, "contact": True, "error": "contact in park: shoulder_lift lag rose to 2.2 units at PWM -500"}
    cell = Scripted({"run grasp_pick": {"holding": True}, "park": [strain]})
    moved = auto.transfer_folded(cell, "lib.json")
    assert moved["result"] == "placed"  # runs 3-4 on 2026-10-28: the second fold reached home, the place went clean
    lift = cell.commands.index("run lift_pick")
    assert cell.commands[lift + 1:lift + 5] == ["park", "retreat", "park", "goto above_place"]
    cell = Scripted({"run grasp_pick": {"holding": True}, "park": [strain, strain]})
    moved = auto.transfer_folded(cell, "lib.json")
    assert moved["result"] == "contact" and "goto above_place" not in cell.commands  # held twice: stop holding


def test_jaws_that_fold_home_on_a_box_after_the_release_are_still_holding_not_placed():
    held = {"ok": True, "state": [0, 0, 0, 0, 0, 52.7]}
    cell = Scripted({"run grasp_pick": {"holding": True}, "park": [{}, held]})
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6)
    assert moved["result"] == "still holding" and moved["jaws"] == 52.7  # Pinky tray, 2026-10-28
    empty = {"ok": True, "state": [0, 0, 0, 0, 0, 48.6]}
    cell = Scripted({"run grasp_pick": {"holding": True}, "park": [{}, empty]})
    assert auto.transfer_folded(cell, "lib.json", closed=46.6)["result"] == "placed"


def test_a_confirmed_place_teaches_the_sites_bias_and_a_far_sighting_does_not(tmp_path):
    cal = tmp_path / "calibration.json"
    config = {"params": None}
    seen = {"found": True, "inside": True, "seen_bias_mm": [20.7, -1.7], "used_bias_mm": [13.3, -2.9]}
    region = auto.learn_bias(config, cal, "pinky", (0.0376, 0.2204), seen)
    assert region["bias_mm"] == [20.7, -1.7]
    saved = json.loads(cal.with_suffix(".bias.json").read_text())["regions"]
    assert [r["site"] for r in saved] == ["pinky"] and saved[0]["point_m"] == [0.0376, 0.2204]
    far = dict(seen, seen_bias_mm=[40.0, -2.9])  # 27 mm from the bias in use: a slid box or another object
    assert auto.learn_bias(config, cal, "pinky", (0.0376, 0.2204), far) is None
    assert auto.learn_bias(config, cal, "pinky", (0.0376, 0.2204), dict(seen, found=False)) is None


def test_decision_rows_and_attempt_context_name_the_arm(tmp_path):
    import cell_attempts as ca
    import cell_decisions as cdm
    ca.start(tmp_path / "attempts.jsonl", arm_id="arm_a")
    cdm.start(tmp_path / "decisions.jsonl")
    try:
        cdm.emit("wrist_align", {"iteration": 0}, ["pass", "refuse"], "pass", "measurement", "within 3 mm")
        row = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[0])
        assert row["arm_id"] == "arm_a"  # two arms will share one cell's records
    finally:
        cdm.RUN["path"] = None
        ca.start(tmp_path / "reset.jsonl")


def test_a_strain_lifting_after_the_release_folds_without_backing_into_the_box():
    strain = {"ok": False, "contact": True, "error": "contact in lift_place: wrist_flex lag rose to 2.6 units"}
    empty = {"ok": True, "state": [0, 0, 0, 0, 0, 48.6]}
    cell = Scripted({"run grasp_pick": {"holding": True}, "run lift_place": strain, "park": [{}, empty, empty]})
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6)
    after = cell.commands[cell.commands.index("run lift_place") + 1:]
    assert "retreat" not in after and after[0] == "park" and moved["result"] == "placed"


def test_a_square_box_closes_along_the_axis_whose_finger_sides_are_clear():
    mask = np.zeros((200, 200), np.uint8)
    px = lambda p: (100 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000)  # noqa: E731  1 px per mm
    cube = {"raw_m": [0.0, 0.1], "width_mm": 30, "length_mm": 30, "long_axis_deg": 0.0}
    mask[85:116, 85:116] = 255  # the cube itself
    mask[90:110, 128:140] = 255  # a 2-cell beside it on the next surface, +x side (2026-10-29: jaws landed on it)
    # closing along x (yaw 0 + 90 -> closing 90: fingers at +-x) meets the neighbour; closing along y is clear
    assert not auto.side_clear(mask, (0, 0, 200, 200), px, cube, 8, closing_deg=0.0)
    assert auto.side_clear(mask, (0, 0, 200, 200), px, cube, 8, closing_deg=90.0)
    mask[128:140, 90:110] = 255  # and one on the +y side too: no clear axis
    assert not auto.side_clear(mask, (0, 0, 200, 200), px, cube, 8, closing_deg=90.0)


def test_a_whole_surface_in_view_is_not_a_finger_obstacle_but_a_box_is():
    mask = np.zeros((200, 300), np.uint8)
    mask[:, 200:] = 255  # the board: a surface, far larger than any container
    mask[50:80, 120:150] = 255  # a container
    kept = auto.object_sized(mask)
    assert not kept[:, 200:].any() and kept[50:80, 120:150].all()


def test_the_jaws_open_just_past_the_object_not_wide():
    assert auto.jaw_open_for(30) == pytest.approx(52.3 + 16 / 10.4, abs=0.01)  # 30 mm + 8 mm each side: ~53.8
    assert auto.jaw_open_for(200) == 56.0  # never past the measured safe opening
    assert auto.jaw_open_for(0) >= 52.8


def test_a_refused_pinch_check_lifts_and_folds_before_the_grasp():
    cell = Scripted({})
    moved = auto.transfer_folded(cell, "lib.json", pinch=lambda: {"verdict": "refuse", "why": "not between the fingers"})
    assert moved["result"] == "misaligned" and moved["at"] == "pinch"
    assert "run grasp_pick" not in cell.commands and cell.commands[-2:] == ["run lift_pick", "park"]


def _feel(tmp_path, libraries, cell=None, reach=0):
    import cell_feel

    target = {"pick": {"x": 0.0, "y": 0.2, "z": 0.02, "yaw_deg": 0.0}, "place": {"x": 0.05, "y": 0.2, "z": 0.06, "yaw_deg": 0.0}}
    write = lambda config, pick, place, path: libraries.append(pick) or str(path)  # noqa: E731
    return cell_feel.feel_hook({"work_dir": str(tmp_path), "params": {"reach.enabled": reach}}, cell, target, write)


def test_an_empty_grasp_feels_along_the_closing_axis_and_carries_what_it_finds(tmp_path):
    libraries = []
    cell = Scripted({"run grasp_pick": [{"holding": False}, {"holding": False}, {"holding": True}]})
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6, feel=_feel(tmp_path, libraries))
    assert moved["result"] == "placed"
    # closing axis = yaw + 90: the tries move along y, +12 mm then -12 mm
    assert [round(1000 * (p["y"] - 0.2)) for p in libraries] == [12, -12] and all(p["x"] == 0.0 for p in libraries)
    assert cell.commands.count("run grasp_pick") == 3


def test_a_bump_while_feeling_backs_off_and_folds(tmp_path):
    stop = {"ok": False, "contact": True}
    cell = Scripted({"run grasp_pick": [{"holding": False}], "run descend_pick": [{}, stop]})
    moved = auto.transfer_folded(cell, "lib.json", feel=_feel(tmp_path, []))
    assert moved["result"] == "contact" and moved["at"] == "feel" and cell.commands[-2:] == ["retreat", "park"]


def test_each_feel_descent_follows_the_same_reach_correction_as_the_first(tmp_path, monkeypatch):
    import cell_reach

    cell = Scripted({"run grasp_pick": [{"holding": False}, {"holding": True}]})
    corrected = []
    monkeypatch.setattr(cell_reach, "correct", lambda c, xy, replan, params: corrected.append((xy, len(cell.commands))) or {"verdict": "pass"})
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6, feel=_feel(tmp_path, [], cell, reach=1))
    assert moved["result"] == "placed" and corrected[0][0] == (0.0, 0.212)  # the shifted pick, not the first one
    assert cell.commands[corrected[0][1] - 1] == "goto above_pick" and cell.commands[corrected[0][1]] == "run descend_pick"


def test_without_a_supervised_trial_an_unreviewed_carry_is_held_before_any_motion(tmp_path, monkeypatch):
    monkeypatch.setattr(auto, "self_calibrate", lambda *a: (a[8], None))  # a bias is known: reach the gate itself
    config = {k: v for k, v in CONFIG.items() if k != "_commissioning"}
    config["operating_envelope_path"] = str(tmp_path / "missing-envelope.json")  # nothing reviewed (D-911)
    path, cell = biased_map(tmp_path), Cell([CONT2])
    result = auto.run_auto(cell, config, cal.load(path), path, CATALOG, ROI, "pinky", "0.060,0.090", tmp_path,
                           cell_choices.Choices(tmp_path / "choices.json"), sleep=no_sleep, log=lambda row: None)
    assert result["result"].startswith("held: ")
    assert not any(c.startswith(("run ", "goto ", "load ")) for c in cell.commands)


def test_the_gate_refuses_a_replan_the_review_does_not_cover(tmp_path):
    import cell_transfer

    cell = Cell([CONT2])
    gate = cell_transfer.Gate(cell, {**CONFIG}, {})
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0] * 6]}}))
    assert gate.open(lib, lambda a: None) is None and gate.assessment["mode"] == "commissioning"
    gate.config = {k: v for k, v in CONFIG.items() if k != "_commissioning"}  # the same carry, now automatic
    gate.config["operating_envelope_path"] = str(tmp_path / "missing-envelope.json")
    refused = gate.act(f"load {lib}")
    assert refused["ok"] is False and refused["error"].startswith("held: ") and not cell.commands[-1].startswith("load")


def test_two_candidates_keep_their_own_libraries(tmp_path):
    """2026-10-29: two square boxes on the floor were planned into one file; the first candidate's library held the
    second one's pick and the arm went to the wrong box."""
    path = biased_map(tmp_path)
    one = {"x": 0.080, "y": 0.120, "long": 0.0, "length": 30, "width": 30}  # two square 1-cells, offset None for both
    other = dict(one, x=0.030, y=0.090)
    _, mask, objects, error = auto.observe(Cell([one, other]), CONFIG, cal.load(path), "pinky", ROI, CATALOG)
    assert error is None and len(objects) == 2
    usable, refused = auto.choose(None, CONFIG, cal.load(path), "pinky", "pinky", (0.06, 0.09), ROI, objects, mask,
                                  CATALOG, {"regions": []}, cell_choices.Choices(tmp_path / "choices.json"), tmp_path)
    assert len(usable) == 2 and usable[0]["library"] != usable[1]["library"], refused
    for u in usable:
        lib = json.loads(Path(u["library"]).read_text())
        assert lib["source"]["pick"]["x"] == u["pick"]["x"] and lib["source"]["pick"]["y"] == u["pick"]["y"]
