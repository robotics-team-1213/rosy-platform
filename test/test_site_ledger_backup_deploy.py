"""매일 원장 백업 타이머 배포 계약 — 유닛 쌍과 compose fleet-backup 서비스 고정."""

from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parents[1] / "deploy/site"


def test_backup_service_runs_the_compose_profile_service():
    text = (SITE / "rosy-site-ledger-backup.service").read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert "docker compose --project-name rosy-site" in text
    assert "run --rm --no-deps fleet-backup" in text
    assert "EnvironmentFile=-/etc/rosy/site/site.env" in text


def test_backup_timer_is_daily_and_catches_up_after_downtime():
    text = (SITE / "rosy-site-ledger-backup.timer").read_text(encoding="utf-8")
    assert "OnCalendar=daily" in text
    assert "Persistent=true" in text
    assert "Unit=rosy-site-ledger-backup.service" in text
    assert "WantedBy=timers.target" in text


def test_compose_backup_service_is_isolated_profiled_and_read_only():
    service = yaml.safe_load(
        (SITE / "compose.yaml").read_text(encoding="utf-8"))["services"]["fleet-backup"]
    assert service["profiles"] == ["backup"]  # 평소 `up`에 끼지 않는다
    assert service["image"].startswith("rosy-site-fleet:")  # 별도 이미지 풀 없음
    assert service["entrypoint"] == ["python3"]  # secret_exec 우회
    assert service["command"][:2] == ["/opt/rosy/site_db.py", "backup"]
    assert service["network_mode"] == "none"
    assert service["read_only"] is True
    volumes = service["volumes"]
    assert "sighting_data:/var/lib/rosy:ro" in volumes  # 원장은 읽기 전용
    assert any(str(volume).endswith(":/backup") for volume in volumes)


def test_compose_backup_command_keeps_fourteen_backups():
    service = yaml.safe_load(
        (SITE / "compose.yaml").read_text(encoding="utf-8"))["services"]["fleet-backup"]
    command = service["command"]
    assert command[command.index("--prune") + 1] == "14"
