from pathlib import Path

import pytest
from core_common.protocol import schemas
from core_common.protocol.sightings import SiteSightingPayload
from fleet.server.app import GoalRequest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[3]


def test_task_contract_is_versioned_documented_and_wired_to_the_site_stack():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    task_dispatch = (ROOT / "operations/fleet/fleet/server/task_dispatch_routes.py").read_text(
        encoding="utf-8")
    intent = (ROOT / "operations/fleet/fleet/server/intent_routes.py").read_text(
        encoding="utf-8")
    web_root = ROOT / "operations/fleet/fleet/server/web"
    web = (web_root / "console.js").read_text(encoding="utf-8")
    roster = (web_root / "roster.js").read_text(encoding="utf-8")
    web_contract = web + roster
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")

    assert "**Version:** v1.179" in reference
    assert "## 10.16 Fleet goal-evidence producer contract (D-348)" in reference
    assert "`/api/fleet/goal-evidence`" in reference
    assert "X-Goal-Evidence-Token" in reference
    assert "GOAL_EVIDENCE_TIMEOUT" in reference
    assert "## 10.12 Site Fleet to OMX local Device Action contract (D-333, D-336)" in reference
    assert "## 10.13 Fleet proposal, Mission draft, and operator admission (D-333/D-334)" in reference
    assert "`/api/fleet/proposals/{proposal_id}/resolve`" in reference
    assert "`/api/fleet/missions/{mission_id}/admit`" in reference
    assert "`/api/fleet/cell-jobs/{mission_id}`" in reference
    assert "different `principal ID`" in reference or "different principal ID" in reference
    assert "`physical_submission: NOT_CONNECTED`" in reference
    assert "GetStopState(LocalStopQuery)" in reference
    assert "`FleetCellTransferGrant`" in reference
    assert "`action_kind: CELL_TRANSFER`" in reference
    assert "trusted producer" in reference
    assert "post-action frame" in reference
    assert "gripper `OPEN` readback" in reference
    assert "`/api/fleet/robots/{robot_id}/goal`" in reference
    assert "Idempotency-Key" in reference
    assert "`/api/fleet/tasks/{task_id}`" in reference
    assert "`/api/fleet/tasks/{task_id}/cancel`" in reference
    assert "`/api/fleet/do` (when `do` is `navigate`)" in reference
    assert "D-316" in reference and "current dispatch `attempt_id`" in reference
    assert "is a physical stop readback" in reference
    assert all(status in reference for status in (
        "REQUESTED", "QUEUED", "ACCEPTED", "RUNNING", "UNKNOWN", "FAILED", "HOLD",
        "CANCELED", "EXPIRED",
    ))
    assert "CORE returned an explicit receipt" in reference
    assert "it does not" in reference and "task started or completed" in reference
    assert {status.value for status in schemas.FleetTaskStatus} == {
        "REQUESTED", "QUEUED", "ACCEPTED", "RUNNING", "COMPLETED", "FAILED",
        "UNKNOWN", "HOLD", "CANCELED", "EXPIRED",
    }
    assert 'alias="Idempotency-Key"' in task_dispatch
    assert 'alias="Idempotency-Key"' in intent
    assert 'call.verb == "navigate"' in intent
    assert '"Idempotency-Key": crypto.randomUUID()' in web
    assert 'task.status === "QUEUED"' in web_contract
    assert 'task.status === "UNKNOWN"' in web_contract
    assert '`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}/cancel`' in web_contract
    assert "`queue_position`" in reference
    assert "task.queue_position" in web
    assert "--tasks-db" in compose
    assert "--users-file" in compose
    assert "policy-admin" in reference and "viewer" in reference
    assert "AUDIT_STORAGE_UNAVAILABLE" in reference


def test_task_path_does_not_enable_automatic_policy_dispatch_by_default():
    source = (ROOT / "operations/fleet/fleet/server/task_service.py").read_text(encoding="utf-8")
    plan = (ROOT / "docs/plans/2026-09-26-middleware-device-server-contract-integration.md").read_text(
        encoding="utf-8")

    assert "POLICY_DISPATCH_ENABLED = False" in source
    assert "POLICY_NOT_ACCEPTED" in source
    assert "Task 7" in plan


