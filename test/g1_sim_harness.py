"""D-778/D-779/D-780/D-781 G1 SIM in one process: Fleet multi-arm dispatch -> two real OMX cell owners.

Test support, not production. What is real and what is bridged:

real   Fleet ``CellJobDispatcher`` (multi-arm pass, claims, pair rule, one-arm mode), ``CellJobStore``,
       the recipe/3 compile (``PalletizingCellJobCompiler.compile_mixed`` + ``compile_mixed_submission``),
       ``CellGoalEvidenceService`` judging per-step ``item_at_pose`` predicates; two ``build_cell_owner``
       owners (ActionApi, ActionRunner, stop latch, D-402 planner, phase runner, barrier supervisor,
       coordinator peer API) and the ``WorkcellCoordinator``.
bridge (1) the UDS: ``InProcessTransport`` is ``UnixLocalActionTransport`` with ``_exchange`` replaced by a
       direct ``ActionApi.dispatch`` as the Fleet UID (JSON round-tripped); the coordinator client does the
       same as the coordinator UID. Peer credentials (SO_PEERCRED) are therefore asserted, not checked.
       (2) ROS: ``SimGoalPort`` accepts every goal, completes it after ``duration_s * time_scale`` wall
       seconds and sets the joint state to the goal's last point; the gripper readback is the labelled
       sim rule of test_platform_cell_owner_barriers (CLOSED with the item until release).
       (3) owner acceptance of recipe/3 + cell/3: the owner's real validator knows recipe/1 only, so
       ``MixedDocumentValidator`` replaces it; it accepts one geometry per sku under the grant's
       ``item_key`` (``box:<sku>``, D-781 §2), as the owner's own recipe/3 validator does.
       (4) goal evidence: ``EvidenceProducer`` reports the item where the arm's own transfer goal left the
       TCP (FK of the goal's last point + the sku's centre offset) in the predicate arm's base frame.
       (5) Fleet goal predicates are attached here per sku: the legacy single predicate in the first
       primary arm's frame and, as the recipe/3 resolver does, one per arm that may run the Step.
"""

from __future__ import annotations

import json
import math
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _relative in ("contracts/skill/src", "middleware/devices/omx/agent/src", "operations/processes/palletizing/src",
                  "operations/site_execution/src", "middleware/skills/api/src", "middleware/skills/manipulation/src",
                  "integrations/robots/omx/src", "middleware/devices/omx/adapter", "operations/fleet",
                  "contracts/foundation"):
    if str(ROOT / _relative) not in sys.path:
        sys.path.insert(0, str(ROOT / _relative))

from core_common.protocol.cell_transfer import item_geometry_key  # noqa: E402
from core_common.protocol.schemas import FleetCellTransferGrant  # noqa: E402
from fleet.server.cell_arm_dispatcher import CellJobDispatcher  # noqa: E402
from fleet.server.cell_compiler import PalletizingCellJobCompiler  # noqa: E402
from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry  # noqa: E402
from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService  # noqa: E402
from fleet.server.cell_job_store import CellJobStore  # noqa: E402
from fleet.server.cell_mixed_submission import compile_mixed_submission  # noqa: E402
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError  # noqa: E402
from fleet.server.goal_evidence_store import GoalEvidenceStore  # noqa: E402
from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport  # noqa: E402
from fleet.server.mission_store import MissionStore  # noqa: E402
from fleet.server.step_action_kinds import step_action_kind  # noqa: E402
from fleet.server.task_store import FleetTaskStore  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from omx_adapter.cell_acceptance import ValidatedCell, ValidatedRecipe  # noqa: E402
from omx_adapter.command_owner import ArmCommandOwner  # noqa: E402
from omx_adapter.gripper_contract import GripperObservation  # noqa: E402
from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose  # noqa: E402
from omx_adapter.pick_place.pick_place_runner import PhaseDispatch  # noqa: E402
from omx_adapter.ros_goal_contract import RosGoalEvent  # noqa: E402
from rosy.execution.site.item_pose import ItemPoseTolerance, centre_above_tcp_m, step_goal_predicate  # noqa: E402
from rosy.processes.palletizing.mixed_cell_doc import load_mixed_cell  # noqa: E402
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe  # noqa: E402
from rosy.processes.palletizing.mixed_submission import ITEM  # noqa: E402
from rosy_agent.omx_cell_owner import CellOwnerSettings, build_cell_owner  # noqa: E402
from rosy_agent.workcell_coordinator import OwnerUnavailable, WorkcellCoordinator  # noqa: E402

