"""Unit tests for guarded `area_xyz_pick` job spec, D-911 commissioning, AMR-bed blocks, and `cell_area_pick_cli`."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "robot" / "omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_area_pick_cli as cli  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_job_spec as spec  # noqa: E402


def _make_workdir(tmp_path: Path) -> tuple[Path, Path]:
    wd = tmp_path / "work"
    wd.mkdir()
    (wd / "cell-auto-arm-s-live.json").write_text(json.dumps({
        "arm_id": "arm_s",
        "work_dir": str(wd),
        "io": str(wd / "io"),
        "profile_path": str(wd / "prof.json"),
        "plan_path": str(wd / "plan.json"),
        "cameras": {
            "top": {"profile_path": str(wd / "prof.json")},
            "wrist": {"profile_path": str(wd / "prof.json")},
        },
    }), encoding="utf-8")
    (wd / "prof.json").write_text("{}", encoding="utf-8")
    (wd / "plan.json").write_text("{}", encoding="utf-8")
    return wd, wd / "cell-auto-arm-s-live.json"


def _base_params(config_name: str = "cell-auto-arm-s-live.json") -> dict:
    return {
        "arm": "arm_s",
        "config": config_name,
        "pick_area": "belt",
        "pick_x": 0.126,
        "pick_y": -0.136,
        "pick_z": 0.052,
        "place_area": "floor",
        "place_x": 0.08,
        "place_y": 0.14,
        "place_z": 0.045,
    }


def test_area_xyz_pick_job_spec_guards_dry_run_and_amr_bed(tmp_path: Path) -> None:
    wd, _ = _make_workdir(tmp_path)
    job = spec.JOBS["area_xyz_pick"]

    # 1) dry_run does not move the arm, allows machine token and pinky observation
    dry_params = {**_base_params(), "pick_area": "pinky", "dry_run": True}
    assert spec.moves_arm(job, dry_params) is False
    eff, auth_err = guards.authorize_principal(
        "area_xyz_pick", job, dry_params, guards.Principal(guards.ROLE_MACHINE, "rosy-cli"), moves_arm_fn=spec.moves_arm,
    )
    assert auth_err is None
    argv_dry = spec.build_argv(job, eff, wd)
    assert argv_dry[:4] == ["bash", "-c", spec.ENV + spec.PY, "cell_area_pick_cli.py"]
    assert "--dry-run" in argv_dry

    # 2) real move blocks ROLE_MACHINE (D-911), requires person_at_switch, blocks proposer == operator
    live_params = {**_base_params(), "operator": "seriggg", "proposer": "agent"}
    assert spec.moves_arm(job, live_params) is True
    _, machine_err = guards.authorize_principal(
        "area_xyz_pick", job, live_params, guards.Principal(guards.ROLE_MACHINE, "rosy-cli"), moves_arm_fn=spec.moves_arm,
    )
    assert machine_err and machine_err["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"

    with pytest.raises(ValueError, match="person_at_switch"):
        spec.build_argv(job, live_params, wd)
    with pytest.raises(ValueError, match="operator must differ from proposer"):
        spec.build_argv(job, {**live_params, "proposer": "Seriggg", "person_at_switch": True}, wd)

    # 3) AMR bed pick_area / place_area blocked on real move
    with pytest.raises(ValueError, match="AMR bed motion requires R cell-task"):
        spec.build_argv(job, {**live_params, "pick_area": "pinky", "person_at_switch": True}, wd)
    with pytest.raises(ValueError, match="AMR bed motion requires R cell-task"):
        spec.build_argv(job, {**live_params, "place_area": "pinky", "person_at_switch": True}, wd)

    # 4) Valid live arm_s argv wraps with with-session-arm-s-live.sh and forwards flags
    argv_live = spec.build_argv(
        job,
        {**live_params, "person_at_switch": True, "pick_yaw_deg": -75.0, "max_attempts": 3, "stay_in_hover": True},
        wd,
    )
    assert argv_live[0] == "./with-session-arm-s-live.sh"
    assert "--stay-in-hover" in argv_live and "--commissioning" in argv_live and "--person-at-switch" in argv_live
    assert "--pick-yaw-deg" in argv_live and "-75.0" in argv_live


def test_cell_area_pick_cli_dry_run_refusals_and_live_closed_loop(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    wd, cfg_path = _make_workdir(tmp_path)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["plan"] = {"pick": {}, "place": {}}

    class _FakeCell:
        def __init__(self, io, cams):
            self.cmds = []

        def frame(self, view: str):
            return np.full((32, 32, 3), 120, dtype=np.uint8)

        def act(self, cmd: str):
            self.cmds.append(cmd)
            return {"ok": True}

    monkeypatch.setattr(cli.cell_auto_setup, "load_config", lambda _p: cfg)
    monkeypatch.setattr(cli.cp, "FifoCell", _FakeCell)
    monkeypatch.setattr(cli.cell_preflight, "ready", lambda _f, _c: [])

    base_argv = [
        "--arm", "arm_s", "--config", str(cfg_path),
        "--pick-area", "belt", "--pick-x", "0.126", "--pick-y", "-0.136", "--pick-z", "0.052",
        "--place-area", "floor", "--place-x", "0.08", "--place-y", "0.14", "--place-z", "0.045",
    ]

    # 1) --dry-run plans and disables side_zone_snap when arm_s has no side camera
    monkeypatch.setattr(
        cli.cell_area_xyz, "plan_library_from_directive",
        lambda d, bp, work_dir=None: ({"chunks": {"above_pick": {}, "descend_pick": {}}}, {"pick": d["pick"], "place": d["place"]}, {}),
    )
    assert cli.main([*base_argv, "--dry-run"]) == 0
    out_plan = json.loads(capsys.readouterr().out)
    assert out_plan["result"] == "planned"
    assert out_plan["vision_refine"] is True and out_plan["side_zone_snap"] is False

    # 2) Workspace refusal
    bad_ws = [
        "--arm", "arm_s", "--config", str(cfg_path),
        "--pick-area", "belt", "--pick-x", "0.40", "--pick-y", "0.0", "--pick-z", "0.05",
        "--place-area", "floor", "--place-x", "0.08", "--place-y", "0.14", "--place-z", "0.045",
        "--dry-run",
    ]
    assert cli.main(bad_ws) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"

    # 3) Camera dark refusal
    monkeypatch.setattr(cli.cell_preflight, "ready", lambda _f, _c: ["top frame missing"])
    assert cli.main([*base_argv, "--dry-run"]) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"
    monkeypatch.setattr(cli.cell_preflight, "ready", lambda _f, _c: [])

    # 4) Live without commissioning flags refused
    assert cli.main(base_argv) == 1
    assert "person-at-switch" in json.loads(capsys.readouterr().out)["error"]

    # 5) Live with execute_directive passes frame_fn("side") -> None and respects stay_in_hover
    captured = {}

    def _fake_exec(directive, *, base_plan, work_dir, act_fn, frame_fn, max_attempts):
        captured["directive"] = directive
        captured["side"] = frame_fn("side")
        captured["wrist_shape"] = frame_fn("wrist").shape
        captured["max_attempts"] = max_attempts
        return {"result": "placed", "task_verified": True}

    monkeypatch.setattr(cli.cell_area_xyz, "execute_directive", _fake_exec)
    assert cli.main([
        *base_argv, "--stay-in-hover", "--max-attempts", "3",
        "--commissioning", "--person-at-switch", "--operator", "seriggg", "--proposer", "agent",
    ]) == 0
    out_live = json.loads(capsys.readouterr().out)
    assert out_live["result"] == "placed" and out_live["operator"] == "seriggg"
    assert captured["side"] is None and captured["wrist_shape"] == (32, 32, 3)
    assert captured["directive"]["execution"]["stay_in_hover"] is True and captured["max_attempts"] == 3

    # 6) Cross-arm config mismatch refused before preflight/motion
    assert cli.main(["--arm", "arm_a", *base_argv[2:], "--dry-run"]) == 1
    out_arm_err = json.loads(capsys.readouterr().out)
    assert out_arm_err["result"] == "refused" and "disagrees" in out_arm_err["error"]

    # 7) ValueError inside execute_directive returns structured JSON refusal (e.g. out-of-range z)
    def _bad_z(*_a, **_kw):
        raise ValueError("pick z=0.3 outside [0.005, 0.145]")

    monkeypatch.setattr(cli.cell_area_xyz, "execute_directive", _bad_z)
    assert cli.main([*base_argv, "--commissioning", "--person-at-switch"]) == 1
    out_z_err = json.loads(capsys.readouterr().out)
    assert out_z_err["result"] == "refused" and "0.3" in out_z_err["error"]
