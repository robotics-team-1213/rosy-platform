"""Real GPT byte-range extraction/compression; fixtures are not bootable OS images."""
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_ab_image_layout import IMAGE, RELEASE_ID
from test_sd_gpt_layout import _table_image


def module():
    spec = importlib.util.spec_from_file_location("os_bundle_export_test", IMAGE / "export-os-bundle-inputs.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def inputs(tmp_path):
    raw, layout = _table_image()
    layout["provision_role"] = "bootstrap"
    source = tmp_path / "factory.img"
    source.write_bytes(raw)
    factory = tmp_path / "factory"
    factory.mkdir()
    manifest = json.dumps({"release_id": RELEASE_ID}).encode()
    (factory / "manifest.json").write_bytes(manifest)
    (factory / "SHA256SUMS").write_text(hashlib.sha256(manifest).hexdigest() + "  manifest.json\n")
    return raw, layout, source, factory


def test_exports_only_slot_a_exact_ranges_with_logical_and_archive_hashes(tmp_path):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    output = tmp_path / "os-bundle-inputs"
    result = m.export(source, layout, output, factory, RELEASE_ID, "a" * 40)
    assert source.read_bytes() == raw
    assert set(p.name for p in output.iterdir()) == {"inputs.json", "rootfs.ext4.xz", "boot.vfat.xz"}
    assert result == json.loads((output / "inputs.json").read_bytes())
    assert result["native_factory"] == dict(release_id=RELEASE_ID,
        checksums_sha256=hashlib.sha256((factory / "SHA256SUMS").read_bytes()).hexdigest())
    assert result["source_revision"] == "a" * 40 and result["boot_abi"] == 2
    for name, role in (("rootfs.ext4", "root_a"), ("boot.vfat", "boot_a")):
        part = next(p for p in layout["partitions"] if p["role"] == role)
        data = bytes(raw[part["start_lba"] * 512:(part["start_lba"] + part["size_lba"]) * 512])
        archive = (output / (name + ".xz")).read_bytes()
        assert lzma.decompress(archive) == data
        assert result["images"][name] == dict(filename=name + ".xz", size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), archive_bytes=len(archive),
            archive_sha256=hashlib.sha256(archive).hexdigest())


@pytest.mark.parametrize("case", ["table", "prototype", "source_symlink", "existing", "factory", "identity"])
def test_rejects_bad_inputs_before_publishing_and_preserves_source(tmp_path, case):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    output = tmp_path / "os-bundle-inputs"
    identity = RELEASE_ID
    if case == "table": layout["partitions"][3]["unique_guid"] = "06641603-f85c-46ea-886c-c64e7a5edc26"
    if case == "prototype": layout["provision_role"] = "boot_a"
    if case == "source_symlink":
        link = tmp_path / "link.img"
        link.symlink_to(source)
        source = link
    if case == "existing":
        output.mkdir()
        (output / "keep").write_text("operator data")
    if case == "factory": (factory / "manifest.json").write_text("tampered")
    if case == "identity": identity = "2026.02.30-001"
    with pytest.raises((ValueError, OSError)):
        m.export(source, layout, output, factory, identity, "a" * 40)
    assert source.read_bytes() == raw
    if case == "existing": assert (output / "keep").read_text() == "operator data"
    else: assert not output.exists()
    assert not list(tmp_path.glob(".os-bundle-inputs-*"))


def test_stream_failure_removes_only_owned_partial_output(tmp_path, monkeypatch):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    def fail(*args, **kwargs): raise OSError("injected disk full")
    monkeypatch.setattr(m, "_extract", fail)
    with pytest.raises(OSError, match="disk full"):
        m.export(source, layout, tmp_path / "os-bundle-inputs", factory, RELEASE_ID, "a" * 40)
    assert source.read_bytes() == raw
    assert not list(tmp_path.glob(".os-bundle-inputs-*"))


def test_native_builder_exports_before_raw_deletion_and_outer_sums_cover_inputs():
    build = (IMAGE / "build-image.sh").read_text()
    assert build.index("export-os-bundle-inputs.py") < build.index('"$SCRIPT_DIR/finalize-image.sh"')
    assert '--factory "$PAYLOAD_ROOT/factory-release"' in build
    manifest = (IMAGE / "create-image-manifest.py").read_text()
    assert "os-bundle-inputs/" in manifest


def test_real_manifest_command_covers_exported_archives_in_outer_checksums(tmp_path):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    dist, payload = tmp_path / "dist", tmp_path / "payload"
    dist.mkdir()
    payload.mkdir()
    m.export(source, layout, dist / "os-bundle-inputs", factory, RELEASE_ID, "a" * 40)
    (dist / f"rosy-os-pinky-pro-{RELEASE_ID}-arm64.img.xz").write_bytes(lzma.compress(raw))
    snapshot = tmp_path / "layout.json"
    snapshot.write_text(json.dumps(layout))
    lock = tmp_path / "lock.yaml"
    lock.write_text("fixture: true\n")
    shutil.copytree(factory, payload / "factory-release")
    for name in ("deb-packages.txt", "rosy-packages.txt", "required-ros-packages.txt", "source-revision.txt"):
        (payload / name).write_text("fixture\n")
    result = subprocess.run([sys.executable, str(IMAGE / "create-image-manifest.py"), "--dist", str(dist),
        "--payload", str(payload), "--lock", str(lock), "--release-id", RELEASE_ID,
        "--source-revision", "a" * 40, "--layout-file", str(snapshot)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    for name in ("inputs.json", "rootfs.ext4.xz", "boot.vfat.xz"):
        path = "os-bundle-inputs/" + name
        assert hashlib.sha256((dist / path).read_bytes()).hexdigest() + "  " + path in (dist / "SHA256SUMS").read_text()


def test_source_mutation_during_export_refuses_publication(tmp_path, monkeypatch):
    m = module()
    raw, layout, source, factory = inputs(tmp_path)
    original = m._extract
    def change(*args):
        result = original(*args)
        with source.open("r+b") as stream:
            stream.seek(1000)
            stream.write(b"changed")
        return result
    monkeypatch.setattr(m, "_extract", change)
    with pytest.raises(ValueError, match="changed"):
        m.export(source, layout, tmp_path / "os-bundle-inputs", factory, RELEASE_ID, "a" * 40)
    assert not (tmp_path / "os-bundle-inputs").exists()
    assert not list(tmp_path.glob(".os-bundle-inputs-*"))


def test_hosted_workflow_verifies_unsigned_bundle_handoff_before_upload():
    workflow = (IMAGE.parents[3] / ".github/workflows/build-pinky-image.yml").read_text()
    for value in ("os-bundle-inputs/inputs.json", "os-bundle-inputs/rootfs.ext4.xz", "os-bundle-inputs/boot.vfat.xz"):
        assert value in workflow
    assert 'inputs["source_revision"] == manifest_revision' in workflow