FLEET_UID, COORDINATOR_UID = 1001, 2002
CELL = "bench_01"
MISSION = "g1-job"
PROFILE_PATH = ROOT / "deploy/robot/omx/sim/cell_profile.yaml"
TOLERANCE_PATH = ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml"
GRIPPER_REVISION = "omx-sim-gripper-joint-position-v2"
EVALUATOR = "g1-fk-placement-v1"


def _json(value):
    return json.loads(json.dumps(value))


class MixedDocumentValidator:
    """Bridge (3): accept recipe/3 + cell/3 on the owner. Hashes are the palletizing content hashes."""

    def __init__(self, kinematics_revision: str) -> None:
        self.kinematics_revision = kinematics_revision

    def validate_cell(self, cell) -> ValidatedCell:
        return ValidatedCell(sha256=load_mixed_cell(json.dumps(cell)).content_hash,
                             kinematics_revision=self.kinematics_revision)

    def validate_recipe(self, recipe, cell) -> ValidatedRecipe:
        parsed = load_mixed_recipe(json.dumps(recipe))
        load_mixed_cell(json.dumps(cell)).workcell(parsed)  # the recipe's pallets exist in this cell
        return ValidatedRecipe(sha256=parsed.content_hash, items={
            item_geometry_key(ITEM, item.sku): {"grasp_width_m": item.width, "grasp_depth_m": item.grasp_depth,
                                                "height_m": item.height} for item in parsed.items})


class FakeRuntime:
    def __init__(self, config):
        self.config = config
        self.owner = ArmCommandOwner(config, SimpleNamespace(), monotonic=lambda: 100.0, session_id="session-1")
        self.latest_joint_state = None
        self.monotonic = lambda: 100.0


@dataclass
class _Goal:
    command: Any
    goal_id: str
    callback: Any
    due: float
    status: int
    sequence: int = 1


class SimGoalPort:
    """Bridge (2): every goal is accepted, then ends after its trajectory time x ``time_scale``."""

    def __init__(self, arm: "SimArm", time_scale: float) -> None:
        self.arm, self.time_scale = arm, time_scale
        self.pending: list[_Goal] = []
        self.submissions: list[tuple[Any, str, float]] = []
        self.finished: dict[str, tuple[Any, float, int]] = {}  # command_id -> (command, t, status)
        self.fail_phase: dict[str, int] = {}  # phase_id -> ROS status for the next goal of that phase
        self.hang_phase: set[str] = set()  # phases whose goals never end on their own
        self.cancelled: list[str] = []

    def submit(self, command, *, on_goal_event):
        goal_id, now = str(uuid.uuid4()), time.monotonic()
        self.submissions.append((command, goal_id, now))
        on_goal_event(RosGoalEvent(kind="GOAL_ACCEPTED", command_id=command.command_id, phase_id=command.phase_id,
                                   goal_id=goal_id, observed_at_monotonic_s=100.0, sequence=1))
        status = self.fail_phase.pop(command.phase_id, 4)
        due = math.inf if command.phase_id in self.hang_phase else now + command.duration_s * self.time_scale
        self.pending.append(_Goal(command, goal_id, on_goal_event, due, status))
        return PhaseDispatch(dispatched=True)

    def cancel_goal(self, goal_id):
        for goal in self.pending:
            if goal.goal_id == goal_id:
                goal.status, goal.due = 5, time.monotonic()
                self.cancelled.append(goal_id)
                return True
        return False

    def pump(self) -> int:
        now, fired = time.monotonic(), 0
        for goal in [g for g in self.pending if g.due <= now]:
            self.pending.remove(goal)
            if goal.status == 4:
                previous = self.arm.owner.runtime.latest_joint_state
                self.arm.owner.runtime.latest_joint_state = SimpleNamespace(
                    sequence=previous.sequence + 1, positions=dict(goal.command.positions), received_at=100.0)
            self.finished[goal.command.command_id] = (goal.command, now, goal.status)
            goal.callback(RosGoalEvent(kind="TERMINAL_RESULT", command_id=goal.command.command_id,
                                       phase_id=goal.command.phase_id, goal_id=goal.goal_id,
                                       observed_at_monotonic_s=100.0, sequence=2, status=goal.status,
                                       result_code=0 if goal.status == 4 else 1))
            fired += 1
        return fired


