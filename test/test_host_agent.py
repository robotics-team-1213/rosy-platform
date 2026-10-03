"""Refusal, audit and idempotency contracts for the Host Agent (WP-4).

The Host Agent is the one ROSY process holding host privilege, so what it
*refuses* is more of the contract than what it does. Every refusal below is
decided without a socket and without running anything, which is why the whole
allowlist can be exercised on any machine.

Contract: docs/reference/rosy-host-agent-contract.md
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from host_agent import (  # via test/conftest.py
    ALLOWLIST,
    SCHEMA_VERSION,
    AuditRecord,
    HostAgent,
    JsonlAudit,
    Role,
    redact,
)
from host_agent_server import SubprocessCommands, peer_is_allowed

ROOT = Path(__file__).resolve().parents[1]

PROFILES = ("rosy-site-sta", "rosy-relay-ap-sta", "rosy-setup-ap")
UNITS = ("rosy-runtime.service", "rosy-release-recover.service", "NetworkManager.service")


class SpyCommands:
    """Records what was asked of it, and answers plausibly."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.fail_with: Exception | None = None

    def _record(self, name: str, *args) -> dict:
        self.calls.append((name, args))
        if self.fail_with is not None:
            raise self.fail_with
        return {"called": name, "args": list(args)}

    def network_status(self) -> dict:
        return self._record("network_status")

    def apply_network_profile(self, profile_id: str) -> dict:
        return self._record("apply_network_profile", profile_id)

    def set_network_mode(self, mode: str) -> dict:
        return self._record("set_network_mode", mode)

    def connect_wifi(self, ssid: str, psk: str) -> dict:
        self.calls.append(("connect_wifi", (ssid, psk)))
        if self.fail_with is not None:
            raise self.fail_with
        return {"called": "connect_wifi", "ssid": ssid}

    def release_status(self) -> dict:
        return self._record("release_status")

    def install_release(self, release_id: str) -> dict:
        return self._record("install_release", release_id)

    def rollback_release(self) -> dict:
        return self._record("rollback_release")

    def clear_recovery_hold(self) -> dict:
        return self._record("clear_recovery_hold")

    def service_status(self, unit: str) -> dict:
        return self._record("service_status", unit)

    def reboot(self) -> dict:
        return self._record("reboot")


@pytest.fixture
def commands() -> SpyCommands:
    return SpyCommands()


@pytest.fixture
def audit() -> list[AuditRecord]:
    return []


@pytest.fixture
def agent(commands: SpyCommands, audit: list) -> HostAgent:
    return HostAgent(
        commands,
        allowed_profiles=PROFILES,
        allowed_units=UNITS,
        audit=audit.append,
    )


def _request(command: str, *, role: str = "administrator", confirmed: bool = True, **params) -> dict:
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": "01J8Zrequest",
        "command": command,
        "actor": {"user_id": "operator-01", "role": role},
        "confirmed": confirmed,
    }
    if params:
        request["params"] = params
    return request


# --- the allowlist is the whole surface -----------------------------------


def test_the_allowlist_matches_the_contract():
    """Every supported command is explicit. Adding one is a contract change."""
    assert set(ALLOWLIST) == {
        "network.status",
        "lane_perception.status",
        "lane_perception.set",
        "network.apply_profile",
        "network.set_mode",
        "network.connect",
        "release.status",
        "release.install",
        "release.rollback",
        "release.clear_hold",
        "service.status",
        "system.reboot",
    }


@pytest.mark.parametrize(
    "command,expected",
    [
        ("network.status", "network_status"),
        ("release.status", "release_status"),
        ("release.rollback", "rollback_release"),
        ("release.clear_hold", "clear_recovery_hold"),
        ("system.reboot", "reboot"),
    ],
)
def test_an_allowed_command_reaches_its_action(agent, commands, command, expected):
    response = agent.handle(_request(command))

    assert response["ok"], response
    assert commands.calls == [(expected, ())]


