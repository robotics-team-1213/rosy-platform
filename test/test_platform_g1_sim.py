"""D-778/D-779/D-781 G1 SIM end to end in one process: the recipe/3 Job compiled by Fleet, dispatched by
the multi-arm CellJobDispatcher to two real OMX cell owners, confirmed by per-step goal evidence.

What is bridged by fakes (UDS, ROS goals, recipe/3 acceptance on the owner, the evidence producer, the
goal predicates) is listed in test/g1_sim_harness.py. Nothing here is ROS-SIM or DEVICE evidence.
Fault cases: D-778 G1 / D-779 §3-5 (claims, pair rule, per-arm HOLD, tight HOLD, one-arm mode).
"""

import sqlite3
from contextlib import closing

import pytest

from g1_layout import G1_FIXTURE, MIXED_FIXTURE, read_documents
from g1_sim_harness import (CELL, MISSION, Rig, as_pair, attach_predicates, compile_submission, quantiles,
                            record_evidence)

from fleet.server.cell_arm_dispatcher import PAIR_REASON
from fleet.server.cell_arm_jobs import TIGHT_PARTNER_REASON
from fleet.server.cell_arm_store import ArmJobStore
from fleet.server.dispatch_admission import reserve
from rosy.processes.palletizing.mixed_plan import descendants

G1_CELL = G1_FIXTURE / "cell_g1.yaml"
RECIPE_2 = MIXED_FIXTURE / "recipe.yaml"
RECIPE_4 = G1_FIXTURE / "recipe_4sku.yaml"
SHARED = "shared_band"


def _rig(tmp_path, recipe=RECIPE_2, *, pair=None, scale=0.002):
    recipe_doc, cell_doc = read_documents(recipe, G1_CELL)
    submission = compile_submission(recipe_doc, cell_doc)
    if pair is not None:
        submission = as_pair(submission, *pair)
    return Rig(tmp_path, attach_predicates(submission, recipe_doc), recipe_doc, cell_doc, time_scale=scale)


def _done(rig):
    return all(step["status"] == "GOAL_CONFIRMED" for step in rig.job()["steps"])


def _arms(job):
    return {arm["arm_role"]: (arm["status"], arm["reason"]) for arm in job["arms"]}


def _claims(rig):
    with closing(sqlite3.connect(rig.path)) as connection:
        return dict(connection.execute("SELECT resource_key, phase FROM fleet_action_claims WHERE owner_id=?",
                                       (MISSION,)).fetchall())


def _assert_claims_belong_to_unfinished_actions(rig):
    job = rig.job()
    placements = {p["step_index"]: p for p in job["placements"]}
    actions = [a for a in job["step_actions"]
               if a["status"] in {"RUNNING", "HOLD"} and a["action_id"] is not None]
    expected = set()
    for action in actions:
        assert action["attempt_id"] is not None and action["grant"] is not None
        assert action["grant"]["dispatch_generation"] == job["dispatch_generation"]
        assert action["grant"]["cell_transfer"]["step_index"] == action["step_index"]
        keys = {f"arm:{CELL}.{action['arm_role']}",
                f"zone:{CELL}.{placements[action['step_index']]['zone_id']}"}
        assert set(action["claims"]) == keys
        expected.update(keys)
    with closing(sqlite3.connect(rig.path)) as connection:
        rows = connection.execute(
            "SELECT resource_key, generation FROM fleet_action_claims WHERE owner_kind='mission' "
            "AND owner_id=? AND resource_kind IN ('arm', 'zone')", (MISSION,)).fetchall()
    assert {key for key, _ in rows} == expected, {"claims": rows, "actions": actions}
    assert all(generation == job["dispatch_generation"] for _, generation in rows)


def _first_two_arm_root(submission):
    """The first Step compiled for both arms that depends on nothing (a shared-band Step)."""
    return next(i for i, step in enumerate(submission["steps"])
                if len(step["placement"]["actions"]) == 2 and not step["placement"]["depends_on"])


def _owner_steps(arm):
    rows = [arm.action(command.command_id.rsplit("-", 1)[0]) for command, _, _ in arm.port.submissions]
    return {row["request"]["payload"]["cell_transfer"]["step_index"]: row for row in rows}


