from types import SimpleNamespace

import pytest

from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_runtime import ControlUnitConfig
from fleet.server.control_unit_stop_runtime import validate_control_stop_owners


def configuration(resources):
    return ControlUnitConfig("R", ControlUnitTopology.from_mapping({"revision": "v1", "units": [
        {"id": "R", "resources": resources}, {"id": "A", "parent": "R", "resources": ["robot:a"]},
    ]}), {})


def test_typed_stop_binds_all_console_devices_to_direct_owner():
    cfg = configuration(["robot:r", "workcell:cell", "signal:crossing"])
    signals = SimpleNamespace(snapshot=lambda: {"crossing": {"endpoint": "private"}})
    assert validate_control_stop_owners(cfg, console=SimpleNamespace(robot_ids=["r"]),
        configured_omx={"cell": "local-instance"}, signals=signals) == ("crossing",)


@pytest.mark.parametrize("roster,omx,signals,code", [
    (["r", "a"], {}, None, "ROBOT_OWNER_MISMATCH"),
    ([], {}, None, "ROBOT_OWNER_MISMATCH"),
    (["r"], {"foreign": "omx"}, None, "OMX_OWNER_MISMATCH"),
    (["r"], {}, SimpleNamespace(snapshot=lambda: {"foreign": {}}), "SIGNAL_OWNER_MISMATCH"),
])
def test_typed_stop_refuses_undeclared_or_foreign_console_device(roster, omx, signals, code):
    cfg = configuration(["robot:r"])
    with pytest.raises(ValueError, match=code):
        validate_control_stop_owners(cfg, console=SimpleNamespace(robot_ids=roster),
                                     configured_omx=omx, signals=signals)


def test_duplicate_workcell_or_signal_owner_is_rejected_by_existing_topology():
    for resource in ["workcell:cell", "signal:crossing"]:
        with pytest.raises(ValueError, match="DUPLICATE_CONTROL_UNIT_OWNERSHIP"):
            ControlUnitTopology.from_mapping({"revision": "v1", "units": [
                {"id": "R", "resources": [resource]},
                {"id": "A", "parent": "R", "resources": [resource]},
            ]})


@pytest.mark.parametrize("kind,code", [
    ("robot", "ROBOT_OWNER_MISMATCH"), ("omx", "OMX_OWNER_MISMATCH"),
    ("signal", "SIGNAL_OWNER_MISMATCH"),
])
def test_real_app_installs_owner_checks_before_accepting_typed_stop(tmp_path, kind, code):
    from hashlib import sha256
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    from test_control_unit_runtime import config_file

    roster = ["a1", "b"] if kind == "robot" else ["a1"]
    signal = SimpleNamespace(snapshot=lambda: {"foreign": {}}) if kind == "signal" else None
    console = FleetConsole([RobotEndpoint(rid, "http://" + rid + ".invalid", "device-token") for rid in roster],
                            [FakeRobot(rid) for rid in roster], signal_console=signal)
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids={"a1"})
    users = {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
             for token, identity, role in [
                 ("human-token", "operator-a1", "operator"),
                 ("parent-token", "control-unit:A", "service")
             ]}
    with pytest.raises(ValueError, match=code):
        create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False,
                   omx_instances={"foreign": "instance"} if kind == "omx" else None,
                   control_unit_config=config_file(tmp_path))
