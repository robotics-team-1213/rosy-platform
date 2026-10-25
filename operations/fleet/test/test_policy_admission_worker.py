"""D-865 P2c policy admission worker: same checks as a human admit, per tick.

Fake stores only — no FastAPI, no live SQLite for the mission side; the audit log
is the real durable store on a temp file because the budget is its contract.
"""

from fleet.server.missions.policy_admission import (
    PolicyAdmissionCore,
    PolicyAdmissionSettings,
)
from fleet.server.missions.policy_admission_audit import PolicyAdmissionAuditLog
from fleet.server.missions.policy_admission_worker import PolicyAdmissionWorker


class FakeProposals:
    def __init__(self, *proposals):
        self._proposals = list(proposals)

    def list_resolved(self, *, limit=20):
        return self._proposals[:limit]


class FakeMissions:
    def __init__(self, records=None, admit_error=None):
        self.records = records or {}
        self.admits = []
        self.admit_error = admit_error

    def get(self, mission_id):
        return self.records.get(mission_id)

    def admit(self, mission_id, *, actor_id, expected_generation, resources):
        if self.admit_error is not None:
            raise self.admit_error
        self.admits.append({"mission_id": mission_id, "actor_id": actor_id,
                            "expected_generation": expected_generation,
                            "resources": resources})
        return {"mission_id": mission_id, "status": "READY"}


class SilentLog:
    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


def _worker(tmp_path, *, missions, proposals, enabled=True, robots=("rosy_01",),
            max_admits=2, issued_provider=None):
    settings = PolicyAdmissionSettings(
        enabled=enabled, robots=frozenset(robots),
        step_approval_kinds=frozenset({"one_person"}),
        max_admits=max_admits, scope_revision="rev-1")
    core = PolicyAdmissionCore(
        settings, now=lambda: "2026-10-25T00:00:00Z",
        issued_provider=issued_provider)
    audit = PolicyAdmissionAuditLog(str(tmp_path / "audit.db"))
    core.audit_log = audit
    return PolicyAdmissionWorker(core=core, proposal_store=proposals,
                                 mission_service=missions, audit_log=audit,
                                 log=SilentLog(), clock=lambda: 0.0), core, audit


def _proposal(mission_id="m-1", resources=(("robot", "rosy_01"),),
              generation=3, state="RESOLVED"):
    return {"proposal_id": mission_id, "mission_id": mission_id, "state": state,
            "source_dispatch_generation": generation,
            "resolution": {"resources": [list(pair) for pair in resources]}}


def _record(action_kind="TRIP", status="PROPOSED"):
    return {"status": status, "action_kind": action_kind}


class TestPolicyAdmissionWorkerTick:
    def test_in_scope_one_person_trip_is_admitted(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(_proposal()))
        assert worker.tick() == 1
        assert missions.admits == [{"mission_id": "m-1",
                                    "actor_id": "fleet-policy-admission",
                                    "expected_generation": 3,
                                    "resources": [("robot", "rosy_01")]}]
        assert audit.latest()[0]["outcome"] == "ADMITTED"

    def test_proposer_only_pick_place_stays_human(self, tmp_path):
        missions = FakeMissions({"m-1": _record("PICK_PLACE")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(_proposal()))
        assert worker.tick() == 1
        assert missions.admits == []
        assert audit.latest()[0]["reason"] == "APPROVAL_RULE_OUT_OF_SCOPE"

    def test_robot_out_of_scope_holds(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(
                                       _proposal(resources=(("robot", "rosy_02"),))))
        assert worker.tick() == 1
        assert missions.admits == []
        assert audit.latest()[0]["reason"] == "ROBOT_OUT_OF_SCOPE"

    def test_unbound_robot_holds(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(
                                       _proposal(resources=(("workcell", "wc"),))))
        assert audit.latest()[0]["reason"] == "ROBOT_UNBOUND"

    def test_admit_refusal_is_recorded_not_raised(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP")},
                                admit_error=ValueError("stop generation changed"))
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(_proposal()))
        assert worker.tick() == 1
        assert audit.latest()[0]["reason"] == "ADMIT_REFUSED"

    def test_budget_exhaustion_stops_the_batch(self, tmp_path):
        missions = FakeMissions({f"m-{i}": _record("TRIP") for i in (1, 2, 3)})
        worker, core, audit = _worker(tmp_path, missions=missions,
                                      proposals=FakeProposals(
                                          *[_proposal(f"m-{i}") for i in (1, 2, 3)]),
                                      max_admits=2)
        worker.tick()
        assert len(missions.admits) == 2
        assert audit.issued_count("rev-1") == 2
        assert core.status().reason == "EXHAUSTED"

    def test_disabled_scope_ticks_zero_without_touching_stores(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(_proposal()),
                                   enabled=False)
        assert worker.tick() == 0
        assert audit.latest() == []

    def test_already_admitted_mission_is_skipped(self, tmp_path):
        missions = FakeMissions({"m-1": _record("TRIP", status="READY")})
        worker, _, audit = _worker(tmp_path, missions=missions,
                                   proposals=FakeProposals(_proposal()))
        assert worker.tick() == 0
        assert audit.latest() == []
