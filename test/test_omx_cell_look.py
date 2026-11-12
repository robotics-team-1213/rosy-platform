"""cell_look: the TCP from one jaw mark and the pivot circle; with a map whose local error is in both the jaws and the
box, one look moves the target onto the box and the next passes - no bias from elsewhere is needed."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_look  # noqa: E402
import cell_pivot  # noqa: E402

REGION = {"radius_mm": 30.0, "phase_deg": 60.0}
CLEAR = [200.0, 200.0]  # free ground each side of the box, more than the opened jaws need


def test_the_tcp_is_the_mark_minus_the_circle_radius_along_yaw_plus_phase():
    tcp, yaw = (0.10, 0.20), -77.8
    a = math.radians(yaw + REGION["phase_deg"])
    mark = (tcp[0] + 0.03 * math.cos(a), tcp[1] + 0.03 * math.sin(a))
    assert cell_look.tcp_from_mark(mark, yaw, REGION) == pytest.approx(tcp, abs=1e-9)


class Arm:
    """The arm stands `droop` short of the last loaded library's pick; the map reads everything `error` off."""

    def __init__(self, cmd, droop):
        self.cmd, self.droop, self.commands = cmd, droop, []

    @property
    def at(self):
        return self.cmd[0] + self.droop[0], self.cmd[1] + self.droop[1]

    def act(self, command):
        self.commands.append(command)
        return {"ok": True, "state": "measured", "target": "commanded"}


def test_looks_move_the_command_onto_the_box_despite_map_error_and_droop(tmp_path, monkeypatch):
    box_true, error, yaw = (0.100, 0.200), (0.012, -0.008), -77.8  # a 14 mm local map error, the pick 1 cm off
    arm = Arm((0.092, 0.206), droop=(0.0, -0.0025))  # gravity: the arm stands 2.5 mm short in y
    libraries = {}

    def write(config, pick, place, path):
        libraries[str(path)] = (pick["x"], pick["y"])
        return path

    def act(command):
        if command.startswith("load "):
            arm.cmd = libraries[command[5:]]
        return Arm.act(arm, command)

    arm.act = act
    monkeypatch.setattr(cell_pivot, "mark_jaws", lambda cell, config, sleep, near=None: (1.0, 1.0))
    monkeypatch.setattr(cell_pivot, "mark_pixel", lambda record, config, site, raw, z: (0.0, 0.0))
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda joints: (*(arm.at if joints == "measured" else arm.cmd), 0.08, yaw))

    def mark_to_arm(record, config, site, pixel, z):
        a = math.radians(yaw + REGION["phase_deg"])
        return arm.at[0] + 0.03 * math.cos(a) + error[0], arm.at[1] + 0.03 * math.sin(a) + error[1]

    monkeypatch.setattr(cell_pivot, "mark_to_arm", mark_to_arm)
    target = {"pick": {"x": 0.092, "y": 0.206, "z": 0.02, "yaw_deg": yaw}, "place": {},
              "object": {"raw_m": [box_true[0] + error[0], box_true[1] + error[1]], "mark_half_mm": CLEAR}, "bias_region": REGION}
    out = cell_look.look(arm, {"params": None}, {}, "floor", target, write, tmp_path, sleep=lambda s: None)
    assert out["verdict"] == "pass" and len(out["looks"]) == 2
    assert arm.at == pytest.approx(box_true, abs=1e-4)  # the arm, not just the command, is over the box
    assert out["looks"][0]["box_minus_tcp_mm"] == pytest.approx([8.0, -3.5], abs=0.2)
    # the hover chain records verdict, dx_mm, dy_mm, total_mm for every hook (a missing key crashed a field carry)
    assert (out["dx_mm"], out["dy_mm"]) == pytest.approx((1000 * (target["pick"]["x"] - 0.092), 1000 * (target["pick"]["y"] - 0.206)), abs=0.1)


