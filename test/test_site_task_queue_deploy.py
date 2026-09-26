"""Deployment invariants for the site-local durable task queue."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_site_compose_persists_task_database_and_keeps_core_on_rest():
    compose = (ROOT / "deploy/site/compose.yaml").read_text(encoding="utf-8")
    fleet_dockerfile = (ROOT / "deploy/site/Dockerfile.fleet").read_text(encoding="utf-8")

    assert "--tasks-db" in compose
    assert "--tasks-db\n      - /var/lib/rosy/fleet.sqlite3" in compose
    assert 'sighting_data:/var/lib/rosy' in compose
    assert "sighting_data:" in compose
    assert "--robots\n      - /run/rosy-config/robots.yaml" in compose
    assert "site_backend:" in compose and "internal: true" in compose
    assert "rosy-site-broker" not in compose
    assert "rabbitmq" not in compose.lower()
    assert "EXPOSE 8090" in fleet_dockerfile
