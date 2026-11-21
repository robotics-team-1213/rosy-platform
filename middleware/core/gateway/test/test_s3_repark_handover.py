"""Detached bench for the exact Nav2-to-S3 correction handover."""

from types import SimpleNamespace

import pytest

from core.bridge.cmd_vel import cmd_vel_cycle

from core_api_web.api.deps import Mode
from test_localization_mission import OPERATOR, VIEWER, _state, core  # noqa: F401
from test_motion_repark import _run
from test_navigation_handover import request
from test_station_return_handover import terminal_navigation


PATH = "/api/v1/motion/repark/run"
GRID = "occupancy:0123456789ab"


@pytest.mark.parametrize("case", ["forward", "reverse", "wrong_nav", "wrong_grid", "stale_idle", "forged_idle"])
def test_named_stop_handover_precedes_motion(core, case):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    services.state.set_map_id("robot-grid", GRID)
    backend = terminal_navigation(services)
    prior = request(services)
    handover = client.post("/api/v1/navigation/handover", headers=OPERATOR,
                           json=dict(prior, expected_map_grid_id=GRID))
    assert handover.status_code == 200, handover.text
    repark_owner = client.get(PATH, headers=VIEWER).json()["owner"]
    delta = -0.04 if case == "reverse" else 0.04
    command = dict(forward_m=delta, left_m=0, operator_name="sim", correlation_id="S3-correction",
                   expected_boot_id=repark_owner["boot_id"],
                   expected_owner_generation=repark_owner["owner_generation"],
                   expected_idle_epoch=handover.json()["idle_mode_epoch"], expected_map_grid_id=GRID,
                   expected_nav_run_id=prior["run_id"], expected_nav_generation=prior["expected_owner_generation"],
                   expected_nav_correlation_id=prior["correlation_id"])
    if case == "wrong_nav":
        command["expected_nav_correlation_id"] = "unrelated-navigation"
    elif case == "wrong_grid":
        services.state.set_map_id("robot-grid", "occupancy:fedcba987654")
    elif case in ("stale_idle", "forged_idle"):
        services.modes.transition(Mode.MANUAL)
        services.modes.transition(Mode.IDLE)
        if case == "forged_idle":
            command["expected_idle_epoch"] = services.modes.epoch
    reply = client.post(PATH, json=command, headers=OPERATOR)
    assert backend.canceled == 0
    if case not in ("forward", "reverse"):
        assert reply.status_code == 409, reply.text
        assert services.loc_mission.runs_started == 0
        assert services.command.select_output().linear == 0.0
        return
    assert reply.status_code == 202, reply.text
    operation = reply.json()["operation"]
    services.loc_mission.tick()
    assert services.command.select_output().linear * delta > 0
    # A zero cycle already in flight at terminal cannot witness the released mode.
    cmd_vel_cycle(services.command, services.power, lambda _: _run(services),
                  readiness=SimpleNamespace(is_ready=lambda: False))
    result = client.get(PATH, params={"correlation_id": command["correlation_id"]}, headers=VIEWER).json()
    assert result["operation"]["run_id"] == operation["run_id"]
    assert result["operation"]["result"] == "SUCCEEDED", result
    assert services.modes.mode is Mode.IDLE
    assert services.command.select_output().linear == 0.0
    owner = result["owner"]
    duplicate = client.post(PATH, headers=OPERATOR, json=dict(command,
                            expected_owner_generation=owner["owner_generation"],
                            expected_idle_epoch=services.modes.epoch))
    assert duplicate.status_code == 409 and services.loc_mission.runs_started == 1
    # An observed zero must come from an actual write after terminal admission is closed.
    assert "idle_zero_write" not in result

    def unresolved_write(_):
        raise RuntimeError("unconfirmed write")

    with pytest.raises(RuntimeError, match="unconfirmed write"):
        cmd_vel_cycle(services.command, services.power, unresolved_write)
    same_run = {"run_id": operation["run_id"]}
    assert "idle_zero_write" not in client.get(PATH, params=same_run, headers=VIEWER).json()

    output = []
    cmd_vel_cycle(services.command, services.power, output.append)
    assert len(output) == 1 and (output[0].linear, output[0].angular) == (0.0, 0.0)
    witness = client.get(PATH, params=same_run, headers=VIEWER).json()["idle_zero_write"]
    assert witness["run_id"] == operation["run_id"] and witness["mode_epoch"] == services.modes.epoch
    assert witness["observed_at"].endswith("+00:00")
    cmd_vel_cycle(services.command, services.power, output.append)
    assert client.get(PATH, params=same_run, headers=VIEWER).json()["idle_zero_write"] == witness
    assert "idle_zero_write" not in client.get(PATH, params={"correlation_id": "other"}, headers=VIEWER).json()

    services.modes.transition(Mode.MANUAL)
    services.modes.transition(Mode.IDLE)
    cmd_vel_cycle(services.command, services.power, output.append)
    assert "idle_zero_write" not in client.get(PATH, params=same_run, headers=VIEWER).json()