def test_a_parameterised_command_passes_only_its_parameter(agent, commands):
    response = agent.handle(_request("network.apply_profile", profile_id="rosy-site-sta"))

    assert response["ok"]
    assert commands.calls == [("apply_network_profile", ("rosy-site-sta",))]


def test_set_mode_passes_only_the_enumerated_mode(agent, commands):
    response = agent.handle(_request("network.set_mode", mode="RELAY_AP_STA"))

    assert response["ok"], response
    assert commands.calls == [("set_network_mode", ("RELAY_AP_STA",))]


def test_connect_passes_ssid_and_psk_to_the_action(agent, commands):
    response = agent.handle(_request("network.connect", ssid="shop wifi", psk="supersecretpsk"))

    assert response["ok"], response
    assert commands.calls == [("connect_wifi", ("shop wifi", "supersecretpsk"))]


@pytest.mark.parametrize(
    "command",
    ["network.reset", "release.delete", "system.shutdown", "", "network", "NETWORK.STATUS"],
)
def test_an_unknown_command_is_refused_without_guessing(agent, commands, command):
    """No fuzzy matching: an unimplemented command must not be approximated."""
    response = agent.handle(_request(command))

    assert response["code"] == "HOST_AGENT_COMMAND_UNKNOWN"
    assert commands.calls == [], "nothing may run for a command we do not implement"


def test_the_refusal_names_what_is_allowed(agent):
    response = agent.handle(_request("network.reset"))
    assert "network.status" in response["recovery"]


# --- roles ----------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "network.apply_profile",
        "network.set_mode",
        "network.connect",
        "release.install",
        "release.rollback",
        "release.clear_hold",
        "system.reboot",
    ],
)
def test_a_viewer_cannot_run_an_administrator_command(agent, commands, command):
    params = {"profile_id": "rosy-site-sta"} if "profile" in command else {}
    if command == "release.install":
        params = {"release_id": "2026.09.05-002"}
    if command == "network.set_mode":
        params = {"mode": "SITE_STA"}
    if command == "network.connect":
        params = {"ssid": "shop-wifi", "psk": "supersecretpsk"}

    response = agent.handle(_request(command, role="viewer", **params))

    assert response["code"] == "HOST_AGENT_ROLE_INSUFFICIENT"
    assert commands.calls == []


@pytest.mark.parametrize("command", ["network.status", "release.status"])
def test_a_viewer_may_read(agent, command):
    assert agent.handle(_request(command, role="viewer"))["ok"]


@pytest.mark.parametrize("role", ["root", "admin", "", None, "ADMINISTRATOR"])
def test_an_unrecognised_role_is_refused(agent, commands, role):
    request = _request("release.rollback")
    request["actor"]["role"] = role

    response = agent.handle(request)

    assert response["code"] == "HOST_AGENT_ROLE_UNKNOWN"
    assert commands.calls == []


def test_a_missing_actor_is_refused(agent, commands):
    request = _request("release.rollback")
    del request["actor"]

    assert agent.handle(request)["code"] == "HOST_AGENT_ROLE_UNKNOWN"
    assert commands.calls == []


# --- confirmation ---------------------------------------------------------


@pytest.mark.parametrize(
    "command,params",
    [
        ("network.apply_profile", {"profile_id": "rosy-site-sta"}),
        ("network.set_mode", {"mode": "SITE_STA"}),
        ("network.connect", {"ssid": "shop-wifi", "psk": "supersecretpsk"}),
        ("release.install", {"release_id": "2026.09.05-002"}),
        ("release.rollback", {}),
        ("release.clear_hold", {}),
        ("system.reboot", {}),
    ],
)
def test_a_destructive_command_without_confirmation_is_refused(agent, commands, command, params):
    response = agent.handle(_request(command, confirmed=False, **params))

    assert response["code"] == "HOST_AGENT_CONFIRMATION_REQUIRED"
    assert commands.calls == []


