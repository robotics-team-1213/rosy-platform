"""Recoverable network changes, using fake NM and claim ports only."""

import json
import os
from pathlib import Path
import re
import subprocess

import pytest


PSK = "supersecretpsk"
OLD = {"uuid": "11111111-1111-4111-8111-111111111111", "name": "rosy-site-sta", "ssid": "old-site"}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Claim:
    def __init__(self):
        self.events = []
        self.lost = False

    def __call__(self):
        return self

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def acquire(self):
        self.events.append("acquire")

    def refresh(self):
        self.events.append("refresh")
        if self.lost:
            raise RuntimeError("claim lost")

    def release(self):
        self.events.append("release")


class Backend:
    def __init__(self):
        self.previous = dict(OLD)
        self.profiles = {OLD["uuid"]: dict(OLD, secret_bytes=b"unchanged old profile")}
        self.active = OLD["uuid"]
        self.calls = []
        self.ipv4 = "192.0.2.7"
        self.wrong_ssid = False
        self.fail = None
        self.interrupt = None
        self.hook = None

    def site_profile(self):
        return self.previous

    def _step(self, name):
        self.calls.append(name)
        if self.hook:
            self.hook(name)
        if self.interrupt == name:
            raise KeyboardInterrupt()
        if self.fail == name:
            raise RuntimeError("NM echoed secret " + PSK)

    def prepare(self, candidate_uuid, ssid, psk):
        self._step("prepare")
        self.candidate = candidate_uuid
        self.profiles[candidate_uuid] = {"uuid": candidate_uuid, "name": "candidate", "ssid": ssid}

    def activate(self, profile_uuid, timeout_s):
        assert 0 < timeout_s <= 120
        self._step("activate")
        self.active = profile_uuid

    def observe(self):
        self._step("observe")
        profile = self.profiles.get(self.active, {})
        return {"uuid": self.active, "ssid": "unrelated" if self.wrong_ssid else profile.get("ssid"),
                "interface": "wlan0", "ipv4": self.ipv4, "active": True, "default_route": False}

    def promote(self, candidate_uuid, previous):
        self._step("promote")
        self.profiles[candidate_uuid]["name"] = "rosy-site-sta"

    def restore(self, previous, timeout_s):
        assert 0 < timeout_s <= 120
        self._step("restore")
        self.active = previous["uuid"]
        self.wrong_ssid = False
        self.ipv4 = "192.0.2.8"

    def discard(self, candidate_uuid):
        self._step("discard")
        self.profiles.pop(candidate_uuid, None)

    def request_recovery(self):
        self._step("recovery")


def transaction(tmp_path, backend=None, **kwargs):
    from network_transaction import NetworkTransaction

    clock = Clock()
    return NetworkTransaction(backend or Backend(), root=tmp_path, clock=clock,
                              sleep=clock.sleep, claim=kwargs.pop("claim", Claim()),
                              maintenance_check=kwargs.pop("maintenance_check", lambda: True), **kwargs)


def test_local_only_candidate_commits_same_uuid_and_keeps_old_profile(tmp_path):
    backend = Backend()
    old_bytes = dict(backend.profiles[OLD["uuid"]])
    tx = transaction(tmp_path, backend)
    result = tx.connect("new-site", PSK, request_id="job-1")
    assert result["state"] == "committed"
    assert result["observed"]["uuid"] == backend.candidate
    assert result["observed"]["default_route"] is False
    assert backend.profiles[OLD["uuid"]] == old_bytes
    assert backend.calls.index("observe") < backend.calls.index("promote")
    assert PSK not in json.dumps(result)
    files = list(tmp_path.rglob("*.json"))
    assert files
    assert all(PSK not in p.read_text() for p in files)
    if os.name == "posix":
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in files)


def test_utf8_ssid_accepts_32_bytes_but_refuses_33(tmp_path):
    assert transaction(tmp_path).connect("가" * 10 + "ab", PSK, request_id="utf8")["state"] == "committed"
    assert transaction(tmp_path).connect("가" * 11, PSK, request_id="utf8-long")["state"] == "rejected"


