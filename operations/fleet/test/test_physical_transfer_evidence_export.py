"""Stored, authenticated measurements reach a scoped reader without changing execution."""
from hashlib import sha256
from importlib import import_module
import json
import sqlite3

import pytest

from test_physical_transfer_observer_api import (
    CONTEXT, OBSERVER, approved, headers, measured, rig,
)
from test_arm_transfer_job_api import PATH
from test_physical_transfer_evidence import geometry, policy  # noqa: F401
from test_physical_transfer_store import installation  # noqa: F401


def joint_measurement(timestamp, sequence, *, instance="arm-1"):
    return dict(sample_id=f"joints-{instance}-{sequence}", sequence=sequence,
                observed_at_ns=timestamp, joint_names=["joint1", "joint2"],
                positions_rad=[0.1, -0.2])


def with_joints(request):
    for sample in request["observations"]:
        for owner in sample["owners"]:
            owner["joints"] = joint_measurement(sample["object_observed_at_ns"], sample["sequence"],
                                                instance=owner["instance_id"])
    return request


def close_job(rig, *, joints=True):
    mission = approved(rig)
    url = PATH + "/" + mission
    for phase in ("PRE_DISPATCH", "POST_ACTION"):
        context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
        request = measured(rig, context, phase=phase)
        if joints:
            with_joints(request)
        response = rig.client.post(url + "/observations", headers=OBSERVER, json=request)
        assert response.status_code == 200, response.text
        if phase == "PRE_DISPATCH":
            assert rig.app.state.arm_transfer_dispatcher.tick()["status"] == "ACTION_SUCCEEDED"
    return mission, request, response.json()["receipt"]


def test_source_joint_facts_are_closed_finite_and_ordered():
    contracts = import_module("core_common.protocol.arm_transfer_observations")
    cls = contracts.ArmJointObservation
    original = joint_measurement(1_000_000_000, 4)
    facts = cls.model_validate(original)
    original["positions_rad"][0] = 9.0
    assert facts.positions_rad == (0.1, -0.2)
    for changes in ({"joint_names": ["joint1", "joint1"]}, {"positions_rad": [0.1]},
                    {"positions_rad": [float("nan"), 0.0]}, {"sequence": True},
                    {"observed_at_ns": -1}, {"joint_names": []}, {"allowed": True}):
        with pytest.raises(ValueError):
            cls.model_validate({**joint_measurement(1_000_000_000, 4), **changes})


def test_legacy_canonical_proof_omits_absent_joint_measurements(policy):
    from test_physical_transfer_evidence import context, samples
    from fleet.server.physical_transfer_observations import evidence_document
    physical = import_module("rosy.world.state.projections.physical_transfer")
    assert hasattr(physical, "JointPhysicalState")
    raw = samples(policy)
    document = evidence_document(context(policy), raw)
    assert '"joints"' not in document
    decoded = json.loads(document)
    assert decoded["samples"][0]["owners"][0]["links_observed_at_ns"] == raw[0].owners[0].links_observed_at_ns


def test_scoped_export_preserves_original_proof_and_never_refreshes_it(rig):
    mission, post, receipt = close_job(rig)
    url = PATH + "/" + mission + "/physical-evidence"
    response = rig.client.get(url, headers=headers("harbor"))
    assert response.status_code == 200, response.text
    exported = response.json()
    assert exported["receipt"] == receipt
    assert exported["released_zone_ids"] == list(rig.installation.policy.zone_resource_ids)
    document = exported["evidence_document"]
    assert sha256(document.encode()).hexdigest() == receipt["evidence_digest"]
    samples = json.loads(document)["samples"]
    assert samples[1]["owners"][0]["joints"] == post["observations"][1]["owners"][0]["joints"]
    assert samples[1]["object_observed_at_ns"] == post["observations"][1]["object_observed_at_ns"]
    rig.clock[0] += 10_000_000_000
    assert rig.client.get(url, headers=headers("harbor")).json() == exported
    assert rig.client.get(url, headers=headers("other")).status_code == 403
    assert rig.client.get(url).status_code == 401
    assert len(rig.port.submitted) == 1
    assert rig.client.post(PATH + "/" + mission + "/observations", headers=OBSERVER, json=post).json()["receipt"] == receipt


def test_pending_and_legacy_receipts_do_not_fabricate_joint_evidence(rig):
    mission, _, receipt = close_job(rig, joints=False)
    url = PATH + "/" + mission
    assert rig.client.get(url + "/physical-receipt", headers=headers("harbor")).json()["receipt"] == receipt
    assert rig.client.get(url + "/physical-evidence", headers=headers("harbor")).status_code == 409
    assert len(rig.port.submitted) == 1


def test_export_rejects_tampered_stored_measurements(rig):
    mission, _, _ = close_job(rig)
    with sqlite3.connect(rig.db) as connection:
        raw = connection.execute("SELECT evidence_json FROM fleet_physical_transfer_observations "
                                 "WHERE mission_id=? AND phase='POST_ACTION'", (mission,)).fetchone()[0]
        document = json.loads(raw)
        document["samples"][1]["owners"][0]["joints"]["positions_rad"][0] = 5.0
        connection.execute("UPDATE fleet_physical_transfer_observations SET evidence_json=? "
                           "WHERE mission_id=? AND phase='POST_ACTION'", (json.dumps(document), mission))
    response = rig.client.get(PATH + "/" + mission + "/physical-evidence", headers=headers("harbor"))
    assert response.status_code == 409
    assert len(rig.port.submitted) == 1


@pytest.mark.parametrize("change", ["stale", "future", "same-sequence", "same-id", "joint-order", "partial"])
def test_new_joint_facts_must_obey_the_existing_source_binding_and_time_gate(rig, change):
    mission = approved(rig)
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = with_joints(measured(rig, context, phase="PRE_DISPATCH"))
    first, second = (sample["owners"][0] for sample in request["observations"])
    if change == "stale":
        first["joints"]["observed_at_ns"] = context["not_before_ns"]
    elif change == "future":
        second["joints"]["observed_at_ns"] = rig.clock[0] + 1
    elif change == "same-sequence":
        second["joints"]["sequence"] = first["joints"]["sequence"]
    elif change == "same-id":
        second["joints"]["sample_id"] = first["joints"]["sample_id"]
    elif change == "joint-order":
        second["joints"]["joint_names"].reverse()
    else:
        second.pop("joints")
    response = rig.client.post(PATH + "/" + mission + "/observations", headers=OBSERVER, json=request)
    assert response.status_code == 409
    assert rig.port.submitted == []