@pytest.mark.parametrize("confirmed", ["true", 1, "yes", None])
def test_only_a_real_boolean_counts_as_confirmation(agent, commands, confirmed):
    """A truthy string is not a confirmation; it is a serialisation accident."""
    request = _request("system.reboot")
    request["confirmed"] = confirmed

    assert agent.handle(request)["code"] == "HOST_AGENT_CONFIRMATION_REQUIRED"
    assert commands.calls == []


def test_a_read_only_command_needs_no_confirmation(agent):
    assert agent.handle(_request("network.status", role="viewer", confirmed=False))["ok"]


@pytest.mark.parametrize("command", ["network.status", "release.status"])
def test_status_reply_stamps_the_host_observation_after_the_read(agent, commands, command):
    before = datetime.now(timezone.utc)
    response = agent.handle(_request(command, role="viewer", confirmed=False))
    after = datetime.now(timezone.utc)

    assert response["ok"] is True
    assert commands.calls[-1][0] == command.replace(".", "_")
    observed = datetime.fromisoformat(response["observed_at"])
    assert before <= observed <= after


# --- parameters are enumerated, never interpolated -------------------------


@pytest.mark.parametrize("mode", ["AP_ONLY", "site_sta", "relay", "SITE-STA", ""])
def test_an_unknown_operating_mode_is_refused(agent, commands, mode):
    response = agent.handle(_request("network.set_mode", mode=mode))

    assert response["code"] in {"HOST_AGENT_MODE_UNKNOWN", "HOST_AGENT_PARAM_INVALID"}
    assert commands.calls == []


@pytest.mark.parametrize("ssid", ["", "x" * 33, "ssid\nwith\nnewline"])
def test_a_malformed_ssid_is_refused(agent, commands, ssid):
    response = agent.handle(_request("network.connect", ssid=ssid, psk="supersecretpsk"))

    assert response["code"] == "HOST_AGENT_PARAM_INVALID"
    assert commands.calls == []


@pytest.mark.parametrize("psk", ["short", "x" * 64, ""])
def test_a_malformed_psk_is_refused_without_echoing_it(agent, commands, psk):
    response = agent.handle(_request("network.connect", ssid="shop-wifi", psk=psk))

    assert response["code"] == "HOST_AGENT_PARAM_INVALID"
    assert commands.calls == []
    blob = json.dumps(response, ensure_ascii=False)
    if psk:
        assert psk not in blob


@pytest.mark.parametrize(
    "profile_id",
    ["rosy-unknown", "../../etc/NetworkManager", "rosy-site-sta; reboot", "", "*"],
)
def test_an_unregistered_or_malformed_profile_is_refused(agent, commands, profile_id):
    response = agent.handle(_request("network.apply_profile", profile_id=profile_id))

    assert response["code"] in {"HOST_AGENT_PROFILE_UNKNOWN", "HOST_AGENT_PARAM_INVALID"}
    assert commands.calls == []


@pytest.mark.parametrize("unit", ["sshd.service", "../../etc/passwd", "rosy-runtime.service.bak"])
def test_an_uninspectable_unit_is_refused(agent, commands, unit):
    response = agent.handle(_request("service.status", role="viewer", confirmed=False, unit=unit))

    assert response["code"] in {"HOST_AGENT_UNIT_UNKNOWN", "HOST_AGENT_PARAM_INVALID"}
    assert commands.calls == []


def test_an_extra_parameter_is_refused_not_ignored(agent, commands):
    """Ignoring an unexpected parameter is how a caller comes to believe it acted."""
    response = agent.handle(
        _request("release.install", release_id="2026.09.05-002", target_path="/etc/rosy")
    )

    assert response["code"] == "HOST_AGENT_PARAM_UNKNOWN"
    assert "target_path" in response["detail"]
    assert commands.calls == []


#: Parameter name tokens that would mean the caller chooses a location.
#: Matched per token — "profile_id" splits to {profile, id}, so it is not a
#: file parameter merely because "file" appears inside "profile".
_LOCATION_TOKENS = frozenset({"path", "file", "dir", "directory", "url", "target", "dest"})


