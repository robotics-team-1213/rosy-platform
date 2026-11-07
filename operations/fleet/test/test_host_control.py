"""D-524 Service Control. No network and no real shutdown."""

import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fleet.server.device_care import DeviceCareStore

from fleet.host_control import (
    CONFIG_DIR,
    HOSTS,
    HostControlError,
    SshHostHelper,
    UnavailableHostHelper,
    catalogue,
    decide,
    helper_from_config,
    update_summary,
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
    assert "rosy-review-v13.service" in hosts["model"]["units"]
    assert hosts["model"]["actions"] == ["reboot", "reboot-over-jobs", "cancel-reboot", "clean-storage", "restart-unit"]
    assert hosts["ai"]["actions"][:4] == ["reboot", "reboot-over-jobs", "cancel-reboot", "clean-storage"]
    assert hosts["site"]["actions"] == ["reboot", "reboot-over-jobs", "cancel-reboot", "restart-unit"]
    assert "docker.service" in hosts["site"]["units"]
    assert "rosy-situation.service" in hosts["ai"]["units"]
    assert not any(unit.startswith("pinky-") for row in hosts.values() for unit in row["units"])


def test_reboot_is_a_delayed_helper_action_and_pkill_is_refused():
    # A person's reboot respects running jobs; only the explicit second step goes past them.
    assert decide("site", "reboot", None, confirmed=True)["argv"] == ("reboot-if-free",)
    assert decide("site", "reboot-over-jobs", None, confirmed=True)["argv"] == ("reboot",)
    for action in ("pkill", "kill", "shell", "poweroff"):
        assert _code(lambda: decide("site", action, None, confirmed=True)) == "UNKNOWN_ACTION"


def test_units_restart_but_no_unit_can_stop():
    for host, units in HOSTS.items():
        for unit in units:
            assert decide(host, "restart-unit", unit, confirmed=True)["argv"] == ("restart-unit", unit)
            assert _code(lambda: decide(host, "stop-unit", unit, confirmed=True)) == "UNKNOWN_ACTION"


def test_only_an_allowlisted_unit_on_that_host_can_restart():
    for host, unit in (("ai", "docker.service"), ("site", "ssh.service"),
                       ("model", "ollama.service"), ("ai", "rosy-situation.service;reboot"),
                       # D-795: cross-host DDS units (AI PC Nav2, rosbridge) are gone.
                       ("ai", "pinky-nav2.service"), ("ai", "pinky-rosbridge-d12.service")):
        assert _code(lambda: decide(host, "restart-unit", unit, confirmed=True)) == "UNIT_NOT_ALLOWED"


def test_a_person_restarts_exactly_the_user_units_services_yaml_flags():
    """Two lists of one fact; a unit retired from a host must leave the restart list in the same change."""
    roles = yaml.safe_load((SITE.parents[1] / "deploy/hosts/services.yaml").read_text(encoding="utf-8"))["roles"]

    def flagged(*names):
        found = set()
        for name in names:
            for unit, entry in roles[name].items():
                if not entry.get("operator_restart"):
                    continue
                assert entry["run"] == "active", unit
                stem = unit[:-len("@.service")] if "@" in unit else None
                found |= {f"{stem}@{i}.service" for i in entry["instances"]} if stem else {unit}
        return found

    assert flagged("model") == set(HOSTS["model"])
    assert flagged("ai") == set(HOSTS["ai"])
    assert flagged("site", "omx") == set(HOSTS["site"]) - {
        "docker.service", "rosy-site-stack.service", "rosy-site-firewall.service"}


def test_only_the_lab_pcs_clean_storage_and_never_with_a_unit():
    for host in ("ai", "model"):
        assert decide(host, "clean-storage", None, confirmed=True)["argv"] == ("clean-storage",)
        assert _code(lambda: decide(host, "clean-storage", "docker.service", confirmed=True)) == "UNIT_NOT_ALLOWED"
    assert _code(lambda: decide("site", "clean-storage", None, confirmed=True)) == "ACTION_NOT_ALLOWED"


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
            assert re.search(rf"\b{host}:restart-unit:{re.escape(unit)}[|)]", text), (host, unit)
    assert len(re.findall(r"\b\w+:restart-unit:\S+?[|)]", text)) == sum(map(len, HOSTS.values()))
    assert "stop-unit" not in text and "systemctl --no-block stop" not in text


@posix
@pytest.mark.parametrize("role, writes", [("ai", True), ("model", True), ("site", False)])
def test_installer_names_the_storage_owner_on_the_lab_pcs(role, writes):
    """D-883: a model PC without units-user refused every clean-storage request."""
    out = subprocess.run(["bash", str(INSTALL), "--role", role, "--dry-run", "--units-user", "lab"],
                         capture_output=True, text=True, timeout=20, check=True).stdout
    assert ("+ write /etc/rosy/host-control/units-user (0644)\n    lab\n" in out) is writes


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
    # D-796: the fleet service also reads the site context-log store's password.
    own = {"fleet": {"registry_token", "fleet_sighting_token", "discovery_token",
                     "vision_preview_secret", "robot_credential_key", "site_cert", "site_key",
                     "site_ca", "postgres_password"},
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
    assert helper.run("ai", ("restart-unit", "rosy-situation.service"))["ok"] is True
    assert seen["argv"][0] == "/usr/bin/ssh" and seen["shell"] is False
    assert seen["argv"][-4:] == ["--", "ai@ai-pc.local", "restart-unit", "rosy-situation.service"]
    assert "StrictHostKeyChecking=yes" in seen["argv"]
    assert helper.run("model", ("reboot",))["code"] == "HOST_HELPER_UNAVAILABLE"


def test_helper_exit_codes_become_api_codes(monkeypatch, tmp_path):
    codes = iter([3, 4, 5, 6, 7, 255])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, next(codes), stdout="", stderr=""))
    helper = helper_from_config(_config(tmp_path, "model rosy@model-pc.local\n"))
    assert [helper.run("model", ("reboot",))["code"] for _ in range(6)] == [
        "REBOOT_ALREADY_SCHEDULED", "NO_HOST_CONTROL_REBOOT", "NO_STORAGE_SERVICE",
        "ARM_SESSION_ACTIVE", "HOST_JOBS_ACTIVE", "HOST_HELPER_FAILED"]


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

    def viewer():
        return SimpleNamespace(principal_id="viewer-1", role="viewer")

    install_host_control_routes(app, require_operator=operator, require_viewer=viewer,
                                require_named_operator=named_operator, helper=helper)
    return TestClient(app)