@pytest.mark.parametrize("bad_ssid,bad_psk", [("x" * 33, PSK), ("", PSK), ("a\nssid", PSK), ("site", "short")])
def test_invalid_credentials_are_rejected_without_nm_calls(tmp_path, bad_ssid, bad_psk):
    backend = Backend()
    result = transaction(tmp_path, backend).connect(bad_ssid, bad_psk, request_id="invalid")
    assert result["state"] == "rejected"
    assert not backend.calls


@pytest.mark.parametrize("failure", ["activate", "promote"])
def test_failure_restores_previous_uuid_without_secret_in_result(tmp_path, failure):
    backend = Backend()
    backend.fail = failure
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="failed")
    assert result["state"] == "rolled_back"
    assert backend.active == OLD["uuid"]
    assert OLD["uuid"] in backend.profiles
    assert backend.candidate not in backend.profiles
    assert PSK not in json.dumps(result)


@pytest.mark.parametrize("observation", ["no_address", "wrong_ssid"])
def test_observation_must_match_candidate_ssid_and_ipv4_within_budget(tmp_path, observation):
    backend = Backend()
    backend.ipv4 = None if observation == "no_address" else backend.ipv4
    backend.wrong_ssid = observation == "wrong_ssid"
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="mismatch")
    assert result["state"] == "rolled_back"
    assert "promote" not in backend.calls
    assert backend.active == OLD["uuid"]


def test_missing_previous_profile_stays_held_and_requests_recovery(tmp_path):
    backend = Backend()
    backend.previous = None
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="missing")
    assert result["state"] == "held"
    assert "prepare" not in backend.calls
    assert "recovery" in backend.calls


def test_failed_restore_stays_held_and_requests_recovery(tmp_path):
    backend = Backend()
    backend.fail = "restore"
    backend.ipv4 = None
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="held")
    assert result["state"] == "held"
    assert "recovery" in backend.calls


def test_same_request_is_durable_idempotent_and_changed_ssid_is_rejected(tmp_path):
    backend = Backend()
    first = transaction(tmp_path, backend).connect("new-site", PSK, request_id="same")
    calls = list(backend.calls)
    tx = transaction(tmp_path, backend)
    assert tx.connect("new-site", PSK, request_id="same")["state"] == first["state"]
    assert backend.calls == calls
    assert tx.connect("other-site", PSK, request_id="same")["state"] == "rejected"
    assert tx.status("same")["request_id"] == "same"


def test_concurrent_request_cannot_mutate_radio(tmp_path):
    backend = Backend()
    competing = []
    def hook(step):
        if step == "prepare":
            competing.append(transaction(tmp_path, Backend()).connect("other", PSK, request_id="other"))
    backend.hook = hook
    transaction(tmp_path, backend).connect("new-site", PSK, request_id="owner")
    assert competing[0]["state"] == "busy"


@pytest.mark.parametrize("step", ["prepare", "activate", "promote", "restore"])
def test_restart_reconciles_interrupted_journal(tmp_path, step):
    backend = Backend()
    backend.interrupt = step
    if step == "restore":
        backend.ipv4 = None
    with pytest.raises(KeyboardInterrupt):
        transaction(tmp_path, backend).connect("new-site", PSK, request_id="interrupted")
    backend.interrupt = None
    backend.ipv4 = "192.0.2.8"
    result = transaction(tmp_path, backend).reconcile()
    assert result["state"] in {"rolled_back", "committed"}
    if result["state"] == "committed":
        assert backend.active == backend.candidate
    else:
        assert backend.active == OLD["uuid"]


def test_commit_hook_runs_under_lock_and_failure_rolls_back(tmp_path):
    backend = Backend()
    def override(record):
        assert record["profile_uuid"] == backend.candidate
        assert record["observation"]["uuid"] == backend.candidate
        assert record["ssid"] == "new-site"
        assert PSK not in json.dumps(record)
        raise OSError("cannot durably hand off")
    result = transaction(tmp_path, backend, on_commit=override).connect("new-site", PSK, request_id="hook")
    assert result["state"] == "rolled_back"
    assert backend.active == OLD["uuid"]


def test_maintenance_is_rechecked_after_claim_and_lock(tmp_path):
    backend = Backend()
    claim = Claim()
    def safe():
        assert claim.events[0] == "acquire"
        return False
    result = transaction(tmp_path, backend, claim=claim, maintenance_check=safe).connect("new-site", PSK, request_id="unsafe")
    assert result["code"] == "needs_maintenance"
    assert not backend.calls
    assert claim.events[-1] == "release"


