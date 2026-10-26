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


def test_only_awaiting_approval_items_do_not_fail_the_check(tmp_path):
    _lib(tmp_path, "approval file /etc/ssh/sshd_config.d/10-rosy.conf common/s.conf\nsafe wifi-allow\n", "",
         {"common/s.conf": "x\n"})
    fake, bin_dir = _fakes(tmp_path, wifi="site-net:802-11-wireless:yes\n")
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 0, result.stdout
    assert [c for c in _calls(fake) if not c.startswith(("systemctl is-", "systemctl show"))] == []
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert status["awaiting_approval"] and not status["drift"] and not status["errors"]


def test_a_matching_host_is_clean(tmp_path):
    _lib(tmp_path, "safe file /etc/a.conf common/a.conf\nsafe enabled a.timer\n", "", {"common/a.conf": "x\n"})
    _host_file(tmp_path, "/etc/a.conf", "x\n")
    fake, bin_dir = _fakes(tmp_path, {"a.timer": ("enabled", "active")})
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 0, result.stdout


def test_check_reports_live_recovery_even_when_config_files_match(tmp_path):
    _lib(tmp_path, "", "", {})
    fake, bin_dir = _fakes(tmp_path)

    result = _run(tmp_path, bin_dir, fake, "check")

    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    recovery = status["recovery"]
    assert recovery["time"] > 0
    assert recovery["state"] != "ok"
    assert recovery["watchdog"]["state"] != "ok"
    assert recovery["ssh"]["state"] != "ok"


def test_recovery_install_is_a_single_explicit_approval_group():
    lines = (ROOT / "deploy/hosts/common/host-state/manifest").read_text().splitlines()
    for target in ("/usr/local/sbin/rosy-ssh-watchdog", "enabled rosy-ssh-watchdog.timer",
                   "/etc/systemd/system/rosy-watchdog-load.service", "enabled rosy-watchdog-load.service",
                   "/etc/systemd/system.conf.d/rosy-watchdog.conf", "/etc/sysctl.d/90-rosy-hang.conf"):
        assert any(line.startswith("approval=recovery ") and target in line for line in lines), target


def test_kernel_activation_failure_is_not_a_successful_install(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    (bin_dir / "sysctl").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "sysctl").chmod(0o755)
    result = _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "/etc/sysctl.d/90-rosy-hang.conf")
    assert result.returncode == 1
    assert "could not be applied" in result.stderr
    assert (tmp_path / "host/var/lib/rosy-host-state/status.json").is_file()


def test_provisioning_reapplies_live_settings_even_when_the_files_already_match(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    for name, target in (("rosy-watchdog.conf", "/etc/systemd/system.conf.d/rosy-watchdog.conf"),
                         ("90-rosy-hang.conf", "/etc/sysctl.d/90-rosy-hang.conf")):
        _host_file(tmp_path, target, (ROOT / "deploy/hosts/common/host-state" / name).read_text())
    result = _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "recovery")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(fake)
    assert "systemctl daemon-reexec" in calls
    assert any(call.startswith("sysctl -q -p ") and call.endswith("90-rosy-hang.conf") for call in calls)


