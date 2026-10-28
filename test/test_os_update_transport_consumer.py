"""Real local HTTP transport with unchanged signed whole-bundle metadata."""
import datetime as dt
import importlib
import json

import pytest

from auto_update_fakes import HOST
from signing import sign_checksums
from test_os_update_feed import feed, publish  # noqa: F401


@pytest.fixture(autouse=True)
def small_transport(monkeypatch):
    try:
        transport = importlib.import_module("os_update_transport")
    except ModuleNotFoundError:
        return  # The old consumer still reproduces the missing transport behavior.
    monkeypatch.setattr(transport, "CHUNK_BYTES", 512)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 1023)


def chunked(hub, private, **kwargs):
    value, body, policy = publish(hub, private, **kwargs)
    entry = hub.releases[-1]
    name = value["bundle"]["filename"]
    entry["assets"] = [a for a in entry["assets"] if a["name"] != name]
    for index, offset in enumerate(range(0, len(body), 512)):
        filename = name + f".part{index:03d}"
        content = body[offset:offset + 512]
        key = value["release_id"] + "/" + filename
        hub.assets[key] = content
        entry["assets"].append(dict(name=filename, size=len(content), browser_download_url=hub.base + "/dl/" + key))
    return value, body, policy, entry


def policy(hub, private, value, original, **changes):
    raw = json.dumps(dict(original, **changes)).encode()
    hub.assets[value["release_id"] + "/os-rollout.json"] = raw
    hub.assets[value["release_id"] + "/os-rollout.json.sig"] = sign_checksums(raw, private).encode()


def test_chunked_engineering_canary_reassembles_exact_readonly_signed_bundle(feed):
    m, hub, host, root, _, journal, private, _ = feed
    value, body, _, entry = chunked(hub, private, canary_ok=False)
    entry["prerelease"] = True
    before = journal.read_bytes()
    client = m.Feed(root, host=host)
    assert client.poll(apply=False)["outcome"] == "staged"
    target = root / "var/lib/rosy-device/os-update/staging" / value["release_id"] / value["bundle"]["filename"]
    assert target.read_bytes() == body and target.stat().st_mode & 0o777 == 0o400
    assert {p.name for p in target.parent.iterdir()} == {target.name, "os-update.json", "os-update.json.sig"}
    assert journal.read_bytes() == before
    assert client._cache()["releases"][0]["prerelease"] is True


def test_noncanary_engineering_never_uses_promotion_or_blocks_older_stable(feed):
    m, hub, host, root, _, _, private, _ = feed
    stable, _, _ = publish(hub, private)
    value, _, original, entry = chunked(hub, private, revision="2026.10.26-012")
    entry["prerelease"] = True
    policy(hub, private, value, original, canary=["rosy-pinky-zzzz"], canary_ok=True, wave_delay_s=0)
    assert m.Feed(root, host=host).poll(apply=False)["release_id"] == stable["release_id"]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "mixed", "size", "corrupt", "url", "signature"])
def test_bad_part_inventory_or_content_never_reaches_install(feed, monkeypatch, fault):
    m, hub, host, root, state, journal, private, _ = feed
    value, body, _, entry = chunked(hub, private)
    part = entry["assets"][-1]
    if fault == "missing": entry["assets"].pop(-2)
    if fault == "duplicate": entry["assets"].append(dict(part))
    if fault == "mixed":
        name = value["bundle"]["filename"]
        entry["assets"].append(dict(name=name, size=len(body), browser_download_url=hub.base + "/dl/" + value["release_id"] + "/" + name))
    if fault in ("size", "corrupt"):
        path = value["release_id"] + "/" + part["name"]
        hub.assets[path] = b"x" + hub.assets[path] if fault == "size" else b"x" * len(hub.assets[path])
    if fault == "url": part["browser_download_url"] += "?escape=1"
    if fault == "signature": hub.assets[value["release_id"] + "/os-update.json.sig"] = b"invalid"
    monkeypatch.setattr(m.lifecycle, "start", lambda *a, **k: pytest.fail("unsafe install"))
    before = journal.read_bytes()
    try:
        result = m.Feed(root, host=host).poll()
        assert result["outcome"] == "no-update"
    except ValueError:
        pass
    target = root / "var/lib/rosy-device/os-update/staging" / value["release_id"] / value["bundle"]["filename"]
    assert not target.exists() and journal.read_bytes() == before and state.read_state(root)["pending"] is None


def test_chunked_space_accounts_for_one_part_and_does_not_download_when_low(feed):
    from auto_update_host import DISK_MARGIN_BYTES
    m, hub, host, root, _, _, private, _ = feed
    value, _, _, _ = chunked(hub, private)
    host.free_bytes = lambda p: DISK_MARGIN_BYTES + value["bundle"]["size_bytes"] + 511
    with pytest.raises(ValueError, match="DISK"):
        m.Feed(root, host=host).poll(apply=False)
    assert not any(".part00" in path for path, _ in hub.requests)


def test_fresh_engineering_admission_rechecks_canary_and_withdrawal(feed):
    m, hub, host, root, _, _, private, _ = feed
    value, _, original, entry = chunked(hub, private)
    entry["prerelease"] = True
    client = m.Feed(root, host=host)
    assert client.poll(apply=False)["outcome"] == "staged"
    policy(hub, private, value, original, canary=["rosy-pinky-zzzz"], canary_ok=True)
    with pytest.raises(ValueError): client.admit(value)
    policy(hub, private, value, original, withdrawn=True)
    with pytest.raises(m.Withdrawn): client.admit(value)
