"""Deployment invariants for the site-local durable task queue."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_site_compose_persists_task_database_and_keeps_core_on_rest():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    fleet_dockerfile = (ROOT / "deploy/site/Dockerfile.fleet").read_text(encoding="utf-8")

    assert "--tasks-db" in compose
    assert "--tasks-db\n      - /var/lib/rosy/fleet.sqlite3" in compose
    assert "--users-file\n      - /run/rosy-config/site-users.yaml" in compose
    assert "site-users.yaml.example" in (ROOT / "deploy/site/README.md").read_text(
        encoding="utf-8")
    assert 'sighting_data:/var/lib/rosy' in compose
    assert "sighting_data:" in compose
    assert "--robots\n      - /run/rosy-config/robots.yaml" in compose
    assert "site_backend:" in compose and "internal: true" in compose
    assert "rosy-site-broker" not in compose
    assert "rabbitmq" not in compose.lower()
    assert "EXPOSE 8090" in fleet_dockerfile


def test_site_compose_uses_a_distinct_core_registry_credential():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    fleet_dockerfile = (ROOT / "deploy/site/Dockerfile.fleet").read_text(encoding="utf-8")
    runbook = (ROOT / "deploy/site/README.md").read_text(encoding="utf-8")

    assert "--token-env\n      - ROSY_SITE_REGISTRY_TOKEN" in compose
    assert '"ROSY_SITE_REGISTRY_TOKEN":"/run/secrets/registry_token"' in compose
    assert '"ROSY_SITE_OPERATOR_TOKEN"' not in compose
    assert "registry_token:" in compose
    assert "registry_token" in runbook
    assert '"--token-env", "ROSY_SITE_REGISTRY_TOKEN"' in fleet_dockerfile


def test_vision_container_uses_python_handled_signal_for_clean_shutdown():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    vision = compose.split("  vision:\n", 1)[1].split("  proxy:\n", 1)[0]

    assert "\n    stop_signal: SIGINT\n" in vision


def test_site_image_bundles_guarded_sqlite_backup_and_restore_tool():
    fleet_dockerfile = (ROOT / "deploy/site/Dockerfile.fleet").read_text(encoding="utf-8")
    utility = (ROOT / "deploy/site/site_db.py").read_text(encoding="utf-8")
    runbook = (ROOT / "deploy/site/README.md").read_text(encoding="utf-8")

    assert "COPY deploy/site/site_db.py /opt/rosy/site_db.py" in fleet_dockerfile
    assert "source_db.backup(destination_db" in utility
    assert "PRAGMA integrity_check" in utility
    assert "PRAGMA journal_mode=DELETE" in utility
    assert "--assume-stopped" in utility and "--replace" in utility
    assert "site_db.py backup" in runbook and "site_db.py restore" in runbook
    assert "verified from a read-only mount" in runbook
    assert runbook.count("--assume-stopped") >= 2
    assert "pre-restore" in runbook and "sighting_data" in runbook
