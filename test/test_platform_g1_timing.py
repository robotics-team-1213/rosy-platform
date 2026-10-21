"""D-780 G1 SIM timing: two real OMX cell owners and the WorkcellCoordinator on a coordinated pair.

Records barrier waits, coordinator contact gaps and request round trips under the sim goal delays,
checks the proposed start values (README "Proposed values"), and runs the two D-780 G1 stop cases:
the coordinator killed in a tight segment (both arms HOLD within coordinator_liveness_s) and a failure
injected on one arm (the partner HOLDs with a COORDINATOR stop). The UDS is bridged in process
(test/g1_sim_harness.py) except in the Linux-only real-socket round-trip test.
"""

import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from g1_layout import G1_FIXTURE, read_documents
from g1_sim_harness import (InProcessOwnerClient, Rtt, SimArm, arm_grant, compile_submission, pair_grants,
                            quantiles, record_evidence, submit_as_fleet)

from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
from rosy_agent.workcell_coordinator import WorkcellCoordinator

# Proposed start values (D-780 §3-4, README "Proposed values").
COORDINATOR_LIVENESS_S = 1.0  # > 0.25 s UDS bound: 4x; > worst healthy contact gap (period + 3 x 0.25 s)
COORDINATOR_PERIOD_S = 0.1  # coordinator tick: GetBarrier to both owners every 0.1 s
MAX_WAIT_S = {"both_ready": 10.0,  # before any motion: Fleet send skew + owner planning; timeout = FAILED
              "both_grasped": 45.0}  # partner's approach (cap 40 s) + grasp (cap 4 s) + 1 s
UDS_BOUND_S = 0.25  # UnixLocalActionTransport / UnixOwnerClient timeout (D-336)
OWNER_PERIOD_S = 0.01
EPOCH, GENERATION = 2, 8
G1_CELL = G1_FIXTURE / "cell_g1.yaml"
RECIPE_4 = G1_FIXTURE / "recipe_4sku.yaml"


class TimedClient(InProcessOwnerClient):
    """Coordinator client that also timestamps every request (the owner's liveness contacts)."""

    def __init__(self, arm, rtt):
        super().__init__(arm, rtt)
        self.sent = []

    def request(self, document):
        self.sent.append(time.monotonic())
        return super().request(document)


