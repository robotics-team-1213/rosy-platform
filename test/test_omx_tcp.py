"""The jaw TCP has one resolver: cell config, plan, environment, then a refusal (0.0885 was rejected 2026-11-08)."""
import json
import logging
from pathlib import Path
import sys

import pytest

pytest.importorskip("numpy")
pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
for _p in (OMX, Path(__file__).parents[1] / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_directive_compiler as cdc  # noqa: E402
import cell_upkeep_checks as cuc  # noqa: E402
import cell_z_shuttle as zs  # noqa: E402
import grasp_planner as gp  # noqa: E402
import multi_dof_kinematics as mdk  # noqa: E402
import omx_tcp  # noqa: E402

ENV = {omx_tcp.ENV: "0.0885"}
DIRECTIVE = {
    "schema": "rosy.omx-cell-area-xyz-directive.v1", "directive_id": "tcp", "arm_id": "arm_s",
    "pick": {"area": "pinky", "x": 0.0535, "y": 0.1720, "z": 0.0200, "yaw_deg": -85.0},
    "place": {"area": "belt", "x": 0.1250, "y": -0.0550, "z": 0.0250, "yaw_deg": -85.0},
}


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(omx_tcp.ENV, raising=False)


def base_plan(**extra):
    return dict(json.loads((OMX / "grasp-plan.example.json").read_text(encoding="utf-8")), **extra)


def test_a_missing_tcp_is_refused_never_0_0885(tmp_path):
    with pytest.raises(SystemExit, match="no jaw TCP"):
        omx_tcp.resolve_tcp(env={})
    with pytest.raises(SystemExit, match="no jaw TCP"):
        cdc.build_plan_from_directive(DIRECTIVE, base_plan(), work_dir=tmp_path)
    assert omx_tcp.resolve_tcp(default=omx_tcp.V21_JAW_TCP_M, env={}) == (0.074, "default 0.074 (measured v2.1 jaw)")


def test_the_order_is_cell_config_then_plan_then_environment():
    assert omx_tcp.resolve_tcp(0.074, 0.09, env=ENV) == (0.074, "cell config tcp_x_m")
    assert omx_tcp.resolve_tcp(None, 0.09, env=ENV) == (0.09, "plan tcp_x_m")
    assert omx_tcp.resolve_tcp(None, None, env=ENV) == (0.0885, omx_tcp.ENV)
    with pytest.raises(SystemExit, match="jaw range"):
        omx_tcp.resolve_tcp(0.3, env={})


def test_the_planner_logs_its_source_and_the_config_beats_the_environment(monkeypatch, caplog):
    monkeypatch.setenv(omx_tcp.ENV, "0.0885")
    omx_tcp._LAST.clear()
    q = [0.0, -0.3, 0.4, 1.2, 0.0]
    with caplog.at_level(logging.INFO, logger="omx.tcp"):
        from_config = gp.load_kinematics(None, 0.0740)[0].fk(q)
    assert "0.0740 m from cell config tcp_x_m" in caplog.text
    from_env = gp.load_kinematics(None)[0].fk(q)
    stock = gp.load_kinematics(None, 0.0885)[0].fk(q)
    assert from_env.x == pytest.approx(stock.x) and from_config.x != pytest.approx(stock.x)


def test_the_compiler_the_kinematics_and_the_shuttle_use_the_resolver(monkeypatch, tmp_path):
    plan, _ = cdc.build_plan_from_directive(dict(DIRECTIVE, execution={"tcp_x_m": 0.074}), base_plan(tcp_x_m=0.09), work_dir=tmp_path)
    assert plan["tcp_x_m"] == 0.074 and plan["tcp_source"] == "cell config tcp_x_m"
    plan, _ = cdc.build_plan_from_directive(DIRECTIVE, base_plan(tcp_x_m=0.09), work_dir=tmp_path)
    assert plan["tcp_source"] == "plan tcp_x_m"
    default = mdk.fk_se3([0.0, -0.3, 0.4, 1.2, 0.0], dof=5)["xyz_m"]
    assert default == mdk.fk_se3([0.0, -0.3, 0.4, 1.2, 0.0], dof=5, tcp_x_m=omx_tcp.V21_JAW_TCP_M)["xyz_m"]
    monkeypatch.setenv(omx_tcp.ENV, "0.0885")
    assert mdk.fk_se3([0.0, -0.3, 0.4, 1.2, 0.0], dof=5)["xyz_m"] != default  # the environment is honoured, not 0.0885 by default
    assert zs.DEFAULT_SHUTTLE_BASE_PLAN["tcp_x_m"] == omx_tcp.V21_JAW_TCP_M


def test_upkeep_warns_when_the_environment_and_the_config_disagree():
    row = cuc.check_tcp({"tcp_x_m": 0.074}, env=ENV)
    assert row["status"] == "warn" and "disagrees" in row["detail"]
    assert cuc.check_tcp({"tcp_x_m": 0.074}, env={omx_tcp.ENV: "0.074"})["status"] == "ok"
    assert cuc.check_tcp({"tcp_x_m": 0.074}, env={})["status"] == "ok"
