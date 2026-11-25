"""cell_surface: a touch probe's contact hold is the surface; no contact or a refusal never gives a height."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_surface as cs  # noqa: E402
import chunk_runner  # noqa: E402

PLAN = json.loads((ROOT / "deploy/robot/omx/grasp-plan.example.json").read_text())


class Scripted:
    def __init__(self, answers=None):
        self.answers, self.sent = answers or {}, []

    def act(self, command):
        self.sent.append(command)
        return self.answers.get(command, {"ok": True})


def test_contact_hold_is_the_surface_then_it_backs_out_and_folds():
    cell = Scripted({"run descend_probe": {"ok": False, "contact": True, "state": [1, 2, 3, 4, 5, 46.6]}})
    out = cs.touch(cell, Path("lib.json"), fk=lambda state: 0.0412)
    assert out["result"] == "touched" and out["surface_z"] == 0.0412
    assert cell.sent[-2:] == ["retreat", "park"]


def test_no_contact_or_refusal_gives_no_height_and_parks():
    out = cs.touch(Scripted(), Path("lib.json"), fk=lambda s: 1 / 0)
    assert out["result"] == "no contact" and "surface_z" not in out
    cell = Scripted({"goto above_probe": {"ok": False, "error": "unknown chunk"}})
    out = cs.touch(cell, Path("lib.json"), fk=lambda s: 1 / 0)
    assert out["result"] == "refused" and cell.sent[-1] == "park"


def test_probe_library_loads_in_the_runner_and_only_descends(tmp_path):
    lib = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01)
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(lib))
    loaded = chunk_runner.load_library(path)
    down = loaded["chunks"]["descend_probe"]
    assert len(down) >= 700 and all(f[5] == PLAN["grip_closed"] for f in down)  # 3 mm/s without retime speedup, jaws closed
    assert cs.fk_z(down[-1]) < cs.fk_z(down[0]) - 0.079  # straight down by the clamped 80 mm range
    assert loaded["chunks"]["above_probe"] == [down[0]]


def test_approach_contact_does_not_record_a_surface():
    cell = Scripted({"goto above_probe": {"ok": False, "contact": True}})
    result = cs.touch(cell, Path("lib.json"), fk=lambda state: 1 / 0)
    assert result["result"] == "refused" and "surface_z" not in result
    assert cell.sent[-2:] == ["retreat", "park"] and "run descend_probe" not in cell.sent


def test_reuse_repeated_contact_only_with_its_original_setup(tmp_path):
    from cell_route_surface import contact_evidence

    site = "tmp-b-2-l1"
    cfg = {"arm_id": "arm_b", "tcp_x_m": 0.074, "plan": PLAN, "work_dir": str(tmp_path),
           "calibration_path": str(tmp_path / "cal.json"),
           "sites": {site: {"place": [0.15, 0.0], "yaw_deg": -14.4}}}
    cal = {"reference_top_sha256": "a" * 64, "reference_map_sha": "b" * 12, "reference_geometry_sha": "c" * 12}
    Path(cfg["calibration_path"]).write_text(json.dumps(cal))
    state = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01, tcp_x_m=0.074)["chunks"]["descend_probe"][-1]
    cell = Scripted({"run descend_probe": {"ok": False, "contact": True, "state": state}})
    cs.run_surface_step(cell, cfg, f"surface {site}", tmp_path)
    assert contact_evidence(cfg, site, cal)["status"] == "matched_contact"
    assert contact_evidence(cfg, site, dict(cal, reference_map_sha="d" * 12))["status"] == "candidate"
    assert contact_evidence(dict(cfg, tcp_x_m=0.088), site, cal)["status"] == "candidate"
    cfg["sites"][site]["place"][0] += 0.01
    assert contact_evidence(cfg, site, cal)["status"] == "candidate"


def test_touch_and_probe_library_apply_configured_tcp_x_m():
    lib_stock = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01)
    lib_v21 = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01, tcp_x_m=0.074)
    state = lib_v21["chunks"]["descend_probe"][-1]
    assert lib_v21["chunks"]["descend_probe"][0] != lib_stock["chunks"]["descend_probe"][0]
    cell = Scripted({"run descend_probe": {"ok": False, "contact": True, "state": state}})
    z_stock = cs.touch(cell, Path("lib.json"))["surface_z"]
    z_v21 = cs.touch(cell, Path("lib.json"), tcp_x_m=0.074)["surface_z"]
    assert abs((z_v21 - z_stock) - 0.0179) < 0.002


def test_validated_probe_z_to_envelope_low_zones_and_cli_check(tmp_path, capsys):
    plan_with_low = {**PLAN, "limits": {**PLAN["limits"], "low_zones": [{"x": [0.05, 0.25], "y": [-0.15, 0.15], "z_min_m": -0.10}]}}
    cfg = {"plan": plan_with_low}
    assert cs.validated_probe_z_to(cfg, {"place": [0.15, 0.0], "probe_z_to_m": -0.09}) == (-0.09, None)
    assert cs.validated_probe_z_to(cfg, {"place": [0.15, 0.0], "probe_z_to_m": -0.11})[0] is None
    assert cs.validated_probe_z_to(cfg, {"place": [0.15, 0.0], "probe_z_to_m": -0.13})[0] is None
    assert cs.validated_probe_z_to(cfg, {"place": [0.15, 0.0], "probe_z_to_m": 0.10})[0] is None

    plan_path, cfg_path = tmp_path / "plan.json", tmp_path / "cfg.json"
    plan_path.write_text(json.dumps(plan_with_low))
    cfg_path.write_text(json.dumps({
        "plan_path": str(plan_path), "work_dir": str(tmp_path), "io": str(tmp_path), "cameras": {},
        "tcp_x_m": 0.074, "sites": {"ship": {"place": [0.15, 0.0], "yaw_deg": 0.0}},
    }))
    assert cs.main(["--config", str(cfg_path), "--site", "ship", "--z-to", "-0.11", "--commissioning", "--person-at-switch"]) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"


def test_touch_repeat_2_checks_spread_and_run_surface_step_resolves_tcp(tmp_path):
    class TwoTouchCell:
        def __init__(self, zs):
            self.zs, self.sent = list(zs), []

        def act(self, command):
            self.sent.append(command)
            if command == "run descend_probe":
                return {"ok": False, "contact": True, "state": [self.zs.pop(0), 0, 0, 0, 0, 46.6]}
            return {"ok": True}

    ok_cell = TwoTouchCell([0.0410, 0.0420])
    out_ok = cs.touch(ok_cell, Path("lib.json"), fk=lambda s: s[0], repeat=2)
    assert out_ok["result"] == "touched" and out_ok["surface_z"] == 0.0415
    assert out_ok["touches_m"] == [0.041, 0.042] and out_ok["spread_mm"] == 1.0
    assert ok_cell.sent[-1] == "park" and ok_cell.sent.count("retreat") == 2

    bad_cell = TwoTouchCell([0.0400, 0.0430])
    out_bad = cs.touch(bad_cell, Path("lib.json"), fk=lambda s: s[0], repeat=2)
    assert out_bad["result"] == "unrepeatable" and out_bad["spread_mm"] == 3.0 and bad_cell.sent[-1] == "park"

    # run_surface_step resolves tcp_x_m via omx_tcp.config_tcp and repeats twice
    cfg = {"plan": {**PLAN, "tcp_x_m": 0.074}, "work_dir": str(tmp_path),
           "sites": {"belt": {"place": [0.15, 0.0], "yaw_deg": -14.4, "probe_z_to_m": 0.01}}}
    state = cs.probe_library(PLAN, 0.15, 0.0, -14.4, 0.10, 0.01, tcp_x_m=0.074)["chunks"]["descend_probe"][-1]
    res = cs.run_surface_step(Scripted({"run descend_probe": {"ok": False, "contact": True, "state": state}}), cfg, "surface belt", tmp_path)
    assert res["surface belt"] == "touched" and abs(res["surface_z"] - 0.010) < 0.002