@pytest.mark.parametrize("recipe", [RECIPE_2, RECIPE_4], ids=["2sku", "4sku"])
def test_two_arm_mixed_job_runs_to_goal_confirmed_with_concurrent_zones_and_one_arm_band(tmp_path, recipe):
    rig = _rig(tmp_path, recipe)
    assert rig.run(_done, timeout_s=240.0), _arms(rig.job())
    job = rig.job()
    assert rig.evidence_refused == {}
    assert all(step["goal_evidence"]["satisfied"] is True for step in job["steps"])
    zones = {p["step_index"]: p["zone_id"] for p in job["placements"]}
    assigned = {p["step_index"]: p["assigned"] for p in job["placements"]}
    spans = rig.step_intervals()
    # every Step ran exactly once, on its assigned arm, and its release goal ended
    assert sorted(spans) == list(range(len(job["steps"])))
    assert all([role for role, _, _ in spans[i]] == assigned[i] and spans[i][0][2] is not None for i in spans)
    flat = {i: spans[i][0] for i in spans}
    overlap = [(i, j) for i in flat for j in flat if i < j and flat[i][0] != flat[j][0] and zones[i] != zones[j]
               and flat[i][1] < flat[j][2] and flat[j][1] < flat[i][2]]
    assert overlap, "no two Steps in different zones ran at the same time"
    band = sorted((flat[i][1], flat[i][2]) for i in flat if zones[i] == SHARED)
    assert band and all(a[1] <= b[0] for a, b in zip(band, band[1:])), "two arms in the shared band at once"
    assert all(len(set(moving.get(SHARED, []))) <= 1 for _, moving in rig.zone_samples)
    assert all(len(roles) == len(set(roles)) <= 1 for _, moving in rig.zone_samples for roles in moving.values())
    for arm in rig.arms.values():  # no owner stop or goal cancel was ever needed
        assert arm.stop_snapshot().state.value == "OPEN" and arm.port.cancelled == []
    makespan = max(v[2] for v in flat.values()) - min(v[1] for v in flat.values())
    serial = sum(v[2] - v[1] for v in flat.values())
    # Recorded, not asserted: at this time_scale a goal lasts milliseconds, so on a loaded host the
    # dispatch overhead between Steps can outweigh the overlap. Concurrency is the overlap check above.
    record_evidence(f"e2e-{recipe.stem}", {
        "time_scale": rig.time_scale, "steps": len(flat), "overlapping_pairs": len(overlap),
        "makespan_wall_s": round(makespan, 3), "serial_wall_s": round(serial, 3),
        "makespan_sim_s": round(makespan / rig.time_scale, 1), "serial_sim_s": round(serial / rig.time_scale, 1),
        "rtt_s": rig.rtt.summary()})


@pytest.mark.parametrize("contention", [("arm", f"{CELL}.right"), ("zone", f"{CELL}.{SHARED}")],
                         ids=["right-arm", "shared-zone"])