def test_no_hook_without_a_pivot_circle_or_when_off():
    target = {"bias_region": {"bias_mm": [4.2, -2.5]}}  # carried from another site: no circle
    cal = {"sites": {"floor~coarse": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}
    assert cell_look.hook({"params": {"look.enabled": 1}, "work_dir": "."}, None, target, None, cal, "floor") is None
    assert cell_look.hook({"params": {"look.enabled": 0}, "work_dir": "."}, None, {"bias_region": REGION}, None, cal, "floor") is None
    assert cell_look.hook({"params": {"look.enabled": 1}, "work_dir": "."}, None, {"bias_region": REGION}, None, cal, "floor")


def test_the_expected_jaw_pixel_is_mark_to_arm_backwards():
    config = {"sites": {"floor": {"z": 0.021}}, "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}}}
    record = {"homography": [[0.0, -1 / 900, 0.072 + 239.5 / 900], [-1 / 900, 0.0, 0.106 + 134.5 / 900], [0, 0, 1]], "z_view": 0.08}
    raw = (0.05, 0.11)
    px = cell_pivot.mark_pixel(record, config, "floor", raw, 0.10)
    assert cell_pivot.mark_to_arm(record, config, "floor", px, 0.10) == pytest.approx(raw, abs=1e-6)


def test_an_unseen_jaw_mark_refuses_the_descent(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_pivot, "mark_jaws", lambda cell, config, sleep, near=None: None)
    monkeypatch.setattr(cell_pivot, "mark_pixel", lambda record, config, site, raw, z: (0.0, 0.0))
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda joints: (0.1, 0.2, 0.08, 0.0))
    target = {"pick": {"x": 0.1, "y": 0.2}, "place": {}, "object": {"raw_m": [0.1, 0.2], "mark_half_mm": CLEAR}, "bias_region": REGION}
    out = cell_look.look(Arm((0.1, 0.2), (0, 0)), {"params": None}, {}, "floor", target, None, tmp_path, sleep=lambda s: None)
    assert out["verdict"] == "refuse" and "not seen" in out["why"]


def dense_row():
    """arm_b 2026-11-03: four 30 mm boxes 6 mm apart (1 px per mm), the second one the target; jaws close along x."""
    import cell_finger_room as fr

    mask = np.zeros((200, 300), np.uint8)
    px = lambda p: (150 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000)  # noqa: E731
    for centre in (-36, 0, 36, 72):
        mask[55:146, 150 + centre - 15:150 + centre + 15] = 255
    box = {"raw_m": [0.0, 0.1], "width_mm": 30, "length_mm": 90, "long_axis_deg": 90.0}
    room = fr.jaw_margin(fr.own_removed(mask, (0, 0, 300, 200), px, box), (0, 0, 300, 200), px, box, None,
                         {"auto.finger_mm": 2.0})  # the field value of arm_b's jaws
    return mask, px, box, room


class Mute:
    """A cell that must see no jaw command and no look: any act or mark is a failure."""

    def act(self, command):
        raise AssertionError(f"the arm was commanded: {command}")


def test_jaws_never_open_for_the_mark_among_neighbours_within_the_opened_width(tmp_path, monkeypatch):
    import cell_finger_room as fr

    _, _, box, room = dense_row()
    assert room["margin_mm"] is not None  # the pick itself fits, opened to its box width plus a small margin
    need = fr.mark_half_gap_mm() + 14.0  # 62 opens about 131 mm: 65.5 each side of the centre, plus the map's error
    assert max(room["mark_half_mm"]) < need - 40  # the neighbours stand 21 mm from the centre
    monkeypatch.setattr(cell_pivot, "mark_jaws", lambda *a, **k: pytest.fail("jaws opened among the boxes"))
    target = {"pick": {"x": 0.0, "y": 0.1}, "place": {}, "object": dict(box, mark_half_mm=room["mark_half_mm"]), "bias_region": REGION}
    refused = cell_look.look(Mute(), {"params": None}, {}, "pallet", target, None, tmp_path)
    assert refused["verdict"] == "refuse" and "no room" in refused["why"] and refused["looks"] == []
    # with a wrist hook behind it the look steps aside and the chain goes on measuring; still no jaw moved
    skipped = cell_look.look(Mute(), {"params": None}, {}, "pallet", target, None, tmp_path, fallback=True)
    assert skipped["verdict"] == "skipped" and (skipped["dx_mm"], skipped["dy_mm"]) == (0.0, 0.0)
    # no measurement of the room at all is no room (a push without a mask, an old object row)
    target["object"].pop("mark_half_mm")
    assert cell_look.look(Mute(), {"params": None}, {}, "pallet", target, None, tmp_path)["verdict"] == "refuse"


def test_the_mark_room_is_free_only_when_the_whole_opened_gap_is_free_and_inside_the_map():
    import cell_finger_room as fr

    mask, px, box, room = dense_row()
    clear = np.zeros_like(mask)
    free = fr.jaw_margin(clear, (0, 0, 300, 200), px, box)["mark_half_mm"]
    assert min(free) >= fr.mark_half_gap_mm() + 14.0 - 0.05  # nothing within reach: the jaws may open
    # a neighbour 70 mm out (past the 65.5 of the gap, inside it with the map's error): not enough
    clear[55:146, 150 - 85:150 - 70] = 255
    assert min(fr.jaw_margin(clear, (0, 0, 300, 200), px, box)["mark_half_mm"]) < fr.mark_half_gap_mm() + 14.0
    # a box too near the edge of what the camera view covers: past it is unknown, not free
    edge = fr.jaw_margin(np.zeros((200, 300), np.uint8), (0, 0, 300, 200), lambda p: (60 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000), box)
    assert min(edge["mark_half_mm"]) < 60


def test_pick_hooks_skips_crowded_look_when_reach_and_calibrated_bias_region_already_measure_position(monkeypatch):
    import cell_hooks
    import cell_reach

    monkeypatch.setattr(cell_reach, "hook", lambda *a, **k: (lambda: {"verdict": "pass", "dx_mm": -1.1, "dy_mm": 0.2, "total_mm": 1.1}))
    cal = {"sites": {"pallet~coarse": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}
    cfg = {"params": {"look.enabled": 1, "reach.enabled": 1}, "plan": {"grip_open": 56}, "work_dir": "."}
    crowded_obj = {"raw_m": [0.1269, -0.1082], "mark_half_mm": [24.3, 20.3], "width_mm": 30.0, "length_mm": 90.0}
    target_ok = {"pick": {"x": 0.1269, "y": -0.1082, "yaw_deg": 0.0}, "place": {}, "object": crowded_obj, "entry": crowded_obj,
                 "bias_region": {"radius_mm": 0.0, "phase_deg": 0.0, "rms_mm": 0.4}}
    wrist_ok, _, _, _ = cell_hooks.pick_hooks(cfg, Mute(), target_ok, None, "pallet", "pallet-l1", calibration=cal)
    res_ok = wrist_ok()
    assert res_ok["verdict"] == "skipped" and res_ok["hooks"][0]["verdict"] == "pass" and res_ok["hooks"][-1]["verdict"] == "skipped"

    target_uncal = dict(target_ok, bias_region={"radius_mm": 30.0, "phase_deg": 60.0, "rms_mm": 8.5})
    wrist_uncal, _, _, _ = cell_hooks.pick_hooks(cfg, Mute(), target_uncal, None, "pallet", "pallet-l1", calibration=cal)
    assert wrist_uncal()["verdict"] == "refuse"


def test_settled_state_averages_three_samples_when_jitter_shaking(monkeypatch):
    import joint_jitter

    class ShakyLookArm:
        def __init__(self):
            self.rows = [
                {"ok": True, "state": [10.0, -20.0, 30.0, 40.0, 50.0, 56.0], "target": [10.0, -20.0, 30.0, 40.0, 50.0, 56.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [13.0, -23.0, 30.0, 40.0, 50.0, 56.0], "target": [10.0, -20.0, 30.0, 40.0, 50.0, 56.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [7.0, -17.0, 30.0, 40.0, 50.0, 56.0], "target": [10.0, -20.0, 30.0, 40.0, 50.0, 56.0], "jitter": {"shaking": False}},
            ]

        def act(self, cmd):
            assert cmd == "state"
            return self.rows.pop(0)

    out = joint_jitter.settled_state(ShakyLookArm())
    assert out["samples"] == 3
    assert out["state"][:2] == pytest.approx([10.0, -20.0])


def test_pivot_calibrate_uses_settled_state_when_shaking(tmp_path, monkeypatch):
    class ShakyPivotArm:
        def __init__(self):
            self.commands = []
            self.state_idx = 0

        def act(self, cmd):
            self.commands.append(cmd)
            if cmd == "state":
                self.state_idx += 1
                # Oscillates +3 / -3 / 0 around [10, -20, 30, 40, 50, 56]
                delta = (3.0, -3.0, 0.0)[(self.state_idx - 1) % 3]
                return {"ok": True, "state": [10.0 + delta, -20.0 - delta, 30.0, 40.0, 50.0, 56.0], "jitter": {"shaking": True}}
            return {"ok": True, "state": [0.0] * 6}

    seen_states = []
    monkeypatch.setattr(cell_pivot, "write_library", lambda *a, **k: tmp_path / "p.json", raising=False)
    import cell_pipeline as cp
    monkeypatch.setattr(cp, "write_library", lambda *a, **k: tmp_path / "p.json")
    monkeypatch.setattr(cell_pivot, "mark_jaws", lambda *a, **k: (320.0, 240.0))
    monkeypatch.setattr(cell_pivot, "mark_to_arm", lambda *a, **k: (0.12, 0.15))
    monkeypatch.setattr(cell_pivot, "fold", lambda *a, **k: None)
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda state, *a, **k: seen_states.append(list(state[:2])) or (0.10, 0.15, 0.08, 0.0))

    cfg = {
        "plan": {"approach_m": 0.03, "home": [0.0] * 5},
        "coarse": {"z_view": 0.08},
        "sites": {"floor": {"z": 0.0, "surface_z": 0.0}},
        "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}},
        "pivot": {"geometry": {"radius_mm": 20.0, "phase_deg": 0.0}},
    }
    cal = {"sites": {"floor~coarse": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}
    res = cell_pivot.pivot_calibrate(ShakyPivotArm(), cfg, (0.10, 0.15), [0.0, 45.0], cal, "floor", tmp_path, sleep=lambda _: None, log=lambda _: None)
    assert res["result"] == "calibrated"
    assert len(seen_states) == 2
    assert seen_states[0] == pytest.approx([10.0, -20.0])
    assert seen_states[1] == pytest.approx([10.0, -20.0])


