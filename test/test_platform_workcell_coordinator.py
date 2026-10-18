"""D-780 §6 workcell coordinator: barrier release and coupled stop against fake and real owner APIs."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("middleware/devices/omx/agent/src", "middleware/devices/omx/adapter"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetCellTransferGrant, LocalStopRequest, StopRequestSource  # noqa: E402
from omx_adapter.action_api import ActionApi, LocalStopApi  # noqa: E402
from omx_adapter.action_runner import ActionRunner  # noqa: E402
from omx_adapter.action_store import ActionStore  # noqa: E402
from omx_adapter.local_stop import LocalStopController  # noqa: E402
from rosy_agent.barrier_journal import BarrierJournal  # noqa: E402
from rosy_agent.barrier_supervisor import BarrierSupervisor, make_coordinator_hold  # noqa: E402
from rosy_agent.coordinator_api import CoordinatorPeerApi  # noqa: E402
from rosy_agent.workcell_coordinator import OwnerUnavailable, WorkcellCoordinator  # noqa: E402

FLEET, COORDINATOR = 1001, 2002
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


def _barrier(barrier_id, state, coupling_after="tight"):
    return {"barrier_id": barrier_id, "state": state, "coupling_after": coupling_after,
            "arrived_at": None if state == "not_reached" else f"{barrier_id}-arrival"}


def _view(instance, partner, *, state="RUNNING", barriers=(), coupling_now="independent", action_id=None):
    return {"action_id": action_id or f"act-{instance}", "attempt_id": "t", "workcell_id": "cell-1",
            "instance_id": instance, "pair_id": "pair-1", "partner_instance_id": partner,
            "coupling": "tight", "coupling_now": coupling_now, "fence_open": True, "authority_epoch": 2,
            "dispatch_generation": 8, "action_state": state, "barriers": list(barriers)}


class FakeOwner:
    def __init__(self, view):
        self.view = view
        self.down = False
        self.requests = []
        self.refuse_release = None  # error code to answer ReleaseBarrier with

    def request(self, document):
        if self.down:
            raise OwnerUnavailable("socket closed")
        self.requests.append(dict(document))
        operation = document["operation"]
        if operation == "GetBarrier":
            if "action_id" in document:
                return {"status": 200, "action": self.view}
            unresolved = self.view["action_state"] in {"SUBMITTING", "ACCEPTED", "RUNNING", "UNKNOWN", "HOLD"}
            return {"status": 200, "actions": [self.view] if unresolved else []}
        if operation == "ReleaseBarrier":
            if self.refuse_release:
                return {"status": 409, "error": {"code": self.refuse_release}}
            for barrier in self.view["barriers"]:
                if barrier["barrier_id"] == document["barrier_id"]:
                    barrier["state"] = "released"
            return {"status": 200}
        if operation == "StopLocal":
            return {"status": 200}
        return {"status": 404}

    def sent(self, operation):
        return [request for request in self.requests if request["operation"] == operation]


def _pair(left_barriers, right_barriers, **right):
    left = FakeOwner(_view("omx-left", "omx-right", barriers=left_barriers))
    right_owner = FakeOwner(_view("omx-right", "omx-left", barriers=right_barriers, **right))
    return left, right_owner, WorkcellCoordinator({"omx-left": left, "omx-right": right_owner}, now=lambda: NOW)


def test_coordinator_needs_exactly_two_owners():
    with pytest.raises(ValueError):
        WorkcellCoordinator({"only": FakeOwner(_view("only", "other"))})


def test_releases_a_barrier_only_when_both_arms_arrived():
    left, right, coordinator = _pair([_barrier("both_grasped", "waiting")],
                                     [_barrier("both_grasped", "not_reached")])
    coordinator.tick()
    assert left.sent("ReleaseBarrier") == right.sent("ReleaseBarrier") == []
    right.view["barriers"][0].update(state="waiting", arrived_at="right-arrival")
    decisions = coordinator.tick()
    assert sorted(item["instance_id"] for item in decisions if item["decision"] == "release") == [
        "omx-left", "omx-right"]
    (release,) = left.sent("ReleaseBarrier")
    assert release["partner_arrival"] == {"instance_id": "omx-right", "action_id": "act-omx-right",
                                          "arrived_at": "right-arrival"}
    assert (release["pair_id"], release["authority_epoch"], release["dispatch_generation"]) == ("pair-1", 2, 8)
    coordinator.tick()
    assert len(left.sent("ReleaseBarrier")) == 1  # nothing left waiting


def test_a_half_released_barrier_is_completed_after_restart():
    left, right, _ = _pair([_barrier("b", "released")], [_barrier("b", "waiting")])
    restarted = WorkcellCoordinator({"omx-left": left, "omx-right": right})
    restarted.tick()
    assert left.sent("ReleaseBarrier") == [] and len(right.sent("ReleaseBarrier")) == 1


@pytest.mark.parametrize("partner_state,reason", [
    ("FAILED", "PARTNER_FAILED"), ("HOLD", "PARTNER_FAILED"), ("UNKNOWN", "PARTNER_UNKNOWN")])
def test_partner_failure_in_a_tight_segment_stops_the_other_arm_once(partner_state, reason):
    left, right, coordinator = _pair([], [])
    left.view["coupling_now"] = "tight"
    coordinator.tick()
    assert left.sent("StopLocal") == []
    right.view["action_state"] = partner_state
    coordinator.tick()
    (stop,) = left.sent("StopLocal")
    assert (stop["reason"], stop["instance_id"], stop["dispatch_generation"]) == (reason, "omx-left", 8)
    assert stop["requested_at"] == NOW.isoformat()
    coordinator.tick()
    assert len(left.sent("StopLocal")) == 1
    assert right.sent("StopLocal") == []


def test_partner_failure_outside_a_tight_segment_is_left_to_the_owner():
    left, right, coordinator = _pair([], [], state="FAILED")
    left.view["coupling_now"] = "loose"
    coordinator.tick()
    assert left.sent("StopLocal") == []


def test_unreachable_partner_owner_is_a_link_loss():
    left, right, coordinator = _pair([], [])
    left.view["coupling_now"] = "tight"
    right.down = True
    decisions = coordinator.tick()
    assert [item["reason"] for item in decisions] == ["PARTNER_LINK_LOST"]


def test_every_tick_polls_both_owners_as_liveness_traffic():
    left, right, coordinator = _pair([], [])
    for _ in range(3):
        coordinator.tick()
    assert len(left.sent("GetBarrier")) == len(right.sent("GetBarrier")) == 3


def test_no_release_unless_both_owners_report_an_open_fence():
    left, right, coordinator = _pair([_barrier("both_grasped", "waiting")], [_barrier("both_grasped", "waiting")])
    right.view["fence_open"] = False
    coordinator.tick()
    assert left.sent("ReleaseBarrier") == right.sent("ReleaseBarrier") == []


@pytest.mark.parametrize("code,reason", [("BARRIER_EXPIRED", "PARTNER_FAILED"), ("FENCE_STALE", "PARTNER_UNKNOWN")])
def test_partial_release_into_a_tight_segment_stops_the_released_arm_at_once(code, reason):
    left, right, coordinator = _pair([_barrier("both_grasped", "waiting")], [_barrier("both_grasped", "waiting")])
    right.refuse_release = code
    decisions = coordinator.tick()
    assert len(left.sent("ReleaseBarrier")) == 1 and left.view["barriers"][0]["state"] == "released"
    (stop,) = left.sent("StopLocal")
    assert stop["reason"] == reason
    assert [item["decision"] for item in decisions].count("stop") == 1


def test_a_refused_first_release_releases_nobody_else():
    left, right, coordinator = _pair([_barrier("both_grasped", "waiting")], [_barrier("both_grasped", "waiting")])
    left.refuse_release = "FENCE_STALE"
    coordinator.tick()
    assert len(left.sent("ReleaseBarrier")) == 1 and right.sent("ReleaseBarrier") == []
    assert left.sent("StopLocal") == right.sent("StopLocal") == []


def test_partial_release_into_a_loose_segment_is_not_stopped():
    left, right, coordinator = _pair([_barrier("both_ready", "waiting", "loose")],
                                     [_barrier("both_ready", "waiting", "loose")])
    right.refuse_release = "FENCE_STALE"
    coordinator.tick()
    assert left.sent("StopLocal") == []


def test_half_released_tight_barrier_with_a_closed_partner_fence_stops_the_released_arm():
    left, right, coordinator = _pair([_barrier("both_grasped", "released")], [_barrier("both_grasped", "waiting")])
    left.view["coupling_now"] = "tight"
    right.view["fence_open"] = False
    coordinator.tick()
    assert right.sent("ReleaseBarrier") == []
    (stop,) = left.sent("StopLocal")
    assert stop["reason"] == "PARTNER_UNKNOWN"


def test_a_partner_that_succeeded_is_not_a_partner_problem():
    left, right, coordinator = _pair([], [])
    left.view["coupling_now"] = "tight"
    coordinator.tick()
    right.view["action_state"] = "SUCCEEDED"
    for _ in range(3):
        coordinator.tick()
    assert left.sent("StopLocal") == []


def test_a_failed_partner_stays_failed_after_it_leaves_the_unresolved_list():
    left, right, coordinator = _pair([], [])
    coordinator.tick()
    right.view["action_state"] = "FAILED"
    coordinator.tick()  # left not yet tight: no stop, but the failure is remembered
    left.view["coupling_now"] = "tight"
    decisions = coordinator.tick()
    assert [item["reason"] for item in decisions if item["decision"] == "stop"] == ["PARTNER_FAILED"]


# --- the same coordinator against two real owner-side APIs (no ROS) ---------------------------

BARRIERS = [{"barrier_id": "both_ready", "before_first_phase": True, "coupling_after": "loose", "max_wait_s": 30.0},
            {"barrier_id": "both_grasped", "after_phase": "grasp", "coupling_after": "tight", "max_wait_s": 30.0}]
POSE = {"x": 0.1, "y": 0.2, "z": 0.3, "yaw": 0.0}


def _grant(instance, partner):
    return FleetCellTransferGrant.model_validate({
        "mission_id": "m-1", "step_id": "s-1", "action_id": f"a-{instance}", "attempt_id": f"t-{instance}",
        "request_digest": "0" * 64, "workcell_id": "cell-1", "instance_id": instance,
        "action_kind": "CELL_TRANSFER", "cell_transfer": {
            "job_id": "job-1", "recipe_sha256": "a" * 64, "cell_sha256": "b" * 64, "step_index": 0,
            "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base", "home": POSE, "pick": POSE,
            "place": POSE, "pick_approach_z": 0.5, "place_approach_z": 0.5, "carry_z": 0.6,
            "barriers": BARRIERS},
        "capability_revision": "c", "config_revision": "r", "authority_epoch": 2, "dispatch_generation": 8,
        "issued_at": NOW, "expires_at": NOW + timedelta(seconds=30), "arm_role": instance.split("-")[-1],
        "pair_id": "pair-1", "partner_instance_id": partner, "coupling": "tight"})


class RealOwner:
    """Owner-side ActionApi + journal for one arm, reached as the coordinator UID."""

    def __init__(self, tmp_path, instance, partner):
        self.store = ActionStore(tmp_path / f"{instance}.sqlite3")
        self.stop = LocalStopController(self.store.path, workcell_id="cell-1", instance_id=instance)
        self.stop.rearm(authority_epoch=2, dispatch_generation=8, operator_confirmed=True,
                        fleet_fence_current=lambda *_: True)
        self.grant = _grant(instance, partner)
        self.store.create_action(
            workcell_id="cell-1", instance_id=instance, principal_id=f"fleet-uid-{FLEET}",
            request_key=self.grant.action_id, action_id=self.grant.action_id, action_kind="CELL_TRANSFER",
            configuration_revision="r", observation_id="", owner_generation=8,
            payload=self.grant.model_dump(mode="json"))
        self.store.begin_submission(self.grant.action_id, expected_generation=8, attempt_id=self.grant.attempt_id)
        runner = ActionRunner(self.store, object(), workcell_id="cell-1", instance_id=instance,
                              principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={FLEET},
                              current_fence=lambda *_: True, capability_current=lambda _grant: True)
        self.journal = BarrierJournal(self.store.path)
        self.supervisor = BarrierSupervisor(
            self.journal, self.store, coordinator_liveness_s=2.0,
            hold_owner=make_coordinator_hold(self.stop, self.store, cancel_active=lambda: None),
            fence_current=lambda epoch, generation: self.stop.is_open(
                authority_epoch=epoch, dispatch_generation=generation))
        peer_api = CoordinatorPeerApi(
            self.store, self.journal, self.supervisor, workcell_id="cell-1",
            coordinator_peer_uids={COORDINATOR}, fleet_peer_uids={FLEET}, read_receipt=runner.read_receipt,
            fence_current=lambda epoch, generation: self.stop.is_open(
                authority_epoch=epoch, dispatch_generation=generation))
        stop_api = LocalStopApi(self.stop, source_by_peer_uid={FLEET: StopRequestSource.FLEET,
                                                               COORDINATOR: StopRequestSource.COORDINATOR})
        self.api = ActionApi(runner, stop_api=stop_api, coordinator_api=peer_api)

    def request(self, document):
        return self.api.dispatch(document, peer_uid=COORDINATOR)


def test_coordinator_releases_real_owner_barriers_and_stops_a_tight_partner(tmp_path):
    left = RealOwner(tmp_path, "omx-left", "omx-right")
    right = RealOwner(tmp_path, "omx-right", "omx-left")
    coordinator = WorkcellCoordinator({"omx-left": left, "omx-right": right})
    left.supervisor.phase_gate(left.grant, "approach")
    coordinator.tick()
    assert left.journal.rows(left.grant.action_id, left.grant.attempt_id)["both_ready"]["state"] == "waiting"
    right.supervisor.phase_gate(right.grant, "approach")
    coordinator.tick()
    for arm in (left, right):
        assert arm.supervisor.phase_gate(arm.grant, "approach") is True
        assert arm.supervisor.phase_gate(arm.grant, "transfer") is not True
    coordinator.tick()
    for arm in (left, right):
        assert arm.supervisor.phase_gate(arm.grant, "transfer") is True
    # Tight segment now: the right arm fails, the coordinator stops the left one.
    right.store.hold_action(right.grant.action_id, right.grant.attempt_id, reason="ROS_GOAL_FAILED")
    decisions = coordinator.tick()
    assert [(item["instance_id"], item["reason"], item["status"]) for item in decisions
            if item["decision"] == "stop"] == [("omx-left", "PARTNER_FAILED", 200)]
    snapshot = left.stop.snapshot(workcell_id="cell-1", instance_id="omx-left")
    assert (snapshot.source, snapshot.reason) == (StopRequestSource.COORDINATOR, "PARTNER_FAILED")


def test_owner_fence_closed_on_a_waiting_partner_reaches_the_released_arm_as_partner_failed(tmp_path):
    left = RealOwner(tmp_path, "omx-left", "omx-right")
    right = RealOwner(tmp_path, "omx-right", "omx-left")
    coordinator = WorkcellCoordinator({"omx-left": left, "omx-right": right})
    for arm in (left, right):
        arm.supervisor.phase_gate(arm.grant, "approach")
    coordinator.tick()
    for arm in (left, right):
        arm.supervisor.phase_gate(arm.grant, "transfer")
    # Partial release: only the left arm passes the tight barrier, then the right latch closes.
    released = left.request({
        "version": 2, "operation": "ReleaseBarrier", "action_id": left.grant.action_id, "pair_id": "pair-1",
        "barrier_id": "both_grasped", "authority_epoch": 2, "dispatch_generation": 8,
        "partner_arrival": {"instance_id": "omx-right", "action_id": right.grant.action_id, "arrived_at": "t"}})
    assert released["status"] == 200 and released["barrier"]["release"]["coordinator"] == "coordinator-uid-2002"
    right.stop.trip(LocalStopRequest(workcell_id="cell-1", instance_id="omx-right", authority_epoch=2,
                                     dispatch_generation=8, requested_at=NOW, reason="operator stop"),
                    source=StopRequestSource.FLEET)
    assert right.supervisor.end_fenced_waits() == [right.grant.action_id]
    action = right.store.get_action(right.grant.action_id)
    assert (action["state"], action["reason"]) == ("FAILED", "STOP_FENCED_AT_BARRIER")
    decisions = coordinator.tick()
    assert [(item["instance_id"], item["reason"]) for item in decisions if item["decision"] == "stop"] == [
        ("omx-left", "PARTNER_FAILED")]