def test_no_command_accepts_a_location():
    """The contract says paths are constructed by the agent, never received."""
    for spec in ALLOWLIST.values():
        for param in spec.params:
            tokens = set(param.lower().split("_"))
            offending = tokens & _LOCATION_TOKENS
            assert not offending, f"{spec.name} takes a caller-chosen location: {param}"


def test_the_whole_parameter_surface_is_enumerated():
    """Every parameter any command accepts, enumerated.

    A new one is a contract change and should fail here first, so that adding
    a parameter is a decision rather than a side effect. ``psk`` is a secret,
    not an identifier; the agent still lists it so the surface stays closed.
    """
    every_param = {param for spec in ALLOWLIST.values() for param in spec.params}
    assert every_param == {"profile_id", "release_id", "unit", "mode", "ssid", "psk", "paint_source"}


def test_a_missing_required_parameter_is_refused(agent, commands):
    response = agent.handle(_request("release.install"))

    assert response["code"] == "HOST_AGENT_PARAM_MISSING"
    assert commands.calls == []


@pytest.mark.parametrize("value", [None, 42, ["a"], {"a": 1}, True])
def test_a_non_string_parameter_is_refused(agent, commands, value):
    response = agent.handle(_request("service.status", role="viewer", confirmed=False, unit=value))

    assert response["code"] == "HOST_AGENT_PARAM_INVALID"
    assert commands.calls == []


# --- a held device refuses an install --------------------------------------


def test_install_is_refused_while_the_device_is_held(commands, audit):
    """Installing through a hold reports success the next boot reverses."""
    agent = HostAgent(
        commands,
        allowed_profiles=PROFILES,
        allowed_units=UNITS,
        recovery_hold=lambda: {"detail": "the previous release also failed its health check"},
        audit=audit.append,
    )

    response = agent.handle(_request("release.install", release_id="2026.09.05-002"))

    assert response["code"] == "RECOVERY_HELD"
    assert "clear_hold" in response["recovery"]
    assert commands.calls == []


def test_clearing_the_hold_is_not_itself_blocked_by_the_hold(commands):
    """Otherwise the only way out of a hold would be blocked by the hold."""
    agent = HostAgent(
        commands,
        allowed_profiles=PROFILES,
        allowed_units=UNITS,
        recovery_hold=lambda: {"detail": "held"},
    )

    assert agent.handle(_request("release.clear_hold"))["ok"]
    assert commands.calls == [("clear_recovery_hold", ())]


def test_a_hold_does_not_block_reading_status(commands):
    agent = HostAgent(
        commands,
        allowed_profiles=PROFILES,
        allowed_units=UNITS,
        recovery_hold=lambda: {"detail": "held"},
    )
    assert agent.handle(_request("release.status", role="viewer"))["ok"]


# --- idempotency ----------------------------------------------------------


def test_a_repeated_request_does_not_run_twice(agent, commands):
    """A dashboard retry across a dropped connection must not be a second reboot."""
    request = _request("system.reboot")
    request["idempotency_key"] = "01J8Zkey"

    first = agent.handle(request)
    second = agent.handle(dict(request, request_id="01J8Zsecond"))

    assert first["ok"] and second["ok"]
    assert commands.calls == [("reboot", ())], "the action ran once"
    assert second["replayed"] is True
    assert second["request_id"] == "01J8Zsecond", "the reply is addressed to the retry"


def test_a_different_key_runs_again(agent, commands):
    for key in ("01J8Zone", "01J8Ztwo"):
        request = _request("release.rollback")
        request["idempotency_key"] = key
        agent.handle(request)

    assert len(commands.calls) == 2


def test_a_failed_request_is_not_remembered(agent, commands):
    """A refusal must not pin the answer for a key the caller will reuse."""
    denied = _request("release.rollback", role="viewer")
    denied["idempotency_key"] = "01J8Zkey"
    assert agent.handle(denied)["code"] == "HOST_AGENT_ROLE_INSUFFICIENT"

    allowed = _request("release.rollback")
    allowed["idempotency_key"] = "01J8Zkey"
    assert agent.handle(allowed)["ok"]
    assert commands.calls == [("rollback_release", ())]


