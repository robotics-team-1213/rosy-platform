"""The one-arm cell pipeline end to end against a simulated cell: the box is put back by the arm, both
surfaces are calibrated for every fixed camera, the wrist learns what aligned looks like, then A/B cycles;
the judge seat decides at each check and every non-passing check is kept as a case."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("cell_pipeline", OMX / "cell_pipeline.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import cell_attempts
    import cell_perception
    import cell_survey
    import judge_seat
finally:
    sys.path.remove(str(OMX))

PROFILE = cell_perception.load_profile(OMX / "cell-profile.example.json")
CONFIG = json.loads((OMX / "cell-pipeline.example.json").read_text())
CONFIG["profiles"] = {name: PROFILE for name in CONFIG["cameras"]}
CONFIG["plan"] = json.loads((OMX / "grasp-plan.example.json").read_text())
START = (0.072, 0.106)


def tray_pixel(x, y):  # arm metres -> top-camera pixel at the box's height: turned and mirrored, ~0.9 px/mm
    return 134.5 - 900 * (y - 0.106), 239.5 - 900 * (x - 0.072)


def belt_pixel(x, y):
    return 330 - 900 * (y - 0.0), 150 - 900 * (x - 0.150)


def rosy_tray_pixel(x, y):  # a second fixed camera, another angle, same surfaces
    return 150 + 800 * (x - 0.072) - 100 * (y - 0.106), 240 - 800 * (y - 0.106)


def rosy_belt_pixel(x, y):
    return 320 + 800 * (x - 0.150), 150 - 800 * y


class Cell:
    """A runner that obeys the chunk commands, and cameras that draw the box and jaws where they are."""

    def __init__(self, box, fail=None, slip=None, blind=(), contact=None, current=0, reach=(0.0, 0.0)):
        self.box, self.held, self.fail, self.slip, self.blind = list(box), False, fail, slip, set(blind)
        self.contact, self.current, self.reach = contact, current, reach  # reach: where the arm ends off its plan
        self.library, self.tcp, self.grip, self.commands = None, None, 56.0, []

    def act(self, command):
        self.commands.append(command)
        if command == self.fail:
            return {"command": command, "ok": False, "fault": "stalled", "error": "stalled"}
        if command == self.contact:  # once: the runner held with torque on
            self.contact = None
            return {"command": command, "ok": False, "contact": True, "fault": "contact in descend_pick",
                    "error": "contact in descend_pick: a joint lagged the command by 2.1 units"}
        if command.startswith("load "):
            self.library = json.loads(Path(command.split(" ", 1)[1]).read_text())["source"]
        elif command == "goto above_pick":
            pick = self.library["pick"]
            self.tcp = (pick["x"] + self.reach[0], pick["y"] + self.reach[1], pick["z"] + CONFIG["plan"]["approach_m"])
        elif command.startswith("grip "):
            self.grip = max(48.5, float(command.split()[1]))  # the follower jaws end at 48.5
        elif command == "state":
            return {"command": "state", "ok": True, "state": [0, 0, 0, 0, 0, self.grip],
                    "health": {"current_ma": [0, 0, 0, 0, 0, self.current]}}
        elif command == "park":
            self.tcp = None
        elif command == "run grasp_pick":
            pick = self.library["pick"]
            if self.slip:  # the box was nudged after the cameras looked
                self.box[0] += self.slip
                self.slip = None
            self.held = math.dist(self.box, (pick["x"], pick["y"])) < 0.006
            return {"command": command, "ok": True, "holding": self.held}
        elif command == "run release_place" and self.held:
            self.box, self.held = [self.library["place"]["x"], self.library["place"]["y"]], False
        return {"command": command, "ok": True}

    def frame(self, camera):
        if camera == "wrist":
            img = np.full((480, 640, 3), (200, 200, 200), np.uint8)
            if self.tcp is not None and not self.held:  # the box under the hovering jaws, offset as it is
                u = 347 + 4000 * (self.box[1] - self.tcp[1])
                v = 204 + 4000 * (self.box[0] - self.tcp[0])
                cv2.rectangle(img, (round(u) - 60, round(v) - 60), (round(u) + 60, round(v) + 60), (30, 90, 200), -1)
            return img
        img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
        img[40:200, 150:510] = (90, 70, 55)  # the belt
        if not self.held and camera not in self.blind:
            on_belt = self.box[0] > 0.12
            pixel = {("top", False): tray_pixel, ("top", True): belt_pixel,
                     ("rosy", False): rosy_tray_pixel, ("rosy", True): rosy_belt_pixel}[camera, on_belt]
            u, v = pixel(*self.box)
            colour = (127, 119, 142) if on_belt else (110, 95, 115)
            cv2.rectangle(img, (round(u) - 16, round(v) - 16), (round(u) + 16, round(v) + 16), colour, -1)
        if camera == "top" and self.tcp is not None:  # the jaws above the box, apart by the grip opening
            u, v = m.cal.parallax(tray_pixel(*self.tcp[:2]), CONFIG["sites"]["pinky"]["z"], self.tcp[2],
                                  CONFIG["cameras"]["top"])
            for side in (-1, 1):
                x = round(u + side * self.grip / 2)  # 47 -> 56 moves each finger ~4.5 px
                cv2.rectangle(img, (x - 3, round(v) - 3), (x + 3, round(v) + 3), (20, 20, 20), -1)
        return img


def quiet(row):
    pass


def test_one_run_calibrates_both_surfaces_then_cycles_and_ends_where_it_started(tmp_path):
    cell = Cell(START)
    result = m.run(cell, CONFIG, tmp_path / "cal.json", tmp_path, cycles=2, log=quiet)
    assert result["result"] == "done", json.dumps(result)[:600]
    sites = json.loads((tmp_path / "cal.json").read_text())["sites"]
    assert set(sites) == {"pinky", "belt"} and all(s["loo_error_mm"]["max"] < 3 for s in sites.values())
    assert sites["pinky"]["wrist"]["samples"] >= 5  # what aligned looks like in the wrist view
    assert math.dist(cell.box, START) < 0.004
    assert [s["episode"] for s in result["steps"] if "episode" in s] == ["A", "B", "A", "B"]
    assert not (tmp_path / "cases.jsonl").exists()


def test_a_box_off_the_start_is_put_back_by_the_arm_itself_before_calibration(tmp_path):
    cell = Cell((0.090, 0.093))  # about 2 cm off the taught pick; no map yet, and nobody moves it
    seen = []
    result = m.run(cell, CONFIG, tmp_path / "cal.json", tmp_path / "work", cycles=1, log=seen.append)
    assert result["result"] == "done", json.dumps(result)[:600]  # a work folder that does not exist yet
    homed = result["steps"][0]
    assert homed["reset"] == "pinky" and homed["result"] == "placed" and homed["start"]["ok"]
    assert sum(1 for row in seen if row.get("jaws")) >= 4  # the jaws found by the fingers opening
    assert math.dist(cell.box, START) < 0.004


def calibrated(tmp_path, config=CONFIG):
    cell = Cell(START)
    assert m.run(cell, config, tmp_path / "cal.json", tmp_path, cycles=0, log=quiet)["result"] == "done"
    return m.cal.load(tmp_path / "cal.json")


def test_a_second_fixed_camera_carries_on_when_the_top_camera_cannot_see_the_box(tmp_path):
    config = copy.deepcopy(CONFIG)
    config["cameras"]["rosy"] = {"url": "unused"}
    config["profiles"]["rosy"] = PROFILE
    calibration = calibrated(tmp_path, config)
    assert {"pinky@rosy", "belt@rosy"} <= set(calibration["sites"])
    cell = Cell((0.080, 0.100), blind={"top"})
    found = m.locate(cell, config, calibration, "pinky")
    assert found["found"] and [e["camera"] for e in found["estimates"]] == ["rosy"]
    assert math.dist(found["arm_m"], (0.080, 0.100)) < 0.003 and "top: box not seen" in found["missing"]


def test_an_empty_grasp_is_decided_by_the_seat_retried_and_kept_as_a_case(tmp_path):
    calibration = calibrated(tmp_path)
    cell = Cell((0.080, 0.100), slip=0.012)
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path)
    assert moved["result"] == "placed" and len(moved["attempts"]) == 2
    assert moved["decisions"][0]["decision"] == "retry"
    rows = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert rows[0]["facts"]["holding"] is False and rows[-1]["outcome"] == "placed"
    replay = rows[0]["scene"]  # enough for cell_cases.from_row to replay it in a simulator
    assert replay["outcome"] == "empty" and replay["place"] == "belt" and len(replay["box_m"]) == 2


def attempt_rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "attempts.jsonl").read_text().splitlines()]


def test_every_attempt_passed_or_not_is_one_row_with_its_context_and_its_case_names_it(tmp_path, monkeypatch):
    calibration = calibrated(tmp_path)
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "run1")
    moved = m.move(Cell((0.080, 0.100), slip=0.012), CONFIG, calibration, "pinky", "belt", tmp_path)
    assert moved["result"] == "placed"
    rows = attempt_rows(tmp_path)
    assert [(r["outcome"], r["fail_stage"]) for r in rows] == [("failed", "grasp"), ("placed", None)]
    assert [r["attempt_id"] for r in rows] == ["run1-001", "run1-002"]
    context = rows[0]["context"]
    assert context["calibration"]["key"] == "pinky" and context["calibration"]["coarse"] is False
    assert context["config_sha"] and context["plan_sha"]
    assert rows[0]["plan"]["pick"]["x"] == rows[0]["locate"]["arm_m"][0]  # where it reached vs where it saw
    cases = [json.loads(line) for line in (tmp_path / "cases.jsonl").read_text().splitlines()]
    assert [c["attempt_id"] for c in cases] == ["run1-001", "run1-002"]
    report = cell_attempts.summary(rows)
    assert report["attempts"] == 2 and report["placed"] == 1
    assert report["failures"] == {"grasp: empty at run grasp_pick": 1}
    assert sum(c["tried"] for c in report["by_position"].values()) == 2


def test_a_box_seen_where_no_ik_reaches_is_kept_as_a_plan_failure_not_a_crash(tmp_path, monkeypatch):
    calibration = calibrated(tmp_path)
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "run1")

    def unreachable(*args, **kwargs):
        raise SystemExit("pick: no IK solution within 1.5 mm")

    monkeypatch.setattr(m, "write_library", unreachable)
    cell = Cell((0.080, 0.100))
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path)
    assert moved["result"].startswith("stopped") and not any(c.startswith("run ") for c in cell.commands)
    rows = attempt_rows(tmp_path)
    assert {(r["fail_stage"], r["fail_class"]) for r in rows} == {("plan", "no IK for the located box")}
    assert "no IK solution" in rows[0]["plan_error"]


def test_a_bare_move_without_a_run_writes_no_attempt_file(tmp_path):
    calibration = calibrated(tmp_path)
    m.move(Cell((0.080, 0.100)), CONFIG, calibration, "pinky", "belt", tmp_path)
    assert not (tmp_path / "attempts.jsonl").exists()


def test_receipts_written_before_the_attempt_log_still_give_rows_by_position(tmp_path):
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    near = {"locate": {"found": True, "arm_m": [0.072, 0.106]}, "transfer": {"result": "placed"},
            "verify": {"inside": True}}
    far = {"locate": {"found": True, "arm_m": [0.090, 0.090]}, "transfer": {"result": "contact", "at": "run descend_pick"}}
    (receipts / "a-reset.json").write_text(json.dumps({"stage": "reset", "from": "pinky", "to": "pinky",
                                                       "attempts": [far, near]}))
    report = cell_attempts.summary(cell_attempts.from_receipts(receipts))
    assert report["by_position"] == {"pinky x70 y110 mm": {"tried": 1, "placed": 1},
                                     "pinky x90 y90 mm": {"tried": 1, "placed": 0}}
    assert report["failures"] == {"transfer: contact at run descend_pick": 1}


@pytest.mark.parametrize("reach, expected", [((0.0, 0.0), (0.0, 0.0)), ((0.006, -0.004), (6.0, -4.0))])
def test_a_survey_sees_where_the_jaws_end_over_the_box_and_never_descends(tmp_path, monkeypatch, reach, expected):
    calibration = calibrated(tmp_path)
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "attempts.jsonl", "run1")
    cell = Cell((0.080, 0.100), reach=reach)
    result = cell_survey.survey(cell, CONFIG, calibration, "pinky", tmp_path)
    assert result["result"] == "surveyed", json.dumps(result, default=str)[:400]
    assert not any(c.startswith(("run descend", "run grasp")) for c in cell.commands) and cell.commands[-1] == "park"
    assert math.dist(result["survey"]["offset_mm"], expected) < 1.5
    row = attempt_rows(tmp_path)[0]
    assert row["outcome"] == "surveyed" and row["survey"]["offset_mm"] == result["survey"]["offset_mm"]
    position = cell_attempts.summary([row])["by_position"]["pinky x80 y100 mm"]
    assert position["tried"] == 1 and position["jaw_offset_mm"] == [result["survey"]["offset_mm"]]


def test_the_arm_error_is_the_measured_joints_against_the_sent_ones_through_fk():
    sent = CONFIG["plan"]["home"][:5] + [50.0]
    row = {"transfer": {"steps": [{"command": "goto above_pick", "target": sent, "state": list(sent)}]}}
    assert cell_attempts.arm_error_mm(row) == [0.0, 0.0, 0.0]
    row["transfer"]["steps"][0]["state"] = sent[:3] + [sent[3] + 2.7] + sent[4:]  # wrist_flex ~5 degrees off
    assert math.hypot(*cell_attempts.arm_error_mm(row)) > 3
    assert cell_attempts.arm_error_mm({"transfer": {"steps": [{"command": "goto above_pick"}]}}) is None


def test_a_wrist_view_off_the_learned_hover_stops_before_the_descent(tmp_path):
    calibration = calibrated(tmp_path)
    cell = Cell((0.080, 0.100))
    real = cell.act

    def drift(command):  # the box moves after the top camera looked, before the jaws arrive above it
        if command == "goto above_pick" and len([c for c in cell.commands if c == "goto above_pick"]) == 0:
            cell.box[1] += 0.010
        return real(command)

    cell.act = drift
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path)
    first = moved["attempts"][0]["transfer"]
    assert first["result"] == "misaligned" and "run descend_pick" not in [s["command"] for s in first["steps"]]
    assert moved["decisions"][0]["facts"]["aligned"] is False and moved["result"] == "placed"


def test_a_fault_stops_at_once_and_the_seat_parks_without_asking_a_model(tmp_path):
    calibration = calibrated(tmp_path)
    asked = []
    seat = judge_seat.Seat(lambda *a: asked.append(a) or {"decision": "retry", "reason": "model"})
    cell = Cell(START, fail="run descend_pick")
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path, seat)
    assert moved["result"].startswith("stopped: park") and not asked
    assert cell.commands[-1] == "run descend_pick"  # no park after a fault: the guard owns that arm


def test_a_box_no_camera_can_see_is_never_grasped(tmp_path):
    calibration = calibrated(tmp_path)
    cell = Cell(START, blind={"top"})
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path)
    assert moved["result"].startswith("stopped: abort") and not any(c.startswith("goto") for c in cell.commands)


def test_jaws_that_stop_short_at_their_end_count_as_arrived():
    clock = [0.0]

    class Jaws:
        def act(self, command):
            return {"ok": True, "state": [0, 0, 0, 0, 0, 48.6]}  # asked 47, the jaws end at 48.6

    def sleep(seconds):
        clock[0] += seconds

    assert m.grip_to(Jaws(), 47.0, sleep=sleep, clock=lambda: clock[0])
    assert clock[0] < 2.0  # about a second of standing still, not the whole timeout


def test_taught_and_measured_start_references_compete_and_the_one_that_held_is_used(tmp_path):
    config = copy.deepcopy(CONFIG)
    profile = copy.deepcopy(PROFILE)
    profile["reference"]["top"] = {"cx": 100.0, "cy": 200.0, "yaw": 0.0}  # belongs to another plan
    config["profiles"] = {name: profile for name in config["cameras"]}
    cell = Cell(START)  # the box is at the top-down plan's start, not at the taught pixel
    result = m.run(cell, config, tmp_path / "cal.json", tmp_path, cycles=1, log=quiet)
    assert result["result"] == "done", json.dumps(result)[:600]
    values = json.loads((tmp_path / "choices.json").read_text())["values"]
    start = {tuple(c["value"]): c for c in values["pinky.start_pixel@topdown"]}
    assert start[(100.0, 200.0)]["ok"] == 0 and start[(100.0, 200.0)]["tries"] >= 1  # kept, with its record
    measured = [c for c in start.values() if c["source"].startswith("measured")]
    assert measured and measured[0]["ok"] >= 1
    closed = {c["value"]: c for c in values["gripper.closed@follower"]}
    assert closed[48.5]["ok"] >= 1 and closed[46.6]["ok"] == 0  # the jaws' own end beat the taught value


def test_grid_points_whose_box_would_overhang_the_flat_zone_are_skipped_before_the_arm_goes():
    points = [(tray_pixel(*q), q) for q in m.cal.grid(START, 0.015)]
    calibration = {"sites": {"pinky~coarse": {"homography": m.cal.fit(points).tolist()}}}
    config = copy.deepcopy(CONFIG)
    config["sites"]["pinky"].update(flat_px=[120, 200, 200, 300], box_half_px=20)
    # x 120..200 shrunk by 20: centres 140..180; the start (134.5 px) would overhang, 20 mm the other way not
    assert m.on_flat(config, calibration, "pinky", START) is False
    assert m.on_flat(config, calibration, "pinky", (0.072, 0.086)) is True
    centre = m.grid_points(config, calibration, "pinky")[4]
    assert math.dist(tray_pixel(*centre), (160, 250)) < 1.0  # the grid is centred on the flat zone
    assert m.on_flat({**config, "sites": {**config["sites"], "pinky": {**config["sites"]["pinky"], "flat_px": None}}},
                     calibration, "pinky", START) is None


def test_the_grasp_yaw_keeps_the_site_yaw_until_the_camera_turn_has_earned_it_and_is_capped_before_the_wrist_learns(tmp_path):
    import cell_choices

    choices = cell_choices.Choices(tmp_path / "choices.json")
    found = {"turn_deg": 25.0}  # 2026-10-25: a 25 degree reading put the jaws on the box's corners
    calibration = {"sites": {}}
    assert m.grasp_yaw(CONFIG, calibration, "pinky", found, choices) == ("site", -67.8)
    choices.outcome("pinky.grasp_yaw@topdown", "site", False)
    choices.outcome("pinky.grasp_yaw@topdown", "camera", True)
    assert m.grasp_yaw(CONFIG, calibration, "pinky", found, choices) == ("camera", -57.8)  # capped at 10
    calibration["sites"]["pinky"] = {"wrist": {"cx": 347, "cy": 204, "spread_px": 15}}
    assert m.grasp_yaw(CONFIG, calibration, "pinky", found, choices) == ("camera", -42.8)


def test_a_soft_contact_retreats_parks_and_the_seat_retries(tmp_path):
    calibration = calibrated(tmp_path)
    cell = Cell((0.080, 0.100), contact="run descend_pick")
    moved = m.move(cell, CONFIG, calibration, "pinky", "belt", tmp_path)
    first = moved["attempts"][0]["transfer"]
    assert first["result"] == "contact" and [s["command"] for s in first["steps"]][-2:] == ["retreat", "park"]
    assert moved["decisions"][0]["decision"] == "retry" and moved["result"] == "placed"


@pytest.mark.parametrize("current, holding", [(190, True), (20, False)])
def test_recover_lifts_clear_then_places_a_held_box_or_folds_home(tmp_path, current, holding):
    config = {**CONFIG, "recover_settle_s": 0}
    cell = Cell(START, current=current)
    assert m.recover(cell, config, "pinky", tmp_path, person_at_switch=False)["result"] == "refused"
    assert cell.commands == []  # nothing moves without a person at the switch
    result = m.recover(cell, config, "pinky", tmp_path, person_at_switch=True)
    assert result["result"] == "recovered" and result["holding"] is holding
    grip, lift = cell.commands[1], cell.commands[2]
    assert grip == ("grip 46.6" if holding else "grip 56.0") and lift.startswith("jog")
    assert ("run release_place" in cell.commands) is holding and cell.commands[-1] == "park"


def test_the_frames_a_decision_used_are_kept_with_the_receipts(tmp_path):
    calibration = calibrated(tmp_path)
    m.KEEP["dir"] = tmp_path / "frames"
    try:
        found = m.locate(Cell(START), CONFIG, calibration, "pinky")
    finally:
        m.KEEP["dir"] = None
    assert Path(found["estimates"][0]["frame"]).is_file()
