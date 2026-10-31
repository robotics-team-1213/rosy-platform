"""D-938 policy admission of ARM_TRANSFER: the human admit's checks under a scoped policy principal."""
from contextlib import closing
import json

import pytest
from pydantic import ValidationError

from core_common.protocol.policy_admission import POLICY_ADMISSION_PRINCIPAL, PolicyAdmissionScope
from fleet.server.arm_transfer_policy_admission import ArmTransferPolicyWorker
from fleet.server.mission_store import MissionConflict
from fleet.server.missions.policy_admission import PolicyAdmissionCore, PolicyAdmissionSettings
from fleet.server.missions.policy_admission_audit import PolicyAdmissionAuditLog
from test_job_provenance_migration import connect
from test_physical_transfer_store import NOW, OPERATOR, admit, claims, create, installation, rig  # noqa: F401
from test_physical_transfer_evidence import geometry, policy  # noqa: F401

SCOPE = dict(scope_revision="arm-rev-1", enabled_by="operator-2", proposers=frozenset({"harbor"}))


def policy_admit(store, proposal, **changes):
    arguments = dict(SCOPE, capabilities=store.installation.capabilities, capabilities_observed_at_ns=NOW - 1)
    return store.admit_by_policy(proposal["mission_id"], **{**arguments, **changes})


def events(path, mission_id):
    with closing(connect(path)) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT event_type,actor_id,detail_json FROM fleet_cell_events WHERE mission_id=?", (mission_id,))]


# --- store -----------------------------------------------------------------------------------------

def test_policy_admit_runs_the_same_admission_and_records_the_scope(rig):
    path, _, control, store = rig
    proposal = create(store)
    ready = policy_admit(store, proposal)
    assert ready["status"] == "READY"
    assert ready["approved_by"] == POLICY_ADMISSION_PRINCIPAL
    assert ready["dispatch_generation"] == control["generation"]
    assert {row["owner_id"] for row in claims(path)} == {ready["mission_id"]}
    admitted = [e for e in events(path, ready["mission_id"]) if e["event_type"] == "PHYSICAL_TRANSFER_ADMITTED"]
    assert len(admitted) == 1 and admitted[0]["actor_id"] == POLICY_ADMISSION_PRINCIPAL
    detail = json.loads(admitted[0]["detail_json"])
    assert (detail["policy_scope_revision"], detail["policy_enabled_by"]) == ("arm-rev-1", "operator-2")


@pytest.mark.parametrize("changes", [dict(proposers=frozenset({"other-app"})), dict(enabled_by="harbor")])
def test_proposer_outside_scope_or_equal_to_the_enabler_is_refused(rig, changes):
    path, _, _, store = rig
    proposal = create(store)
    with pytest.raises(PermissionError):
        policy_admit(store, proposal, **changes)
    assert not claims(path)


def test_closed_stop_generation_and_stale_capability_are_refused(rig):
    path, _, _, store = rig
    proposal = create(store)
    with pytest.raises(MissionConflict):
        policy_admit(store, proposal, capabilities_observed_at_ns=NOW - store.installation.policy.max_age_ns - 1)
    with closing(connect(path)) as connection:
        connection.execute("UPDATE fleet_dispatch_control SET dispatch_enabled=0 WHERE control_id=1")
        connection.commit()
    with pytest.raises(MissionConflict):
        policy_admit(store, proposal)
    assert not claims(path)


def test_busy_arm_resources_hold_a_second_policy_admit(rig):
    path, _, control, store = rig
    first, second = create(store), create(store, key="move-2")
    admit(store, first, control)  # a human-admitted operation holds the participant claims
    with pytest.raises(MissionConflict):
        policy_admit(store, second)
    assert {row["owner_id"] for row in claims(path)} == {first["mission_id"]}


def test_already_admitted_operation_is_not_policy_admitted_again(rig):
    _, _, control, store = rig
    proposal = create(store)
    admit(store, proposal, control)
    with pytest.raises(MissionConflict):
        policy_admit(store, proposal)


def test_only_the_policy_principal_may_skip_the_named_operator_check(rig):
    _, _, control, store = rig
    proposal = create(store)
    with closing(store._journal._connect()) as connection:
        with pytest.raises(PermissionError):
            store._admit(connection, proposal["mission_id"], actor="operator-2",
                         expected_proposal_digest=proposal["proposal_digest"], expected_generation=control["generation"],
                         capabilities=store.installation.capabilities, capabilities_observed_at_ns=NOW - 1)