def test_a_transient_failure_is_not_remembered(agent, commands):
    """Otherwise a retry replays the failure forever.

    A refusal decided before execution never reaches the store, so the case
    that matters is a command that ran and failed — a dropped nmcli, a busy
    unit. The caller retries with the same key precisely because it wants
    another attempt, and handing back the remembered failure would make the
    device permanently unfixable through the dashboard.
    """
    request = _request("network.apply_profile", profile_id="rosy-site-sta")
    request["idempotency_key"] = "01J8Zkey"

    commands.fail_with = RuntimeError("nmcli exited 4")
    first = agent.handle(request)
    assert first["code"] == "HOST_AGENT_COMMAND_FAILED"

    commands.fail_with = None
    second = agent.handle(request)

    assert second["ok"], "a retry after a transient failure must run again"
    assert second.get("replayed") is not True
    assert len(commands.calls) == 2


def test_replay_happens_before_any_side_effect(agent, commands):
    """The check must precede execution, not merely dedupe the response."""
    request = _request("system.reboot")
    request["idempotency_key"] = "01J8Zkey"
    agent.handle(request)

    commands.fail_with = RuntimeError("must not be reached")
    assert agent.handle(request)["ok"], "the replay must not re-enter the action"


@pytest.mark.parametrize("key", ["", "has space", "../escape", 42])
def test_a_malformed_idempotency_key_is_refused(agent, commands, key):
    request = _request("release.rollback")
    request["idempotency_key"] = key

    assert agent.handle(request)["code"] == "HOST_AGENT_MALFORMED_REQUEST"
    assert commands.calls == []


# --- the wire -------------------------------------------------------------


def test_a_valid_line_round_trips(agent):
    response = json.loads(agent.handle_line(json.dumps(_request("network.status", role="viewer"))))
    assert response["ok"]


@pytest.mark.parametrize("line", ["{ not json", "", "[]", '"a string"', "null"])
def test_a_malformed_line_becomes_a_response_not_a_crash(agent, line):
    response = json.loads(agent.handle_line(line))
    assert response["code"] == "HOST_AGENT_MALFORMED_REQUEST"


def test_an_oversized_line_is_refused_unread(agent, commands):
    """The socket is reachable by anything running as ROSY_UID."""
    response = json.loads(agent.handle_line("x" * (64 * 1024 + 1)))

    assert response["code"] == "HOST_AGENT_REQUEST_TOO_LARGE"
    assert commands.calls == []


def test_invalid_utf8_becomes_a_response(agent):
    response = json.loads(agent.handle_line(bytes([0xFF, 0xFE]) + b"{}"))
    assert response["code"] == "HOST_AGENT_MALFORMED_REQUEST"


@pytest.mark.parametrize("version", [0, 2, None, "1"])
def test_an_unknown_request_schema_is_refused(agent, commands, version):
    request = _request("network.status", role="viewer")
    request["schema_version"] = version

    assert agent.handle(request)["code"] == "HOST_AGENT_SCHEMA_UNKNOWN"
    assert commands.calls == []


@pytest.mark.parametrize("request_id", [None, "", "has space", 42])
def test_a_missing_request_id_is_refused(agent, commands, request_id):
    request = _request("network.status", role="viewer")
    request["request_id"] = request_id

    assert agent.handle(request)["code"] == "HOST_AGENT_MALFORMED_REQUEST"
    assert commands.calls == []


def test_a_failing_action_becomes_a_response(agent, commands):
    commands.fail_with = RuntimeError("nmcli exited 4")

    response = agent.handle(_request("network.apply_profile", profile_id="rosy-site-sta"))

    assert response["code"] == "HOST_AGENT_COMMAND_FAILED"
    assert "nmcli exited 4" in response["detail"]