class Pair:
    def __init__(self, tmp_path, *, scale=0.002, liveness_s=COORDINATOR_LIVENESS_S):
        self.recipe_doc, self.cell_doc = read_documents(RECIPE_4, G1_CELL)
        self.submission = compile_submission(self.recipe_doc, self.cell_doc)
        self.arms = {}
        for arm in self.cell_doc["arms"]:
            sim = SimArm(tmp_path / arm["role"], role=arm["role"], workcell_id=arm["workcell_id"],
                         instance_id=arm["instance_id"], home=tuple(arm["home"][k] for k in ("x", "y", "z", "yaw")),
                         time_scale=scale, liveness_s=liveness_s)
            sim.accept(self.recipe_doc, self.cell_doc)
            sim.rearm(EPOCH, GENERATION)
            self.arms[sim.instance_id] = sim
        self.by_role = {arm.role: arm for arm in self.arms.values()}
        self.rtt = Rtt()
        self.clients = {instance: TimedClient(arm, self.rtt) for instance, arm in self.arms.items()}
        self.coordinator = WorkcellCoordinator(self.clients)
        self.alive, self._next = True, 0.0

    def two_arm_steps(self):
        return [i for i, step in enumerate(self.submission["steps"]) if len(step["placement"]["actions"]) == 2]

    def start(self, index):
        grants = pair_grants(self.arms, self.submission, index, epoch=EPOCH, generation=GENERATION,
                             max_wait_s=MAX_WAIT_S)
        for role, grant in grants.items():
            response = submit_as_fleet(self.by_role[role], grant)
            assert response["status"] == 200, response
        return grants

    def loop(self, until, *, timeout_s=60.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for arm in self.arms.values():
                arm.tick()
            now = time.monotonic()
            if self.alive and now >= self._next:
                self.coordinator.tick()
                self._next = now + COORDINATOR_PERIOD_S
            if until():
                return True
            time.sleep(OWNER_PERIOD_S)
        return False

    def state(self, role, grant):
        return self.by_role[role].action(grant.action_id)["state"]

    def in_tight_transfer(self, grants):
        return all(any(goal.command.phase_id == "transfer" for goal in self.by_role[role].port.pending)
                   for role in grants)

    def barrier_waits(self, grants):
        out = {}
        for role, grant in grants.items():
            rows = self.by_role[role].owner.barriers.journal.rows(grant.action_id, grant.attempt_id)
            for barrier_id, row in rows.items():
                if row.get("released_monotonic") is not None:
                    out.setdefault(barrier_id, []).append(row["released_monotonic"] - row["arrived_monotonic"])
        return out

    def contact_gaps(self):
        return [b - a for client in self.clients.values() for a, b in zip(client.sent, client.sent[1:])]


def test_contact_gap_window_excludes_setup_but_keeps_active_delays():
    pair = SimpleNamespace(clients={"left": SimpleNamespace(sent=[0.0, 0.1, 5.0, 5.1, 6.0])})
    assert Pair.contact_gaps(pair, {"left": 2}) == pytest.approx([0.1, 0.9])
    assert max(Pair.contact_gaps(pair)) == pytest.approx(4.9)


def test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds(tmp_path):
    pair = Pair(tmp_path)
    steps = pair.two_arm_steps()
    assert len(steps) >= 3
    waits = {}
    for index in steps:
        grants = pair.start(index)
        assert pair.loop(lambda: all(pair.state(role, g) == "SUCCEEDED" for role, g in grants.items())), {
            role: pair.state(role, g) for role, g in grants.items()}
        for barrier_id, values in pair.barrier_waits(grants).items():
            waits.setdefault(barrier_id, []).extend(values)
    assert sorted(waits) == ["both_grasped", "both_ready"]
    assert all(len(values) == 2 * len(steps) for values in waits.values())
    for barrier_id, values in waits.items():
        assert max(values) < MAX_WAIT_S[barrier_id]
    gaps, rtt = quantiles(pair.contact_gaps()), pair.rtt.summary()
    assert gaps["p99"] < COORDINATOR_LIVENESS_S / 2  # healthy contact never comes near the liveness bound
    assert all(summary["p99"] < UDS_BOUND_S for summary in rtt.values())
    for arm in pair.arms.values():
        assert arm.stop_snapshot().state.value == "OPEN"
    record_evidence("timing-pairs", {"pairs": len(steps), "time_scale": 0.002,
                                     "coordinator_period_s": COORDINATOR_PERIOD_S,
                             "barrier_wait_wall_s": {k: quantiles(v) for k, v in waits.items()},
                             "contact_gap_s": gaps, "rtt_s": rtt})


def test_killing_the_coordinator_in_a_tight_segment_holds_both_arms_within_liveness(tmp_path):
    pair = Pair(tmp_path)
    for arm in pair.arms.values():
        arm.port.hang_phase.add("transfer")  # stay inside the tight segment after both_grasped
    grants = pair.start(pair.two_arm_steps()[0])
    assert pair.loop(lambda: pair.in_tight_transfer(grants))
    pair.alive = False
    killed = time.monotonic()
    held = {}

    def both_held():
        for role, arm in pair.by_role.items():
            snapshot = arm.stop_snapshot()
            if role not in held and snapshot.source.value == "coordinator":
                held[role] = (time.monotonic() - killed, snapshot.reason)
        return len(held) == 2
    assert pair.loop(both_held, timeout_s=COORDINATOR_LIVENESS_S + 5)
    for role, (after, reason) in held.items():
        assert reason == "PARTNER_LINK_LOST"
        assert COORDINATOR_LIVENESS_S - COORDINATOR_PERIOD_S - 0.05 <= after <= COORDINATOR_LIVENESS_S + 0.25
        assert pair.state(role, grants[role]) == "HOLD"
        assert pair.by_role[role].port.cancelled  # the hanging transfer goal was cancelled
    record_evidence("timing-coordinator-kill", {"liveness_s": COORDINATOR_LIVENESS_S,
                                        "hold_after_kill_s": {r: round(v[0], 3) for r, v in held.items()}})


def test_a_failure_in_a_tight_segment_holds_the_partner_with_a_coordinator_stop(tmp_path):
    pair = Pair(tmp_path)
    left, right = pair.by_role["left"], pair.by_role["right"]
    left.port.hang_phase.add("transfer")
    right.port.fail_phase["transfer"] = 6  # ABORTED after the tight barrier
    grants = pair.start(pair.two_arm_steps()[0])

    def left_stopped():
        return left.stop_snapshot().source.value == "coordinator"
    assert pair.loop(left_stopped, timeout_s=30)
    stopped = time.monotonic()
    failed_at = next(t for command, t, status in right.port.finished.values()
                     if command.phase_id == "transfer" and status == 6)
    snapshot = left.stop_snapshot()
    assert snapshot.reason in {"PARTNER_FAILED", "PARTNER_UNKNOWN"}
    assert stopped - failed_at <= COORDINATOR_PERIOD_S + UDS_BOUND_S + 0.1
    assert pair.state("left", grants["left"]) == "HOLD"
    assert pair.state("right", grants["right"]) in {"HOLD", "FAILED"}
    assert right.stop_snapshot().state.value == "OPEN"  # the failed arm holds by itself, no coupled stop
    record_evidence("timing-partner-failure", {"stop_after_failure_s": round(stopped - failed_at, 3),
                                       "reason": snapshot.reason})


@pytest.mark.skipif(not hasattr(socket, "SO_PEERCRED"), reason="real owner UDS needs Linux SO_PEERCRED")
def test_real_uds_round_trip_stays_inside_the_bound(tmp_path):
    root = Path(tempfile.mkdtemp(prefix="g1uds", dir="/tmp"))  # AF_UNIX paths are short
    recipe_doc, cell_doc = read_documents(RECIPE_4, G1_CELL)
    submission = compile_submission(recipe_doc, cell_doc)
    spec = cell_doc["arms"][0]
    arm = SimArm(tmp_path / "left", role=spec["role"], workcell_id=spec["workcell_id"],
                 instance_id=spec["instance_id"], home=tuple(spec["home"][k] for k in ("x", "y", "z", "yaw")),
                 time_scale=0.002, fleet_uid=os.getuid(), socket_root=root)
    arm.accept(recipe_doc, cell_doc)
    arm.rearm(EPOCH, GENERATION)
    (root / arm.instance_id).mkdir()
    server = threading.Thread(target=arm.owner.uds_server.serve_forever, daemon=True)
    server.start()
    try:
        transport, rtt = UnixLocalActionTransport(root, timeout_s=UDS_BOUND_S), Rtt()
        deadline = time.monotonic() + 5
        # bind creates the path before listen; readiness needs a real read-only reply.
        while time.monotonic() < deadline:
            try:
                transport.owner_identity(arm.instance_id)
                break
            except LocalActionUnavailable:
                time.sleep(0.01)
        else:
            pytest.fail("owner UDS did not become ready within five seconds")
        for _ in range(100):
            start = time.perf_counter()
            transport.owner_identity(arm.instance_id)
            rtt.add("GetOwnerIdentity", time.perf_counter() - start)
        index = next(i for i, s in enumerate(submission["steps"]) if s["placement"]["arm"] == "left")
        grant = arm_grant(arm, submission, index, "left", epoch=EPOCH, generation=GENERATION)
        start = time.perf_counter()
        transport.submit(grant)  # journal + D-402 plan + first goal, inside one request
        rtt.add("SubmitAction", time.perf_counter() - start)
        while arm.action(grant.action_id)["state"] not in {"SUCCEEDED", "FAILED", "HOLD"}:
            arm.tick()
            start = time.perf_counter()
            transport.get(grant)
            rtt.add("GetAction", time.perf_counter() - start)
        assert arm.action(grant.action_id)["state"] == "SUCCEEDED"
    finally:
        arm.owner.uds_server.stop()
        server.join(timeout=2)
    summary = rtt.summary()
    assert all(item["p99"] < UDS_BOUND_S for item in summary.values())  # max is recorded, see README
    record_evidence("timing-real-uds", {"rtt_s": summary})