def test_dry_run_prints_the_diff_and_changes_nothing(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    result = _run(tmp_path, bin_dir, fake, "install", "model", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "+OnCalendar=*-*-* 06:03:00" in result.stdout
    assert "[approval=recovery] /etc/systemd/system.conf.d/rosy-watchdog.conf: missing: skip (needs --approve)" in result.stdout
    assert not (tmp_path / "host").exists()
    assert [c for c in _calls(fake) if not c.startswith(("systemctl is-", "nmcli -t"))] == []


def test_install_applies_approval_lines_only_when_named(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    assert _run(tmp_path, bin_dir, fake, "install", "ai").returncode == 0
    sshd = tmp_path / "host/etc/systemd/system.conf.d/rosy-watchdog.conf"
    assert not sshd.exists()
    assert (tmp_path / "host/etc/systemd/system/rosy-nightly-reboot.timer").read_bytes() == \
        (ROOT / "deploy/ai_pc/host-state/rosy-nightly-reboot.timer").read_bytes()
    assert (tmp_path / "host/usr/local/lib/rosy-host-state/login").read_text() == "op\n"
    assert _run(tmp_path, bin_dir, fake, "install", "ai", "--approve", "/etc/systemd/system.conf.d/rosy-watchdog.conf").returncode == 0
    assert sshd.read_text().startswith("[Manager]")


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
    assert _run(tmp_path, bin_dir, fake, "check").returncode == 0  # no allow list: not configured, fine
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


@pytest.mark.parametrize("role, wanted", [("ai", True), ("model", True), ("site", False)])
def test_the_lab_pcs_carry_the_storage_owner_as_desired_state(role, wanted):
    """D-883: a model PC installed without units-user refused every clean-storage request."""
    lines = (ROOT / "deploy" / ROLES[role] / "host-state" / "manifest").read_text(encoding="utf-8").splitlines()
    line = "approval=recovery file /etc/rosy/host-control/units-user common/host-control-units-user.in"
    assert (line in lines) is wanted
    assert (ROOT / "deploy/hosts/common/host-state/host-control-units-user.in").read_text() == "@LOGIN@\n"


@pytest.mark.parametrize("role", sorted(ROLES))
def test_every_role_manifest_parses_and_its_sources_exist(role):
    dirs = {"common": ROOT / "deploy/hosts/common/host-state", "role": ROOT / "deploy" / ROLES[role] / "host-state"}
    kinds = set()
    for name, folder in dirs.items():
        for raw in (folder / "manifest").read_text().splitlines():
            line = raw.split("#", 1)[0].split()
            if not line:
                continue
            assert line[0] in ("safe", "report", "approval") or line[0].startswith("approval="), raw
            kinds.add((line[1], line[2] if len(line) > 2 else ""))
            if line[1] == "file":
                base, rel = line[3].split("/", 1)
                src = (ROOT / "deploy" if base == "deploy" else dirs[base]) / rel
                assert src.is_file(), raw
                assert b"\r\n" not in src.read_bytes(), src
    assert ("enabled", "rosy-nightly-reboot.timer") in kinds
    assert ("file", "/etc/systemd/system/rosy-nightly-reboot.timer") in kinds


def test_a_rootless_dry_run_treats_unreadable_files_as_not_comparable(tmp_path):
    if os.name == "nt" or os.geteuid() == 0:
        pytest.skip("needs a non-root POSIX user")
    fake, bin_dir = _fakes(tmp_path)
    locked = _host_file(tmp_path, "/etc/sudoers.d/rosy-host-control", "op ALL=(root) NOPASSWD: x\n")
    locked.chmod(0)
    try:
        result = _run(tmp_path, bin_dir, fake, "install", "ai", "--dry-run")
    finally:
        locked.chmod(0o644)
    assert result.returncode == 0, result.stderr
    assert "/etc/sudoers.d/rosy-host-control: cannot compare without root" in result.stdout


def test_a_failed_copy_keeps_the_old_approved_copy(tmp_path, monkeypatch):
    import importlib.machinery
    import importlib.util
    monkeypatch.setenv("ROSY_HOST_STATE_ROOT", str(tmp_path / "host"))
    monkeypatch.setenv("SUDO_USER", "op")
    loader = importlib.machinery.SourceFileLoader("rosy_host_state_under_test", str(TOOL))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    mod.copy_approved("model")
    lib = tmp_path / "host/usr/local/lib/rosy-host-state"
    marker = lib / "common/manifest"
    before = marker.read_bytes()

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        mod.copy_approved("model")
    assert marker.read_bytes() == before and (lib / "role-name").read_text() == "model\n"
    assert (lib / "login").read_text() == "op\n"


def test_firewall_and_wifi_lines_wait_for_their_approval_group(tmp_path):
    fake, bin_dir = _fakes(tmp_path)
    assert _run(tmp_path, bin_dir, fake, "install", "site").returncode == 0
    calls = _calls(fake)
    assert not any("rosy-site-firewall.service" in c or "rosy-site-stack.service" in c for c in calls if " enable" in c)
    assert not any("modify" in c for c in calls)
    status = _run(tmp_path, bin_dir, fake, "install", "site", "--dry-run").stdout
    assert "[approval=firewall] rosy-site-firewall.service" in status and "skip (needs --approve)" in status
    assert _run(tmp_path, bin_dir, fake, "install", "site", "--approve", "firewall,wifi").returncode == 0
    assert "systemctl enable --now rosy-site-firewall.service" in _calls(fake)
    assert "systemctl enable --now rosy-site-stack.service" in _calls(fake)


def test_an_overwritten_file_is_backed_up_and_the_report_names_the_backup(tmp_path):
    _lib(tmp_path, "safe file /etc/a.conf common/a.conf\n", "", {"common/a.conf": "new\n"})
    _host_file(tmp_path, "/etc/a.conf", "hand edited\n")
    fake, bin_dir = _fakes(tmp_path)
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode == 0, result.stdout
    saved = list((tmp_path / "host/var/lib/rosy-host-state/backup").glob("*/etc/a.conf"))
    assert len(saved) == 1 and saved[0].read_text() == "hand edited\n"
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert "old content saved to" in status["fixed"][0] and "a.conf" in status["fixed"][0]


def test_hang_settings_wait_for_approval_on_every_pc():
    """D-530 decision: the hardware watchdog (with its iTCO_wdt load unit) and panic settings need approval."""
    names = ("system/rosy-watchdog-load.service", "system.conf.d/rosy-watchdog.conf", "sysctl.d/90-rosy-hang.conf")
    for role in ROLES.values():
        manifest = ROOT / "deploy" / role / "host-state" / "manifest"
        lines = (manifest.read_text(encoding="utf-8") + "\n" +
                 (ROOT / "deploy/hosts/common/host-state/manifest").read_text(encoding="utf-8")).splitlines()
        for name in names:
            found = [ln for ln in lines if name in ln and not ln.startswith("#")]
            assert found and all(ln.startswith("approval") for ln in found), (role, name)
    unit = (ROOT / "deploy/hosts/common/host-state/rosy-watchdog-load.service").read_text()
    assert "modprobe iTCO_wdt" in unit and "modprobe wdat_wdt" in unit and "RemainAfterExit=yes" in unit


def test_ssh_password_login_stays_on():
    """User decision 2026-10-09: no manifest installs the key-only sshd drop-in."""
    for folder in (ROOT / "deploy/hosts/common/host-state", *(ROOT / "deploy" / r / "host-state" for r in ROLES.values())):
        text = (folder / "manifest").read_text(encoding="utf-8")
        assert not any("sshd" in ln for ln in text.splitlines() if not ln.startswith("#")), folder


def test_installer_and_host_state_write_the_same_sudoers_file():
    """install-host-control.sh and the D-530 template must give byte-identical files, or check reports drift."""
    env = {**os.environ, "SUDO_USER": "op"}
    out = subprocess.run(["bash", str(ROOT / "deploy/site/install-host-control.sh"), "--role", "model", "--dry-run"],
                         env=env, capture_output=True, text=True, timeout=60, check=True).stdout.splitlines()
    start = out.index("+ write /etc/sudoers.d/rosy-host-control (0440)")
    installer = out[start + 1].removeprefix("    ") + "\n"
    template = (ROOT / "deploy/hosts/common/host-state/sudoers-rosy-host-control.in").read_text(encoding="utf-8")
    assert template.replace("@LOGIN@", "op") == installer


def test_avahi_interfaces_pick_physical_ones_and_restart_only_on_change(tmp_path):
    net = tmp_path / "sys/class/net"
    for name, physical in (("eth0", 1), ("wlan0", 1), ("lo", 0), ("docker0", 1), ("br-1a2b", 1), ("veth9", 0),
                           ("tailscale0", 0), ("virbr0", 1), ("zt0", 1), ("dummy0", 0)):
        (net / name).mkdir(parents=True)
        if physical:
            (net / name / "device").mkdir()
    conf = tmp_path / "etc/avahi/avahi-daemon.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("[server]\nuse-ipv4=yes\n#allow-interfaces=eth0\n[wide-area]\n")
    tool = ROOT / "deploy/hosts/common/rosy-avahi-interfaces"
    env = {**os.environ, "ROSY_AVAHI_ROOT": str(tmp_path)}

    def run():
        return subprocess.run([sys.executable, str(tool)], env=env, capture_output=True, text=True, timeout=30)

    assert run().stdout == "set allow-interfaces=eth0,wlan0\n"
    assert conf.read_text() == "[server]\nuse-ipv4=yes\nallow-interfaces=eth0,wlan0\n[wide-area]\n"
    assert run().stdout == ""  # unchanged: no write, no restart
    (net / "enp3s0").mkdir()
    (net / "enp3s0/device").mkdir()
    assert run().stdout == "set allow-interfaces=enp3s0,eth0,wlan0\n"
    assert conf.read_text().count("allow-interfaces") == 1


def test_avahi_interfaces_unit_is_in_the_common_manifest():
    manifest = (ROOT / "deploy/hosts/common/host-state/manifest").read_text(encoding="utf-8")
    assert "safe enabled rosy-avahi-interfaces.service" in manifest
    unit = (ROOT / "deploy/hosts/common/rosy-avahi-interfaces.service").read_text(encoding="utf-8")
    assert "Before=avahi-daemon.service" in unit


def test_avahi_restart_never_blocks_its_own_start_job():
    """rosy-avahi-interfaces runs Before=avahi-daemon; a blocking restart from inside it deadlocks."""
    script = (ROOT / "deploy" / "hosts" / "common" / "rosy-avahi-interfaces").read_text(encoding="utf-8")
    for line in script.splitlines():
        if "try-restart" in line or '"restart"' in line:
            assert "--no-block" in line, line


def _apt_fakes(tmp_path, installed):
    """dpkg-query reports `installed`; apt-get logs its call."""
    fake, bin_dir = _fakes(tmp_path)
    (fake / "dpkg.out").write_text("".join(f"{name} install ok installed\n" for name in installed))
    for name, body in (("dpkg-query", 'cat "$FAKE/dpkg.out"\n'), ("apt-get", "")):
        path = bin_dir / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$FAKE/calls"\n{body}exit 0\n')
        path.chmod(0o755)
    return fake, bin_dir


def test_apt_lines_wait_for_the_sim_approval_and_the_timer_only_reports(tmp_path):
    """D-571: packages install only with --approve sim; the drift timer never runs apt-get."""
    fake, bin_dir = _apt_fakes(tmp_path, ["pkg-a"])
    _lib(tmp_path, "", "approval=sim apt pkg-a pkg-b\n", {})
    assert _run(tmp_path, bin_dir, fake, "check").returncode == 0
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert status["awaiting_approval"] == [
        "apt packages missing: pkg-b (apt-get install -y -q --no-install-recommends --no-upgrade --no-remove)"]
    assert not [c for c in _calls(fake) if c.startswith("apt-get")]

    dry = _run(tmp_path, bin_dir, fake, "install", "model", "--dry-run").stdout
    assert "[approval=sim] apt packages missing:" in dry and "skip (needs --approve)" in dry
    assert "--no-upgrade --no-remove" in dry  # the dry run states how it would install
    (fake / "dpkg.out").write_text("ros-jazzy-xacro install ok installed\n")
    assert _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "sim").returncode == 0
    installs = [c for c in _calls(fake) if c.startswith("apt-get install")]
    # Only missing names, after `--`; nothing installed is upgraded and nothing is removed.
    assert len(installs) == 1 and installs[0].startswith(
        "apt-get install -y -q --no-install-recommends --no-upgrade --no-remove -- ros-jazzy-ros-gz ")
    assert "ros-jazzy-xacro" not in installs[0]


def test_an_apt_line_without_an_approval_policy_is_refused(tmp_path):
    """D-571: the timer (safe) and a plain install (report) must never reach apt-get."""
    for policy in ("safe", "report"):
        fake, bin_dir = _apt_fakes(tmp_path / policy, [])
        _lib(tmp_path / policy, "", f"{policy} apt pkg-a\n", {})
        result = _run(tmp_path / policy, bin_dir, fake, "check")
        assert result.returncode != 0 and "apt needs an approval policy" in result.stderr
        assert not [c for c in _calls(fake) if c.startswith("apt-get")]


def test_sim_packages_are_approval_only_and_never_on_the_site_pc():
    """D-571: the site PC is production only and excluded from simulation, so it gets no sim packages."""
    for role, folder in ROLES.items():
        lines = [line for line in (ROOT / "deploy" / folder / "host-state" / "manifest").read_text(
            encoding="utf-8").splitlines() if line.split()[1:2] == ["apt"]]
        if role == "site":
            assert not lines
        else:
            assert len(lines) == 1 and lines[0].startswith("approval=sim apt ros-jazzy-ros-gz "), role
    # The common manifest reaches every PC, the site PC included: no sim package, only uv's pip (D-802).
    common = (ROOT / "deploy/hosts/common/host-state/manifest").read_text(encoding="utf-8").splitlines()
    assert [line for line in common if line.split("#", 1)[0].split()[1:2] == ["apt"]] == [
        "approval=uv apt python3-pip"]


def _pip_fake(bin_dir):
    """python3 -m pip install ... --target DIR: logs the call and drops DIR/bin/uv and uvx."""
    path = bin_dir / "python3"
    path.write_text('#!/bin/sh\necho "python3 $*" >> "$FAKE/calls"\n'
                    'while [ $# -gt 0 ]; do [ "$1" = --target ] && T="$2"; shift; done\n'
                    'mkdir -p "$T/bin" && touch "$T/bin/uv" "$T/bin/uvx"\nexit 0\n')
    path.chmod(0o755)


def test_uv_installs_only_with_its_approval_hash_checked_and_linked(tmp_path):
    """D-802: the pinned uv wheel goes in with --approve uv; without it, install and the timer only report."""
    fake, bin_dir = _apt_fakes(tmp_path, ["python3-pip"])
    _pip_fake(bin_dir)
    dry = _run(tmp_path, bin_dir, fake, "install", "model").stdout
    assert "[approval=uv] uv 0.12.22 not installed in" in dry and "skip (needs --approve)" in dry
    assert not [c for c in _calls(fake) if c.startswith("python3")]

    assert _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "uv").returncode == 0
    pip = [c for c in _calls(fake) if c.startswith("python3")]
    assert len(pip) == 1 and "--no-deps --only-binary=:all: --require-hashes --target" in pip[0]
    folder = tmp_path / "host/usr/local/lib/rosy-tools/uv-0.12.22"
    for name in ("uv", "uvx"):
        link = tmp_path / "host/usr/local/bin" / name
        assert link.is_symlink() and Path(os.readlink(link)) == folder / "bin" / name
    _run(tmp_path, bin_dir, fake, "check")  # the model's unapproved sim apt lines still report
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert not [item for item in status["awaiting_approval"] if "uv" in item]


@pytest.mark.parametrize("stale", [False, True], ids=["missing", "stale"])
def test_uvx_link_drift_is_reported_and_repaired_only_with_approval(tmp_path, stale):
    fake, bin_dir = _apt_fakes(tmp_path, ["python3-pip"])
    _pip_fake(bin_dir)
    assert _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "uv").returncode == 0
    link = tmp_path / "host/usr/local/bin/uvx"
    expected = Path(os.readlink(link))
    link.unlink()
    if stale:
        link.symlink_to(expected.with_name("old-uvx"))

    _run(tmp_path, bin_dir, fake, "check")  # unrelated unapproved SIM packages can report drift
    status = json.loads((tmp_path / "host/var/lib/rosy-host-state/status.json").read_text())
    assert any("uvx" in item for item in status["awaiting_approval"])
    assert not link.exists()

    assert _run(tmp_path, bin_dir, fake, "install", "model", "--approve", "uv").returncode == 0
    assert link.is_symlink() and Path(os.readlink(link)) == expected
    assert len([c for c in _calls(fake) if c.startswith("python3")]) == 1


def test_a_wheel_tool_line_without_an_approval_policy_is_refused(tmp_path):
    fake, bin_dir = _apt_fakes(tmp_path, [])
    _lib(tmp_path, "safe wheel-tool uv 0.12.22 " + "ab" * 32 + "\n", "", {})
    result = _run(tmp_path, bin_dir, fake, "check")
    assert result.returncode != 0 and "wheel-tool needs an approval policy" in result.stderr


def test_the_installed_copy_tells_install_to_run_from_the_repo(tmp_path):
    copy = tmp_path / "sbin" / "rosy-host-state"
    copy.parent.mkdir()
    copy.write_bytes(TOOL.read_bytes())
    result = subprocess.run([sys.executable, str(copy), "install", "model", "--dry-run"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and "install reads the repo" in result.stderr
