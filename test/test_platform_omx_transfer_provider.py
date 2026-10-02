"""ROS-free contract tests for the OMX transfer integration provider."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for package_root in (
    ROOT / "modules/skills/api/src",
    ROOT / "modules/skills/manipulation/src",
    ROOT / "src/contracts/foundation",
    ROOT / "src/products/omx/adapter",
    ROOT / "integrations/robots/omx/src",
    ROOT / "src/products/omx/adapter/test",
):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from core_common.protocol.schemas import FleetCellTransferGrant  # noqa: E402
from omx_adapter.pose_plan import CellPlanningProfile  # noqa: E402
from rosy.integrations.robots.omx.transfer_provider import (  # noqa: E402
    OMXAnalyticTransferPlanner,
    cell_transfer_invocation,
    create_cell_transfer_phase_factory,
)
from rosy.skills.api import SkillInvocation  # noqa: E402
from rosy.skills.manipulation.transfer import PlannedTransfer, TransferSkill  # noqa: E402


NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _grant():
    return FleetCellTransferGrant.model_validate({
        "mission_id": "mission-1", "step_id": "step-1", "action_id": "action-1",
        "attempt_id": "attempt-1", "request_digest": "a" * 64,
        "workcell_id": "cell-1", "instance_id": "cell-1-a", "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "b" * 64, "cell_sha256": "c" * 64,
            "step_index": 2, "item": "box", "pallet": "pallet-1", "layer": 1,
            "frame": "robot_base",
            "home": {"x": 0.1, "y": 0.0, "z": 0.2, "yaw": 0.0},
            "pick": {"x": 0.2, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "place": {"x": 0.3, "y": 0.0, "z": 0.04, "yaw": 0.0},
            "pick_approach_z": 0.12, "place_approach_z": 0.12, "carry_z": 0.18,
        },
        "capability_revision": "cap-1", "config_revision": "cfg-1",
        "authority_epoch": 4, "dispatch_generation": 9,
        "issued_at": NOW, "expires_at": NOW + timedelta(minutes=5),
    })


class _Planner:
    def __init__(self):
        self.calls = []

    def plan(self, invocation):
        self.calls.append(invocation)
        return "opaque-plan"


class _Runner:
    def __init__(self, plan):
        self.plan = plan
        self.started = 0
        self.cancelled = 0
        self.active_phase_id = None

    def start(self):
        self.started += 1
        self.active_phase_id = "approach"
        return {"state": "SUBMITTING"}

    def cancel_current(self):
        self.cancelled += 1
        return {"state": "CANCEL_REQUESTED"}


def test_grant_maps_to_skill_invocation_and_existing_runner_ports():
    grant = _grant()
    invocation = cell_transfer_invocation(grant)
    planner = _Planner()
    runners = []

    def runner_for_grant(received, recorder, planned):
        runner = _Runner(planned.plan)
        runners.append((received, recorder, planned, runner))
        return runner

    factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(), planner_for_grant=lambda received: planner,
        executor_for_grant=runner_for_grant,
    )
    phase = factory(grant, "recorder")
    assert phase.active_phase_id is None
    receipt = phase.start()
    assert phase.active_phase_id == "approach"
    runners[0][3].active_phase_id = "carry"
    assert phase.active_phase_id == "carry"
    cancelled = phase.cancel_current()

    assert invocation.inputs["item"] == "box"
    assert invocation.inputs["source_pose_base"]["x_m"] == pytest.approx(0.2)
    assert invocation.inputs["destination_pose_base"]["x_m"] == pytest.approx(0.3)
    assert planner.calls == [invocation]
    received, recorder, planned, runner = runners[0]
    assert received is grant and recorder == "recorder"
    assert isinstance(planned, PlannedTransfer) and planned.plan == "opaque-plan"
    assert (runner.started, runner.cancelled) == (1, 1)
    assert receipt == {"state": "SUBMITTING"}
    assert cancelled == {"state": "CANCEL_REQUESTED"}


def test_omx_planner_uses_grant_hashes_and_accepted_recipe_geometry():
    grant = _grant()
    calls = []
    marker = object()
    planner = SimpleNamespace(plan_transfer=lambda request, profile, state: (
        calls.append((request, profile, state)) or marker
    ))
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    state = object()
    geometry_calls = []
    adapter = OMXAnalyticTransferPlanner(
        grant, profile=profile, planner=planner, execution_state=lambda: state,
        accepted_item_geometry=lambda recipe, item: (
            geometry_calls.append((recipe, item)) or {
                "grasp_width_m": 0.06, "grasp_depth_m": 0.02, "height_m": 0.1,
            }
        ),
    )

    result = adapter.plan(cell_transfer_invocation(grant))

    request, used_profile, used_state = calls[0]
    assert result is marker
    assert (request.job_id, request.recipe_sha256, request.cell_sha256) == (
        "job-1", "b" * 64, "c" * 64,
    )
    assert (request.step_index, request.item, request.grasp_width_m, request.grasp_depth_m) == (
        2, "box", 0.06, 0.02,
    )
    assert (request.home.x, request.pick.x, request.place.x) == (0.1, 0.2, 0.3)
    assert (used_profile, used_state) == (profile, state)
    assert geometry_calls == [("b" * 64, "box")]


def test_provider_rejects_invocation_or_invalid_accepted_geometry_before_planning():
    grant = _grant()
    profile = CellPlanningProfile.load(ROOT / "deploy/robot/omx/sim/cell_profile.yaml")
    calls = []
    adapter = OMXAnalyticTransferPlanner(
        grant, profile=profile,
        planner=SimpleNamespace(plan_transfer=lambda *args: calls.append(args)),
        execution_state=lambda: object(),
        accepted_item_geometry=lambda *_args: {
            "grasp_width_m": 0.06, "grasp_depth_m": 0.02, "height_m": float("nan"),
        },
    )
    altered = SkillInvocation("pallet.transfer", "1.0.0", {
        **dict(cell_transfer_invocation(grant).inputs), "pallet_id": "another-pallet",
    })
    with pytest.raises(ValueError, match="does not match"):
        adapter.plan(altered)
    with pytest.raises(ValueError, match="height"):
        adapter.plan(cell_transfer_invocation(grant))
    assert calls == []


def test_skill_wrapped_cell_action_cancels_only_its_live_phase(tmp_path):
    from omx_adapter.action_api import ActionApi
    from omx_adapter.action_store import InvalidActionTransition
    from test_omx_action_api import FakePhaseExecution, _cell_transfer_grant, _runner

    executions = []

    def executor_for_grant(grant, recorder, planned):
        execution = FakePhaseExecution(recorder)
        execution.plan = planned.plan
        executions.append(execution)
        return execution

    factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(), planner_for_grant=lambda _: _Planner(),
        executor_for_grant=executor_for_grant,
    )
    store, driver, runner = _runner(
        tmp_path, phase_runner_factories={"CELL_TRANSFER": factory},
    )
    api = ActionApi(runner)
    submitted = api.dispatch({
        "version": 2, "operation": "SubmitAction", "grant": FleetCellTransferGrant.model_validate(
            _cell_transfer_grant(),
        ).model_dump(mode="json"),
    }, peer_uid=1001)
    assert submitted["status"] == 200, submitted
    assert submitted["receipt"]["state"] == "ACCEPTED"
    with pytest.raises(InvalidActionTransition, match="active ROS goal"):
        runner.cancel_phase("cell-action-1", "cell-attempt-1",
                            phase_id="release", peer_uid=1001)
    assert store.action_phases("cell-action-1")[0]["state"] == "ACCEPTED"

    cancelled = api.dispatch({
        "version": 2, "operation": "CancelAction", "action_id": "cell-action-1",
        "attempt_id": "cell-attempt-1", "reason": "SITE_STOP",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }, peer_uid=1001)
    assert cancelled["status"] == 200
    # A phase cancel request does not establish a terminal parent Action result.
    assert cancelled["receipt"]["state"] == "ACCEPTED"
    phase = store.action_phases("cell-action-1")[0]
    assert (phase["phase_id"], phase["driver_goal_id"], phase["state"]) == (
        "approach", "ros-goal-approach", "CANCEL_REQUESTED",
    )
    assert len(executions) == 1
    assert driver.submissions == driver.cancellations == driver.phase_cancellations == []