def test_every_response_carries_a_code_and_a_recovery_action(agent):
    """Design section 11: an operator sees a code and what to do, not a count."""
    refusal = agent.handle(_request("release.rollback", role="viewer"))
    for field in ("schema_version", "request_id", "ok", "code", "detail", "recovery"):
        assert field in refusal, f"missing {field}"
    assert refusal["recovery"], "a refusal must say what to do next"


# --- audit ----------------------------------------------------------------


def test_every_decision_is_audited_including_refusals(agent, audit):
    agent.handle(_request("network.status", role="viewer"))
    agent.handle(_request("release.rollback", role="viewer"))
    agent.handle(_request("nonsense.command"))

    assert [record.code for record in audit] == [
        "OK",
        "HOST_AGENT_ROLE_INSUFFICIENT",
        "HOST_AGENT_COMMAND_UNKNOWN",
    ]
    assert all(record.at for record in audit)


def test_connect_does_not_put_the_psk_on_the_wire_or_in_audit(agent, commands, audit):
    """PSK reaches NetworkManager through the action. It does not come back."""
    secret = "supersecretpsk"
    response = agent.handle(_request("network.connect", ssid="shop-wifi", psk="supersecretpsk"))

    assert response["ok"], response
    blob = json.dumps(response, ensure_ascii=False)
    blob += json.dumps([record.__dict__ for record in audit], default=str)
    assert secret not in blob
    assert "psk" not in (response.get("data") or {})


def test_the_audit_names_the_actor_and_the_command(agent, audit):
    agent.handle(_request("system.reboot"))

    record = audit[-1]
    assert record.command == "system.reboot"
    assert record.actor["user_id"] == "operator-01"
    assert record.request_id == "01J8Zrequest"


@pytest.mark.parametrize(
    "payload",
    [
        {"psk": "hunter2swordfish"},
        {"wifi_password": "hunter2swordfish"},
        {"api_token": "deadbeef"},
        {"nested": {"private_key": "-----BEGIN"}},
        {"credential": "x"},
    ],
)
def test_secrets_never_reach_the_audit(payload):
    """Design section 11: no token, Wi-Fi password, private key or whole config."""
    redacted = redact(payload)
    assert "hunter2swordfish" not in json.dumps(redacted)
    assert "deadbeef" not in json.dumps(redacted)
    assert "BEGIN" not in json.dumps(redacted)


def test_a_secret_in_an_actor_is_redacted(agent, audit):
    request = _request("network.status", role="viewer")
    request["actor"]["session_token"] = "deadbeefcafebabe"

    agent.handle(request)

    assert "deadbeefcafebabe" not in json.dumps(audit[-1].actor)


def test_the_audit_survives_as_jsonl(tmp_path, commands):
    path = tmp_path / "audit.jsonl"
    agent = HostAgent(
        commands, allowed_profiles=PROFILES, allowed_units=UNITS, audit=JsonlAudit(path)
    )

    agent.handle(_request("network.status", role="viewer"))
    agent.handle(_request("release.rollback", role="viewer"))

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["code"] == "OK"
    assert json.loads(lines[1])["ok"] is False


# --- peer credentials ------------------------------------------------------


def test_only_the_expected_uid_may_connect():
    assert peer_is_allowed(1000, expected_uid=1000)
    for uid in (0, 999, 1001, 65534):
        assert not peer_is_allowed(uid, expected_uid=1000), f"uid {uid} was allowed"


def test_root_is_not_special_cased():
    """The agent runs as root; that is no reason to accept root as a client."""
    assert not peer_is_allowed(0, expected_uid=1000)


# --- the privileged actions build argument lists, never shell strings ------