def test_a_one_sided_claim_failure_of_a_pair_leaves_nothing(tmp_path, monkeypatch, contention):
    recipe_doc, cell_doc = read_documents(RECIPE_2, G1_CELL)
    index = _first_two_arm_root(compile_submission(recipe_doc, cell_doc))
    rig = _rig(tmp_path, pair=(index, "independent"))
    job = rig.job()
    with closing(sqlite3.connect(rig.path)) as connection:
        assert reserve(connection, owner_kind="mission", owner_id="other-job", generation=job["dispatch_generation"],
                       resources=[contention], phase="CLAIMED")
        connection.commit()
    placement = next(p for p in job["placements"] if p["step_index"] == index)
    grants = {role: rig.dispatcher.arms._arm_grant(job, index, role, ["left", "right"], placement, "pair-x")
              for role in ("left", "right")}
    with closing(sqlite3.connect(rig.path)) as connection:
        before = tuple(connection.iterdump())
    started = ArmJobStore(rig.cells).start_actions(
        MISSION, step_index=index, grants={role: g.model_dump(mode="json") for role, g in grants.items()})
    assert started["state"] == "CLAIM_BUSY"
    with closing(sqlite3.connect(rig.path)) as connection:
        assert tuple(connection.iterdump()) == before
    after = rig.job()
    assert not any(key.startswith(("arm:", "zone:")) for key in _claims(rig))
    assert {a["status"] for a in after["step_actions"] if a["step_index"] == index} <= {"WAITING", "READY"}
    assert all(a["action_id"] is None for a in after["step_actions"] if a["step_index"] == index)
    # the dispatcher never starts it either, while the left arm works its own chain
    left_chain = [i for i, p in enumerate(rig.submission["steps"]) if p["placement"]["arm"] == "left" and i < index]
    assert rig.run(lambda r: all(r.job()["steps"][i]["status"] == "GOAL_CONFIRMED" for i in left_chain), timeout_s=60)
    if contention[0] == "arm":
        left = rig.by_role["left"]
        submit = left.port.submit
        held = []

        def hold_unrelated_shared_goal(command, *, on_goal_event):
            dispatched = submit(command, on_goal_event=on_goal_event)
            row = left.action(command.command_id.rsplit("-", 1)[0])
            step_index = row["request"]["payload"]["cell_transfer"]["step_index"]
            zone = next(p["zone_id"] for p in rig.job()["placements"] if p["step_index"] == step_index)
            if step_index != index and zone == SHARED:
                goal = next(g for g in left.port.pending if g.command.command_id == command.command_id)
                goal.due = float("inf")
                held.append(step_index)
            return dispatched

        monkeypatch.setattr(left.port, "submit", hold_unrelated_shared_goal)
        assert rig.run(lambda r: bool(held), timeout_s=60), _claims(rig)
    for _ in range(20):
        rig.tick()
        _assert_claims_belong_to_unfinished_actions(rig)
    assert all(index not in _owner_steps(arm) for arm in rig.arms.values())
    # Later left-arm steps may legitimately hold the shared zone; inspect this blocked pair.
    pair_actions = [a for a in rig.job()["step_actions"] if a["step_index"] == index]
    assert {a["status"] for a in pair_actions} <= {"WAITING", "READY"}
    assert all(a[key] is None for a in pair_actions for key in ("action_id", "attempt_id", "grant"))
    assert all(a["claims"] == [] for a in pair_actions)
    with closing(sqlite3.connect(rig.path)) as connection:
        assert connection.execute(
            "SELECT owner_id, phase, generation FROM fleet_action_claims WHERE resource_key=?",
            (f"{contention[0]}:{contention[1]}",)).fetchone() == ("other-job", "CLAIMED", job["dispatch_generation"])


def test_a_rejected_pair_grant_cancels_the_accepted_partner(tmp_path):
    recipe_doc, cell_doc = read_documents(RECIPE_2, G1_CELL)
    index = _first_two_arm_root(compile_submission(recipe_doc, cell_doc))
    rig = _rig(tmp_path, pair=(index, "independent"))
    right = rig.by_role["right"]
    right.owner.runner.capability_current = lambda grant: grant.cell_transfer.step_index != index
    assert rig.run(lambda r: index in _owner_steps(r.by_role["left"]) and bool(r.transport.cancels), timeout_s=120)
    assert (rig.by_role["left"].instance_id, PAIR_REASON) in rig.transport.cancels
    job = rig.job()
    assert _arms(job)["right"] == ("HOLD", "LOCAL_ACTION_REJECTED")
    assert index not in _owner_steps(right)  # the refusal was before any journal row
    for _ in range(50):
        rig.tick()
    left = rig.by_role["left"]
    left_row = _owner_steps(left)[index]
    assert left_row["state"] not in {"SUCCEEDED", "RUNNING", "ACCEPTED"}  # cancelled, never finished alone
    sent = [(c.phase_id, goal) for c, goal, _ in left.port.submissions
            if c.command_id.startswith(left_row["action_id"])]
    assert [phase for phase, _ in sent] == ["approach"] and sent[0][1] in left.port.cancelled


