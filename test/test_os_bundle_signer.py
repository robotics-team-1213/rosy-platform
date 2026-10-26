"""Offline publication with real Ed/CMS/verity; filesystem preparation is explicitly modeled."""
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import shutil

import pytest

from test_ab_image_layout import IMAGE, RELEASE_ID
from test_os_bundle_export import module as exporter, inputs
from test_factory_release_signature import _keys
from sign_image_release import sign_image_release
from signing import sign_checksums
from os_rauc_fakes import rauc_tool, signer
from test_os_update_feed import feed  # Actual HTTP catalogue/staging fixture.
from auto_update_fakes import HOST


def module():
    exporter()
    spec = importlib.util.spec_from_file_location("os_bundle_signer_test", IMAGE.parent / "release/os_bundle.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def distribution(tmp_path):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    # RAUC requires squashfs >4KiB; zero-filled GPT fixtures otherwise compress below that boundary.
    for part in layout["partitions"]:
        if part["role"] in {"root_a", "boot_a"}:
            start = part["start_lba"] * 512
            raw[start:start + 8192] = os.urandom(8192)
    source.write_bytes(raw)
    dist = tmp_path / "signed-image"
    dist.mkdir()
    exporter().export(source, layout, dist / "os-bundle-inputs", factory, RELEASE_ID, "a" * 40)
    shutil.copytree(factory, dist / "factory-release" / RELEASE_ID)
    image = dist / f"rosy-os-pinky-pro-{RELEASE_ID}-arm64.img.xz"
    image.write_bytes(lzma.compress(raw))
    (dist / "manifest.json").write_text(json.dumps(dict(schema_version=2, release_id=RELEASE_ID,
        product="rosy-os", board="pinky_pro", architecture="arm64", layout=layout,
        image=dict(filename=image.name, sha256=hashlib.sha256(image.read_bytes()).hexdigest()))))
    (dist / "build-provenance.json").write_text(json.dumps(dict(source_revision="a" * 40, architecture="aarch64")))
    paths = sorted(p for p in dist.rglob("*") if p.is_file())
    (dist / "SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.relative_to(dist).as_posix() + "\n" for p in paths))
    private, public = _keys(tmp_path / "ed-keys", "distribution")
    sign_image_release(dist, private, public)
    return m, dist, private, public


def test_authenticates_distribution_and_factory_before_parsing_os_inputs(tmp_path):
    m, dist, _, public = distribution(tmp_path)
    value = m.read_inputs(dist, public)
    assert value["release_id"] == RELEASE_ID
    assert value["native_factory"]["checksums_sha256"] == hashlib.sha256((dist / "factory-release" / RELEASE_ID / "SHA256SUMS").read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["metadata", "archive", "outer_signature", "factory_signature", "foreign_board"])
def test_refuses_untrusted_inputs_without_mutating_distribution(tmp_path, change):
    m, dist, private, public = distribution(tmp_path)
    path = dist / {"metadata": "os-bundle-inputs/inputs.json", "archive": "os-bundle-inputs/rootfs.ext4.xz",
        "outer_signature": "SHA256SUMS.sig", "factory_signature": f"factory-release/{RELEASE_ID}/SHA256SUMS.sig",
        "foreign_board": "manifest.json"}[change]
    if change == "foreign_board":
        value = json.loads(path.read_bytes())
        path.write_text(json.dumps({**value, "board": "foreign-robot"}))
    else: path.write_bytes(b"tampered")
    if change in {"factory_signature", "foreign_board"}:
        # Even an outer signature does not replace the native factory signature.
        from signing import build_sha256sums
        entries = [p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()
                   and p.relative_to(dist).as_posix() not in {"SHA256SUMS.sig", "SHA256SUMS"}]
        (dist / "SHA256SUMS").write_bytes(build_sha256sums(dist, entries))
        (dist / "SHA256SUMS.sig").write_text(sign_checksums((dist / "SHA256SUMS").read_bytes(), private))
    before = {p.relative_to(dist).as_posix(): p.read_bytes() for p in dist.rglob("*") if p.is_file()}
    with pytest.raises((ValueError, OSError)):
        m.read_inputs(dist, public)
    assert before == {p.relative_to(dist).as_posix(): p.read_bytes() for p in dist.rglob("*") if p.is_file()}


def test_decompression_is_bounded_by_both_size_and_digest(tmp_path):
    m = module()
    data = b"a" * 8192
    archive = tmp_path / "image.xz"
    archive.write_bytes(lzma.compress(data))
    expected = dict(size_bytes=8192, sha256=hashlib.sha256(data).hexdigest())
    m.decompress(archive, expected, tmp_path / "image.ext4")
    assert (tmp_path / "image.ext4").read_bytes() == data
    for field, value in (("size_bytes", 512), ("sha256", "0" * 64)):
        bad = {**expected, field: value}
        with pytest.raises(ValueError): m.decompress(archive, bad, tmp_path / (field + ".ext4"))


def test_real_bundle_signing_is_accepted_by_existing_os_consumer(tmp_path, monkeypatch, rauc_tool, feed):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)  # Ephemeral fixture keys only, never a product CI signer.
    m, dist, private, public = distribution(tmp_path)
    cms_private, certificate = signer(tmp_path / "cms")
    # These fixture ranges are not filesystems. Actual root preparation is a separate SYSTEM gate.
    prepared = []
    monkeypatch.setattr(m, "prepare_root", lambda work, *_: prepared.append(work))
    output = tmp_path / "signed-os"
    m.sign(dist, output, private, public, cms_private, certificate, canary=[HOST], rauc=str(rauc_tool))
    assert len(prepared) == 1
    assert {p.name for p in output.iterdir()} == {f"rosy-os-pinky-pro-{RELEASE_ID}-arm64.raucb",
        "os-update.json", "os-update.json.sig", "os-rollout.json", "os-rollout.json.sig"}
    from test_os_rauc import _consumer
    consumer = _consumer(monkeypatch, rauc_tool)
    root = tmp_path / "device"
    ring = root / "etc/rauc/keyring.pem"
    ring.parent.mkdir(parents=True)
    shutil.copyfile(certificate, ring)
    key = root / "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
    key.parent.mkdir(parents=True)
    shutil.copyfile(public, key)
    stage = root / "var/lib/rosy-device/os-update/staging" / RELEASE_ID
    stage.mkdir(parents=True)
    bundle = next(output.glob("*.raucb"))
    shutil.copyfile(bundle, stage / bundle.name)
    (stage / bundle.name).chmod(0o400)
    raw = (output / "os-update.json").read_bytes()
    facts = consumer.verify_bundle(root, stage / bundle.name, raw, (output / "os-update.json.sig").read_text().strip())
    assert facts["metadata"]["release_id"] == RELEASE_ID
    from os_update_rollout import verify, authorize
    rollout = verify((output / "os-rollout.json").read_bytes(), (output / "os-rollout.json.sig").read_text().strip(), public, facts["metadata"])
    from datetime import datetime, timezone
    authorize(rollout, HOST, datetime.now(timezone.utc))
    client_module, hub, host, device, state, journal, _, _ = feed
    host.t = datetime.now(timezone.utc)
    (device / "etc/rosy/trusted-release-keys" / public.name).write_bytes(public.read_bytes())
    entry = dict(tag_name="os-pinky-pro-" + RELEASE_ID, draft=False, prerelease=False, assets=[])
    for path in output.iterdir():
        asset = RELEASE_ID + "/" + path.name
        hub.assets[asset] = path.read_bytes()
        entry["assets"].append(dict(name=path.name, size=path.stat().st_size, browser_download_url=hub.base + "/dl/" + asset))
    hub.releases.append(entry)
    client = client_module.Feed(device, host=host)
    assert client.poll(apply=False)["outcome"] == "staged"
    downloaded = device / "var/lib/rosy-device/os-update/staging" / RELEASE_ID / bundle.name
    assert downloaded.read_bytes() == bundle.read_bytes()
    withdrawn = json.dumps({**rollout, "withdrawn": True}).encode()
    hub.assets[RELEASE_ID + "/os-rollout.json"] = withdrawn
    hub.assets[RELEASE_ID + "/os-rollout.json.sig"] = sign_checksums(withdrawn, private).encode()
    with pytest.raises(client_module.Withdrawn): client.admit(facts["metadata"])
    record = json.loads(journal.read_bytes())
    record["failed_versions"] = [RELEASE_ID]
    journal.write_text(json.dumps(record))
    assert client.poll(apply=False)["outcome"] == "no-update"
    assert state.read_state(device)["pending"] is None
