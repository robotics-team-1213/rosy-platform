from pathlib import Path

from core_common.protocol import schemas


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

    assert "**Version:** v1.33" in reference
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


def test_task_path_does_not_enable_automatic_policy_dispatch_by_default():
    source = (ROOT / "src/site/fleet/fleet/server/task_service.py").read_text(encoding="utf-8")
    plan = (ROOT / "docs/plans/2026-09-26-middleware-device-server-contract-integration.md").read_text(
        encoding="utf-8")

    assert "POLICY_DISPATCH_ENABLED = False" in source
    assert "POLICY_NOT_ACCEPTED" in source
    assert "Task 7" in plan