def test_claim_loss_holds_without_promoting(tmp_path):
    backend = Backend()
    claim = Claim()
    backend.hook = lambda step: setattr(claim, "lost", True) if step == "activate" else None
    result = transaction(tmp_path, backend, claim=claim).connect("new-site", PSK, request_id="claim-loss")
    assert result["state"] == "held"
    assert "promote" not in backend.calls


@pytest.mark.skipif(os.name != "posix", reason="product no-follow semantics are POSIX")
def test_symlinked_state_directory_is_refused_without_nm_calls(tmp_path):
    backend = Backend()
    target = tmp_path / "outside"
    target.mkdir()
    directory = tmp_path / "var/lib/rosy/network"
    directory.parent.mkdir(parents=True)
    directory.symlink_to(target, target_is_directory=True)
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="symlink")
    assert result["state"] == "held"
    assert not backend.calls
    assert not list(target.iterdir())


def test_nm_adapter_loads_private_keyfile_and_never_passes_psk_in_argv(tmp_path):
    from nm_network import NMNetworkBackend

    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        assert PSK not in repr(argv)
        assert kwargs["timeout"] <= 120
        if "load" in argv:
            path = Path(argv[-1])
            assert PSK in path.read_text()
            if os.name == "posix":
                assert path.stat().st_mode & 0o777 == 0o600
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    backend = NMNetworkBackend(root=tmp_path, runner=runner)
    backend.prepare("22222222-2222-4222-8222-222222222222", "new-site", PSK)
    assert any("load" in argv for argv in calls)
    assert not list((tmp_path / "run/rosy-network").glob("*.nmconnection"))


def test_nm_adapter_sanitizes_subprocess_failure(tmp_path):
    from nm_network import NMNetworkBackend

    def runner(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv, stderr=PSK)
    with pytest.raises(RuntimeError) as error:
        NMNetworkBackend(root=tmp_path, runner=runner).prepare("22222222-2222-4222-8222-222222222222", "new-site", PSK)
    assert PSK not in str(error.value)
    assert not list((tmp_path / "run/rosy-network").glob("*.nmconnection"))


@pytest.mark.parametrize("changed", [False, True])
def test_nm_restore_only_modifies_previous_profile_when_promotion_changed_it(tmp_path, changed):
    from nm_network import NMNetworkBackend

    previous = dict(OLD, autoconnect="yes", autoconnect_priority="0")
    before = b"old profile bytes, including formatting and the original secret"
    profile = tmp_path / "old-profile.nmconnection"
    profile.write_bytes(before)
    calls = []
    values = {"connection.id": "rosy-site-backup-" + OLD["uuid"] if changed else OLD["name"],
              "connection.autoconnect": "no" if changed else "yes", "connection.autoconnect-priority": "0"}
    def runner(argv, **kwargs):
        calls.append(argv)
        if "modify" in argv:
            profile.write_bytes(b"NetworkManager rewrote this profile")
        output = ""
        if "-g" in argv:
            fields = argv[argv.index("-g") + 1].split(",")
            output = "\n".join(values.get(field, "") for field in fields)
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
    NMNetworkBackend(root=tmp_path, runner=runner).restore(previous, timeout_s=120)
    assert any("up" in argv for argv in calls)
    assert any("modify" in argv for argv in calls) is changed
    if not changed:
        assert profile.read_bytes() == before


def _nm_keyfile_ssid(raw):
    """Decode the two documented NM keyfile SSID forms, independently of writer.

    https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-settings-keyfile.html
    Table 1 permits strings and decimal-byte lists. GLib keyfile strings use
    backslash escapes; plain numeric-semicolon input selects the byte-list form.
    """
    value = next(line[5:] for line in raw.splitlines() if line.startswith("ssid="))
    if re.fullmatch(r"(?:[0-9]{1,3};)+", value):
        return bytes(int(part) for part in value.split(";")[:-1]).decode("utf-8")
    escapes = {"s": " ", "t": "\t", "n": "\n", "r": "\r", "\\": "\\"}
    return re.sub(r"\\(.)", lambda match: escapes[match[1]], value.strip())