class RecordingRunner:
    def __init__(self, stdout: str = "{}", returncode: int = 0) -> None:
        self.argvs: list[list[str]] = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, argv):
        self.argvs.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def test_actions_never_go_through_a_shell():
    """A single string would be a shell command; a list is an exec."""
    runner = RecordingRunner(stdout=json.dumps({
        "state": "IDLE", "activation": None, "recovery_hold": None, "staged": [],
    }))
    commands = SubprocessCommands(runner=runner)

    commands.network_status()
    commands.apply_network_profile("rosy-site-sta")
    commands.set_network_mode("SITE_STA")
    commands.connect_wifi("shop-wifi", "supersecretpsk")
    commands.release_status()
    commands.install_release("2026.09.05-002")
    commands.rollback_release()
    commands.clear_recovery_hold()
    commands.service_status("rosy-runtime.service")
    commands.reboot()

    assert runner.argvs
    for argv in runner.argvs:
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)
        assert not any(";" in part or "|" in part or "&&" in part for part in argv)


def test_an_identifier_reaches_the_command_as_one_argument():
    """Even if a value slipped the allowlist it cannot become two arguments."""
    runner = RecordingRunner()
    SubprocessCommands(runner=runner).apply_network_profile("rosy-site-sta")

    assert runner.argvs[0] == ["nmcli", "connection", "up", "id", "rosy-site-sta"]


def test_set_mode_up_site_sta_and_downs_the_relay():
    runner = RecordingRunner()
    SubprocessCommands(runner=runner).set_network_mode("SITE_STA")

    assert ["nmcli", "connection", "up", "id", "rosy-site-sta"] in runner.argvs
    assert ["nmcli", "connection", "down", "id", "rosy-relay-ap-sta"] in runner.argvs
    for argv in runner.argvs:
        assert isinstance(argv, list)


def test_set_mode_up_relay_keeps_site_sta():
    runner = RecordingRunner()
    SubprocessCommands(runner=runner).set_network_mode("RELAY_AP_STA")

    assert ["nmcli", "connection", "up", "id", "rosy-relay-ap-sta"] in runner.argvs
    assert ["nmcli", "connection", "down", "id", "rosy-site-sta"] not in runner.argvs


def test_connect_modifies_the_site_profile_then_brings_it_up():
    runner = RecordingRunner()
    SubprocessCommands(runner=runner).connect_wifi("shop wifi", "supersecretpsk")

    modify = next(argv for argv in runner.argvs if argv[:3] == ["nmcli", "connection", "modify"])
    assert "rosy-site-sta" in modify
    assert "shop wifi" in modify
    assert "supersecretpsk" in modify
    assert ["nmcli", "connection", "up", "id", "rosy-site-sta"] in runner.argvs


def test_network_status_is_structured_site_sta_not_raw_nmcli():
    from host_agent_server import parse_network_status

    active = "rosy-site-sta:802-11-wireless:wlan0:activated\nlo:loopback:lo:activated\n"
    device = "IP4.ADDRESS[1]:192.168.0.42/24\nIP4.GATEWAY:192.168.0.1\nIP4.DNS[1]:1.1.1.1\n"
    wifi = "802-11-wireless.ssid:factory-wifi\n802-11-wireless.mode:infrastructure\n"
    data = parse_network_status(active, device_show=device, wifi_show=wifi)

    assert data["mode"] == "SITE_STA"
    assert data["ap_active"] is False
    assert data["ssid"] == "factory-wifi"
    assert data["ipv4"] == "192.168.0.42"
    assert data["default_route"] is True
    assert data["dns"] == ["1.1.1.1"]
    assert data["profile_id"] == "rosy-site-sta"
    assert "psk" not in data
    assert "output" not in data


def test_network_status_marks_relay_as_ap_on():
    from host_agent_server import parse_network_status

    active = (
        "rosy-site-sta:802-11-wireless:wlan0:activated\n"
        "rosy-relay-ap-sta:802-11-wireless:wlan0:activated\n"
    )
    wifi = "802-11-wireless.ssid:ROSY-01\n802-11-wireless.mode:ap\n"
    data = parse_network_status(active, wifi_show=wifi)

    assert data["mode"] == "RELAY_AP_STA"
    assert data["ap_active"] is True
    assert data["profile_id"] == "rosy-relay-ap-sta"


