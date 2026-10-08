"""D-524 Service Control. No network and no real shutdown."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.host_control import (
    HOSTS,
    HostControlError,
    SubprocessHostHelper,
    catalogue,
    decide,
    helper_from_environment,
)
from fleet.server.host_control_routes import install_host_control_routes

HELPER = Path(__file__).resolve().parents[3] / "deploy" / "site" / "rosy-host-control"


def test_catalogue_is_the_three_ubuntu_hosts():
    hosts = {row["host"]: row for row in catalogue()["hosts"]}
    assert set(hosts) == {"site", "ai", "model"}
    assert hosts["model"]["units"] == []
    assert hosts["model"]["actions"] == ["reboot", "cancel-reboot"]
    assert "docker.service" in hosts["site"]["units"]
    assert "pinky-backend.service" in hosts["ai"]["units"]


def test_reboot_is_a_delayed_helper_action_and_pkill_is_refused():
    command = decide("site", "reboot", None, confirmed=True)
    assert command["argv"] == ("reboot",)
    for action in ("pkill", "kill", "shell", "poweroff"):
        try:
            decide("site", action, None, confirmed=True)
        except HostControlError as exc:
            assert exc.code == "UNKNOWN_ACTION"
        else:
            raise AssertionError(action)


def test_only_an_allowlisted_unit_on_that_host_can_stop():
    assert decide("site", "stop-unit", "docker.service", confirmed=True)["argv"] == (
        "stop-unit", "docker.service")
    for host, unit in (
        ("ai", "docker.service"),
        ("site", "ssh.service"),
        ("model", "ollama.service"),
        ("site", "docker.service;reboot"),
    ):
        try:
            decide(host, "stop-unit", unit, confirmed=True)
        except HostControlError as exc:
            assert exc.code == "UNIT_NOT_ALLOWED"
        else:
            raise AssertionError((host, unit))


def test_reboot_rejects_a_unit_and_an_unconfirmed_call():
    try:
        decide("model", "reboot", "docker.service", confirmed=True)
    except HostControlError as exc:
        assert exc.code == "UNIT_NOT_ALLOWED"
    else:
        raise AssertionError("unit")
    try:
        decide("model", "reboot", None, confirmed=False)
    except HostControlError as exc:
        assert exc.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("confirm")


def test_helper_script_matches_the_allowlist_and_has_no_pkill():
    text = HELPER.read_text(encoding="utf-8")
    assert "pkill" not in text
    for host, units in HOSTS.items():
        assert f"{host}:reboot:" in text
        assert f"{host}:cancel-reboot:" in text
        for unit in units:
            assert f"{host}:stop-unit:{unit}" in text
            assert f"{host}:restart-unit:{unit}" in text


def test_subprocess_helper_uses_an_argument_list(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["shell"] = kwargs.get("shell", False)
        return subprocess.CompletedProcess(argv, 0, stdout="scheduled\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    helper = SubprocessHostHelper(helper="/usr/local/sbin/rosy-host-control", role="site")
    assert helper.run("site", ("reboot",))["ok"] is True
    assert seen["argv"] == ["/usr/local/sbin/rosy-host-control", "reboot"]
    assert seen["shell"] is False
    assert helper.run("ai", ("reboot",))["code"] == "HOST_NOT_LOCAL"
    try:
        SubprocessHostHelper(helper="/bin/bash", role="site")
    except HostControlError as exc:
        assert exc.code == "HELPER_REFUSED"
    else:
        raise AssertionError("name")


def test_environment_without_the_named_helper_stays_unavailable():
    helper = helper_from_environment({})
    assert helper.run("site", ("reboot",))["code"] == "HOST_HELPER_UNAVAILABLE"
    helper = helper_from_environment({
        "ROSY_HOST_CONTROL_HELPER": "/tmp/bash",
        "ROSY_HOST_CONTROL_ROLE": "site",
    })
    assert helper.run("site", ("reboot",))["code"] == "HOST_HELPER_UNAVAILABLE"


def _client(helper):
    app = FastAPI()

    def operator():
        return SimpleNamespace(principal_id="operator-1", role="operator")

    install_host_control_routes(app, require_operator=operator, helper=helper)
    return TestClient(app)


def test_route_schedules_a_confirmed_reboot_and_refuses_pkill():
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
    accepted = client.post("/api/fleet/hosts/ai/control", json={
        "action": "restart-unit", "unit": "pinky-backend.service",
        "operator_confirmed": True})
    assert accepted.status_code == 200
    assert helper.call == ("ai", ("restart-unit", "pinky-backend.service"))
    assert accepted.json()["requested_by"] == "operator-1"


def test_route_reports_a_missing_helper_and_hides_other_hosts():
    client = _client(helper_from_environment({}))
    missing = client.post("/api/fleet/hosts/site/control", json={
        "action": "reboot", "operator_confirmed": True})
    assert missing.status_code == 503
    assert missing.json()["detail"]["code"] == "HOST_HELPER_UNAVAILABLE"
    listed = client.get("/api/fleet/hosts")
    assert listed.status_code == 200
    assert {row["host"] for row in listed.json()["hosts"]} == {"site", "ai", "model"}