@pytest.mark.parametrize("ssid", ["12;34;", "32;32;", " leading and trailing ", "가나다 현장", "slash\\semi;colon"])
def test_nm_keyfile_ssid_roundtrips_exact_utf8_bytes(tmp_path, ssid):
    from nm_network import NMNetworkBackend

    decoded = []
    def runner(argv, **kwargs):
        if "load" in argv:
            decoded.append(_nm_keyfile_ssid(Path(argv[-1]).read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    NMNetworkBackend(root=tmp_path, runner=runner).prepare("22222222-2222-4222-8222-222222222222", ssid, PSK)
    assert decoded == [ssid]


def test_completed_job_survives_crash_before_archive_and_another_request(tmp_path):
    backend = Backend()
    first = transaction(tmp_path, backend).connect("new-site", PSK, request_id="first")
    assert first["state"] == "committed"
    # A power cut after active-journal fsync but before the archive fsync.
    (tmp_path / "var/lib/rosy/network/jobs/first.json").unlink()
    assert transaction(tmp_path, backend).connect("next-site", PSK, request_id="second")["state"] == "committed"
    calls = list(backend.calls)
    repeated = transaction(tmp_path, backend).connect("new-site", PSK, request_id="first")
    assert repeated["profile_uuid"] == first["profile_uuid"]
    assert backend.calls == calls


def test_nm_gateway_does_not_prove_an_observed_default_route(tmp_path):
    from nm_network import NMNetworkBackend

    def runner(argv, **kwargs):
        output = ("GENERAL.CON-UUID:" + OLD["uuid"] + "\nGENERAL.STATE:100 (connected)\n"
                  "IP4.ADDRESS[1]:192.0.2.7/24\nIP4.GATEWAY:192.0.2.1\n")
        if "wifi" in argv:
            output = "*:old-site\n"
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
    observed = NMNetworkBackend(root=tmp_path, runner=runner).observe()
    assert observed["active"] is True
    assert observed["ipv4"] == "192.0.2.7"
    assert observed["default_route"] is None


def test_later_connect_reconciles_after_startup_was_not_maintenance_ready(tmp_path):
    backend = Backend()
    backend.interrupt = "activate"
    with pytest.raises(KeyboardInterrupt):
        transaction(tmp_path, backend).connect("interrupted-site", PSK, request_id="old-job")
    old_candidate = backend.candidate
    backend.interrupt = None
    before = list(backend.calls)
    blocked = transaction(tmp_path, backend, maintenance_check=lambda: False).reconcile()
    assert blocked["code"] == "needs_maintenance"
    assert backend.calls == before
    claim = Claim()
    result = transaction(tmp_path, backend, claim=claim).connect("new-site", PSK, request_id="new-job")
    assert result["state"] == "committed"
    assert result["request_id"] == "new-job"
    assert old_candidate not in backend.profiles
    assert transaction(tmp_path, backend).status("old-job")["state"] == "rolled_back"
    assert claim.events.count("acquire") == claim.events.count("release") == 1


def test_same_request_finishes_interrupted_commit_without_new_candidate(tmp_path):
    backend = Backend()
    backend.interrupt = "promote"
    with pytest.raises(KeyboardInterrupt):
        transaction(tmp_path, backend).connect("new-site", PSK, request_id="same-job")
    candidate = backend.candidate
    backend.interrupt = None
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="same-job")
    assert result["state"] == "committed"
    assert result["profile_uuid"] == candidate
    assert backend.calls.count("prepare") == 1


def test_failed_resume_keeps_original_held_journal_and_blocks_new_prepare(tmp_path):
    backend = Backend()
    backend.interrupt = "activate"
    with pytest.raises(KeyboardInterrupt):
        transaction(tmp_path, backend).connect("old-requested-site", PSK, request_id="old-job")
    backend.interrupt = None
    backend.fail = "restore"
    result = transaction(tmp_path, backend).connect("new-site", PSK, request_id="new-job")
    assert result["state"] == "held"
    journal = json.loads((tmp_path / "var/lib/rosy/network/transaction.json").read_text())
    assert journal["request_id"] == "old-job" and journal["state"] == "held"
    assert backend.calls.count("prepare") == 1