def test_network_status_names_setup_ap_without_inventing_operating_mode():
    from host_agent_server import parse_network_status

    active = "rosy-setup-ap:802-11-wireless:wlan0:activated\n"
    wifi = "802-11-wireless.ssid:ROSY-SETUP\n802-11-wireless.mode:ap\n"
    data = parse_network_status(active, wifi_show=wifi)

    assert data["mode"] == "PROVISIONING_AP"
    assert data["ap_active"] is True
    assert data["ssid"] == "ROSY-SETUP"


def test_a_failing_process_raises_rather_than_reporting_success():
    runner = RecordingRunner(stdout="", returncode=4)
    with pytest.raises(RuntimeError, match="exited 4"):
        SubprocessCommands(runner=runner).network_status()


@pytest.mark.parametrize("failed_command", ["wifi", "device"])
def test_network_status_rejects_partial_nmcli_results(failed_command):
    def runner(argv):
        command = "wifi" if "802-11-wireless.ssid,802-11-wireless.mode" in argv else (
            "device" if "device" in argv else "active")
        output = "rosy-site-sta:802-11-wireless:wlan0:activated\n" if command == "active" else ""
        return subprocess.CompletedProcess(argv, 3 if command == failed_command else 0, output, "failed")

    with pytest.raises(RuntimeError, match="exited 3"):
        SubprocessCommands(runner=runner).network_status()


def test_release_status_rejects_non_json_output():
    runner = RecordingRunner(stdout="release is ready")
    with pytest.raises(RuntimeError):
        SubprocessCommands(runner=runner).release_status()


def test_release_status_rejects_partial_json_output():
    runner = RecordingRunner(stdout='{"state":"IDLE"}')
    with pytest.raises(RuntimeError, match="missing required fields"):
        SubprocessCommands(runner=runner).release_status()


def test_release_status_rejects_declared_failure_even_with_fields():
    runner = RecordingRunner(stdout=json.dumps({
        "ok": False, "state": "FAILED", "activation": None, "recovery_hold": None, "staged": [],
    }))
    with pytest.raises(RuntimeError, match="reported failure"):
        SubprocessCommands(runner=runner).release_status()


def test_a_stopped_unit_is_an_answer_not_a_failure():
    """systemctl is-active exits non-zero for a stopped unit."""
    runner = RecordingRunner(stdout="inactive\n", returncode=3)
    status = SubprocessCommands(runner=runner).service_status("rosy-runtime.service")

    assert status == {"unit": "rosy-runtime.service", "active": "inactive"}


# --- the contract document and the code agree ------------------------------


def test_the_contract_document_lists_exactly_these_commands():
    """Two statements of one allowlist drift apart unless something checks."""
    contract = (ROOT / "docs" / "reference" / "rosy-host-agent-contract.md").read_text(
        encoding="utf-8"
    )
    table = contract.split("## 6. Allowlist", 1)[1].split("## 7.", 1)[0]

    for name in ALLOWLIST:
        assert f"`{name}`" in table, f"{name} is implemented but not in the contract"

    documented = set(re.findall(r"^\| `([a-z_]+\.[a-z_]+)` \|", table, flags=re.MULTILINE))
    assert documented == set(ALLOWLIST), f"contract and code disagree: {documented ^ set(ALLOWLIST)}"


def test_the_contract_records_which_commands_need_administrator():
    contract = (ROOT / "docs" / "reference" / "rosy-host-agent-contract.md").read_text(
        encoding="utf-8"
    )
    table = contract.split("## 6. Allowlist", 1)[1].split("## 7.", 1)[0]

    for line in table.splitlines():
        match = re.match(r"^\| `([a-z_]+\.[a-z_]+)` \|", line)
        if not match:
            continue
        spec = ALLOWLIST[match.group(1)]
        expected_role = "administrator" if spec.role is Role.ADMINISTRATOR else "viewer"
        assert expected_role in line, f"{spec.name}: contract role disagrees with the code"
        expected_confirm = "필요" if spec.requires_confirmation else "불필요"
        assert expected_confirm in line, f"{spec.name}: contract confirmation disagrees with the code"
