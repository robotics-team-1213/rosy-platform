"""D-785: the native OMX hardware owner starts no-goal. One ArmCommandOwner, the D-336 UDS API
with stop/recovery/readback, a disabled Action runner and an honest non-simulation identity.
The ROS runtime is a fake; no serial, torque or controller is touched."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/skill/src", "middleware/devices/omx/agent/src", "operations/processes/palletizing/src",
                 "operations/site_execution/src", "middleware/skills/api/src", "middleware/skills/manipulation/src",
                 "integrations/robots/omx/src", "middleware/devices/omx/adapter", "deploy/robot/omx"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetCellTransferGrant  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from omx_adapter.command_owner import ArmCommandConfig, ArmCommandOwner  # noqa: E402
from rosy_agent.omx_hardware_owner import (  # noqa: E402
    HARDWARE_PROFILE, HardwareOwnerSettings, build_hardware_owner,
)

FLEET_UID = 10001
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")


class FakeRuntime:
    owner_clock = "steady"

    def __init__(self, config):
        self.config = config
        self.owner = ArmCommandOwner(config, SimpleNamespace(), monotonic=lambda: 100.0,
                                     session_id="session-1")
        self.latest_joint_state = None
        self.monotonic = lambda: 100.0


def _config(**overrides):
    values = dict(
        enabled=True, workcell_id="omx_cell_a", instance_id="omx_cell_a_01", joint_names=JOINTS,
        position_limits={name: (-0.1, 0.1) for name in JOINTS}, allowed_owners=("rule_based",),
        calibration_revision="omx-a-measured-r1", max_joint_state_age_s=0.2,
        max_goal_duration_s=1.0, action_timeout_s=2.0)
    values.update(overrides)
    return ArmCommandConfig(**values)


def _settings(tmp_path, **overrides):
    tmp_path.mkdir(parents=True, exist_ok=True)
    values = dict(workcell_id="omx_cell_a", instance_id="omx_cell_a_01",
                  journal_path=tmp_path / "owner.sqlite3", socket_root=tmp_path / "run",
                  fleet_peer_uid=FLEET_UID, calibration_revision="omx-a-measured-r1")
    values.update(overrides)
    return HardwareOwnerSettings(**values)


def _build(tmp_path, config=None, runtime_cls=FakeRuntime, **settings_overrides):
    calls = {"runtime": [], "guard": 0}

    def runtime_factory(cfg):
        runtime = runtime_cls(cfg)
        calls["runtime"].append(runtime)
        return runtime

    def guard():
        calls["guard"] += 1

    owner = build_hardware_owner(
        _settings(tmp_path, **settings_overrides), config or _config(),
        runtime_factory=runtime_factory, refuse_second_owner=guard,
        fleet_fence_current=lambda epoch, generation: True)
    return owner, calls


def test_identity_is_hardware_no_goal_and_never_simulation(tmp_path):
    owner, calls = _build(tmp_path)
    assert calls["guard"] == 1 and len(calls["runtime"]) == 1
    response = owner.action_api.dispatch({"version": 2, "operation": "GetOwnerIdentity"}, peer_uid=FLEET_UID)
    reported = dict(response["identity"])
    assert len(reported.pop("journal_id")) == 36
    assert reported == {"workcell_id": "omx_cell_a", "instance_id": "omx_cell_a_01",
                        "simulation": False, "profile": HARDWARE_PROFILE, "goals_enabled": False}
    assert owner.uds_server.socket_path == tmp_path / "run" / "omx_cell_a_01" / "control.sock"


def _grant():
    now = datetime.now(timezone.utc)
    value = {
        "mission_id": "m-1", "step_id": "m-1:step-1", "action_id": "a-1", "attempt_id": "t-1",
        "request_digest": "0" * 64, "workcell_id": "omx_cell_a", "instance_id": "omx_cell_a_01",
        "action_kind": "CELL_TRANSFER", "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "1" * 64, "cell_sha256": "2" * 64,
            "step_index": 0, "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
            "home": {"x": 0.12, "y": 0.0, "z": 0.12, "yaw": 0.0},
            "pick": {"x": 0.0, "y": 0.17, "z": 0.015, "yaw": 0.0},
            "place": {"x": 0.15, "y": 0.02, "z": 0.025, "yaw": 0.0},
            "pick_approach_z": 0.06, "place_approach_z": 0.07, "carry_z": 0.11,
        },
        "capability_revision": "none", "config_revision": "none",
        "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": now, "expires_at": now + timedelta(seconds=30),
    }
    value["request_digest"] = action_grant_digest(value)
    return FleetCellTransferGrant.model_validate(value)


def test_submit_is_refused_and_journals_nothing(tmp_path):
    owner, _ = _build(tmp_path)
    response = owner.action_api.dispatch(
        {"version": 2, "operation": "SubmitAction", "grant": _grant().model_dump(mode="json")},
        peer_uid=FLEET_UID)
    assert response["status"] >= 400
    assert owner.store.get_action("a-1") is None
    assert owner.runner.enabled is False and owner.runner.phase_runner_factories == {}


def test_stop_and_owner_state_are_served_to_fleet_only(tmp_path):
    owner, _ = _build(tmp_path)
    query = {"version": 1, "operation": "GetStopState", "workcell_id": "omx_cell_a",
             "instance_id": "omx_cell_a_01"}
    assert owner.action_api.dispatch(query, peer_uid=FLEET_UID)["status"] == 200
    assert owner.action_api.dispatch(query, peer_uid=FLEET_UID + 1)["status"] == 403
    stop = dict(query, operation="StopLocal", authority_epoch=2, dispatch_generation=8,
                requested_at=datetime.now(timezone.utc).isoformat(), reason="operator")
    tripped = owner.action_api.dispatch(stop, peer_uid=FLEET_UID)
    assert tripped["status"] == 200 and tripped["snapshot"]["state"] != "OPEN"
    state = owner.action_api.dispatch({"version": 2, "operation": "GetOwnerState"}, peer_uid=FLEET_UID)
    assert state["status"] != 503


@pytest.mark.parametrize("override, message", [
    ({"workcell_id": "omx_cell_b"}, "identity"),
    ({"instance_id": "omx_cell_a_02"}, "identity"),
    ({"calibration_revision": "omx-f-gazebo-only-v1"}, "identity"),
    ({"allowed_owners": ("pilot_sim", "rule_based")}, "rule_based"),
    ({"allowed_owners": ("rule_based", "learned_policy")}, "rule_based"),
    ({"allowed_owners": ("learned_policy",)}, "rule_based"),
])
def test_owner_config_must_match_and_admit_only_rule_based(tmp_path, override, message):
    with pytest.raises(ValueError, match=message):
        _build(tmp_path, config=_config(**override))


def test_disabled_policy_is_refused_before_any_runtime(tmp_path):
    with pytest.raises(ValueError, match="enabled"):
        _build(tmp_path, config=ArmCommandConfig())


@pytest.mark.parametrize("revision", ["omx-f-gazebo-only-v1", "omx-sim-r1", "<measured>", ""])
def test_simulation_or_placeholder_calibration_is_refused(tmp_path, revision):
    with pytest.raises(ValueError, match="calibration"):
        _build(tmp_path, config=_config(calibration_revision=revision or "x"),
               calibration_revision=revision)


def test_simulation_clock_runtime_is_refused(tmp_path):
    class SimRuntime(FakeRuntime):
        owner_clock = "sim"

    with pytest.raises(RuntimeError, match="steady"):
        _build(tmp_path, runtime_cls=SimRuntime)


def test_second_owner_guard_runs_before_runtime(tmp_path):
    built = []

    def busy():
        raise RuntimeError("another arm owner process is running")

    with pytest.raises(RuntimeError, match="another arm owner"):
        build_hardware_owner(_settings(tmp_path), _config(),
                             runtime_factory=lambda cfg: built.append(cfg),
                             refuse_second_owner=busy,
                             fleet_fence_current=lambda epoch, generation: True)
    assert built == []


def test_root_fleet_uid_is_refused(tmp_path):
    with pytest.raises(ValueError, match="peer UID"):
        _build(tmp_path, fleet_peer_uid=0)


# --- run_hardware_owner.py config loader (no ROS, no files outside tmp_path) ---

import json  # noqa: E402

import run_hardware_owner  # noqa: E402


@pytest.mark.parametrize('blocked', ['owner', 'action', None])
def test_cleanup_retains_context_and_lock_until_both_executors_stop(blocked):
    events = []
    def destroy_action():
        events.append('action')
        if blocked == 'action':
            raise RuntimeError('action event executor did not stop')
    def shutdown_owner(**kwargs):
        assert kwargs == dict(timeout_sec=5, wait_for_threads=False)
        events.append('owner')
        return blocked != 'owner'
    owner = SimpleNamespace(uds_server=SimpleNamespace(stop=lambda: events.append('uds')),
                            runtime=SimpleNamespace(destroy=destroy_action))
    executor = SimpleNamespace(shutdown=shutdown_owner)
    node = SimpleNamespace(destroy_node=lambda: events.append('node'))
    context = SimpleNamespace(shutdown=lambda: events.append('context'))
    lock = SimpleNamespace(close=lambda: events.append('lock'))
    if blocked:
        with pytest.raises(RuntimeError):
            run_hardware_owner.close_runtime(owner, executor, node, context, lock)
        assert not {'node', 'context', 'lock'} & set(events)
    else:
        run_hardware_owner.close_runtime(owner, executor, node, context, lock)
        assert events == ['uds', 'owner', 'action', 'node', 'context', 'lock']


def _document(**overrides):
    value = {
        "schema": "rosy.omx-hardware-owner.v1", "workcell_id": "omx_cell_a", "instance_id": "omx_cell_a_01",
        "namespace": "/omx_a", "fleet_peer_uid": FLEET_UID, "journal_path": "/var/lib/rosy-omx/a.sqlite3",
        "socket_root": "/run/rosy/omx",
        "owner_config": {
            "enabled": True, "workcell_id": "omx_cell_a", "instance_id": "omx_cell_a_01",
            "joint_names": list(JOINTS), "position_limits": {name: [-0.1, 0.1] for name in JOINTS},
            "allowed_owners": ["rule_based"], "calibration_revision": "omx-a-measured-r1",
            "max_joint_state_age_s": 0.2, "max_goal_duration_s": 1, "action_timeout_s": 2},
    }
    value.update(overrides)
    return value


def _load(document, environ=None):
    environ = {"ROSY_OMX_ROS_NAMESPACE": "/omx_a"} if environ is None else environ
    return run_hardware_owner.load_config("/cfg.json", environ, read=lambda _path: json.dumps(document))


def test_loader_builds_settings_config_and_names():
    settings, config, names = _load(_document())
    assert (settings.instance_id, settings.fleet_peer_uid) == ("omx_cell_a_01", FLEET_UID)
    assert config.joint_names == JOINTS and config.allowed_owners == ("rule_based",)
    assert names.trajectory_action == "/omx_a/arm_controller/follow_joint_trajectory"
    assert names.joint_state_topic == "/omx_a/joint_states"


@pytest.mark.parametrize("document, message", [
    (dict(_document(), extra=1), "exactly"),
    (_document(schema="rosy.omx-collection-profile.v1"), "exactly"),
    (_document(instance_id="<accepted-instance>"), "placeholder"),
    (_document(socket_root="run/rosy/omx"), "absolute"),
    (_document(owner_config=dict(_document()["owner_config"], position_limits={})), "position_limits"),
    (_document(owner_config=dict(_document()["owner_config"], allowed_owners=["rule_based", "learned_policy"])),
     "rule_based"),
])
def test_loader_refuses_incomplete_or_foreign_documents(document, message):
    with pytest.raises(ValueError, match=message):
        _load(document)


def test_loader_requires_the_environment_namespace():
    with pytest.raises(ValueError, match="ROSY_OMX_ROS_NAMESPACE"):
        _load(_document(), environ={})


@pytest.mark.parametrize("environ, message", [
    ({"ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST"}, "ROS_DOMAIN_ID"),
    ({"ROS_DOMAIN_ID": "41"}, "localhost"),
])
def test_ros_environment_must_be_explicit_and_local(environ, message):
    with pytest.raises(RuntimeError, match=message):
        run_hardware_owner.require_ros_environment(environ)


def test_hardware_owner_is_a_known_arm_owner_for_the_simulation_guard(tmp_path):
    from cell_sim_tools import refuse_second_owner

    (tmp_path / "4001").mkdir()
    (tmp_path / "4001" / "cmdline").write_bytes(b"python3\0deploy/robot/omx/run_hardware_owner.py\0--config\0x")
    (tmp_path / "4001" / "environ").write_bytes(b"ROSY_OMX_ROS_NAMESPACE=/omx_a\0")
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=tmp_path, namespace="/omx_a")
    refuse_second_owner(proc_root=tmp_path, namespace="/omx_b")


def test_shipped_example_config_is_refused_until_filled():
    text = (ROOT / "deploy/robot/omx/hardware-owner.json.example").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder"):
        run_hardware_owner.load_config("/cfg.json", {"ROSY_OMX_ROS_NAMESPACE": "/x"}, read=lambda _path: text)


def test_owner_unit_runs_the_no_goal_entrypoint_without_device_access():
    unit = (ROOT / "deploy/robot/omx/rosy-omx-owner@.service").read_text(encoding="utf-8")
    assert "run_hardware_owner.py" in unit and "NoNewPrivileges=true" in unit
    for forbidden in ("/dev/", "torque", "ros2 control", "ros2 launch", "--approve"):
        assert forbidden not in unit.split("[Service]", 1)[1].split("ExecStart=", 1)[1].splitlines()[0]


def test_loader_accepts_a_final_state_policy():
    owner_config = dict(_document()["owner_config"], max_final_state_errors={
        **{name: 0.02 for name in JOINTS[:-1]}, "gripper_joint_1": None})
    _, config, _ = _load(_document(owner_config=owner_config))
    assert config.max_final_state_errors["joint1"] == 0.02
    assert config.max_final_state_errors["gripper_joint_1"] is None
