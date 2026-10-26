"""Real local HTTP, Ed25519 and bounded private files; installation is an explicitly modeled boundary."""
import datetime as dt
import hashlib
import importlib
import json

import pytest

from auto_update_fakes import FakeGitHub, FakeHost, REPO, HOST
from signing import sign_checksums
from test_factory_release_signature import _keys
from test_os_update_state import _state
from test_os_update_manifest import metadata
from test_os_update_rollout import rollout


@pytest.fixture
def feed(tmp_path, monkeypatch):
    state, root, journal, _, _, _ = _state(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_feed")
    hub = FakeGitHub()
    host = FakeHost(root)
    host.t = dt.datetime(2026, 10, 26, 1, tzinfo=dt.timezone.utc)
    host.current_release = lambda: "2026.10.26-999"  # Native ordering must not suppress a newer OS release.
    private, public = _keys(tmp_path / "ed", "feed")
    key = root / "etc/rosy/trusted-release-keys" / public.name
    key.parent.mkdir(parents=True)
    key.write_bytes(public.read_bytes())
    directory = root / "var/lib/rosy-device/policy/updates"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(json.dumps(dict(enabled=True, repo=REPO, api_base=hub.base)))
    import auto_update_records
    monkeypatch.setattr(auto_update_records, "policy_file", lambda r, name: directory / name)
    monkeypatch.setattr(m.Feed, "_freeze", lambda self: None)
    yield m, hub, host, root, state, journal, private, directory
    hub.close()


def publish(hub, private, *, revision="2026.10.26-011", withdrawn=False, canary_ok=True):
    value = metadata()
    value["release_id"] = revision
    body = b"real bounded OS download" * 100
    name = f"rosy-os-pinky-pro-{revision}-arm64.raucb"
    value["bundle"] = dict(filename=name, sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
    policy = dict(rollout(value), canary=[HOST], canary_ok=canary_ok, withdrawn=withdrawn)
    raw = json.dumps(value).encode()
    policy_raw = json.dumps(policy).encode()
    assets = {name: body, "os-update.json": raw, "os-update.json.sig": sign_checksums(raw, private).encode(),
              "os-rollout.json": policy_raw, "os-rollout.json.sig": sign_checksums(policy_raw, private).encode()}
    entry = dict(tag_name="os-pinky-pro-" + revision, draft=False, prerelease=False, assets=[])
    for filename, content in assets.items():
        key = revision + "/" + filename
        hub.assets[key] = content
        entry["assets"].append(dict(name=filename, size=len(content), browser_download_url=hub.base + "/dl/" + key))
    hub.releases.append(entry)
    return value, body, policy


def test_signed_catalogue_stages_exact_readonly_bundle_using_committed_os_order(feed):
    m, hub, host, root, _, journal, private, _ = feed
    value, body, _ = publish(hub, private)
    hub.releases.insert(0, dict(tag_name="payload-2026.10.26-999", draft=False, prerelease=False, assets=[]))
    before = journal.read_bytes()
    result = m.Feed(root, host=host).poll(apply=False)
    assert result["outcome"] == "staged" and result["release_id"] == value["release_id"]
    bundle = root / "var/lib/rosy-device/os-update/staging" / value["release_id"] / value["bundle"]["filename"]
    assert bundle.read_bytes() == body and bundle.stat().st_mode & 0o777 == 0o400
    assert journal.read_bytes() == before
    requests = len(hub.requests)
    m.Feed(root, host=host).admit(value)
    assert len(hub.requests) > requests  # Cached staging never authorizes the later arm.


@pytest.mark.parametrize("fault", ["metadata_signature", "rollout_signature", "withdrawn", "failed", "size", "digest", "disabled", "url"])
def test_untrusted_or_ineligible_release_cannot_reach_install(feed, monkeypatch, fault):
    m, hub, host, root, state, journal, private, directory = feed
    value, _, _ = publish(hub, private, withdrawn=fault == "withdrawn")
    prefix = value["release_id"] + "/"
    if fault.endswith("signature"):
        asset = "os-update.json.sig" if fault == "metadata_signature" else "os-rollout.json.sig"
        hub.assets[prefix + asset] = b"untrusted signature"
    elif fault == "failed":
        current = json.loads(journal.read_text()); current["failed_versions"] = [value["release_id"]]
        journal.write_text(json.dumps(current))
    elif fault in ("size", "digest"):
        key = prefix + value["bundle"]["filename"]
        hub.assets[key] = hub.assets[key] + b"x" if fault == "size" else b"x" * value["bundle"]["size_bytes"]
    elif fault == "disabled": (directory / "config.json").write_text('{"enabled":false}')
    elif fault == "url": hub.releases[0]["assets"][0]["browser_download_url"] = "http://127.0.0.1:1/private"
    monkeypatch.setattr(m.lifecycle, "start", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unsafe apply")))
    before = journal.read_bytes()
    try: result = m.Feed(root, host=host).poll()
    except ValueError: pass
    assert journal.read_bytes() == before and state.read_state(root)["pending"] is None


def test_staged_withdrawal_is_refetched_and_rejected_before_later_arm(feed):
    m, hub, host, root, _, _, private, _ = feed
    value, _, policy = publish(hub, private)
    client = m.Feed(root, host=host)
    client.poll(apply=False)
    raw = json.dumps(dict(policy, withdrawn=True)).encode()
    hub.assets[value["release_id"] + "/os-rollout.json"] = raw
    hub.assets[value["release_id"] + "/os-rollout.json.sig"] = sign_checksums(raw, private).encode()
    with pytest.raises(m.Withdrawn): client.admit(value)


def test_insufficient_real_staging_space_never_downloads_or_changes_os_state(feed):
    m, hub, host, root, _, journal, private, _ = feed
    value, _, _ = publish(hub, private)
    host.free_bytes = lambda path: 0
    before = journal.read_bytes()
    with pytest.raises(ValueError, match="DISK"): m.Feed(root, host=host).poll(apply=False)
    assert journal.read_bytes() == before
    assert not any(path.endswith(value["bundle"]["filename"]) for path, _ in hub.requests)