def home_joints(kin: OmxKinematics, profile, home: tuple[float, float, float, float]) -> dict[str, float]:
    joints = kin.solve_top_down(TopDownPose(*home), profile.ik_limits()).joints
    positions = dict(zip(ARM_JOINTS, joints))
    positions[profile.gripper_joint] = profile.gripper_open
    return positions


class SimArm:
    """One real ``build_cell_owner`` (two-arm settings) with the sim goal port and gripper readback."""

    def __init__(self, tmp: Path, *, role: str, workcell_id: str, instance_id: str, home, time_scale: float,
                 liveness_s: float = 1.0, fleet_uid: int = FLEET_UID, socket_root: Path | None = None) -> None:
        tmp.mkdir(parents=True, exist_ok=True)
        self.role, self.workcell_id, self.instance_id, self.down = role, workcell_id, instance_id, False
        self.port = SimGoalPort(self, time_scale)
        settings = CellOwnerSettings(
            workcell_id=workcell_id, instance_id=instance_id, journal_path=tmp / "owner.sqlite3",
            socket_root=socket_root or tmp / "run", fleet_peer_uid=fleet_uid, profile_path=PROFILE_PATH,
            calibration_revision="omx-f-gazebo-only-v1", transform_revision="gz-world-is-link0-v1",
            stack_tol_m=0.001, coordinator_peer_uids=frozenset({COORDINATOR_UID}), coordinator_liveness_s=liveness_s)
        self.owner = build_cell_owner(
            settings, runtime_factory=FakeRuntime, goal_port_factory=lambda runtime: self.port,
            http_app_factory=lambda runtime: None, refuse_second_owner=lambda: None,
            gripper_readback=self._gripper, fleet_fence_current=lambda epoch, generation: True)
        self.kin = OmxKinematics.load()
        self.owner.acceptance.validator = MixedDocumentValidator(self.kin.revision)
        self.owner.runtime.latest_joint_state = SimpleNamespace(
            sequence=1, positions=home_joints(self.kin, self.owner.profile, home), received_at=100.0)

    def _gripper(self, grant):
        state = self.owner.runtime.latest_joint_state
        mine = [command for command, _, _ in self.port.submissions if command.command_id.startswith(grant.action_id)]
        released = bool(mine) and mine[-1].phase_id == "release"
        return GripperObservation(grant.workcell_id, grant.instance_id, GRIPPER_REVISION, state.sequence,
                                  state.received_at, "OPEN" if released else "CLOSED", not released,
                                  None if released else "box", grant.dispatch_generation)

    def accept(self, recipe_doc: dict, cell_doc: dict) -> tuple[str, str]:
        cell = self.owner.acceptance.accept_cell(cell_doc, actor_id="operator-1")["cell_sha256"]
        recipe = self.owner.acceptance.accept_recipe(recipe_doc, actor_id="operator-1")["recipe_sha256"]
        return cell, recipe

    def rearm(self, epoch: int, generation: int) -> None:
        self.owner.stop.rearm(authority_epoch=epoch, dispatch_generation=generation, operator_confirmed=True,
                              fleet_fence_current=lambda e, g: True)

    def tick(self) -> None:
        self.port.pump()
        self.owner.advance_pending()

    def action(self, action_id: str) -> dict | None:
        return self.owner.store.get_action(action_id)

    def stop_snapshot(self):
        return self.owner.stop.snapshot(workcell_id=self.workcell_id, instance_id=self.instance_id)

    def intervals(self) -> dict[str, tuple[float, float | None]]:
        """action_id -> (first goal sent, release goal ended or None) in monotonic seconds."""
        out: dict[str, list] = {}
        for command, _, sent in self.port.submissions:
            action_id = command.command_id.rsplit("-", 1)[0]
            out.setdefault(action_id, [sent, None])
        for command_id, (command, ended, status) in self.port.finished.items():
            if command.phase_id == "release" and status == 4:
                out[command_id.rsplit("-", 1)[0]][1] = ended
        return {key: tuple(value) for key, value in out.items()}

    def transfer_end_joints(self, action_id: str) -> tuple[float, ...] | None:
        done = self.port.finished.get(f"{action_id}-transfer")
        if done is None or done[2] != 4:
            return None
        return tuple(done[0].positions[name] for name in ARM_JOINTS)


