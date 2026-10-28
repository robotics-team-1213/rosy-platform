"""Real local HTTP transport with unchanged signed whole-bundle metadata."""
import importlib
import json

import pytest

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
    stable, _, _, _ = chunked(hub, private)
    value, _, original, entry = chunked(hub, private, revision="2026.10.26-012")
    entry["prerelease"] = True
    policy(hub, private, value, original, canary=["rosy-pinky-zzzz"], canary_ok=True, wave_delay_s=600)
    assert m.Feed(root, host=host).poll(apply=False)["release_id"] == stable["release_id"]


@pytest.mark.parametrize("fault", ["missing", "last_missing", "duplicate", "mixed", "size", "corrupt", "url", "escaped_url", "signature", "rollout_signature"])
def test_bad_part_inventory_or_content_never_reaches_install(feed, monkeypatch, fault):
    m, hub, host, root, state, journal, private, _ = feed
    value, body, _, entry = chunked(hub, private)
    part = entry["assets"][-1]
    if fault == "missing": entry["assets"].pop(-2)
    if fault == "last_missing": entry["assets"].pop()
    if fault == "duplicate": entry["assets"].append(dict(part))
    if fault == "mixed":
        name = value["bundle"]["filename"]
        entry["assets"].append(dict(name=name, size=len(body), browser_download_url=hub.base + "/dl/" + value["release_id"] + "/" + name))
    if fault in ("size", "corrupt"):
        path = value["release_id"] + "/" + part["name"]
        hub.assets[path] = b"x" + hub.assets[path] if fault == "size" else b"x" * len(hub.assets[path])
    if fault == "url": part["browser_download_url"] += "?escape=1"
    if fault == "escaped_url": part["browser_download_url"] = part["browser_download_url"].replace("/dl/", "/dl/%2e%2e/")
    if fault == "signature": hub.assets[value["release_id"] + "/os-update.json.sig"] = b"invalid"
    if fault == "rollout_signature": hub.assets[value["release_id"] + "/os-rollout.json.sig"] = b"invalid"
    monkeypatch.setattr(m.lifecycle, "start", lambda *a, **k: pytest.fail("unsafe install"))
    before = journal.read_bytes()
    try:
        result = m.Feed(root, host=host).poll()
        assert result["outcome"] == "no-update"
    except ValueError:
        pass
    target = root / "var/lib/rosy-device/os-update/staging" / value["release_id"] / value["bundle"]["filename"]
    assert not target.exists() and journal.read_bytes() == before and state.read_state(root)["pending"] is None
    if target.parent.exists(): assert not any(p.name.endswith((".part", ".chunk")) for p in target.parent.iterdir())


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


def test_legacy_stable_cache_remains_stable_and_unknown_classification_fails_closed(feed):
    m, hub, host, root, _, _, private, _ = feed
    _, _, _, entry = chunked(hub, private)
    client = m.Feed(root, host=host)
    normalized = client._entry(entry)
    normalized.pop("prerelease")
    assert client._cached_entry(normalized)["prerelease"] is False
    normalized["prerelease"] = "false"
    with pytest.raises(ValueError): client._cached_entry(normalized)


@pytest.mark.parametrize("leftovers", [(".part",), (".chunk",), (".part", ".chunk")])
def test_interrupted_current_release_reclaims_safe_partials_before_space_check(feed, leftovers):
    from auto_update_host import DISK_MARGIN_BYTES
    m, hub, host, root, _, journal, private, _ = feed
    value, body, _, _ = chunked(hub, private)
    directory = root / "var/lib/rosy-device/os-update/staging" / value["release_id"]
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    paths = [directory / (value["bundle"]["filename"] + suffix) for suffix in leftovers]
    for path in paths:
        path.write_bytes(b"interrupted download")
        path.chmod(0o600)
    need = DISK_MARGIN_BYTES + len(body) + 512
    # Model available filesystem bytes, including the real files left by a crash.
    host.free_bytes = lambda p: need - sum(path.stat().st_size for path in paths if path.exists())
    assert host.free_bytes(directory) < need
    before = journal.read_bytes()
    assert m.Feed(root, host=host).poll(apply=False)["outcome"] == "staged"
    assert (directory / value["bundle"]["filename"]).read_bytes() == body
    assert not any(path.exists() for path in paths)
    assert journal.read_bytes() == before


@pytest.mark.parametrize("unsafe", [False, True])
def test_partial_recovery_preserves_unknown_or_unsafe_current_release_files(feed, unsafe):
    m, hub, host, root, _, _, private, _ = feed
    value, _, _, _ = chunked(hub, private)
    directory = root / "var/lib/rosy-device/os-update/staging" / value["release_id"]
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    path = directory / (value["bundle"]["filename"] + ".part" if unsafe else "operator-note.txt")
    path.write_bytes(b"preserve")
    path.chmod(0o644)
    host.free_bytes = lambda p: 0
    with pytest.raises(ValueError): m.Feed(root, host=host).poll(apply=False)
    assert path.read_bytes() == b"preserve"
    assert not any(".part00" in address for address, _ in hub.requests)
