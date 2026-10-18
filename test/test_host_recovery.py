"""Read-only recovery evidence, including disabled settings behind matching config files."""
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/hosts/common/rosy_host_recovery.py"


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("host_recovery_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = {
        "proc/meminfo": "MemTotal: 32768 kB\nMemAvailable: 16384 kB\nSwapTotal: 65536 kB\nSwapFree: 32768 kB\n",
        "proc/loadavg": "1.5 2.0 3.0 1/100 123\n", "proc/uptime": "1000.0 100.0\n",
        "proc/sys/kernel/panic": "10\n", "proc/sys/kernel/softlockup_panic": "1\n",
        "dev/watchdog0": "", "usr/local/lib/rosy-host-state/role-name": "model\n",
        **{f"var/lib/rosy-ssh-watchdog/{name}": "0\n" for name in (
            "ssh_failures", "tailscale_failures", "gateway_failures", "reboots")},
    }
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    responses = {
        ("systemctl", "show", "--property=RuntimeWatchdogUSec", "--value"): "30s",
        ("systemctl", "show", "rosy-ssh-watchdog.service", "--property=Result,ExecMainStatus,ExecMainExitTimestampMonotonic"):
            "Result=success\nExecMainStatus=0\nExecMainExitTimestampMonotonic=999000000\n",
    }
    for unit in ("rosy-watchdog-load.service", "rosy-ssh-watchdog.timer"):
        responses[("systemctl", "is-enabled", unit)] = "enabled"
        responses[("systemctl", "is-active", unit)] = "active"
    def run(*command):
        return SimpleNamespace(stdout=responses.get(command, ""), returncode=0 if command in responses else 1)
    monkeypatch.setattr(module.time, "time", lambda: 10000)
    return module, responses, run


def test_snapshot_is_healthy_only_with_all_live_evidence(tmp_path, recovery):
    module, _, run = recovery
    value = module.snapshot(str(tmp_path), run)
    assert value["state"] == "ok" and value["role"] == "model"
    assert value["watchdog"]["timeout_s"] == 30
    assert value["swap"] == {"state": "ok", "total_bytes": 65536 * 1024, "used_bytes": 32768 * 1024}
    assert value["resources"]["avail_pct"] == 50
    assert value["ssh"]["last_check_age_s"] == 1


@pytest.mark.parametrize("fault", ["device", "timeout", "panic", "ssh-old", "ssh-failed", "no-swap",
                                  "counter-missing", "counter-invalid"])
def test_live_failures_are_reported_without_repairing_anything(tmp_path, recovery, fault):
    module, responses, run = recovery
    if fault == "device":
        (tmp_path / "dev/watchdog0").unlink()
    elif fault == "timeout":
        responses[("systemctl", "show", "--property=RuntimeWatchdogUSec", "--value")] = "0"
    elif fault == "panic":
        (tmp_path / "proc/sys/kernel/panic").write_text("0\n")
    elif fault == "counter-missing":
        (tmp_path / "var/lib/rosy-ssh-watchdog/ssh_failures").unlink()
    elif fault == "counter-invalid":
        (tmp_path / "var/lib/rosy-ssh-watchdog/ssh_failures").write_text("bad\n")
    elif fault in ("ssh-old", "ssh-failed"):
        stamp = 1 if fault == "ssh-old" else 999000000
        code = 0 if fault == "ssh-old" else 1
        responses[("systemctl", "show", "rosy-ssh-watchdog.service", "--property=Result,ExecMainStatus,ExecMainExitTimestampMonotonic")] = (
            f"Result=success\nExecMainStatus={code}\nExecMainExitTimestampMonotonic={stamp}\n")
    else:
        (tmp_path / "proc/meminfo").write_text("MemTotal: 32768 kB\nMemAvailable: 16384 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    calls = []
    def read_only(*command):
        calls.append(command)
        return run(*command)
    value = module.snapshot(str(tmp_path), read_only)
    assert value["state"] != "ok" and value["issues"]
    assert all(c[0] == "systemctl" and c[1] in ("show", "is-enabled", "is-active") for c in calls)


def test_missing_evidence_and_timeouts_are_unknown_not_healthy(tmp_path, recovery):
    module, _, _ = recovery
    (tmp_path / "proc/meminfo").unlink()
    def timeout(*command):
        raise subprocess.TimeoutExpired(command, 1)
    value = module.snapshot(str(tmp_path), timeout)
    assert value["state"] != "ok"
    assert value["swap"]["state"] == "unknown"
    assert value["watchdog"]["state"] != "ok"


def test_legacy_model_installer_uses_the_shared_loader_without_changing_the_host():
    source = SOURCE.parents[2] / "site/install-model-pc-guard.sh"
    result = subprocess.run(["bash", str(source), "--dry-run"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "host-state/rosy-watchdog-load.service" in result.stdout
    assert "enable --now rosy-watchdog-load.service" in result.stdout