def test_site_fleet_intent_and_message_boundaries_are_governed_together():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    adr = (ROOT / "docs/adr/D-293-site-fleet-intent-api-contracts.md").read_text(
        encoding="utf-8")

    assert "**Version:** v1.179" in reference
    assert "X-Frame-Width" in reference and "X-Frame-Height" in reference
    assert "X-Frame-Rotation-Deg" in reference
    assert (
        "## 10.10 Site Fleet intent interpretation and message boundaries "
        "(D-293 Accepted, D-316 Accepted)" in reference
    )
    assert "D-293" in reference
    assert "`core_common.intent.request_schema()`" in reference
    assert "1 through 8 steps" in reference
    assert "`400 INVALID_FIELD_TYPE`" in reference
    assert "TOO_LONG" in adr
    assert all(f"`{code}`" in reference for code in (
        "UNKNOWN_VERB", "UNKNOWN_FIELD", "INVALID_NUMBER", "INVALID_FIELD_TYPE",
        "MISSING", "FORBIDDEN", "TOO_LONG",
    ))
    assert "**Status:** Accepted (2026-09-26)" in adr
    assert "클라이언트가 `priority_class`" in adr
    assert "priority_class" in adr
    assert "`protocol_version`은 `1.0`으로 유지" in adr
    assert "RabbitMQ" in adr
    # Public request schemas carry only domain intent. Fleet derives identity,
    # priority and dispatch state from authenticated server-side context.
    assert set(GoalRequest.model_fields) == {"x", "y", "yaw"}
    assert not {"source", "actor_id", "priority_class", "worker_id"}.intersection(
        GoalRequest.model_fields)
    with pytest.raises(ValidationError):
        GoalRequest.model_validate({"x": 1.0, "y": 2.0, "priority_class": 0})
    with pytest.raises(ValidationError):
        GoalRequest.model_validate({"x": True, "y": 2.0})
    with pytest.raises(ValidationError):
        GoalRequest.model_validate({"x": float("inf"), "y": 2.0})
    assert not {"source_id", "source", "jpeg", "image", "image_url", "policy"}.intersection(
        SiteSightingPayload.model_fields)
    assert schemas.PROTOCOL_VERSION == "1.0"


def test_site_estop_audit_failure_boundary_is_documented():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    site_auth = (ROOT / "operations/fleet/fleet/server/site_auth.py").read_text(
        encoding="utf-8")
    task_dispatch = (ROOT / "operations/fleet/fleet/server/task_dispatch_routes.py").read_text(
        encoding="utf-8")

    assert "still sends the stop fanout if the audit store" in reference
    assert "POST /api/fleet/do` continues to use the normal audit gate" in reference
    assert "emergency stop audit unavailable" in site_auth
    assert "emergency stop dispatch latch unavailable" in task_dispatch


def test_site_camera_rectification_contract_keeps_preview_and_sightings_separate():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    adr = (ROOT / "docs/adr/D-318-site-camera-preview-rectification.md").read_text(
        encoding="utf-8")
    vision = (ROOT / "operations/vision/rosy_vision/ingest.py").read_text(encoding="utf-8")
    ui = (ROOT / "operations/fleet/fleet/server/web/install.html").read_text(encoding="utf-8")

    assert "## D-318 Site Fleet camera preview supports measured lens and plane rectification" in adr
    assert "### 10.6.1 Site Fleet camera preview and rectification (D-318 Accepted)" in reference
    assert "`X-Frame-Rectified`" in reference
    assert "rectification" in vision and "rectify_jpeg(frame.jpeg, settings)" in vision
    assert "Fleet does not relay image" in reference and "for the original" in reference
    assert "sightings" in adr and "cmd_vel" in adr
    assert 'id="vision-adjustments"' in ui
    assert "calibrated site evidence" in reference


def test_policy_evidence_contract_is_governed_together():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    schema = (ROOT / "contracts/foundation/core_common/protocol/policy_evidence.py").read_text(
        encoding="utf-8")
    task_service = (ROOT / "operations/fleet/fleet/server/task_service.py").read_text(
        encoding="utf-8")
    store = (ROOT / "operations/fleet/fleet/server/policy_evidence.py").read_text(
        encoding="utf-8")

    assert "### 10.6.2 Site Fleet policy-eligible evidence" in reference or (
        "## 10.6.2 Site Fleet policy-eligible evidence" in reference)
    assert "/api/fleet/policy-evidence" in reference
    assert "INVALID_EVIDENCE_REFERENCE" in reference
    assert "EVIDENCE_OBSERVATION_KIND_UNKNOWN" in reference
    assert "POLICY_DISPATCH_ENABLED" in reference and "fail-closed" in reference
    # The payload refuses client identity and D-328 goal vocabulary.
    assert "satisfied" in schema and "source_id" in schema
    # The admission path keeps the valve closed and speaks the audit vocabulary.
    assert "POLICY_DISPATCH_ENABLED = False" in task_service
    assert "EVIDENCE_NOT_CONFIGURED" in task_service
    assert "EVIDENCE_REPLAY" in store and "TRANSIT_MAX_S = 0.300" in store