class Rtt:
    """Round-trip samples (seconds) per operation."""

    def __init__(self) -> None:
        self.samples: dict[str, list[float]] = {}

    def add(self, operation: str, seconds: float) -> None:
        self.samples.setdefault(operation, []).append(seconds)

    def summary(self) -> dict[str, dict[str, float]]:
        return {op: quantiles(values) for op, values in sorted(self.samples.items())}


def record_evidence(name: str, document: dict) -> None:
    """Write run evidence when ROSY_G1_EVIDENCE_DIR is set (the lab run copies it into docs/validation)."""
    import os
    folder = os.environ.get("ROSY_G1_EVIDENCE_DIR")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / f"{name}.json").write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")


def quantiles(values) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def q(p):
        return round(ordered[min(len(ordered) - 1, int(math.ceil(p * len(ordered))) - 1)], 6)
    return {"n": len(ordered), "p50": q(0.5), "p90": q(0.9), "p99": q(0.99), "max": round(ordered[-1], 6)}


class InProcessTransport(UnixLocalActionTransport):
    """Bridge (1): the Fleet UDS client with its socket exchange replaced by a direct ActionApi call."""

    def __init__(self, arms: dict[str, SimArm], rtt: Rtt, socket_root: Path) -> None:
        super().__init__(socket_root, timeout_s=0.25)
        self.arms, self.rtt = arms, rtt
        self.cancels: list[tuple[str, str]] = []

    def _exchange(self, instance_id, document):
        arm = self.arms.get(instance_id)
        if arm is None or arm.down:
            raise LocalActionUnavailable("local Action transport outcome is unknown")
        if document.get("operation") == "CancelAction":
            self.cancels.append((instance_id, document["reason"]))
        start = time.perf_counter()
        response = arm.owner.action_api.dispatch(_json(document), peer_uid=FLEET_UID)
        self.rtt.add(f"fleet:{document.get('operation')}", time.perf_counter() - start)
        return _json(response)


class InProcessOwnerClient:
    """Bridge (1) for the coordinator: one owner reached as the coordinator UID."""

    def __init__(self, arm: SimArm, rtt: Rtt) -> None:
        self.arm, self.rtt = arm, rtt

    def request(self, document):
        if self.arm.down:
            raise OwnerUnavailable("socket closed")
        start = time.perf_counter()
        response = self.arm.owner.action_api.dispatch(_json(document), peer_uid=COORDINATOR_UID)
        self.rtt.add(f"coordinator:{document.get('operation')}", time.perf_counter() - start)
        return _json(response)


# Fleet ---------------------------------------------------------------------------------------------
def compile_submission(recipe_doc: dict, cell_doc: dict) -> dict:
    """The recipe/3 candidate through Fleet's compiler and resolver (no goal predicates yet)."""
    compiler = PalletizingCellJobCompiler(tol_m=0.001)
    compiled = compiler.compile_mixed(recipe_doc, cell_doc)
    candidate = {"kind": "cell_job", "recipe": recipe_doc, "cell": cell_doc, "recipe_sha256": compiled.recipe_digest,
                 "cell_sha256": compiled.cell_digest, "job": _json(compiled.job)}
    return compile_mixed_submission(candidate, compiler=compiler, workcell_id=CELL,
                                    instance_id=compiled.arms[0]["instance_id"])


def attach_predicates(submission: dict, recipe_doc: dict) -> dict:
    """Bridge (5): each Step's item_at_pose predicate per sku, in the first primary arm's frame
    (``goal_predicate``) and in every arm's own frame (``goal_predicates``, D-781 §5)."""
    import yaml
    out = _json(submission)
    tolerance = ItemPoseTolerance.from_mapping(yaml.safe_load(TOLERANCE_PATH.read_text(encoding="utf-8")))
    items = {item["sku"]: item for item in recipe_doc["items"]}
    for step, planned in zip(out["steps"], out["job"]["plan"]["steps"]):
        item = items[planned["sku"]]
        placement = step["placement"]
        frame = placement["arm"] if isinstance(placement["arm"], str) else placement["arm"][0]
        offset = centre_above_tcp_m(grasp_depth_m=item.get("grasp_depth", 0.0), height_m=item["height"])
        step["goal_predicate"] = step_goal_predicate(placement["actions"][frame], tolerance, offset)
        step["goal_predicates"] = {role: step_goal_predicate(inputs, tolerance, offset)
                                   for role, inputs in sorted(placement["actions"].items())}
    return out


