"""Existing observer ingress preserves unsuccessful task evidence without dispatch."""
from contextlib import closing
from importlib import import_module
import json

import pytest

from test_physical_transfer_evidence import geometry, policy
from test_physical_transfer_store import installation, claims
from test_physical_transfer_observer_api import (
    CONTEXT, OBSERVER, PATH, approved, measured, rig,
)


def post_action(rig):
    mission = approved(rig)
    url = PATH + "/" + mission + "/observations"
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    before = measured(rig, context, phase="PRE_DISPATCH")
    assert rig.client.post(url, headers=OBSERVER, json=before).status_code == 200
    assert rig.app.state.arm_transfer_dispatcher.tick()["status"] == "ACTION_SUCCEEDED"
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    return mission, url, measured(rig, context, phase="POST_ACTION")


def recorded(rig):
    with closing(rig.store._journal._connect()) as connection:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT detail_json FROM fleet_cell_events WHERE event_type='PHYSICAL_TRANSFER_ASSESSED'")]


@pytest.mark.parametrize("kind, outcome", [("target", "succeeded"), ("miss", "failed"), ("missing", "unknown")])
def test_http_observations_record_distinct_task_results_without_new_motion(rig, kind, outcome):
    mission, url, request = post_action(rig)
    for sample in request["observations"]:
        if kind == "miss":
            sample["object_pose"]["position_m"] = [0., 0., .2]
        elif kind == "missing":
            sample["object_pose"] = None
    response = rig.client.post(url, headers=OBSERVER, json=request)
    assert response.status_code == (200 if kind == "target" else 409)
    rows = recorded(rig)
    assert len(rows) == 1 and rows[0]["task_outcome"] == outcome
    assert rows[0]["action_outcome"] == "SUCCEEDED"
    assert rows[0]["scope"] == "observation_assessment_only"
    assert rows[0]["execution_authorized"] is False
    assert len(rig.port.submitted) == 1
    if kind != "target":
        assert {c["phase"] for c in claims(rig.db)} == {"HELD"}
        assert rig.app.state.arm_transfer_dispatcher.execution.snapshot(mission)["status"] == "ACTION_SUCCEEDED"
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == response.status_code
    assert recorded(rig) == rows


def test_wrong_attempt_or_late_observations_cannot_create_failure_labels(rig):
    _, url, request = post_action(rig)
    request["observations"][0]["object_pose"]["position_m"] = [0., 0., .2]
    request["observations"][1]["attempt_id"] = "another-attempt"
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == 409
    assert recorded(rig) == []
    request["observations"][1]["attempt_id"] = request["observations"][0]["attempt_id"]
    rig.clock[0] += rig.installation.policy.max_age_ns
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == 409
    assert recorded(rig) == []


def test_assessment_storage_failure_does_not_confirm_or_release_claims(rig):
    mission, url, request = post_action(rig)
    with closing(rig.store._journal._connect()) as connection:
        connection.execute("CREATE TRIGGER fail_assessment BEFORE INSERT ON fleet_cell_events "
            "WHEN NEW.event_type='PHYSICAL_TRANSFER_ASSESSED' BEGIN SELECT RAISE(ABORT,'injected'); END")
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == 503
    assert recorded(rig) == [] and {c["phase"] for c in claims(rig.db)} == {"HELD"}
    assert rig.app.state.arm_transfer_dispatcher.execution.snapshot(mission)["status"] == "ACTION_SUCCEEDED"


def test_site_stop_blocks_new_assessment_and_never_restarts_motion(rig):
    _, url, request = post_action(rig)
    rig.tasks.trip_stop_latch(actor_id="operator")
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == 409
    assert recorded(rig) == [] and len(rig.port.submitted) == 1


def test_export_preserves_original_attempt_and_is_explicitly_unreviewed(rig, tmp_path):
    mission, url, request = post_action(rig)
    for sample in request["observations"]:
        sample["object_pose"] = None
    assert rig.client.post(url, headers=OBSERVER, json=request).status_code == 409
    module = import_module("fleet.server.physical_transfer_outcomes")
    output = tmp_path / "outcomes.json"
    module.export_transfer_outcomes(rig.store, mission, output)
    doc = json.loads(output.read_text())
    assert doc["scope"] == "unreviewed_metadata_only"
    assert doc["outcomes"][0]["task_outcome"] == "unknown"
    assert doc["outcomes"][0]["evidence"]["samples"] == request["observations"]
    assert doc["raw_camera_bytes_available"] is False and doc["behavior_training_eligible"] is False
    with pytest.raises(FileExistsError):
        module.export_transfer_outcomes(rig.store, mission, output)
    with closing(rig.store._journal._connect()) as connection:
        connection.execute("UPDATE fleet_cell_events SET detail_json=json_set(detail_json, "
            "'$.evidence.samples[0].object_ref','tampered') WHERE event_type='PHYSICAL_TRANSFER_ASSESSED'")
        connection.commit()
    with pytest.raises(ValueError, match="evidence"):
        module.export_transfer_outcomes(rig.store, mission, tmp_path / "changed.json")
    assert not (tmp_path / "changed.json").exists()
