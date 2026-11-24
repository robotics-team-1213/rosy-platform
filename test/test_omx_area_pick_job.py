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
    (wd / "prof.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-profile.v1",
        "top_box": {"roi": [0, 0, 100, 100]},
        "wrist_box": {},
        "reference": {},
        "home": [0, 0, 0, 0, 0],
    }), encoding="utf-8")
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


def test_arm_s_negative_x_white_jaw_and_failure_bundle(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    import cell_arm_cal
    import cell_directive_compiler as cdc

    wd, cfg_path = _make_workdir(tmp_path)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["tcp_x_m"] = 0.074
    cfg["plan"] = {"pick": {}, "place": {}, "limits": {"workspace_min_m": [-0.28, -0.28, 0.005]}}

    class _FakeCell:
        def __init__(self, io, cams):
            pass

        def frame(self, view: str):
            return np.full((32, 32, 3), 120, dtype=np.uint8)

        def act(self, cmd: str):
            return {"ok": True}

    monkeypatch.setattr(cli.cell_auto_setup, "load_config", lambda _p: cfg)
    monkeypatch.setattr(cli.cp, "FifoCell", _FakeCell)
    monkeypatch.setattr(cli.cell_preflight, "ready", lambda _f, _c: [])

    # 1) Negative-x rear floor coordinates accepted for arm_s, rejected for extreme arm_s (-0.20) and arm_b (-0.06)
    floor_argv = [
        "--arm", "arm_s", "--config", str(cfg_path),
        "--pick-area", "floor", "--pick-x", "0.044", "--pick-y", "0.156", "--pick-z", "0.021",
        "--place-area", "floor", "--place-x", "-0.06", "--place-y", "0.17", "--place-z", "0.025",
    ]
    monkeypatch.setattr(
        cli.cell_area_xyz, "plan_library_from_directive",
        lambda d, bp, work_dir=None: ({"chunks": {"above_pick": {}}}, {"pick": d["pick"], "place": d["place"]}, {"finger_color": d["execution"].get("finger_color")}),
    )
    assert cli.main([*floor_argv, "--dry-run"]) == 0
    planned = json.loads(capsys.readouterr().out)
    assert planned["result"] == "planned" and planned["finger_color"] == "white"

    too_far_back = [*floor_argv[:15], "-0.20", *floor_argv[16:], "--dry-run"]
    assert cli.main(too_far_back) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"

    arm_b_neg_x = ["--arm", "arm_b", *floor_argv[2:], "--dry-run"]
    assert cli.main(arm_b_neg_x) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "refused"

    # 2) Directive compiler honors execution.finger_color='white' without altering ARM_DEFAULTS['arm_s']
    ns = cli._parser().parse_args(floor_argv)
    directive = cli._build_directive(ns, cfg)
    assert directive["execution"]["finger_color"] == "white"
    _, cal = cdc.build_plan_from_directive(directive, cfg["plan"], work_dir=wd)
    assert cal["finger_color"] == "white"
    assert cell_arm_cal.default_profile("arm_s")["finger_color"] == "dark"

    # 3) Live non-placed exit emits a failure bundle for rosy diagnose; placed exit does not
    emitted: list[dict] = []
    monkeypatch.setattr(
        cli.cell_bundle_emit, "emit_pick_failure",
        lambda cell, config, calibration, src, dst, work, res, tried, **kw: emitted.append({"arm": config.get("arm_id"), "src": src, "dst": dst, "res": res}) or "20261124T000000Z-arm_s-stop-abc123",
    )
    monkeypatch.setattr(
        cli.cell_area_xyz, "execute_directive",
        lambda *_a, **_kw: {"result": "empty", "at": "run grasp_pick"},
    )
    assert cli.main([*floor_argv, "--commissioning", "--person-at-switch"]) == 1
    out_fail = json.loads(capsys.readouterr().out)
    assert out_fail["failure_bundle_id"] == "20261124T000000Z-arm_s-stop-abc123"
    assert len(emitted) == 1 and emitted[0]["arm"] == "arm_s" and emitted[0]["src"] == "floor"

    monkeypatch.setattr(
        cli.cell_area_xyz, "execute_directive",
        lambda *_a, **_kw: {"result": "placed", "task_verified": True},
    )
    assert cli.main([*floor_argv, "--commissioning", "--person-at-switch"]) == 0
    out_ok = json.loads(capsys.readouterr().out)
    assert "failure_bundle_id" not in out_ok and len(emitted) == 1


def test_real_load_config_white_jaw_rear_floor_and_recovery(tmp_path: Path, monkeypatch, capsys) -> None:
    import cell_area_recovery as car
    import cell_area_xyz
    import cell_auto_setup
    import cell_directive_compiler as cdc
    from omx_adapter.area_xyz import coerce_area_xyz

    wd = tmp_path / "real_work"
    wd.mkdir()
    (wd / "prof.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-profile.v1",
        "top_box": {"roi": [0, 0, 100, 100]},
        "wrist_box": {},
        "reference": {},
        "home": [0, 0, 0, 0, 0],
    }), encoding="utf-8")
    (wd / "plan.json").write_text(json.dumps({
        "pick": {}, "place": {}, "limits": {"workspace_min_m": [-0.28, -0.28, 0.005]},
    }), encoding="utf-8")
    cfg_path = wd / "cell-auto-arm-s-live.json"
    cfg_path.write_text(json.dumps({
        "arm_id": "arm_s",
        "work_dir": str(wd),
        "io": str(wd / "chunk-io-s"),
        "profile_path": str(wd / "prof.json"),
        "plan_path": str(wd / "plan.json"),
        "tcp_x_m": 0.074,
        "cameras": {"top": {}, "wrist": {}},
    }), encoding="utf-8")

    # Real load_config injects ARM_DEFAULTS['arm_s']['finger_color'] == 'dark' into config['wrist'],
    # yet raw_config + tcp_x_m >= 0.073 still resolves 'white' and coerce_area_xyz accepts x=-0.11.
    raw_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    loaded_cfg = cell_auto_setup.load_config(cfg_path)
    assert loaded_cfg["wrist"]["finger_color"] == "dark"

    rear_argv = [
        "--arm", "arm_s", "--config", str(cfg_path),
        "--pick-area", "floor", "--pick-x", "-0.11", "--pick-y", "0.13", "--pick-z", "0.021",
        "--place-area", "floor", "--place-x", "0.044", "--place-y", "0.156", "--place-z", "0.025",
        "--dry-run",
    ]
    args = cli._parser().parse_args(rear_argv)
    assert cli._check_workspace(args) is None
    directive = cli._build_directive(args, loaded_cfg, raw_config=raw_cfg)
    assert directive["execution"]["finger_color"] == "white"
    assert coerce_area_xyz(directive["pick"])["effective_xyz_m"][0] == -0.11
    _, cal = cdc.build_plan_from_directive(directive, loaded_cfg["plan"], work_dir=wd)
    assert cal["finger_color"] == "white"

    # Explicit wrist.finger_color in raw JSON file takes precedence over tcp_x_m fallback
    explicit_raw = {**raw_cfg, "wrist": {"finger_color": "dark"}}
    assert cli._resolve_finger_color("arm_s", loaded_cfg, explicit_raw) == "dark"

    # Recovery clamp preserves negative-x floor coordinates for arm_s instead of jumping to +0.055
    rec = car.diagnose_and_recover_pick(
        attempt=0,
        cur_directive={
            "arm_id": "arm_s",
            "pick": {"area": "floor", "effective_xyz_m": [-0.08, 0.13, 0.021], "col": 1, "yaw_deg": -90.0},
        },
        r_desc={"ok": False},
        r_grasp={},
        cal={"held_30mm": 54.3},
        tried_xs=[],
    )
    assert rec["recovered_pick_xyz_m"][0] < -0.05
    # Unused cell_area_xyz import ensures module compatibility with workspace change
    assert cell_area_xyz.coerce_area_xyz(directive["pick"])["effective_xyz_m"][0] == -0.11
