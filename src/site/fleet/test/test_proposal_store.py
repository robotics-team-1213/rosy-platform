import pytest
from datetime import datetime, timezone

from fleet.server.proposal_store import ProposalConflict, ProposalStore


def _candidate(observation_id="obs-1"):
    return {
        "source": "gemini_robotics_er2",
        "model_id": "gemini-robotics-er2",
        "provider_interaction_id": "interaction-1",
        "provider_call_id": "call-1",
        "instruction": "Move the red block to the green tray",
        "source_observation": {
            "observation_id": observation_id,
            "camera_id": "camera-top", "frame_id": "camera_top_optical",
            "image_sha256": "a" * 64,
            "calibration_revision": "cal-4",
            "transform_revision": "tf-9",
        },
        "target_selector": {"label": "red block", "point_yx_1000": [575, 664]},
        "destination_selector": {"label": "green tray", "point_yx_1000": [475, 305]},
    }


def test_proposal_store_is_idempotent_and_scopes_request_key_to_authenticated_principal(tmp_path):
    store = ProposalStore(tmp_path / "fleet.sqlite3")

    first = store.create(principal_id="operator-1", request_key="request-1",
                         workcell_id="omx_01", instance_id="omx_01_control",
                         candidate=_candidate())
    duplicate = store.create(principal_id="operator-1", request_key="request-1",
                             workcell_id="omx_01", instance_id="omx_01_control",
                             candidate=_candidate())
    other_user = store.create(principal_id="operator-2", request_key="request-1",
                              workcell_id="omx_01", instance_id="omx_01_control",
                              candidate=_candidate())

    assert first["created"] is True
    assert duplicate["created"] is False
    assert duplicate["proposal"]["proposal_id"] == first["proposal"]["proposal_id"]
    assert other_user["created"] is True
    assert store.get(first["proposal"]["proposal_id"])["principal_id"] == "operator-1"
    with pytest.raises(ProposalConflict, match="different candidate"):
        store.create(principal_id="operator-1", request_key="request-1",
                     workcell_id="omx_02", instance_id="omx_02_control",
                     candidate=_candidate())


def test_proposal_store_rejects_digest_replay_and_never_persists_image_or_principal_claims(tmp_path):
    store = ProposalStore(tmp_path / "fleet.sqlite3")
    store.create(principal_id="operator-1", request_key="request-1",
                 workcell_id="omx_01", instance_id="omx_01_control",
                 candidate=_candidate())

    with pytest.raises(ProposalConflict, match="different candidate"):
        store.create(principal_id="operator-1", request_key="request-1",
                     workcell_id="omx_01", instance_id="omx_01_control",
                     candidate=_candidate("obs-2"))
    with pytest.raises(ValueError, match="principal"):
        store.create(principal_id="operator-1", request_key="request-2",
                     workcell_id="omx_01", instance_id="omx_01_control",
                     candidate={**_candidate(), "principal_id": "admin"})
    with pytest.raises(ValueError, match="image bytes"):
        store.create(principal_id="operator-1", request_key="request-3",
                     workcell_id="omx_01", instance_id="omx_01_control",
                     candidate={**_candidate(), "image_bytes": "raw-frame"})


def test_expired_candidate_metadata_is_purged_and_request_key_can_be_reused(tmp_path):
    store = ProposalStore(tmp_path / "fleet.sqlite3", retention_days=1)
    created = store.create(principal_id="operator-1", request_key="request-1",
                           workcell_id="omx_01", instance_id="omx_01_control",
                           candidate=_candidate())

    removed = store.purge_expired(now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    recreated = store.create(principal_id="operator-1", request_key="request-1",
                             workcell_id="omx_01", instance_id="omx_01_control",
                             candidate=_candidate("obs-2"))

    assert removed == 1
    assert store.get(created["proposal"]["proposal_id"]) is None
    assert recreated["created"] is True


def test_candidate_instruction_has_a_field_level_bound(tmp_path):
    store = ProposalStore(tmp_path / "fleet.sqlite3")
    candidate = _candidate()
    candidate["instruction"] = "x" * 2001

    with pytest.raises(ValueError, match="instruction"):
        store.create(principal_id="operator-1", request_key="request-1",
                     workcell_id="omx_01", instance_id="omx_01_control",
                     candidate=candidate)