def as_pair(submission: dict, index: int, coupling: str) -> dict:
    """Make a Step compiled for two arms (a shared-band Step with an alternate) a coordinated pair.
    Call before ``attach_predicates`` so the predicate is in the pair's first arm frame."""
    out = _json(submission)
    placement = out["steps"][index]["placement"]
    roles = sorted(placement["actions"])
    if len(roles) != 2:
        raise ValueError(f"step {index} is not compiled for two arms")
    placement.update(arm=roles, alternates=[], coupling=coupling)
    return out


@dataclass
class Rig:
    """Fleet stores + dispatcher + goal service, two SimArms and a coordinator, one tick loop."""

    tmp: Path
    submission: dict
    recipe_doc: dict
    cell_doc: dict
    time_scale: float = 0.002
    rtt: Rtt = field(default_factory=Rtt)

    def __post_init__(self) -> None:
        path = self.tmp / "fleet.sqlite3"
        tasks = FleetTaskStore(path)
        self.control = tasks.store if hasattr(tasks, "store") else tasks
        before = self.control.dispatch_control()
        enabled = self.control.rearm_dispatch(expected_generation=before["generation"], actor_id="operator-1")
        MissionStore(path)
        self.path, self.cells = path, CellJobStore(path)
        self.cells.create(mission_id=MISSION, proposal_principal_id="cell-service", request_key="rk-g1",
                          request_digest="d" * 64, submission=self.submission)
        job = self.cells.admit(MISSION, actor_id="operator-1", expected_generation=enabled["generation"])
        homes = {arm["role"]: tuple(arm["home"][k] for k in ("x", "y", "z", "yaw")) for arm in self.cell_doc["arms"]}
        self.arms = {arm["instance_id"]: SimArm(
            self.tmp / arm["role"], role=arm["role"], workcell_id=arm["workcell_id"], instance_id=arm["instance_id"],
            home=homes[arm["role"]], time_scale=self.time_scale) for arm in self.cell_doc["arms"]}
        self.by_role = {arm.role: arm for arm in self.arms.values()}
        for arm in self.arms.values():
            arm.accept(self.recipe_doc, self.cell_doc)
            arm.rearm(job["authority_epoch"], job["dispatch_generation"])
        self.transport = InProcessTransport(self.arms, self.rtt, self.tmp / "run")
        omx = {arm.workcell_id: arm.instance_id for arm in self.arms.values()}
        revisions = {arm.instance_id: {"capability_revision": "cell-transfer-sim-v1",
                                       "config_revision": arm.owner.profile.revision} for arm in self.arms.values()}
        self.dispatcher = CellJobDispatcher(self.cells, self.control, self.transport, omx, revisions,
                                            deployment_profile="simulation",
                                            on_step_action_succeeded=self._goal_hook)
        producers = tuple(CellGoalProducer(
            producer_id=f"g1-pose-{arm.role}", token=f"g1-secret-{arm.role}", workcell_id=CELL,
            instance_id=arm.instance_id, recipe_sha256=self.submission["recipe_digest"],
            cell_sha256=self.submission["cell_digest"], evaluator_revisions=(EVALUATOR,), max_age_s=30.0,
            valid_until=datetime.now(timezone.utc) + timedelta(hours=1)) for arm in self.arms.values())
        self.goals = CellGoalEvidenceService(self.cells, CellGoalRegistry(producers), GoalEvidenceStore(path))
        self.coordinator = WorkcellCoordinator({instance: InProcessOwnerClient(arm, self.rtt)
                                                for instance, arm in self.arms.items()})
        self.coordinator_alive = True
        self.evidence_sent: set[tuple[int, str]] = set()
        self.evidence_refused: dict[int, str] = {}
        self.zone_samples: list[tuple[float, dict[str, list[str]]]] = []
        self.kin = OmxKinematics.load()

    def _goal_hook(self, job, index):
        return self.goals.on_action_terminal(job["mission_id"], index)

    def job(self) -> dict:
        return self.cells.get(MISSION)

    def tick(self) -> None:
        self.dispatcher.dispatch_next()
        for arm in self.arms.values():
            arm.tick()
        if self.coordinator_alive:
            self.coordinator.tick()
        self._produce_evidence()
        self._sample_zones()

    def run(self, until, *, timeout_s: float = 120.0, period_s: float = 0.002) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.tick()
            if until(self):
                return True
            time.sleep(period_s)
        return False

    # Goal evidence (bridge 4) --------------------------------------------------------------------
    def _produce_evidence(self) -> None:
        job = self.job()
        items = {item["sku"]: item for item in self.recipe_doc["items"]}
        for step in job["steps"]:
            index = step["step_index"]
            if step["status"] != "ACTION_SUCCEEDED":
                continue
            placement = next(p for p in job["placements"] if p["step_index"] == index)
            frame = placement["arms"][0]
            action = next((a for a in job["step_actions"] if a["step_index"] == index and a["arm_role"] == frame
                           and a["status"] == "ACTION_SUCCEEDED"), None)
            executed = [a for a in job["step_actions"]
                        if a["step_index"] == index and a["status"] == "ACTION_SUCCEEDED"]
            if action is None:  # an alternate ran it: evidence names the action it actually has
                action = executed[0] if executed else None
            if action is None or (index, action["action_id"]) in self.evidence_sent:
                continue
            self.evidence_sent.add((index, action["action_id"]))
            sku = job["job"]["plan"]["steps"][index]["sku"]
            evidence = self._evidence(job, index, action, items[sku], executed)
            if evidence is None:
                self.evidence_refused[index] = "NO_TRANSFER_GOAL"
                continue
            try:
                self.goals.submit(token=f"g1-secret-{action['arm_role']}", mission_id=MISSION, raw_evidence=evidence)
            except GoalEvidenceSubmissionError as exc:
                self.evidence_refused[index] = exc.code

    def _evidence(self, job, index, action, item, peers) -> dict | None:
        arm = self.by_role[action["arm_role"]]
        joints = arm.transfer_end_joints(action["action_id"])
        if joints is None:
            return None
        tcp = self.kin.fk(joints)
        centre = centre_above_tcp_m(grasp_depth_m=item.get("grasp_depth", 0.0), height_m=item["height"])
        issued = max(datetime.fromisoformat(a["grant"]["issued_at"].replace("Z", "+00:00")).timestamp()
                     for a in peers if a["grant"] is not None)
        observed = time.time()
        grant = action["grant"]
        evidence_id = f"g1-{index}-{action['action_id'][:8]}"
        pose = {"x_m": float(tcp.x), "y_m": float(tcp.y), "z_m": float(tcp.z + centre),
                "roll_rad": 0.0, "pitch_rad": 0.0, "yaw_rad": float(tcp.yaw)}
        return {
            "producer_id": f"g1-pose-{action['arm_role']}", "evidence_id": evidence_id,
            "evidence_source": "sim_model_pose", "evaluator_revision": EVALUATOR, "job_id": job["job_id"],
            "step_id": job["steps"][index]["step_id"], "step_index": index, "action_id": action["action_id"],
            "attempt_id": action["attempt_id"], "request_digest": action["request_digest"],
            "recipe_sha256": grant["cell_transfer"]["recipe_sha256"],
            "cell_sha256": grant["cell_transfer"]["cell_sha256"], "model_id": "cell_" + action["action_id"],
            "observation_id": f"{evidence_id}-pose", "observation_digest": "d" * 64,
            "evidence_revision": "g1-fk-v1", "observed_at": observed, "model_pose_base": pose,
            "initial_observation_id": f"{evidence_id}-initial", "initial_observation_digest": "c" * 64,
            "initial_observed_at": float(issued), "initial_model_pose_base": {**pose, "z_m": 0.0},
            "gripper_state": "OPEN", "gripper_evidence_id": f"{evidence_id}-gripper",
            "gripper_evidence_revision": GRIPPER_REVISION, "gripper_observed_at": observed}

    # Observation ---------------------------------------------------------------------------------
    def _sample_zones(self) -> None:
        """Which arms have a goal in flight, per zone of the Step they run (for the overlap checks)."""
        job = self.job()
        zones = {p["step_index"]: p["zone_id"] for p in job["placements"]}
        moving: dict[str, list[str]] = {}
        for arm in self.arms.values():
            for goal in arm.port.pending:
                action_id = goal.command.command_id.rsplit("-", 1)[0]
                row = arm.action(action_id)
                index = row["request"]["payload"]["cell_transfer"]["step_index"]
                moving.setdefault(zones[index], []).append(arm.role)
        self.zone_samples.append((time.monotonic(), moving))

    def step_intervals(self) -> dict[int, list[tuple[str, float, float | None]]]:
        """step_index -> [(arm role, first goal sent, release ended)] from the owners' goal ports."""
        out: dict[int, list] = {}
        for arm in self.arms.values():
            for action_id, (start, end) in arm.intervals().items():
                index = arm.action(action_id)["request"]["payload"]["cell_transfer"]["step_index"]
                out.setdefault(index, []).append((arm.role, start, end))
        return out


