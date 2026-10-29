"""Publisher-produced assets traverse real HTTP and signatures; installation is modeled."""
import hashlib
import json

import pytest

from auto_update_fakes import HOST
from signing import sign_checksums
from test_os_update_feed import feed  # noqa: F401
from test_publish_os_release import GitHub, module, prepared  # noqa: F401


@pytest.fixture(autouse=True)
def publisher_bootstrap():
    # Exercise the actual operator import bootstrap in an isolated pytest invocation too.
    return module()


def distribute(prepared, feed, publisher, monkeypatch):
    directory, public, metadata, private = prepared
    client_module, hub, host, root, state, journal, _, _ = feed
    import os_update_transport as transport
    monkeypatch.setattr(transport, "CHUNK_BYTES", 17)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 20)
    policy = json.loads((directory / "os-rollout.json").read_bytes())
    policy.update(canary=[HOST], canary_ok=False)
    raw = json.dumps(policy).encode()
    (directory / "os-rollout.json").write_bytes(raw)
    (directory / "os-rollout.json.sig").write_text(sign_checksums(raw, private))
    (root / "etc/rosy/trusted-release-keys" / public.name).write_bytes(public.read_bytes())
    github = GitHub()
    result = publisher.publish(directory, public, release_id=metadata["release_id"],
                               source_revision=metadata["source_revision"], apply=True, gh=github)
    assert result["applied"] and github.release["prerelease"] and not github.release["draft"]
    entry = dict(github.release, assets=[])
    for name, content in github.uploaded.items():
        key = metadata["release_id"] + "/" + name
        hub.assets[key] = content
        entry["assets"].append(dict(github.assets[name], browser_download_url=hub.base + "/dl/" + key))
    hub.releases.append(entry)
    return client_module, hub, host, root, state, journal, metadata, policy


@pytest.mark.parametrize("fault", [None, "corrupt", "missing", "noncanary"])
def test_real_publisher_prerelease_reaches_only_the_signed_canary_with_exact_bundle(
        prepared, feed, publisher_bootstrap, monkeypatch, fault):
    m, hub, host, root, state, journal, metadata, _ = distribute(prepared, feed, publisher_bootstrap, monkeypatch)
    original = (prepared[0] / metadata["bundle"]["filename"]).read_bytes()
    parts = [a for a in hub.releases[0]["assets"] if ".part" in a["name"]]
    assert len(parts) == 3
    if fault == "corrupt": hub.assets[metadata["release_id"] + "/" + parts[1]["name"]] = b"x" * parts[1]["size"]
    if fault == "missing": hub.releases[0]["assets"].remove(parts[-1])
    if fault == "noncanary": host.hostname = lambda: "rosy-pinky-other"
    before, installed = journal.read_bytes(), []

    def install_boundary(_root, bundle, raw, signature, **kwargs):
        assert fault is None
        assert bundle.read_bytes() == original
        assert hashlib.sha256(bundle.read_bytes()).hexdigest() == metadata["bundle"]["sha256"]
        assert m.verify_metadata(raw, signature, root / "etc/rosy/trusted-release-keys" / prepared[1].name) == metadata
        installed.append(bundle)
        return dict(pending={"phase": "PREPARED"})

    monkeypatch.setattr(m.lifecycle, "start", install_boundary)
    try:
        outcome = m.Feed(root, host=host).poll()
    except ValueError:
        assert fault in {"corrupt", "missing"}
    else:
        assert outcome["outcome"] == ("trial-requested" if fault is None else "no-update")
    assert bool(installed) == (fault is None)
    assert journal.read_bytes() == before and state.read_state(root)["pending"] is None


def test_publisher_policy_withdrawal_is_fetched_again_after_successful_staging(
        prepared, feed, publisher_bootstrap, monkeypatch):
    m, hub, host, root, _, journal, metadata, policy = distribute(prepared, feed, publisher_bootstrap, monkeypatch)
    client = m.Feed(root, host=host)
    assert client.poll(apply=False)["outcome"] == "staged"
    before = journal.read_bytes()
    policy["withdrawn"] = True
    raw = json.dumps(policy).encode()
    prefix = metadata["release_id"] + "/"
    hub.assets[prefix + "os-rollout.json"] = raw
    hub.assets[prefix + "os-rollout.json.sig"] = sign_checksums(raw, prepared[3]).encode()
    with pytest.raises(m.Withdrawn):
        client.admit(metadata)
    assert journal.read_bytes() == before