def test_scope_change_before_commit_rolls_the_admission_back(rig):
    path, _, _, store = rig
    proposal = create(store)
    with pytest.raises(MissionConflict):
        policy_admit(store, proposal, recheck=lambda: "DISABLED")
    assert not claims(path)
    assert store.proposed_ids() == [(proposal["mission_id"], "harbor")]
    with closing(connect(path)) as connection:
        assert not connection.execute("SELECT * FROM fleet_physical_transfer_approvals").fetchall()


def test_proposed_ids_lists_only_proposed_physical_operations_oldest_first(rig):
    _, _, control, store = rig
    first, second = create(store), create(store, key="move-2")
    assert store.proposed_ids() == [(first["mission_id"], "harbor"), (second["mission_id"], "harbor")]
    admit(store, first, control)
    assert store.proposed_ids() == [(second["mission_id"], "harbor")]


# --- core ------------------------------------------------------------------------------------------

def arm_settings(**overrides):
    base = dict(enabled=True, robots=frozenset({"arm-a", "arm-b"}), step_approval_kinds=frozenset({"arm_transfer"}),
                max_admits=2, valid_until="2026-12-31T00:00:00Z", scope_revision="arm-rev-1",
                proposers=frozenset({"harbor"}))
    base.update(overrides)
    return PolicyAdmissionSettings(**base)


def arm_core(now="2026-10-31T00:00:00Z", **overrides):
    return PolicyAdmissionCore(arm_settings(**overrides), lambda: now)


@pytest.mark.parametrize("missing", ["proposers", "valid_until"])
def test_arm_transfer_config_requires_proposers_and_expiry(missing):
    section = {"enabled": True, "robots": ["arm-a"], "step_approval_kinds": ["arm_transfer"],
               "proposers": ["harbor"], "valid_until": "2026-12-31T00:00:00Z"}
    del section[missing]
    with pytest.raises(ValueError):
        PolicyAdmissionSettings.from_config(section)


def test_config_rejects_two_person_and_naive_expiry():
    with pytest.raises(ValueError):
        PolicyAdmissionSettings.from_config({"enabled": True, "robots": ["arm-a"], "step_approval_kinds": ["two_person"]})
    with pytest.raises(ValueError):
        PolicyAdmissionSettings.from_config({"enabled": True, "robots": ["arm-a"], "step_approval_kinds": ["one_person"],
                                             "valid_until": "2026-12-31T00:00:00"})


def test_arm_scope_needs_a_runtime_named_enabler_distinct_from_the_proposer():
    core = arm_core()
    judge = lambda proposer="harbor": core.hold_reason(robot_id="arm-a", approval_rule="arm_transfer", proposer=proposer)
    assert judge() == "SCOPE_NOT_ACKNOWLEDGED"  # config default alone is not the second person
    core.toggle(enabled=True, actor="operator-2")
    assert core.status().enabled_by == "operator-2"
    assert judge() is None
    assert judge("other-app") == "PROPOSER_OUT_OF_SCOPE"
    assert core.hold_reason(robot_id="arm-z", approval_rule="arm_transfer", proposer="harbor") == "ROBOT_OUT_OF_SCOPE"
    assert core.hold_reason(robot_id="arm-a", approval_rule="one_person") == "APPROVAL_RULE_OUT_OF_SCOPE"
    core.toggle(enabled=True, actor="harbor")
    assert judge() == "PROPOSER_IS_ENABLER"
    core.toggle(enabled=False, actor="operator-2")
    assert judge() == "DISABLED" and core.status().enabled_by is None


@pytest.mark.parametrize("kind,rule", [("arm_transfer", "arm_transfer"), ("one_person", "one_person")])
def test_expired_scope_holds_every_kind(kind, rule):
    core = arm_core(now="2027-01-01T00:00:00Z", step_approval_kinds=frozenset({kind}))
    core.toggle(enabled=True, actor="operator-2")
    assert core.hold_reason(robot_id="arm-a", approval_rule=rule, proposer="harbor") == "EXPIRED"
    status = core.status()
    assert (status.reason, status.admits_remaining) == ("EXPIRED", 0)


def test_arm_scope_contract_requires_proposers_and_expiry():
    with pytest.raises(ValidationError):
        PolicyAdmissionScope(enabled=True, robots=["arm-a"], step_approval_kinds=["arm_transfer"],
                             valid_until="2026-12-31T00:00:00Z", scope_revision="r")
    with pytest.raises(ValidationError):
        PolicyAdmissionScope(enabled=True, robots=["arm-a"], step_approval_kinds=["two_person"], scope_revision="r")
    scope = PolicyAdmissionScope(enabled=True, robots=["arm-a"], step_approval_kinds=["arm_transfer"],
                                 proposers=["harbor"], valid_until="2026-12-31T00:00:00Z", scope_revision="r")
    assert scope.proposers == ["harbor"]