# Coordinated pair outside Fleet (D-780 G1: barriers, tight segment, coordinator liveness) ----------
BARRIERS = ({"barrier_id": "both_ready", "before_first_phase": True, "coupling_after": "loose"},
            {"barrier_id": "both_grasped", "after_phase": "grasp", "coupling_after": "tight"})


def arm_grant(arm: SimArm, submission: dict, index: int, role: str, *, epoch: int, generation: int,
              pair: tuple[str, str] | None = None,
              max_wait_s: dict[str, float] | None = None) -> FleetCellTransferGrant:
    """A Fleet-shaped grant for ``role``'s compiled inputs of one Step; ``pair`` = (pair_id, partner
    instance) adds the pair fields, the D-780 barriers (BARRIERS with ``max_wait_s``) and tight coupling."""
    job = {"job_id": submission["job_id"], "recipe_digest": submission["recipe_digest"],
           "cell_digest": submission["cell_digest"]}
    body = step_action_kind("CELL_TRANSFER").body(job, index, submission["steps"][index]["placement"]["actions"][role])
    now = datetime.now(timezone.utc)
    value = {"mission_id": "g1-pair", "step_id": f"g1-pair:step-{index}", "action_id": str(uuid.uuid4()),
             "attempt_id": str(uuid.uuid4()), "request_digest": "0" * 64, "workcell_id": arm.workcell_id,
             "instance_id": arm.instance_id, "action_kind": "CELL_TRANSFER", "cell_transfer": body,
             "capability_revision": "cell-transfer-sim-v1", "config_revision": arm.owner.profile.revision,
             "authority_epoch": epoch, "dispatch_generation": generation, "issued_at": now,
             "expires_at": now + timedelta(seconds=30), "arm_role": role}
    if pair is not None:
        body["barriers"] = [{**barrier, "max_wait_s": max_wait_s[barrier["barrier_id"]]} for barrier in BARRIERS]
        value.update(pair_id=pair[0], partner_instance_id=pair[1], coupling="tight")
    value["request_digest"] = action_grant_digest(FleetCellTransferGrant.model_validate(value))
    return FleetCellTransferGrant.model_validate(value)