def test_each_request_and_its_answer_stay_in_the_care_history(tmp_path):
    """D-991: the audit row names only the host; a person asking what happened needs the action."""
    class Answers:
        def __init__(self):
            self.codes = iter([{"ok": True, "code": "ACCEPTED"}, {"ok": False, "code": "ARM_SESSION_ACTIVE"}])

        def run(self, host, argv):
            return next(self.codes)

    client = _client(Answers())
    client.app.state.device_care = DeviceCareStore(tmp_path / "care.db")
    send = {"operator_confirmed": True}
    assert client.post("/api/fleet/hosts/model/control", json={
        **send, "action": "restart-unit", "unit": "rosy-review-v13.service"}).status_code == 200
    assert client.post("/api/fleet/hosts/model/control", json={**send, "action": "reboot"}).status_code == 409
    rows = client.get("/api/fleet/hosts").json()["history"]["model"]
    assert [row["text"] for row in rows] == ["reboot ARM_SESSION_ACTIVE", "restart-unit rosy-review-v13.service ACCEPTED"]
    assert {row["actor"] for row in rows} == {"operator-1"}


def test_history_is_optional_and_a_broken_store_never_changes_the_answer(tmp_path):
    class Broken:
        def add_host_event(self, *_, **__):
            raise sqlite3.OperationalError("disk full")

        def host_events(self, *_):
            raise sqlite3.OperationalError("disk full")

    class Accepts:
        def run(self, host, argv):
            return {"ok": True, "code": "ACCEPTED"}

    client = _client(Accepts())
    assert client.get("/api/fleet/hosts").json()["history"] == {}
    client.app.state.device_care = Broken()
    assert client.get("/api/fleet/hosts").json()["history"] == {}
    assert client.post("/api/fleet/hosts/ai/control", json={
        "action": "cancel-reboot", "unit": None, "operator_confirmed": True}).status_code == 200


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
        "action": "restart-unit", "unit": "rosy-situation.service",
        "operator_confirmed": True})
    assert accepted.status_code == 200
    assert helper.call == ("ai", ("restart-unit", "rosy-situation.service"))
    assert accepted.json()["requested_by"] == "operator-1"
    logged = [r.getMessage() for r in caplog.records]
    assert any("action=restart-unit unit=rosy-situation.service principal=operator-1" in m
               and "code=ACCEPTED" in m for m in logged)
    assert any(m.startswith("host control request host=ai") for m in logged)


