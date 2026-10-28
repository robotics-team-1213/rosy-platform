"""D-412 updater: config, GitHub list, rollout, staging, the rollout gate and network errors.

Moved out of test/test_rosy_auto_update.py (D-798); the fakes are in auto_update_fakes.py.
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import subprocess

import pytest

from auto_update_fakes import (CURRENT, HOST, NEWER, NEXT, OTHER, REPO, T0, _z, device, host, hub, keys,
    kinds, state, status, upd, updater, write_json)


def test_a_robot_without_a_config_is_on_by_default(device, host, hub, keys):
    # D-412 (2026-10-02): default flipped to ON after the first real canary
    # (rosy-pinky-9dfk committed 2026.10.02-026); only enabled=false turns it off.
    hub.publish(keys, NEXT)
    (device / "var/lib/rosy/updates/config.json").unlink()

    result = updater(host, hub).run()

    assert result["phase"] != "disabled"
    assert hub.requests != []


def test_a_config_without_the_enabled_key_is_on(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/config.json", {"repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] != "disabled"
    assert hub.requests != []


def test_disabled_config_stops_before_any_request(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": False, "repo": REPO})

    result = updater(host, hub).run()

    assert result["phase"] == "disabled"
    assert hub.requests == []
    assert host.calls == []


def test_unreadable_config_fails_closed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    path = device / "var/lib/rosy/updates/config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert updater(host, hub).run()["phase"] == "error"
    assert hub.requests == []


def test_config_api_base_points_the_updater_at_another_server(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    write_json(device / "var/lib/rosy/updates/config.json",
               {"enabled": True, "repo": REPO, "api_base": hub.base + "/"})

    # The CLI default; the config key must win over it (device twin, tests).
    result = upd.Updater(host, api_base=upd.API_BASE).run()

    assert hub.list_requests(), "the release list was not requested from config api_base"
    assert result["candidate"] == NEXT


@pytest.mark.parametrize("api_base", ["ftp://example.test", "http://", 42, "http://host/ path"])
def test_invalid_config_api_base_fails_closed(device, host, hub, keys, api_base):
    hub.publish(keys, NEXT, canary=())
    write_json(device / "var/lib/rosy/updates/config.json", {"enabled": True, "repo": REPO, "api_base": api_base})

    result = upd.Updater(host, api_base=hub.base).run()

    assert result["phase"] == "error"
    assert "CONFIG_INVALID" in result["reason"]
    assert hub.requests == []


def test_api_request_carries_user_agent_and_etag(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    up = updater(host, hub)

    up.run()
    first = hub.list_requests()[-1]
    assert first["user-agent"].startswith("rosy-auto-update")
    assert "if-none-match" not in first
    assert state(device)["etag_v2"] == hub.etag

    up.run()
    second = hub.list_requests()[-1]
    assert second["if-none-match"] == hub.etag


def test_304_reuses_the_cached_release_list(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    up = updater(host, hub)
    up.run()
    calls_before = len(hub.list_requests())

    result = up.run()

    assert len(hub.list_requests()) == calls_before + 1
    assert result["candidate"] == NEXT  # from the cache: the 304 carried no body
    assert result["phase"] == "waiting"


def test_chooses_the_highest_newer_complete_release(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, canary=())
    hub.publish(keys, "2026.10.01-024", canary=(), skip_asset="rollout.json.sig")
    hub.publish(keys, "2026.10.01-025", canary=(), draft=True)
    hub.publish(keys, "2026.10.01-026", canary=(), prerelease=True)

    result = updater(host, hub).run()

    assert result["candidate"] == NEWER
    assert (device / "opt/rosy/releases" / NEWER).is_dir()
    assert not (device / "opt/rosy/releases" / NEXT).exists()


def test_invalid_rollout_signature_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, canary=(), bad_signature=True)

    result = updater(host, hub).run()

    assert result["candidate"] == NEXT
    assert not (device / "opt/rosy/releases" / NEWER).exists()


def test_withdrawn_rollout_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER, withdrawn=True)

    assert updater(host, hub).run()["candidate"] == NEXT


def test_rollout_for_another_release_is_skipped(device, host, hub, keys):
    hub.publish(keys, NEWER, rollout_overrides={"release_id": NEXT})

    result = updater(host, hub).run()

    assert result["phase"] == "idle" and result["candidate"] is None


def test_failed_id_is_never_retried(device, host, hub, keys):
    hub.publish(keys, NEXT)
    write_json(device / "var/lib/rosy/updates/state.json",
               {"failed": {NEXT: {"at": _z(T0), "detail": "health"}}})

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert "unpack" not in kinds(host) and "activate" not in kinds(host)


@pytest.mark.parametrize("release_id", ["2026.10.01-020", CURRENT])
def test_lower_or_equal_id_is_ignored(device, host, hub, keys, release_id):
    hub.publish(keys, release_id)

    result = updater(host, hub).run()

    assert result["phase"] == "idle"
    assert host.calls == []
    assert not any(path.startswith("/dl/") for path, _ in hub.requests)


def test_apply_refuses_an_id_at_or_below_current(device, host, hub):
    up = updater(host, hub)
    with pytest.raises(upd.UpdateError, match="NOT_NEWER"):
        up.apply(CURRENT, {})
    with pytest.raises(upd.UpdateError, match="NOT_NEWER"):
        up.apply("2026.09.30-001", {})
    assert host.calls == []


def test_sha_mismatch_does_not_stage(device, host, hub, keys):
    hub.publish(keys, NEXT, sha="0" * 64)

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert "SHA256_MISMATCH" in result["reason"]
    assert "unpack" not in kinds(host)
    assert not (device / "opt/rosy/releases" / NEXT).exists()
    assert not list((device / "var/lib/rosy/updates").rglob("*.part"))
    assert not list((device / "var/lib/rosy/updates").rglob("*.tar.gz"))


def test_stages_while_held_and_leaves_current_alone(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("tester", "G4 recording", 2)

    result = up.run()

    assert result["phase"] == "held"
    assert (device / "opt/rosy/releases" / NEXT).is_dir()
    assert kinds(host) == ["unpack", "verify"]
    assert host.links["current"] == CURRENT
    assert state(device)["staged"] == NEXT
    unpack = host.calls[0]
    assert unpack[0] == "bash" and unpack[1].endswith("rosy-release-unpack.sh")
    assert unpack[-3] == NEXT and unpack[-1] == str(device / "opt/rosy/releases")


def test_already_staged_release_is_not_downloaded_again(device, host, hub, keys):
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("tester", "G4", 2)
    up.run()
    downloads = sum(path.endswith(".tar.gz") for path, _ in hub.requests)

    up.run()

    assert sum(path.endswith(".tar.gz") for path, _ in hub.requests) == downloads
    assert kinds(host).count("unpack") == 1


def test_failed_verify_marks_the_id_failed(device, host, hub, keys):
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_INVALID: x"}), "")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT in state(device)["failed"]
    assert "activate" not in kinds(host)


def test_canary_host_applies_before_canary_ok(device, host, hub, keys):
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=False)

    result = updater(host, hub).run()

    assert result["phase"] == "committed"
    assert host.links["current"] == NEXT


def test_non_canary_waits_for_canary_ok(device, host, hub, keys):
    host.host = OTHER
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=False, published_at=_z(T0 - dt.timedelta(hours=2)))

    result = updater(host, hub).run()

    assert result["phase"] == "waiting"
    assert "activate" not in kinds(host)


def test_non_canary_waits_for_the_wave_delay(device, host, hub, keys):
    host.host = OTHER
    hub.publish(keys, NEXT, canary=(HOST,), canary_ok=True, wave_delay_s=600,
                published_at=_z(T0 - dt.timedelta(seconds=599)))

    assert updater(host, hub).run()["phase"] == "waiting"
    assert "activate" not in kinds(host)

    host.t = T0 + dt.timedelta(seconds=2)
    assert updater(host, hub).run()["phase"] == "committed"


@pytest.mark.parametrize("code", [403, 429])
def test_rate_limit_backs_off_without_crashing(device, host, hub, keys, code):
    hub.publish(keys, NEXT)
    hub.status = code
    hub.extra_headers = {"Retry-After": "120"}
    up = updater(host, hub)

    result = up.run()
    assert result["phase"] == "error"
    assert str(code) in result["reason"]
    requests = len(hub.requests)

    host.t += dt.timedelta(seconds=60)
    assert up.run()["phase"] == "error"
    assert len(hub.requests) == requests  # still backing off: no request

    hub.status = None
    host.t += dt.timedelta(seconds=61)
    assert up.run()["phase"] == "committed"


def test_network_error_is_an_error_phase(device, host, hub, keys):
    up = upd.Updater(host, api_base="http://127.0.0.1:9")  # nothing listens

    result = up.run()

    assert result["phase"] == "error"
    assert result["reason"]


def test_server_error_is_an_error_phase(device, host, hub, keys):
    hub.status = 500
    assert updater(host, hub).run()["phase"] == "error"


def test_staging_verify_timeout_is_transient(device, host, hub, keys):
    # H3
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess([], 124, "", "TIMEOUT")

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})


def test_a_withdrawal_is_remembered(device, host, hub, keys):
    # M4
    hub.publish(keys, NEXT, withdrawn=True, rollout_overrides={"reason": "bad canary"})
    up = updater(host, hub)
    assert up.run()["phase"] == "idle"
    assert NEXT in state(device)["withdrawn"]

    hub.publish(keys, NEXT, withdrawn=False)
    result = up.run()

    assert result["phase"] == "idle"
    assert "activate" not in kinds(host) and "unpack" not in kinds(host)


def test_definitive_stage_errors_back_off_and_fail_after_three(device, host, hub, keys):
    # M5
    hub.publish(keys, NEXT, sha="0" * 64)
    up = updater(host, hub)
    for attempt in range(1, 4):
        result = up.run()
        assert result["phase"] == "error"
        downloads = sum(path.endswith(".tar.gz") for path, _ in hub.requests)
        assert downloads == attempt
        # inside the backoff: no new download
        up.run()
        assert sum(path.endswith(".tar.gz") for path, _ in hub.requests) == attempt
        host.t += dt.timedelta(hours=7)
    assert NEXT in state(device)["failed"]
    assert up.run()["phase"] == "idle"


def test_network_stage_errors_back_off_but_never_fail(device, host, hub, keys):
    # M5
    hub.publish(keys, NEXT)
    hub.asset_status[f"{NEXT}/{NEXT}.tar.gz"] = 503
    up = updater(host, hub)
    for _ in range(4):
        assert up.run()["phase"] == "error"
        host.t += dt.timedelta(hours=7)
    assert NEXT not in state(device).get("failed", {})
    assert state(device)["stage_errors"][NEXT]["attempts"] == 4


def test_not_enough_disk_is_refused_before_downloading(device, host, hub, keys):
    # M5: tarball size x 2 + 512 MiB
    hub.publish(keys, NEXT)
    host.free = 512 * 1024 * 1024
    result = updater(host, hub).run()
    assert result["phase"] == "error" and "DISK" in result["reason"]
    assert not any(path.endswith(".tar.gz") for path, _ in hub.requests)


def test_rollout_network_errors_do_not_fall_through_to_a_lower_release(device, host, hub, keys):
    # L1
    hub.publish(keys, NEXT, canary=())
    hub.publish(keys, NEWER)
    hub.asset_status[f"{NEWER}/rollout.json"] = 502

    result = updater(host, hub).run()

    assert result["phase"] == "error"
    assert result["candidate"] == NEWER
    assert not (device / "opt/rosy/releases" / NEXT).exists()


def test_a_stray_directory_in_downloads_does_not_block_staging(device, host, hub, keys):
    # L7
    stray = device / "var/lib/rosy/updates/downloads/junk"
    stray.mkdir(parents=True)
    (stray / "file").write_text("x", encoding="utf-8")
    hub.publish(keys, NEXT)
    up = updater(host, hub)
    up.hold("agent", "x", 1)

    assert up.run()["phase"] == "held"
    assert not stray.exists()


@pytest.mark.parametrize("error,definitive", [
    ("NATIVE_MANIFEST_PAYLOAD: digest mismatch for x", True),
    ("NATIVE_TARGET_MISMATCH: host", True),
    ("NATIVE_PYTHON_RUNTIME: mismatch", True),
    ("SIGNATURE_INVALID: does not verify", True),
    ("CHECKSUM_MISMATCH: x", True),
    ("candidate failed health check and was rolled back", True),
    ("SIGNATURE_KEY_UNREADABLE: trusted public key is missing", False),
    ("Command '['systemctl', 'stop', 'rosy-core.service']' timed out after 120 seconds", False),
    ("[Errno 28] No space left on device", False),
    ("NATIVE_RELEASE_MISSING: release directory is unavailable", False),
], ids=lambda value: str(value)[:30])
def test_only_known_release_errors_are_definitive(device, host, hub, keys, error, definitive):
    # N3
    hub.publish(keys, NEXT)
    host.overrides["activate"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": error}), "")

    result = updater(host, hub).run()

    assert (NEXT in state(device).get("failed", {})) is definitive
    assert result["phase"] == ("image_required" if error.startswith("NATIVE_PYTHON_RUNTIME:")
                               else "failed" if definitive else "error")


def test_staging_verify_with_an_unreadable_key_is_transient(device, host, hub, keys):
    # N3
    hub.publish(keys, NEXT)
    host.overrides["verify"] = lambda h, argv: subprocess.CompletedProcess(
        [], 1, json.dumps({"ok": False, "error": "SIGNATURE_KEY_UNREADABLE: missing"}), "")

    assert updater(host, hub).run()["phase"] == "error"
    assert NEXT not in state(device).get("failed", {})