def test_an_independent_step_failure_holds_only_that_arm_and_zone(tmp_path):
    rig = _rig(tmp_path)
    left_steps = [i for i, s in enumerate(rig.submission["steps"]) if s["placement"]["arm"] == "left"]
    first = left_steps[0]
    rig.by_role["left"].port.fail_phase["transfer"] = 6  # ABORTED: the arm moved, so the owner holds
    deps = [tuple(s["placement"]["depends_on"]) for s in rig.submission["steps"]]
    after = descendants(deps)
    blocked = {first} | after[first]
    right_free = [i for i, s in enumerate(rig.submission["steps"]) if s["placement"]["arm"] == "right"
                  and i not in blocked]
    assert right_free
    assert rig.run(lambda r: all(r.job()["steps"][i]["status"] == "GOAL_CONFIRMED" for i in right_free),
                   timeout_s=240), _arms(rig.job())
    job = rig.job()
    assert _arms(job)["left"][0] == "HOLD" and _arms(job)["right"][0] in {"READY", "RUNNING"}
    zone = next(p["zone_id"] for p in job["placements"] if p["step_index"] == first)
    claims = _claims(rig)
    assert claims[f"arm:{CELL}.left"] in {"HELD", "UNKNOWN"} and claims[f"zone:{CELL}.{zone}"] in {"HELD", "UNKNOWN"}
    assert f"arm:{CELL}.right" not in claims
    assert _owner_steps(rig.by_role["left"])[first]["state"] in {"HOLD", "FAILED"}
    assert set(_owner_steps(rig.by_role["left"])) == {first}  # nothing after the failure on that arm
    assert all(arm.stop_snapshot().state.value == "OPEN" for arm in rig.arms.values())  # no owner stop


def test_a_tight_pair_failure_holds_both_arms_in_the_ledger(tmp_path):
    recipe_doc, cell_doc = read_documents(RECIPE_2, G1_CELL)
    index = _first_two_arm_root(compile_submission(recipe_doc, cell_doc))
    rig = _rig(tmp_path, pair=(index, "tight"))
    rig.by_role["right"].port.fail_phase["transfer"] = 6  # the right arm's first transfer is in the pair
    assert rig.run(lambda r: r.job()["status"] == "HOLD", timeout_s=240), _arms(rig.job())
    arms = _arms(rig.job())
    assert arms["left"] == ("HOLD", TIGHT_PARTNER_REASON) and arms["right"][0] == "HOLD"
    sent = {i for arm in rig.arms.values() for i in _owner_steps(arm)}
    for _ in range(20):
        rig.tick()
    assert {i for arm in rig.arms.values() for i in _owner_steps(arm)} == sent  # nothing new starts


def test_an_offline_arms_shared_band_step_goes_to_the_alternate_arm(tmp_path):
    rig = _rig(tmp_path)
    ArmJobStore(rig.cells).set_arm_offline(MISSION, arm_role="right", actor_id="operator-2",
                                           reason="OWNER_REAPPROVAL")
    moved = [p["step_index"] for p in rig.job()["placements"] if p["assigned"] == ["right"] and p["alternates"]]
    assert moved
    first = moved[0]
    assert rig.run(lambda r: r.job()["steps"][first]["status"] == "GOAL_CONFIRMED" or first in r.evidence_refused,
                   timeout_s=240), _arms(rig.job())
    job = rig.job()
    placement = next(p for p in job["placements"] if p["step_index"] == first)
    assert placement["assigned"] == ["left"]
    event = next(e for e in job["events"] if e["event_type"] == "CELL_STEP_ALTERNATE_ARM")
    assert event["detail"]["primary_arm"] == "right" and event["detail"]["primary_status"] == "OFFLINE"
    assert _owner_steps(rig.by_role["left"])[first]["state"] == "SUCCEEDED"  # planned from the left base
    assert rig.by_role["right"].port.submissions == []
    # The Step stores one predicate per arm (D-781 §5), so the alternate's evidence is judged in its own frame.
    assert first not in rig.evidence_refused
    assert job["steps"][first]["status"] == "GOAL_CONFIRMED"


def test_quantiles_report_the_samples():
    assert quantiles([]) == {"n": 0}
    assert quantiles([0.3, 0.1, 0.2]) == {"n": 3, "p50": 0.2, "p90": 0.3, "p99": 0.3, "max": 0.3}