# --- worker ----------------------------------------------------------------------------------------

class Participant:
    def __init__(self, instance_id):
        self.instance_id = instance_id


class FakeStore:
    def __init__(self, proposed, refuse=None):
        self.proposed = list(proposed)
        self.refuse = refuse
        self.before_commit = None
        self.calls = []
        self.installation = type("I", (), {"policy": type("P", (), {
            "participants": (Participant("arm-a"), Participant("arm-b"))})()})()

    def proposed_ids(self, *, limit):
        return self.proposed[:limit]

    def admit_by_policy(self, mission_id, **kwargs):
        self.calls.append((mission_id, kwargs))
        if self.refuse is not None:
            raise self.refuse
        if self.before_commit is not None:
            self.before_commit()
        reason = kwargs["recheck"]()
        if reason is not None:
            raise MissionConflict(reason)
        self.proposed = [p for p in self.proposed if p[0] != mission_id]
        return {"mission_id": mission_id, "status": "READY", "dispatch_generation": 7}


class FakeDispatcher:
    def __init__(self):
        self.prepared = []

    def prepare(self, mission_id):
        self.prepared.append(mission_id)


class SilentLog:
    def warning(self, *a, **k):
        pass

    def exception(self, *a, **k):
        pass


def worker_rig(tmp_path, store, *, enabled_by="operator-2", max_admits=2):
    audit = PolicyAdmissionAuditLog(str(tmp_path / "audit.sqlite3"))
    core = PolicyAdmissionCore(arm_settings(max_admits=max_admits), lambda: "2026-10-31T00:00:00Z",
                               issued_provider=audit.issued_count)
    if enabled_by:
        core.toggle(enabled=True, actor=enabled_by)
    dispatcher = FakeDispatcher()
    worker = ArmTransferPolicyWorker(core=core, store=store, read_capabilities=lambda: (("cap",), NOW - 1),
                                     dispatcher=dispatcher, audit_log=audit, log=SilentLog(), clock=lambda: 0)
    return worker, audit, dispatcher


def test_worker_admits_one_scoped_proposal_per_tick_and_prepares_it(tmp_path):
    store = FakeStore([("m-human", "operator-9"), ("m-1", "harbor"), ("m-2", "harbor")])
    worker, audit, dispatcher = worker_rig(tmp_path, store)
    assert worker.tick() == 1
    assert [c[0] for c in store.calls] == ["m-1"]  # the human proposal is passed over silently
    call = store.calls[0][1]
    assert (call["enabled_by"], call["proposers"], call["scope_revision"]) == ("operator-2", frozenset({"harbor"}), "arm-rev-1")
    assert dispatcher.prepared == ["m-1"]
    assert [(r["mission_id"], r["outcome"]) for r in audit.latest()] == [("m-1", "ADMITTED")]
    assert worker.tick() == 1 and worker.tick() == 0  # second admit, then the budget of 2 is spent
    assert [c[0] for c in store.calls] == ["m-1", "m-2"]


def test_worker_records_a_refusal_once_and_retries(tmp_path):
    store = FakeStore([("m-1", "harbor")], refuse=MissionConflict("claim busy"))
    worker, audit, dispatcher = worker_rig(tmp_path, store)
    assert worker.tick() == 1 and worker.tick() == 1
    assert len(store.calls) == 2 and not dispatcher.prepared
    assert [(r["outcome"], r["reason"]) for r in audit.latest()] == [("HELD", "ADMIT_REFUSED:MissionConflict")]


def test_worker_does_nothing_without_a_named_enabler(tmp_path):
    store = FakeStore([("m-1", "harbor")])
    worker, audit, _ = worker_rig(tmp_path, store, enabled_by=None)
    assert worker.tick() == 0 and not store.calls and audit.latest() == []


@pytest.mark.parametrize("change", ["off", "enabler"])
def test_toggle_during_the_admit_transaction_holds_it(tmp_path, change):
    store = FakeStore([("m-1", "harbor")])
    worker, audit, dispatcher = worker_rig(tmp_path, store)
    core = worker._core
    store.before_commit = ((lambda: core.toggle(enabled=False, actor="operator-2")) if change == "off"
                           else (lambda: core.toggle(enabled=True, actor="operator-3")))
    assert worker.tick() == 1
    assert not dispatcher.prepared
    assert [r["outcome"] for r in audit.latest()] == ["HELD"]