def test_route_needs_a_named_operator():
    client = _client(UnavailableHostHelper(), named=False)
    refused = client.post("/api/fleet/hosts/site/control", json={
        "action": "reboot", "operator_confirmed": True})
    assert refused.status_code == 403


def test_route_reports_a_missing_helper_and_lists_all_hosts(tmp_path, monkeypatch):
    import fleet.server.host_control_routes as routes

    # The route reads absolute host paths. A test PC may already have them.
    monkeypatch.setattr(routes, "GUARD_STATUS", tmp_path / "missing-guard.json")
    monkeypatch.setattr(routes, "DRIFT_STATUS", tmp_path / "missing-drift.json")
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
    web = Path(__file__).resolve().parents[3] / 'applications/fleet/web'
    page = (web / "installation" / "install.html").read_text(encoding="utf-8")
    script = (web / "installation" / "host-services.js").read_text(encoding="utf-8")
    install = (web / "installation" / "install.js").read_text(encoding="utf-8")
    assets = json.loads((web / 'assets.json').read_text(encoding='utf-8'))['assets']
    assert 'id="host-services"' in page and "호스트 서비스" in page
    assert "pkill" not in script and "kill" not in script
    assert "10분 뒤 재부팅" in script and "operator_confirmed: true" in script
    assert '.includes("clean-storage")' in script  # only hosts whose catalogue offers it get the button
    assert 'id: "hosts"' in install and 'from "./host-services.js"' in install
    assert assets['host-services.js']['path'] == 'installation/host-services.js'


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
    for name in ("systemctl", "logger", "systemd-run"):
        (stub / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {tmp_path}/calls\n')
    (stub / "flock").write_text("#!/bin/sh\nexit 0\n")  # the helper's own `flock 9`; sessions use real locks
    for path in stub.iterdir():
        path.chmod(0o755)
    (tmp_path / "conf").mkdir(exist_ok=True)
    (tmp_path / "conf" / "role").write_text(role + "\n")
    (tmp_path / "conf" / "units-user").write_text("pinky\n")
    text = HELPER.read_text(encoding="utf-8")
    for old, new in (("CONF=/etc/rosy/host-control", f"CONF={tmp_path / 'conf'}"),
                     ("/run/systemd/shutdown/scheduled", sched),
                     ("/run/rosy-host-control", tmp_path / "state"),
                     ("HOME_ROOT=/home", f"HOME_ROOT={tmp_path / 'home'}"),
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


def _arm_session(tmp_path, shared=False):
    """A real lock in /proc/locks, the way joint_tune (exclusive) and per-arm sessions (shared) hold it."""
    lock = tmp_path / "home" / "op" / "rosy-omx" / "session.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
    return fd


def _job_lock(tmp_path, pid, kind="gpu"):
    jobs = tmp_path / "home" / "op" / "rosy-jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / f"train-{pid}.lock").write_text(f"{pid} {kind} 8 16\n")


@posix
def test_no_reboot_path_cuts_an_arm_session(tmp_path):
    """2026-10-28: a reboot cut a chunk session mid-move and the arm dropped with torque off.
    Only the nightly timer looked at the lock; the button and the guard's ladder did not."""
    helper = _helper_copy(tmp_path, "site")
    session = _arm_session(tmp_path)
    assert helper("reboot") == 6
    assert helper("reboot-if-free") == 6
    assert not (tmp_path / "scheduled").exists()
    os.close(session)
    session = _arm_session(tmp_path, shared=True)
    assert helper("reboot") == 6
    os.close(session)
    assert (tmp_path / "home" / "op" / "rosy-omx" / "session.lock").exists()  # a finished session leaves its file
    assert helper("reboot") == 0


@posix
def test_a_session_started_during_the_delay_cancels_only_our_reboot(tmp_path):
    """The +10 min is a window of its own: the helper asks again just before it ends."""
    helper = _helper_copy(tmp_path, "site")
    assert helper("reboot") == 0
    calls = (tmp_path / "calls").read_text()
    assert "systemd-run" in calls and "/usr/local/sbin/rosy-host-control recheck-reboot" in calls
    assert helper("recheck-reboot") == 0
    assert (tmp_path / "scheduled").exists()  # free: it goes ahead
    session = _arm_session(tmp_path)
    assert helper("recheck-reboot") == 0
    os.close(session)
    assert not (tmp_path / "scheduled").exists()
    assert (tmp_path / "calls").read_text().splitlines().count("cancel") == 1
    (tmp_path / "scheduled").write_text("USEC=1\nMODE=reboot\n")  # someone else's reboot is not ours
    session = _arm_session(tmp_path)
    assert helper("recheck-reboot") == 0
    os.close(session)
    assert (tmp_path / "scheduled").exists()


@posix
def test_a_refused_recheck_timer_means_no_reboot_is_scheduled(tmp_path):
    """Without the second look the delay is unguarded, so the reboot must not start at all."""
    helper = _helper_copy(tmp_path, "site")
    (tmp_path / "bin" / "systemd-run").write_text("#!/bin/sh\nexit 1\n")
    assert helper("reboot") != 0
    assert not (tmp_path / "scheduled").exists()


@posix
def test_a_persons_reboot_stops_at_live_jobs_and_the_guard_does_not(tmp_path):
    """D-530: rebooting a PC a runaway training job has wedged is the guard's whole purpose."""
    helper = _helper_copy(tmp_path, "model")
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        _job_lock(tmp_path, sleeper.pid)
        assert helper("reboot-if-free") == 7
        assert not (tmp_path / "scheduled").exists()
        assert helper("reboot") == 0
    finally:
        sleeper.kill()
        sleeper.wait()


@posix
def test_dead_and_malformed_job_locks_do_not_block(tmp_path):
    helper = _helper_copy(tmp_path, "model")
    finished = subprocess.Popen(["true"])
    finished.wait()
    _job_lock(tmp_path, finished.pid)
    jobs = tmp_path / "home" / "op" / "rosy-jobs"
    for name, text in (("word", "abc gpu 1 1\n"), ("zero", "0 gpu 1 1\n"), ("init", "1 gpu 1 1\n"), ("huge", "9" * 40 + "\n")):
        (jobs / f"{name}.lock").write_text(text)
    assert helper("reboot-if-free") == 0


@posix
def test_a_job_lock_from_before_this_boot_does_not_block(tmp_path):
    """Its pid may belong to something else by now."""
    helper = _helper_copy(tmp_path, "model")
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        _job_lock(tmp_path, sleeper.pid)
        os.utime(tmp_path / "home" / "op" / "rosy-jobs" / f"train-{sleeper.pid}.lock", (1, 1))
        assert helper("reboot-if-free") == 0
    finally:
        sleeper.kill()
        sleeper.wait()


@posix
def test_a_users_file_cannot_hang_or_flood_the_root_helper(tmp_path):
    """Root holding its own lock on a FIFO's open would also stop the re-check timer."""
    helper = _helper_copy(tmp_path, "model")
    home = tmp_path / "home" / "op"
    (home / "rosy-omx").mkdir(parents=True)
    (home / "rosy-jobs").mkdir()
    os.mkfifo(home / "rosy-omx" / "session.lock")
    os.mkfifo(home / "rosy-jobs" / "pipe.lock")
    os.mkfifo(home / "rosy-jobs" / "busy")
    (home / "rosy-jobs" / "zero.lock").symlink_to("/dev/zero")
    assert helper("reboot-if-free") == 0  # the copy's run times out in 20 s if any of these hang


@posix
@pytest.mark.parametrize("delta, blocks", [(3600, True), (-3600, False)])
def test_an_isaac_reservation_is_a_job_until_it_expires(tmp_path, delta, blocks):
    """A supervised Isaac run holds only a .resv (remote_isaac.py), no lock."""
    helper = _helper_copy(tmp_path, "model")
    jobs = tmp_path / "home" / "op" / "rosy-jobs"
    jobs.mkdir(parents=True)
    (jobs / "isaac-run.resv").write_text(f"{int(time.time()) + delta} gpu 6 8\n")
    assert helper("reboot-if-free") == (7 if blocks else 0)


@posix
@pytest.mark.parametrize("delta, blocks", [(3600, True), (-3600, False)])
def test_a_busy_hold_blocks_a_persons_reboot_until_it_expires(tmp_path, delta, blocks):
    helper = _helper_copy(tmp_path, "site")
    jobs = tmp_path / "home" / "op" / "rosy-jobs"
    jobs.mkdir(parents=True)
    (jobs / "busy").write_text(f"{int(time.time()) + delta} person 1\n")
    assert helper("reboot-if-free") == (7 if blocks else 0)


@posix
def test_a_bare_touch_busy_ends_with_the_boot(tmp_path):
    helper = _helper_copy(tmp_path, "site")
    busy = tmp_path / "home" / "op" / "rosy-jobs" / "busy"
    busy.parent.mkdir(parents=True)
    busy.touch()
    assert helper("reboot-if-free") == 7
    os.utime(busy, (1, 1))
    assert helper("reboot-if-free") == 0


@posix
def _systemd_like(tmp_path, load_state):
    """systemd 255 refuses `cat` over --machine ("Cannot remotely cat units.") and answers
    `show -p LoadState --value` with loaded or not-found; the plain stub accepted both."""
    (tmp_path / "bin" / "systemctl").write_text(
        f'#!/bin/sh\necho "systemctl $*" >> {tmp_path}/calls\n'
        'case "$*" in *--machine=*" cat "*) echo "Cannot remotely cat units." >&2; exit 1;;\n'
        f'  *"show -p LoadState --value"*) echo {load_state};; esac\n')


@posix
def test_helper_starts_only_the_lab_storage_service_and_refuses_the_site(tmp_path):
    """2026-10-26 on the model PC: the linked unit was refused with exit 5 by a remote `cat`."""
    helper = _helper_copy(tmp_path, "model")
    _systemd_like(tmp_path, "loaded")
    assert helper("clean-storage") == 0
    calls = (tmp_path / "calls").read_text()
    assert "systemctl --user --machine=pinky@ --no-block start rosy-test-storage.service" in calls
    assert helper("clean-storage", "x.service") == 2
    _systemd_like(tmp_path, "not-found")  # a PC where rosy-ops never linked the unit
    assert helper("clean-storage") == 5
    (tmp_path / "conf" / "role").write_text("site\n")
    assert helper("clean-storage") == 2
    assert (tmp_path / "calls").read_text().count(" start rosy-test-storage.service") == 1


@posix
def test_helper_refuses_site_stop_and_unknown_role(tmp_path):
    helper = _helper_copy(tmp_path, "site")
    assert helper("stop-unit", "rosy-site-firewall.service") == 2
    session = _arm_session(tmp_path)
    assert helper("restart-unit", "rosy-omx-camera@arm_a_wrist.service") == 6  # a session is reading it
    assert helper("restart-unit", "rosy-site-stack.service") == 0  # Fleet is not what moves the arm
    os.close(session)
    assert helper("restart-unit", "rosy-omx-camera@arm_a_wrist.service") == 0
    assert "--user --machine=pinky@ --no-block restart rosy-omx-camera@arm_a_wrist.service" in (
        tmp_path / "calls").read_text()
    assert helper("restart-unit", "rosy-site-firewall.service") == 0
    assert "systemctl --no-block restart rosy-site-firewall.service" in (tmp_path / "calls").read_text()
    (tmp_path / "conf" / "role").write_text("robot\n")
    assert helper("reboot") == 2
    (tmp_path / "conf" / "role").write_text("ai\n")
    assert helper("stop-unit", "rosy-situation.service") == 2
    assert helper("restart-unit", "pinky-frontend.service") == 2  # another owner's service
    assert helper("restart-unit", "rosy-situation.service") == 0
    assert "systemctl --user --machine=pinky@ --no-block restart rosy-situation.service" in (
        tmp_path / "calls").read_text()


@posix
def test_forced_command_passes_at_most_two_words(tmp_path):
    def remote(command):
        env = {**os.environ, "SSH_ORIGINAL_COMMAND": command}
        return subprocess.run(["sh", str(REMOTE)], env=env, capture_output=True, timeout=10).returncode

    assert remote("restart-unit a b") == 2
    assert remote("") == 2
    assert remote("reboot *") == 2
    assert remote("recheck-reboot") == 2  # the helper's own timer, never a caller's
    assert remote("restart-unit a;b") == 2


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


NOW = 2_000_000_000.0


def _report(*updaters, gate="open", **extra):
    return {"schema": "rosy.update-report/1", "time": int(NOW), "gate": gate, "updaters": list(updaters), **extra}


def _updater(unit, *, timer="enabled", healthy=NOW - 60, step="up_to_date", release="c47d7c3e78c9", reason=None):
    return {"unit": unit, "timer": timer, "healthy_at": healthy,
            "last": {"step": step, "release": release, "reason": reason, "at": NOW - 30}}


def test_update_summary_names_each_channel_ok_off_or_stuck_and_never_guesses_a_silent_pc():
    guard = {
        "site": {"updates": _report(_updater("rosy-omx-devices-autoupdate.service"),
                                    site_stack={"current": "site-221aedf1bdd5", "result": "idle"})},
        "model": {"updates": _report(_updater("rosy-learning-center-update.service", timer="disabled"),
                                     _updater("rosy-model-code-update.service", healthy=NOW - 7 * 3600,
                                              step="held", reason="work_lock_busy"))},
        "ai": {"state": "ok", "updates": None},  # an older forced command: no report
        "robot-a": {"state": "ok"},  # robots are probed, not updated here
        "cell-c": {"updates": _report({"unit": "../../etc/passwd", "timer": "enabled"},
                                      _updater("rosy-omx-autoupdate.service", release="<script>"), gate="open; rm")},
        "cell-b": {"updates": _report(_updater("rosy-omx-autoupdate.service"), gate="frozen")},
    }
    hosts = {h["host"]: h for h in update_summary(guard, NOW)["hosts"]}
    assert hosts["site"]["state"] == "ok"
    assert [c["release"] for c in hosts["site"]["channels"]] == ["c47d7c3e78c9", "site-221aedf1bdd5"]
    assert [c["state"] for c in hosts["model"]["channels"]] == ["off", "stuck"] and hosts["model"]["state"] == "stuck"
    assert hosts["ai"] == {"host": "ai", "state": "unknown", "gate": None, "channels": []}
    assert hosts["cell-b"]["state"] == "frozen"  # more than three PCs: one per OMX cell
    assert "robot-a" not in hosts
    assert [c["unit"] for c in hosts["cell-c"]["channels"]] == ["rosy-omx-autoupdate.service"]
    assert hosts["cell-c"]["channels"][0]["release"] is None and hosts["cell-c"]["gate"] is None
    assert "work_lock_busy" not in json.dumps(hosts)  # reasons are for operators (/api/fleet/hosts)


def test_every_signed_in_role_reads_the_update_summary(tmp_path, monkeypatch):
    import fleet.server.host_control_routes as routes

    guard = tmp_path / "guard.json"
    guard.write_text(json.dumps({"ai": {"updates": _report(_updater("rosy-situation-autoupdate.service"))}}),
                     encoding="utf-8")
    monkeypatch.setattr(routes, "GUARD_STATUS", guard)
    body = _client(UnavailableHostHelper()).get("/api/fleet/updates").json()
    assert body["hosts"][0]["host"] == "ai" and body["hosts"][0]["channels"][0]["unit"] == "rosy-situation-autoupdate.service"
