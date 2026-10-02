"""C4b G2b: one OMX cell owner process: one ArmCommandOwner, the HTTP app and the D-336 UDS API,
sharing one accepted cell/recipe store (D-403 §8, D-404 §6). The ROS runtime is a fake."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("apps/agent/src", "modules/processes/palletizing/src", "modules/execution/src",
                 "modules/skills/api/src", "modules/skills/manipulation/src",
                 "integrations/robots/omx/src", "src/products/omx/adapter", "deploy/robot/omx"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetCellTransferGrant  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from rosy_agent.omx_cell_owner import CellOwnerSettings, build_cell_owner  # noqa: E402

EXAMPLES = ROOT / "src/site/cell/examples/omx_sim"
FLEET_UID = 1001


class FakeRuntime:
    def __init__(self, config):
        self.config = config
        self.owner = SimpleNamespace(session_id="session-1", state="ready")
        self.latest_joint_state = None
        self.monotonic = lambda: 100.0


def _settings(tmp_path):
    return CellOwnerSettings(
        workcell_id="omx_cell_sim", instance_id="omx_cell_sim_01",
        journal_path=tmp_path / "owner.sqlite3", socket_root=tmp_path / "run",
        fleet_peer_uid=FLEET_UID, profile_path=ROOT / "deploy/robot/omx/sim/cell_profile.yaml",
        calibration_revision="omx-f-gazebo-only-v1", transform_revision="gz-world-is-link0-v1",
        stack_tol_m=0.001,
    )


def _build(tmp_path, **overrides):
    calls = {"runtime": [], "http": [], "guard": 0}

    def runtime_factory(config):
        runtime = FakeRuntime(config)
        calls["runtime"].append(runtime)
        return runtime

    def guard():
        calls["guard"] += 1

    kwargs = dict(
        runtime_factory=runtime_factory, goal_port_factory=lambda runtime: object(),
        http_app_factory=lambda runtime: calls["http"].append(runtime) or "http-app",
        refuse_second_owner=guard, gripper_readback=lambda: None,
        fleet_fence_current=lambda epoch, generation: True,
    )
    kwargs.update(overrides)
    return build_cell_owner(_settings(tmp_path), **kwargs), calls


def _docs():
    return (yaml.safe_load((EXAMPLES / "recipe.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((EXAMPLES / "cell.yaml").read_text(encoding="utf-8")))


def _grant(owner, cell_sha, recipe_sha):
    now = datetime.now(timezone.utc)
    value = {
        "mission_id": "m-1", "step_id": "m-1:step-1", "action_id": "a-1", "attempt_id": "t-1",
        "request_digest": "0" * 64, "workcell_id": "omx_cell_sim", "instance_id": "omx_cell_sim_01",
        "action_kind": "CELL_TRANSFER", "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": recipe_sha, "cell_sha256": cell_sha,
            "step_index": 0, "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
            "home": {"x": 0.12, "y": 0.0, "z": 0.12, "yaw": 0.0},
            "pick": {"x": 0.0, "y": 0.17, "z": 0.015, "yaw": 1.5707963267948966},
            "place": {"x": 0.1525, "y": 0.0275, "z": 0.025, "yaw": 0.0},
            "pick_approach_z": 0.06, "place_approach_z": 0.07, "carry_z": 0.11,
        },
        "capability_revision": "cell-transfer-sim-v1", "config_revision": owner.profile.revision,
        "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": now, "expires_at": now + timedelta(seconds=30),
    }
    value["request_digest"] = action_grant_digest(value)
    return FleetCellTransferGrant.model_validate(value)


def _submit(owner, grant):
    return owner.action_api.dispatch({"version": 2, "operation": "SubmitAction",
                                      "grant": grant.model_dump(mode="json")}, peer_uid=FLEET_UID)


def test_one_owner_with_the_simulation_owner_policy_serves_both_surfaces(tmp_path):
    owner, calls = _build(tmp_path)
    assert calls["guard"] == 1
    assert len(calls["runtime"]) == 1
    runtime = calls["runtime"][0]
    assert runtime.config.allowed_owners == ("pilot_sim", "rule_based")
    assert calls["http"] == [runtime] and owner.http_app == "http-app"
    assert owner.uds_server.api is owner.action_api
    assert owner.uds_server.socket_path == tmp_path / "run" / "omx_cell_sim_01" / "control.sock"
    assert owner.runner.capability_current == owner.acceptance.capability_current
    assert owner.planner.accepted_cell_sha256 == owner.acceptance.accepted_cell_sha256


def test_a_second_owner_stops_the_build_before_any_runtime(tmp_path):
    def busy():
        raise RuntimeError("another arm owner process is running")

    with pytest.raises(RuntimeError, match="another arm owner"):
        _build(tmp_path, refuse_second_owner=busy, runtime_factory=lambda config: pytest.fail("built"))


def test_uds_submit_sees_the_store_the_owner_accepted(tmp_path):
    owner, _ = _build(tmp_path)
    owner.stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    recipe, cell = _docs()

    unknown = _submit(owner, _grant(owner, "c" * 64, "d" * 64))
    assert (unknown["status"], unknown["error"]["code"]) == (403, "GRANT_REJECTED")

    cell_sha = owner.acceptance.accept_cell(cell, actor_id="operator-1")["cell_sha256"]
    recipe_sha = owner.acceptance.accept_recipe(recipe, actor_id="operator-1")["recipe_sha256"]
    accepted = _submit(owner, _grant(owner, cell_sha, recipe_sha))
    # Admitted and journaled; the fake runtime has no joint state, so the planner holds it.
    assert accepted["status"] == 200
    assert owner.store.get_action("a-1")["action_kind"] == "CELL_TRANSFER"
    assert accepted["receipt"]["state"] == "HOLD"


def test_stop_api_shares_the_owner_latch(tmp_path):
    owner, _ = _build(tmp_path)
    response = owner.action_api.dispatch({
        "version": 1, "operation": "GetStopState", "workcell_id": "omx_cell_sim",
        "instance_id": "omx_cell_sim_01"}, peer_uid=FLEET_UID)
    assert response["status"] == 200 and response["snapshot"]["state"] == "UNKNOWN"


def test_refuse_second_owner_sees_the_cell_owner_and_the_pilot(tmp_path):
    from cell_sim_tools import refuse_second_owner

    proc = tmp_path / "proc"
    for pid, cmd in (("4001", b"python3\0deploy/robot/omx/run_cell_owner.py"),):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "cmdline").write_bytes(cmd)
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=proc)
    (proc / "4001" / "cmdline").write_bytes(b"python3\0-m\0omx_adapter.pilot_sim_server")
    with pytest.raises(RuntimeError, match="4001"):
        refuse_second_owner(proc_root=proc)
    (proc / "4001" / "cmdline").write_bytes(b"bash\0-c\0sleep")
    refuse_second_owner(proc_root=proc)
