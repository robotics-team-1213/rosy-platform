from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def test_task_contract_is_versioned_documented_and_wired_to_the_site_stack():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(
        encoding="utf-8")
    app = (ROOT / "src/site/fleet/fleet/server/app.py").read_text(encoding="utf-8")
    web = (ROOT / "src/site/fleet/fleet/server/web/console.js").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")

    assert "**Version:** v1.31" in reference
    assert "`/api/fleet/robots/{robot_id}/goal`" in reference
    assert "Idempotency-Key" in reference
    assert "`/api/fleet/tasks/{task_id}`" in reference
    assert "`/api/fleet/do` (when `do` is `navigate`)" in reference
    assert "REQUESTED" in reference and "UNKNOWN" in reference and "HOLD" in reference
    assert 'alias="Idempotency-Key"' in app
    assert 'call.verb == "navigate"' in app
    assert '"Idempotency-Key": crypto.randomUUID()' in web
    assert "--tasks-db" in compose


def test_task_path_does_not_enable_automatic_policy_dispatch_by_default():
    source = (ROOT / "src/site/fleet/fleet/server/task_service.py").read_text(encoding="utf-8")
    plan = (ROOT / "docs/plans/2026-09-26-middleware-device-server-contract-integration.md").read_text(
        encoding="utf-8")

    assert "POLICY_DISPATCH_ENABLED = False" in source
    assert "POLICY_NOT_ACCEPTED" in source
    assert "Task 7" in plan
