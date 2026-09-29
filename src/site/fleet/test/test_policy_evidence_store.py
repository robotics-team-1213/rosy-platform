"""Policy-evidence store validation tests (D-268 ladder step 1, T3).

The v1 observation registry is empty, so every well-formed submission is
rejected with EVIDENCE_OBSERVATION_KIND_UNKNOWN — that is the fail-closed
invariant this suite pins, alongside transit, binding, and replay rules.
"""

from __future__ import annotations

import pytest

from fleet.server.policy_evidence import PolicyEvidenceError, PolicyEvidenceStore
from fleet.server.policy_evidence_config import PolicyEvidenceSource

_TOKEN = "site-secret-1"
_NOW = 1_760_000_000.0


def _source(**overrides) -> PolicyEvidenceSource:
    fields = {
        "source_id": "ceiling-vision-1",
        "token": _TOKEN,
        "asset_kinds": ("robot",),
        "task_kinds": ("navigate",),
        "map_id": "site-map-a",
        "calibration_revision": "cal-2026-09-26",
        "model_revisions": ("aruco-v3",),
    }
    fields.update(overrides)
    return PolicyEvidenceSource(**fields)


def _payload(**overrides) -> dict:
    raw = {
        "evidence_id": "ev-20260929-0001",
        "asset_kind": "robot",
        "asset_id": "rosy_01",
        "task_kind": "navigate",
        "captured_at": _NOW - 0.120,
        "map_id": "site-map-a",
        "calibration_revision": "cal-2026-09-26",
        "model_revision": "aruco-v3",
        "observation": {"kind": "robot_zone"},
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def store(tmp_path):
    return PolicyEvidenceStore([_source()], tmp_path / "policy-evidence.sqlite3")


def test_unknown_token_is_rejected_before_anything_is_stored(store):
    with pytest.raises(PolicyEvidenceError, match="EVIDENCE_SOURCE_UNKNOWN"):
        store.submit(_payload(), token="not-a-known-token", now=_NOW)
    assert store.latest() == []


def test_revoked_source_is_unknown(tmp_path):
    store = PolicyEvidenceStore([_source(revoked=True)], tmp_path / "pe.sqlite3")
    with pytest.raises(PolicyEvidenceError, match="EVIDENCE_SOURCE_UNKNOWN"):
        store.submit(_payload(), token=_TOKEN, now=_NOW)


def test_future_timestamp_is_transit_late(store):
    raw = _payload(captured_at=_NOW + 5.0)
    record = store.submit(raw, token=_TOKEN, now=_NOW)
    assert record["outcome"] == "rejected"
    assert record["reason"] == "EVIDENCE_TRANSIT_LATE"


def test_stale_timestamp_is_transit_late(store):
    raw = _payload(captured_at=_NOW - 0.301)
    record = store.submit(raw, token=_TOKEN, now=_NOW)
    assert record["reason"] == "EVIDENCE_TRANSIT_LATE"


def test_v1_empty_registry_rejects_every_well_formed_submission(store):
    """Fail-closed invariant: no observation kind is registered in v1."""
    record = store.submit(_payload(), token=_TOKEN, now=_NOW)
    assert record["outcome"] == "rejected"
    assert record["reason"] == "EVIDENCE_OBSERVATION_KIND_UNKNOWN"
    assert store.latest(limit=1)[0]["reason"] == "EVIDENCE_OBSERVATION_KIND_UNKNOWN"


def test_revision_mismatch_is_rejected(store):
    raw = _payload(map_id="site-map-b")
    record = store.submit(raw, token=_TOKEN, now=_NOW)
    assert record["reason"] == "EVIDENCE_REVISION_MISMATCH"


def test_model_revision_must_be_listed_for_the_source(store):
    raw = _payload(model_revision="aruco-v2")
    record = store.submit(raw, token=_TOKEN, now=_NOW)
    assert record["reason"] == "EVIDENCE_REVISION_MISMATCH"


def test_task_kind_not_permitted_for_the_source(tmp_path):
    source = _source(task_kinds=("other",))  # hand-built; config cannot produce this today
    store = PolicyEvidenceStore([source], tmp_path / "pe.sqlite3")
    record = store.submit(_payload(), token=_TOKEN, now=_NOW)
    assert record["reason"] == "EVIDENCE_TASK_KIND_NOT_REGISTERED"


def test_asset_kind_not_permitted_for_the_source(tmp_path):
    source = _source(asset_kinds=("workcell",))
    store = PolicyEvidenceStore([source], tmp_path / "pe.sqlite3")
    record = store.submit(_payload(), token=_TOKEN, now=_NOW)
    assert record["reason"] == "EVIDENCE_ASSET_NOT_PERMITTED"


def test_malformed_payload_is_invalid_not_a_binding_rejection(store):
    raw = _payload()
    raw["evidence_id"] = "has spaces"
    with pytest.raises(PolicyEvidenceError, match="EVIDENCE_INVALID"):
        store.submit(raw, token=_TOKEN, now=_NOW)


def test_identical_resubmission_is_idempotent(store):
    first = store.submit(_payload(), token=_TOKEN, now=_NOW)
    second = store.submit(_payload(), token=_TOKEN, now=_NOW + 1.0)
    assert second["evidence_id"] == first["evidence_id"]
    assert second["outcome"] == first["outcome"]
    assert len(store.latest()) == 1


def test_same_id_different_content_is_replay(store):
    store.submit(_payload(), token=_TOKEN, now=_NOW)
    raw = _payload(asset_id="rosy_02")
    with pytest.raises(PolicyEvidenceError, match="EVIDENCE_REPLAY"):
        store.submit(raw, token=_TOKEN, now=_NOW)
    assert len(store.latest()) == 1


def test_latest_returns_decoded_payload(store):
    store.submit(_payload(), token=_TOKEN, now=_NOW)
    row = store.latest(limit=1)[0]
    assert row["payload"]["observation"] == {"kind": "robot_zone"}
    assert row["source_id"] == "ceiling-vision-1"
