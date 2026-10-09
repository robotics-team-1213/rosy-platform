"""D-530 host desired state: diff detection, safe-only auto-fix, approval gate (deploy/hosts/common)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "deploy" / "hosts" / "common" / "rosy-host-state"
ROLES = {"site": "site", "model": "model_pc", "ai": "ai_pc"}
PENDING_D524 = "deploy/site/rosy-host-control"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs POSIX fakes on PATH")


def _fakes(tmp_path, units=None, sshd_rc=0, wifi=""):
    fake = tmp_path / "fake"
    (fake / "units").mkdir(parents=True)
    for unit, (enabled, active) in (units or {}).items():
        (fake / "units" / f"{unit}.enabled").write_text(enabled + "\n")
        (fake / "units" / f"{unit}.active").write_text(active + "\n")
    (fake / "nmcli.out").write_text(wifi)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "systemctl": 'case "$1" in\n is-enabled) cat "$FAKE/units/$2.enabled" 2>/dev/null || echo disabled;;\n'
                     ' is-active) cat "$FAKE/units/$2.active" 2>/dev/null || echo inactive;;\nesac\n',
        "loginctl": "",
        "nmcli": '[ "$1" = -t ] && cat "$FAKE/nmcli.out"\n',
        "sshd": f"exit {sshd_rc}\n",
        "sysctl": "",
        "visudo": 'grep -q "^Bad" "$2" && exit 1\n',
    }
    for name, body in scripts.items():
        path = bin_dir / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$FAKE/calls"\n{body}exit 0\n'
                        if name != "sshd" else f'#!/bin/sh\necho "sshd $*" >> "$FAKE/calls"\n{body}')
        path.chmod(0o755)
    return fake, bin_dir


def _run(tmp_path, bin_dir, fake, *args, sudo_user="op"):
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE": str(fake),
           "ROSY_HOST_STATE_ROOT": str(tmp_path / "host"), "SUDO_USER": sudo_user}
    return subprocess.run([sys.executable, str(TOOL), *args], env=env, capture_output=True, text=True, timeout=60)


def _calls(fake):
    path = fake / "calls"
    return path.read_text().splitlines() if path.exists() else []


def _lib(tmp_path, common, role, files):
    lib = tmp_path / "host" / "usr/local/lib/rosy-host-state"
    for name, text in (("common", common), ("role", role)):
        (lib / name).mkdir(parents=True)
        (lib / name / "manifest").write_text(text)
    for rel, text in files.items():
        (lib / rel).write_text(text)
    (lib / "login").write_text("op\n")
    return lib


def _host_file(tmp_path, path, text):
    target = tmp_path / "host" / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    target.chmod(0o644)
    return target


def test_check_fixes_only_the_safe_lines_and_reports_the_rest(tmp_path):
    _lib(tmp_path,
         "safe file /etc/systemd/system/a.timer common/a.timer\n"
         "safe enabled a.timer\n"
         "approval file /etc/ssh/sshd_config.d/10-rosy.conf common/sshd.conf\n",
         "report file /etc/sysctl.d/90-x.conf role/x.conf\n"
         "report enabled stack.service\n"
         "safe linger\n",
         {"common/a.timer": "[Timer]\nOnCalendar=06:00\n", "common/sshd.conf": "PasswordAuthentication no\n",
          "role/x.conf": "kernel.panic = 10\n"})
    timer = _host_file(tmp_path, "/etc/systemd/system/a.timer", "[Timer]\nOnCalendar=07:00\n")
    sysctl = _host_file(tmp_path, "/etc/sysctl.d/90-x.conf", "kernel.panic = 0\n")
    fake, bin_dir = _fakes(tmp_path, {"a.timer": ("disabled", "inactive"), "stack.service": ("disabled", "inactive")})

    result = _run(tmp_path, bin_dir, fake, "check")

    assert result.returncode == 1, result.stdout + result.stderr  # report drift remains
    assert timer.read_text() == "[Timer]\nOnCalendar=06:00\n"
    assert sysctl.read_text() == "kernel.panic = 0\n"
    assert not (tmp_path / "host/etc/ssh/sshd_config.d/10-rosy.conf").exists()
    calls = _calls(fake)
    assert "systemctl daemon-reload" in calls
    assert "systemctl enable --now a.timer" in calls
    assert "loginctl enable-linger op" in calls
    assert not any("stack.service" in c and "enable" in c.split()[1:2] for c in calls)
    assert not any(c.startswith(("sshd", "sysctl")) for c in calls)
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert len(status["fixed"]) == 3
    assert any("90-x.conf" in d for d in status["drift"]) and any("stack.service" in d for d in status["drift"])
    assert status["awaiting_approval"] == ["/etc/ssh/sshd_config.d/10-rosy.conf: missing"]


def test_a_matching_host_is_clean(tmp_path):
    _lib(tmp_path, "safe file /etc/a.conf common/a.conf\nsafe enabled a.timer\n", "", {"common/a.conf": "x\n"})
    _host_file(tmp_path, "/etc/a.conf", "x\n")
    fake, bin_dir = _fakes(tmp_path, {"a.timer": ("enabled", "active")})
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 0, result.stdout
    assert [c for c in _calls(fake) if not c.startswith("systemctl is-")] == []


def test_dry_run_prints_the_diff_and_changes_nothing(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    result = _run(tmp_path, bin_dir, fake, "install", "model", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "+OnCalendar=*-*-* 06:03:00" in result.stdout
    assert "[approval] /etc/ssh/sshd_config.d/10-rosy.conf: missing: skip (needs --approve)" in result.stdout
    assert not (tmp_path / "host").exists()
    assert [c for c in _calls(fake) if not c.startswith(("systemctl is-", "nmcli -t"))] == []


def test_install_applies_approval_lines_only_when_named(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    assert _run(tmp_path, bin_dir, fake, "install", "ai").returncode == 0
    sshd = tmp_path / "host/etc/ssh/sshd_config.d/10-rosy.conf"
    assert not sshd.exists()
    assert (tmp_path / "host/etc/systemd/system/rosy-nightly-reboot.timer").read_bytes() == \
        (ROOT / "deploy/ai_pc/host-state/rosy-nightly-reboot.timer").read_bytes()
    assert (tmp_path / "host/usr/local/lib/rosy-host-state/login").read_text() == "op\n"
    assert _run(tmp_path, bin_dir, fake, "install", "ai", "--approve", "/etc/ssh/sshd_config.d/10-rosy.conf").returncode == 0
    assert sshd.read_text().startswith("# D-530")
    assert "systemctl reload ssh" in _calls(fake)


def test_a_broken_sshd_config_is_rolled_back(tmp_path):
    _lib(tmp_path, "safe file /etc/ssh/sshd_config.d/10-rosy.conf common/s.conf\n", "", {"common/s.conf": "Bad yes\n"})
    old = _host_file(tmp_path, "/etc/ssh/sshd_config.d/10-rosy.conf", "PasswordAuthentication yes\n")
    fake, bin_dir = _fakes(tmp_path, sshd_rc=1)
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 1
    assert old.read_text() == "PasswordAuthentication yes\n"
    assert "systemctl reload ssh" not in _calls(fake)
    assert "sshd -t failed, restored" in result.stdout


def test_wifi_autoconnect_is_cut_only_outside_a_nonempty_allow_list(tmp_path):
    _lib(tmp_path, "safe wifi-allow\n", "", {})
    wifi = "site-net:802-11-wireless:yes\nold\\:cafe:802-11-wireless:yes\nlab:802-11-wireless:no\ntailscale0:tun:yes\n"
    fake, bin_dir = _fakes(tmp_path, wifi=wifi)
    assert _run(tmp_path, bin_dir, fake, "check").returncode == 1  # no allow list: refuse, report
    assert not any("modify" in c for c in _calls(fake))
    _host_file(tmp_path, "/etc/rosy/host-state/wifi-allow", "site-net\n")
    _run(tmp_path, bin_dir, fake, "check")
    assert [c for c in _calls(fake) if "modify" in c] == ["nmcli connection modify old:cafe connection.autoconnect no"]


def test_sudoers_gets_the_login_and_a_broken_file_is_never_installed(tmp_path):
    _lib(tmp_path, "safe file /etc/sudoers.d/rosy-host-control common/s.in 0440\n", "",
         {"common/s.in": "@LOGIN@ ALL=(root) NOPASSWD: /usr/local/sbin/rosy-host-control\n"})
    fake, bin_dir = _fakes(tmp_path)
    assert _run(tmp_path, bin_dir, fake, "check").returncode == 0
    sudoers = tmp_path / "host/etc/sudoers.d/rosy-host-control"
    assert sudoers.read_text() == "op ALL=(root) NOPASSWD: /usr/local/sbin/rosy-host-control\n"
    assert sudoers.stat().st_mode & 0o777 == 0o440
    assert _run(tmp_path, bin_dir, fake, "check").returncode == 0  # idempotent: no drift now

    (tmp_path / "host/usr/local/lib/rosy-host-state/common/s.in").write_text("Bad line\n")
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 1 and "visudo -c failed" in result.stdout
    assert sudoers.read_text().startswith("op ALL")
    assert not list(sudoers.parent.glob("*.rosy-tmp"))


@pytest.mark.parametrize("role", sorted(ROLES))
def test_every_role_manifest_parses_and_its_sources_exist(role):
    dirs = {"common": ROOT / "deploy/hosts/common/host-state", "role": ROOT / "deploy" / ROLES[role] / "host-state"}
    kinds = set()
    for name, folder in dirs.items():
        for raw in (folder / "manifest").read_text().splitlines():
            line = raw.split("#", 1)[0].split()
            if not line:
                continue
            assert line[0] in ("safe", "report", "approval"), raw
            kinds.add((line[1], line[2] if len(line) > 2 else ""))
            if line[1] == "file":
                base, rel = line[3].split("/", 1)
                src = (ROOT / "deploy" if base == "deploy" else dirs[base]) / rel
                if line[3] == PENDING_D524:
                    assert line[0] == "approval", raw  # lands with D-524 (feat/host-control)
                    continue
                assert src.is_file(), raw
                assert b"\r\n" not in src.read_bytes(), src
    assert ("enabled", "rosy-nightly-reboot.timer") in kinds
    assert ("file", "/etc/systemd/system/rosy-nightly-reboot.timer") in kinds
