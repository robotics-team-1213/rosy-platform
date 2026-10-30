"""D-930: a confirmed job gets fresh measured facts without any new execution, claim or receipt."""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3

import pytest

from test_physical_transfer_observer_api import CONTEXT, OBSERVER, approved, headers, rig  # noqa: F401
from test_physical_transfer_evidence_export import close_job
from test_arm_transfer_job_api import PATH
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401


def recheck_samples(rig, post, not_before_ns):
    request = deepcopy(post)
    request["phase"] = "RECHECK"
    for sample, offset in zip(request["observations"], (100_000_000, 300_000_000)):
        at = not_before_ns + offset
        sample.update(evidence_id="recheck-" + sample["evidence_id"], sequence=sample["sequence"] + 10,
                      object_observed_at_ns=at)
        for owner in sample["owners"]:
            owner.update(links_observed_at_ns=at, gripper_observed_at_ns=at)
            joints = owner["joints"]
            joints.update(sample_id="recheck-" + joints["sample_id"], sequence=joints["sequence"] + 10, observed_at_ns=at)
    rig.clock[0] = not_before_ns + 350_000_000
    return request


def events(rig):
    with sqlite3.connect(rig.db) as connection:
        return [row[0] for row in connection.execute("SELECT event_type FROM fleet_cell_events ORDER BY rowid")]


def test_recheck_records_fresh_facts_and_changes_nothing_else(rig):
    mission, post, receipt = close_job(rig)
    url = PATH + "/" + mission
    evidence = rig.client.get(url + "/physical-evidence", headers=headers("harbor")).json()
    response = rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "final-1"})
    assert response.status_code == 200, response.text
    waiting = response.json()["recheck"]
    assert waiting["status"] == "WAITING_OBSERVATIONS" and waiting["evidence_document"] is None
    assert waiting["requested_at_ns"] == rig.clock[0]
    assert (waiting["action_id"], waiting["attempt_id"]) == (receipt["action_id"], receipt["attempt_id"])
    assert rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "final-1"}).json() == response.json()
    assert rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "final-2"}).status_code == 409
    assert rig.client.post(url + "/rechecks", headers=headers("other"), json={"recheck_key": "x"}).status_code == 403

    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    assert (context["mission_id"], context["phase"], context["status"]) == (mission, "RECHECK", "GOAL_CONFIRMED")
    assert context["not_before_ns"] == waiting["requested_at_ns"] and context["capture_deadline"] is None
    request = recheck_samples(rig, post, context["not_before_ns"])
    reply = rig.client.post(url + "/observations", headers=OBSERVER, json=request)
    assert reply.status_code == 200, reply.text
    assert reply.json()["receipt"] == receipt and reply.json()["job"]["status"] == "GOAL_CONFIRMED"

    confirmed = rig.client.get(url + "/rechecks/final-1", headers=headers("harbor")).json()["recheck"]
    assert confirmed["status"] == "CONFIRMED" and confirmed["validated_at_ns"] == rig.clock[0]
    assert sha256(confirmed["evidence_document"].encode()).hexdigest() == confirmed["evidence_digest"]
    document = json.loads(confirmed["evidence_document"])
    assert document["context"]["phase"] == "RECHECK"
    assert document["samples"][1]["owners"][0]["joints"] == request["observations"][1]["owners"][0]["joints"]
    assert confirmed["zone_ids"] == list(rig.installation.policy.zone_resource_ids)
    assert rig.client.get(url + "/physical-evidence", headers=headers("harbor")).json() == evidence
    assert rig.client.get(CONTEXT, headers=OBSERVER).json() == {"context": None}
    assert rig.client.get(url + "/rechecks/final-1", headers=headers("other")).status_code == 403
    assert rig.client.get(url + "/rechecks/absent", headers=headers("harbor")).status_code == 404
    assert len(rig.port.submitted) == 1
    assert events(rig)[-2:] == ["PHYSICAL_TRANSFER_RECHECK_REQUESTED", "PHYSICAL_TRANSFER_RECHECKED"]
    # A finished recheck frees the job for the next one; the stored proof is never replaced.
    assert rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "final-2"}).status_code == 200
    assert rig.client.get(url + "/rechecks/final-1", headers=headers("harbor")).json()["recheck"] == confirmed


@pytest.mark.parametrize("change", ["stale", "no-joints", "moved", "request"])
def test_recheck_never_accepts_old_partial_or_wrong_facts(rig, change):
    mission, post, _ = close_job(rig)
    url = PATH + "/" + mission
    rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "final-1"})
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = recheck_samples(rig, post, context["not_before_ns"])
    if change == "stale":
        request["observations"][0]["object_observed_at_ns"] = context["not_before_ns"]
    elif change == "no-joints":
        request["observations"][1]["owners"][0].pop("joints")
    elif change == "moved":
        request["observations"][1]["object_pose"]["position_m"][0] += 1.0
    else:
        request["expected_request_digest"] = "f" * 64
    before = events(rig)
    assert rig.client.post(url + "/observations", headers=OBSERVER, json=request).status_code == 409
    assert rig.client.get(url + "/rechecks/final-1", headers=headers("harbor")).json()["recheck"]["status"] \
        == "WAITING_OBSERVATIONS"
    assert events(rig) == before


def test_an_unconfirmed_job_cannot_be_rechecked(rig):
    url = PATH + "/" + approved(rig)
    assert rig.client.post(url + "/rechecks", headers=headers("harbor"), json={"recheck_key": "early"}).status_code == 409


def test_recheck_facts_without_a_waiting_request_are_refused(rig):
    closed, post, _ = close_job(rig)
    request = recheck_samples(rig, post, rig.clock[0])
    assert rig.client.post(PATH + "/" + closed + "/observations", headers=OBSERVER, json=request).status_code == 409


def test_recheck_wire_binds_proof_bytes_and_measured_joints():
    from core_common.protocol.schemas import ArmTransferRecheck
    waiting = dict(mission_id="m-1", recheck_key="k", action_id="a-1", attempt_id="t-1", requested_at_ns=5,
                   status="WAITING_OBSERVATIONS", evidence_document=None, evidence_digest=None,
                   validated_at_ns=None, zone_ids=["zone"])
    ArmTransferRecheck.model_validate(waiting)
    with pytest.raises(ValueError):
        ArmTransferRecheck.model_validate({**waiting, "evidence_digest": "a" * 64})
    with pytest.raises(ValueError):
        ArmTransferRecheck.model_validate({**waiting, "status": "CONFIRMED", "evidence_document": "{}",
                                           "evidence_digest": "a" * 64, "validated_at_ns": 6})