def pair_grants(arms: dict[str, SimArm], submission: dict, index: int, *, epoch: int, generation: int,
                max_wait_s: dict[str, float]) -> dict[str, FleetCellTransferGrant]:
    """One paired, barrier-carrying grant per arm for a Step compiled for both arms (its own inputs each)."""
    pair_id = str(uuid.uuid4())
    roles = {arm.role: arm for arm in arms.values()}
    return {role: arm_grant(arm, submission, index, role, epoch=epoch, generation=generation,
                            pair=(pair_id, next(o.instance_id for o in roles.values() if o is not arm)),
                            max_wait_s=max_wait_s) for role, arm in roles.items()}


def submit_as_fleet(arm: SimArm, grant: FleetCellTransferGrant) -> dict:
    return arm.owner.action_api.dispatch({"version": 2, "operation": "SubmitAction",
                                          "grant": grant.model_dump(mode="json")}, peer_uid=FLEET_UID)


__all__ = ["BARRIERS", "CELL", "COORDINATOR_UID", "FLEET_UID", "InProcessOwnerClient", "InProcessTransport", "MISSION",
           "Rig", "Rtt", "SimArm", "arm_grant", "as_pair", "attach_predicates", "compile_submission", "pair_grants",
           "quantiles", "record_evidence", "submit_as_fleet"]
