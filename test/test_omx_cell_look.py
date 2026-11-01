"""cell_look: the TCP from one jaw mark and the pivot circle; with a map whose local error is in both the jaws and the
box, one look moves the target onto the box and the next passes - no bias from elsewhere is needed."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_look  # noqa: E402
import cell_pivot  # noqa: E402

REGION = {"radius_mm": 30.0, "phase_deg": 60.0}


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
              "object": {"raw_m": [box_true[0] + error[0], box_true[1] + error[1]]}, "bias_region": REGION}
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
    target = {"pick": {"x": 0.1, "y": 0.2}, "place": {}, "object": {"raw_m": [0.1, 0.2]}, "bias_region": REGION}
    out = cell_look.look(Arm((0.1, 0.2), (0, 0)), {"params": None}, {}, "floor", target, None, tmp_path, sleep=lambda s: None)
    assert out["verdict"] == "refuse" and "not seen" in out["why"]
