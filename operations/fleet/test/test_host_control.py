"""D-524 Service Control. No network and no real shutdown."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fleet.host_control import (
    CONFIG_DIR,
    HOSTS,
    HostControlError,
    SshHostHelper,
    UnavailableHostHelper,
    catalogue,
    decide,
    helper_from_config,
)
from fleet.server.host_control_routes import install_host_control_routes

SITE = Path(__file__).resolve().parents[3] / "deploy" / "site"
HELPER = SITE / "rosy-host-control"
REMOTE = SITE / "rosy-host-control-remote"
INSTALL = SITE / "install-host-control.sh"
posix = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt",
                           reason="needs a POSIX shell")


def _code(call):
    with pytest.raises(HostControlError) as caught:
        call()
    return caught.value.code


def test_catalogue_is_the_three_ubuntu_hosts():
    hosts = {row["host"]: row for row in catalogue()["hosts"]}
    assert set(hosts) == {"site", "ai", "model"}
    assert hosts["model"]["units"] == []
    assert hosts["model"]["actions"] == ["reboot", "cancel-reboot"]
    assert hosts["site"]["actions"] == ["reboot", "cancel-reboot", "restart-unit"]
    assert hosts["site"]["stoppable_units"] == []
    assert "docker.service" in hosts["site"]["units"]
    assert "pinky-backend.service" in hosts["ai"]["stoppable_units"]


def test_reboot_is_a_delayed_helper_action_and_pkill_is_refused():
    assert decide("site", "reboot", None, confirmed=True)["argv"] == ("reboot",)
    for action in ("pkill", "kill", "shell", "poweroff"):
        assert _code(lambda: decide("site", action, None, confirmed=True)) == "UNKNOWN_ACTION"


def test_site_units_restart_but_never_stop():
    for unit in HOSTS["site"]:
        assert decide("site", "restart-unit", unit, confirmed=True)["argv"] == ("restart-unit", unit)
        assert _code(lambda: decide("site", "stop-unit", unit, confirmed=True)) == "UNIT_NOT_ALLOWED"


def test_only_an_allowlisted_unit_on_that_host_can_stop():
    assert decide("ai", "stop-unit", "pinky-nav2.service", confirmed=True)["argv"] == (
        "stop-unit", "pinky-nav2.service")
    for host, unit in (("ai", "docker.service"), ("site", "ssh.service"),
                       ("model", "ollama.service"), ("ai", "pinky-nav2.service;reboot")):
        assert _code(lambda: decide(host, "stop-unit", unit, confirmed=True)) == "UNIT_NOT_ALLOWED"


def test_reboot_rejects_a_unit_and_an_unconfirmed_call():
    assert _code(lambda: decide("model", "reboot", "docker.service", confirmed=True)) == "UNIT_NOT_ALLOWED"
    assert _code(lambda: decide("model", "reboot", None, confirmed=False)) == "CONFIRMATION_REQUIRED"


def test_helper_script_matches_the_allowlist_and_has_no_test_switch():
    text = HELPER.read_text(encoding="utf-8")
    assert "pkill" not in text and "ROSY_HOST_CONTROL_PRINT" not in text
    assert 'ROLE=$(cat "$CONF/role"' in text and "ROSY_HOST_CONTROL_ROLE" not in text
    assert "--machine=ai@" not in text and "\nCONF=/etc/rosy/host-control\n" in text
    for host, units in HOSTS.items():
        for unit, actions in units.items():
            for action in ("restart-unit", "stop-unit"):
                listed = re.search(rf"\b{host}:{action}:{re.escape(unit)}[|)]", text) is not None
                assert listed is (action in actions), (host, action, unit)


def test_installer_ships_a_sudoers_line_without_env_rights():
    text = INSTALL.read_text(encoding="utf-8")
    assert "ALL=(root) NOPASSWD: /usr/local/sbin/rosy-host-control\"" in text
    assert "SETENV" not in text and "env_keep" not in text
    assert ('from=\\"$FROM\\",command=\\"/usr/local/sbin/rosy-host-control-remote\\",restrict'
            in text)
    assert 'grep -qxF "$LINE"' in text  # an unrestricted line with the same key is replaced
    assert "/etc/rosy/host-control/role" in text and "host-control-role" not in text
    assert "exec sudo -n /usr/local/sbin/rosy-host-control" in REMOTE.read_text(encoding="utf-8")


def test_only_fleet_mounts_the_service_control_key():
    services = yaml.safe_load((SITE / "compose.yaml").read_text(encoding="utf-8"))["services"]
    mount = "/etc/rosy/fleet-host-control:/run/rosy-fleet-host-control:ro"
    assert mount in services["fleet"]["volumes"]
    assert CONFIG_DIR.as_posix() == "/run/rosy-fleet-host-control"
    for name, service in services.items():
        mounted = " ".join(str(item) for item in service.get("volumes", []))
        secrets = " ".join(str(item) for item in service.get("secrets", []))
        if name != "fleet":
            assert "host-control" not in mounted and "host_control" not in secrets, name
    # The key dir must not sit inside the config dir that Vision mounts too.
    env = (SITE / ".env.example").read_text(encoding="utf-8")
    config_dir = next(line.split("=", 1)[1] for line in env.splitlines()
                      if line.startswith("ROSY_SITE_CONFIG_DIR="))
    assert not "/etc/rosy/fleet-host-control".startswith(config_dir.rstrip("/") + "/")
    assert "FLEET_DIR=/etc/rosy/fleet-host-control" in INSTALL.read_text(encoding="utf-8")


def test_vision_cannot_reach_fleet_secrets():
    compose = yaml.safe_load((SITE / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    env = dict(line.split("=", 1) for line in
               (SITE / ".env.example").read_text(encoding="utf-8").splitlines()
               if re.match(r"^ROSY_SITE_\w+_DIR=", line))
    config, excluded_dir = env["ROSY_SITE_CONFIG_DIR"].rstrip("/"), env["ROSY_SITE_SECRETS_DIR"]
    assert not (excluded_dir + "/").startswith(config + "/") and excluded_dir != config
    # Vision may mount exactly one config file, never a directory that could hold secrets.
    for item in services["vision"]["volumes"]:
        if isinstance(item, str):
            assert item.split(":")[0] == "vision_state", item
            continue
        if item["type"] == "bind":
            assert item["source"].endswith("/site-cameras.yaml") and item["read_only"], item
    mounted = str(services["vision"]["volumes"])
    assert "SECRETS_DIR" not in mounted and "host-control" not in mounted
    own = {"fleet": {"registry_token", "fleet_sighting_token", "discovery_token",
                     "vision_preview_secret", "robot_credential_key", "site_cert", "site_key",
                     "site_ca"},
           "vision": {"phone_ingress_token", "fleet_sighting_token", "vision_preview_secret",
                      "site_cert", "site_key", "site_ca"},
           "proxy": {"site_cert", "site_key", "site_ca"}}
    for name, expected in own.items():
        assert set(services[name]["secrets"]) == expected, name
    for forbidden in ("registry_token", "discovery_token", "robot_credential_key"):
        assert forbidden not in services["vision"]["secrets"]
        assert forbidden not in services["proxy"]["secrets"]
    # Every credential path an app reads names a secret the service itself is given.
    pairing = yaml.safe_load((SITE / "compose.pairing.yaml").read_text(encoding="utf-8"))
    for name in ("fleet", "vision"):
        paths = json.loads(services[name]["environment"]["ROSY_CREDENTIAL_PATHS"]).values()
        extra = pairing["services"][name]["environment"]["ROSY_CREDENTIAL_PATHS"]
        paths = list(paths) + list(json.loads(extra).values())
        allowed = {"/run/secrets/" + s for s in own[name] | {"pairing_sync_token"}}
        assert set(paths) <= allowed, name
        assert {Path(p).name for p in paths}.isdisjoint(
            {"robot_credential_key"} if name == "vision" else set()), name
    for source in list(compose["secrets"].values()) + list(pairing["secrets"].values()):
        assert source["file"].startswith("${ROSY_SITE_SECRETS_DIR:?"), source
    pairing = yaml.safe_load((SITE / "compose.pairing.yaml").read_text(encoding="utf-8"))
    assert pairing["services"]["vision"].get("volumes") is None
    for name in ("fleet", "vision"):
        assert pairing["services"][name]["secrets"] == ["pairing_sync_token"]
    assert "proxy" not in pairing["services"]


def _config(tmp_path, targets):
    (tmp_path / "id_ed25519").write_text("k")
    (tmp_path / "known_hosts").write_text("h")
    (tmp_path / "targets").write_text(targets)
    return tmp_path


def test_ssh_helper_uses_an_argument_list_and_a_fixed_ssh(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["shell"] = argv, kwargs.get("shell", False)
        return subprocess.CompletedProcess(argv, 0, stdout="scheduled\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    helper = helper_from_config(_config(tmp_path, "site rosy@site-pc.local\nai ai@ai-pc.local\n"))
    assert helper.run("ai", ("restart-unit", "pinky-backend.service"))["ok"] is True
    assert seen["argv"][0] == "/usr/bin/ssh" and seen["shell"] is False
    assert seen["argv"][-4:] == ["--", "ai@ai-pc.local", "restart-unit", "pinky-backend.service"]
    assert "StrictHostKeyChecking=yes" in seen["argv"]
    assert helper.run("model", ("reboot",))["code"] == "HOST_HELPER_UNAVAILABLE"


def test_helper_exit_codes_become_api_codes(monkeypatch, tmp_path):
    codes = iter([3, 4, 255])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, next(codes), stdout="", stderr=""))
    helper = helper_from_config(_config(tmp_path, "model rosy@model-pc.local\n"))
    assert [helper.run("model", ("reboot",))["code"] for _ in range(3)] == [
        "REBOOT_ALREADY_SCHEDULED", "NO_HOST_CONTROL_REBOOT", "HOST_HELPER_FAILED"]


def test_missing_or_bad_config_stays_unavailable(tmp_path):
    assert isinstance(helper_from_config(tmp_path), UnavailableHostHelper)
    for bad in ("site -oProxyCommand=x@h\n", "robot rosy@h\n", "site rosy@h extra\n"):
        assert isinstance(helper_from_config(_config(tmp_path, bad)), UnavailableHostHelper)
    with pytest.raises(HostControlError):
        SshHostHelper({"site": "-oProxyCommand=sh@h"}, key=tmp_path, known_hosts=tmp_path)


def _client(helper, *, named=True):
    app = FastAPI()

    def operator():
        return SimpleNamespace(principal_id="operator-1", role="operator")

    def named_operator():
        if not named:
            raise HTTPException(status_code=403, detail={"code": "OPERATOR_IDENTITY_REQUIRED"})
        return operator()

    install_host_control_routes(app, require_operator=operator,
                                require_named_operator=named_operator, helper=helper)
    return TestClient(app)


def test_route_schedules_a_confirmed_restart_and_refuses_pkill(caplog):
    class Recording:
        def run(self, host, argv):
            self.call = (host, argv)
            return {"ok": True, "code": "ACCEPTED", "output": "scheduled"}

    helper = Recording()
    client = _client(helper)
    refused = client.post("/api/fleet/hosts/site/control", json={
        "action": "pkill", "operator_confirmed": True})
    assert refused.status_code == 400
    assert refused.json()["detail"]["code"] == "UNKNOWN_ACTION"
    assert not hasattr(helper, "call")
    caplog.set_level("INFO", logger="fleet.server.host_control_routes")
    accepted = client.post("/api/fleet/hosts/ai/control", json={
        "action": "restart-unit", "unit": "pinky-backend.service",
        "operator_confirmed": True})
    assert accepted.status_code == 200
    assert helper.call == ("ai", ("restart-unit", "pinky-backend.service"))
    assert accepted.json()["requested_by"] == "operator-1"
    logged = [r.getMessage() for r in caplog.records]
    assert any("action=restart-unit unit=pinky-backend.service principal=operator-1" in m
               and "code=ACCEPTED" in m for m in logged)
    assert any(m.startswith("host control request host=ai") for m in logged)


def test_route_needs_a_named_operator():
    client = _client(UnavailableHostHelper(), named=False)
    refused = client.post("/api/fleet/hosts/site/control", json={
        "action": "reboot", "operator_confirmed": True})
    assert refused.status_code == 403


def test_route_reports_a_missing_helper_and_lists_all_hosts(tmp_path):
    client = _client(helper_from_config(tmp_path))
    missing = client.post("/api/fleet/hosts/site/control", json={
        "action": "reboot", "operator_confirmed": True})
    assert missing.status_code == 503
    assert missing.json()["detail"]["code"] == "HOST_HELPER_UNAVAILABLE"
    listed = client.get("/api/fleet/hosts")
    assert listed.status_code == 200
    assert {row["host"] for row in listed.json()["hosts"]} == {"site", "ai", "model"}
    assert listed.json()["guard"] is None and listed.json()["drift"] is None


def test_hosts_route_attaches_guard_headroom_and_ignores_a_bad_drift_file(tmp_path, monkeypatch):
    import fleet.server.host_control_routes as routes

    guard = tmp_path / "guard.json"
    guard.write_text('{"model": {"state": "ok", "resources": {"avail_pct": 41, "load": 1.5, "cores": 8}}}',
                     encoding="utf-8")
    (tmp_path / "drift.json").write_text("[1]", encoding="utf-8")
    monkeypatch.setattr(routes, "GUARD_STATUS", guard)
    monkeypatch.setattr(routes, "DRIFT_STATUS", tmp_path / "drift.json")
    body = _client(UnavailableHostHelper()).get("/api/fleet/hosts").json()
    assert body["guard"]["model"]["resources"]["avail_pct"] == 41
    assert body["drift"] is None


def test_install_task_shows_host_headroom_and_has_no_process_kill():
    web = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
    page = (web / "install.html").read_text(encoding="utf-8")
    script = (web / "host-services.js").read_text(encoding="utf-8")
    install = (web / "install.js").read_text(encoding="utf-8")
    assets = (web.parent / "static_routes.py").read_text(encoding="utf-8")
    assert 'id="host-services"' in page and "호스트 서비스" in page
    assert "pkill" not in script and "kill" not in script
    assert "10분 뒤 재부팅" in script and "operator_confirmed: true" in script
    assert 'id: "hosts"' in install and 'from "./host-services.js"' in install
    assert '"host-services.js"' in assets


def test_app_without_named_principals_never_reaches_a_helper(monkeypatch):
    import fleet.host_control as host_control
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole

    monkeypatch.setattr(host_control, "helper_from_config",
                        lambda *a: pytest.fail("helper built without named principals"))
    client = TestClient(create_app(FleetConsole({}, [])))
    answer = client.post("/api/fleet/hosts/site/control", json={
        "action": "reboot", "operator_confirmed": True})
    assert answer.status_code == 403
    assert answer.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"


# The shipped helper reads fixed root paths; the test runs its own copy with those paths
# moved under tmp_path and stub shutdown/systemctl/logger on PATH.
def _helper_copy(tmp_path, role):
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    sched = tmp_path / "scheduled"
    (stub / "shutdown").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = -c ]; then rm -f {sched}; echo cancel >> {tmp_path}/calls; exit 0; fi\n'
        f'printf "USEC=%s\\nMODE=reboot\\n" "$(date +%s%N)" > {sched}; echo reboot >> {tmp_path}/calls\n')
    for name in ("systemctl", "logger", "flock"):
        (stub / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {tmp_path}/calls\n')
    for path in stub.iterdir():
        path.chmod(0o755)
    (tmp_path / "conf").mkdir(exist_ok=True)
    (tmp_path / "conf" / "role").write_text(role + "\n")
    (tmp_path / "conf" / "units-user").write_text("pinky\n")
    text = HELPER.read_text(encoding="utf-8")
    for old, new in (("CONF=/etc/rosy/host-control", f"CONF={tmp_path / 'conf'}"),
                     ("/run/systemd/shutdown/scheduled", sched),
                     ("/run/rosy-host-control", tmp_path / "state"),
                     ("PATH=/usr/sbin:/usr/bin:/sbin:/bin", f"PATH={stub}:/usr/bin:/bin")):
        assert old in text
        text = text.replace(old, str(new))
    copy = tmp_path / "helper"
    copy.write_text(text)
    return lambda *argv: subprocess.run(["bash", str(copy), *argv], capture_output=True,
                                        text=True, timeout=20).returncode


@posix
def test_helper_refuses_a_second_reboot_and_cancels_only_its_own(tmp_path):
    helper = _helper_copy(tmp_path, "model")
    assert helper("cancel-reboot") == 4
    assert helper("reboot") == 0
    assert helper("reboot") == 3
    assert helper("cancel-reboot") == 0
    assert helper("cancel-reboot") == 4
    # A reboot someone else scheduled (nightly window, unattended-upgrades) is not ours.
    (tmp_path / "scheduled").write_text("USEC=1\nMODE=reboot\n")
    assert helper("reboot") == 3
    assert helper("cancel-reboot") == 4
    assert (tmp_path / "calls").read_text().splitlines().count("cancel") == 1


@posix
def test_helper_refuses_site_stop_and_unknown_role(tmp_path):
    helper = _helper_copy(tmp_path, "site")
    assert helper("stop-unit", "rosy-site-firewall.service") == 2
    assert helper("restart-unit", "rosy-site-firewall.service") == 0
    assert "systemctl --no-block restart rosy-site-firewall.service" in (tmp_path / "calls").read_text()
    (tmp_path / "conf" / "role").write_text("robot\n")
    assert helper("reboot") == 2
    (tmp_path / "conf" / "role").write_text("ai\n")
    assert helper("stop-unit", "pinky-nav2.service") == 0
    assert "systemctl --user --machine=pinky@ --no-block stop pinky-nav2.service" in (
        tmp_path / "calls").read_text()


@posix
def test_forced_command_passes_at_most_two_words(tmp_path):
    def remote(command):
        env = {**os.environ, "SSH_ORIGINAL_COMMAND": command}
        return subprocess.run(["sh", str(REMOTE)], env=env, capture_output=True, timeout=10).returncode

    assert remote("restart-unit a b") == 2
    assert remote("") == 2
    assert remote("reboot *") == 2


def _install_copy(tmp_path):
    """The helper with root paths under tmp_path; runuser/getent/chown stubbed (no root here)."""
    helper = _helper_copy(tmp_path, "site")  # writes conf/, state stubs; we rewrite one more path
    del helper
    stub = tmp_path / "bin"
    home = tmp_path / "home"
    (home / ".rosy" / "site-incoming").mkdir(parents=True)
    (stub / "runuser").write_text('#!/bin/sh\n[ "$1" = -u ] && shift 2; [ "$1" = -- ] && shift; exec "$@"\n')
    (stub / "getent").write_text(f'#!/bin/sh\necho "op:x:1000:1000::{home}:/bin/sh"\n')
    (stub / "chown").write_text("#!/bin/sh\nexit 0\n")
    for name in ("runuser", "getent", "chown"):
        (stub / name).chmod(0o755)
    site, backup = tmp_path / "site", tmp_path / "backup"
    site.mkdir()
    copy = tmp_path / "helper"
    text = copy.read_text()
    for old, new in (("SITE_CONF=/etc/rosy/site", f"SITE_CONF={site}"),
                     ("BACKUP=/var/lib/rosy-host-control/backup", f"BACKUP={backup}")):
        assert old in text
        text = text.replace(old, new)
    copy.write_text(text)

    def run(name, user="op"):
        env = {**os.environ, "SUDO_USER": user}
        return subprocess.run(["bash", str(copy), "install-site-config", name], env=env,
                              capture_output=True, text=True, timeout=20).returncode
    return run, home / ".rosy" / "site-incoming", site, backup


@posix
def test_site_config_install_copies_checks_and_backs_up(tmp_path):
    run, incoming, site, backup = _install_copy(tmp_path)
    (incoming / "fleet-site.yaml").write_text("fleet: {traffic: {}}\n")
    assert run("fleet-site.yaml") == 0
    assert (site / "fleet-site.yaml").read_text() == "fleet: {traffic: {}}\n"
    assert oct((site / "fleet-site.yaml").stat().st_mode & 0o777) == "0o644"
    (incoming / "fleet-site.yaml").write_text("fleet: {traffic: {zones: {}}}\n")
    assert run("fleet-site.yaml") == 0
    assert [p.read_text() for p in backup.iterdir()] == ["fleet: {traffic: {}}\n"]
    # Refusals leave the installed file alone and no temp file behind.
    (incoming / "fleet-site.yaml").write_text("fleet: [unclosed\n")
    assert run("fleet-site.yaml") == 2
    (incoming / "fleet-site.yaml").write_text("a: " + "x" * 70000 + "\n")
    assert run("fleet-site.yaml") == 2
    assert run("robots.yaml") == 2                 # not allowlisted (holds robot tokens)
    assert run("../site-cameras.yaml") == 2
    assert run("site-cameras.yaml") == 2           # nothing staged
    assert run("fleet-site.yaml", user="root") == 2
    assert (site / "fleet-site.yaml").read_text() == "fleet: {traffic: {zones: {}}}\n"
    assert sorted(p.name for p in site.iterdir()) == ["fleet-site.yaml"]


@posix
def test_fleet_key_cannot_install_site_config():
    env = {**os.environ, "SSH_ORIGINAL_COMMAND": "install-site-config fleet-site.yaml"}
    assert subprocess.run(["sh", str(REMOTE)], env=env, capture_output=True, timeout=10).returncode == 2
