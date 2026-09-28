from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_update_timer_only_checks_and_stages():
    service = (ROOT / "deploy/robot/pinky_pro/rosy-update-check.service").read_text(encoding="utf-8")
    command = next(line for line in service.splitlines() if line.startswith("ExecStart="))
    assert command == "ExecStart=/usr/local/bin/rosy-release check --download --json"
    assert "ProtectSystem=strict" in service


def test_managed_boot_uses_record_and_recovery_before_start():
    service = (ROOT / "deploy/robot/pinky_pro/rosy-release-runtime.service").read_text(encoding="utf-8")
    assert "Requires=rosy-release-recover.service" in service
    assert "After=rosy-release-recover.service" in service
    assert "ExecStart=/usr/local/bin/rosy-release runtime up" in service
    recovery = (ROOT / "deploy/robot/pinky_pro/rosy-release-recovery.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/rosy-release recover --json" in recovery


def test_source_install_installs_its_required_recovery_unit():
    source = (ROOT / "deploy/robot/pinky_pro/install-pi.sh").read_text(encoding="utf-8")
    body = source.split("enable_boot_service() {", 1)[1].split("\n}", 1)[0]
    assert 'install -m 0644 "$INSTALL_ROOT/deploy/robot/rosy-release-recover.service"' in body


def test_publish_is_explicit_and_verifies_before_release():
    path = ROOT / ".github/workflows/publish-release.yml"
    source = path.read_text(encoding="utf-8")
    data = yaml.safe_load(source)
    triggers = data.get("on", data.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    steps = data["jobs"]["publish"]["steps"]
    commands = [s.get("run", "") for s in steps]
    verify = next(i for i, command in enumerate(commands) if "verify-publication" in command)
    publish = next(i for i, command in enumerate(commands) if "gh release edit" in command)
    assert verify < publish
    assert "PRIVATE_KEY" not in source
