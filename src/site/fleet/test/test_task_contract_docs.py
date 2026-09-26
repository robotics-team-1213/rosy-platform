from pathlib import Path

import pytest
from core_common.protocol import schemas
from core_common.protocol.sightings import SiteSightingPayload
from fleet.server.app import GoalRequest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[4]


def test_task_contract_is_versioned_documented_and_wired_to_the_site_stack():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    app = (ROOT / "src/site/fleet/fleet/server/app.py").read_text(encoding="utf-8")
    web_root = ROOT / "src/site/fleet/fleet/server/web"
    web = (web_root / "console.js").read_text(encoding="utf-8")
    roster = (web_root / "roster.js").read_text(encoding="utf-8")
    web_contract = web + roster
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")

    assert "**Version:** v1.39" in reference
    assert "`/api/fleet/robots/{robot_id}/goal`" in reference
    assert "Idempotency-Key" in reference
    assert "`/api/fleet/tasks/{task_id}`" in reference
    assert "`/api/fleet/tasks/{task_id}/cancel`" in reference
    assert "`/api/fleet/do` (when `do` is `navigate`)" in reference
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
    assert 'alias="Idempotency-Key"' in app
    assert 'call.verb == "navigate"' in app
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
    source = (ROOT / "src/site/fleet/fleet/server/task_service.py").read_text(encoding="utf-8")
    plan = (ROOT / "docs/plans/2026-09-26-middleware-device-server-contract-integration.md").read_text(
        encoding="utf-8")

    assert "POLICY_DISPATCH_ENABLED = False" in source
    assert "POLICY_NOT_ACCEPTED" in source
    assert "Task 7" in plan


def test_site_fleet_intent_and_message_boundaries_are_governed_together():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    adr = (ROOT / "docs/adr/D-288-site-fleet-intent-api-contracts.md").read_text(
        encoding="utf-8")

    assert "**Version:** v1.39" in reference
    assert "## 10.9 Site Fleet intent interpretation and message boundaries (D-288 Accepted)" in reference
    assert "D-288" in reference
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
