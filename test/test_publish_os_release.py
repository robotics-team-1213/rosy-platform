"""Engineering-only publication: real ephemeral signatures, an offline GitHub transport."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from signing import sign_checksums
from test_factory_release_signature import _keys
from test_os_update_manifest import metadata
from test_os_update_rollout import rollout

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location("publish_os_release", ROOT / "tools/release/publish_os_release.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class GitHub:
    def __init__(self):
        self.calls, self.assets = [], {}
        self.uploaded = {}
        self.operations = []
        self.release = None
        self.refs = []
        self.fault = None
        self.on_create = lambda: None

    def __call__(self, argv):
        self.calls.append(argv)
        assert argv[0] == "gh"
        assert not any("--clobber" in arg or "delete" == arg for arg in argv)
        assert argv[1] == "api"
        endpoint = argv[2]
        assert "robotics-team-1213/rosy-platform" in endpoint
        assert argv[argv.index("--hostname") + 1] == "github.com"
        method = argv[argv.index("--method") + 1] if "--method" in argv else "GET"
        if endpoint.endswith("/releases") and method == "POST":
            fields = dict(argv[i + 1].split("=", 1) for i, arg in enumerate(argv) if arg in ("-f", "-F"))
            assert fields["draft"] == fields["prerelease"] == "true"
            self.operations.append("create")
            self.release = dict(id=17, tag_name=fields["tag_name"], target_commitish=fields["target_commitish"],
                                draft=True, prerelease=True)
            result = dict(self.release)
            if self.fault == "id_missing": result.pop("id")
            if self.fault == "id_bool": result["id"] = True
            if self.fault == "id_string": result["id"] = "17"
            self.on_create()
        elif endpoint.startswith("https://uploads.github.com/"):
            assert "/releases/17/assets?name=" in endpoint and method == "POST"
            self.operations.append("upload")
            path = Path(argv[argv.index("--input") + 1])
            assert endpoint.endswith("?name=" + path.name)
            assert "Content-Type: application/octet-stream" in argv
            raw = path.read_bytes()
            self.uploaded[path.name] = raw
            assert "Content-Length: " + str(len(raw)) in argv
            self.assets[path.name] = dict(name=path.name, size=len(raw), digest="sha256:" + hashlib.sha256(raw).hexdigest())
            result = self.assets[path.name]
            if self.fault == "partial": self.assets.pop(next(iter(self.assets)))
            if self.fault == "extra": self.assets["extra"] = dict(name="extra", size=1, digest="sha256:" + "0" * 64)
            if self.fault == "digest": next(iter(self.assets.values()))["digest"] = "sha256:" + "0" * 64
            if self.fault == "missing_digest": next(iter(self.assets.values())).pop("digest", None)
            if self.fault == "size": next(iter(self.assets.values()))["size"] += 1
            if self.fault == "missing_chunk" and ".part" in path.name: self.assets.pop(path.name)
            if self.fault == "corrupt_chunk" and ".part" in path.name: self.assets[path.name]["digest"] = "sha256:" + "0" * 64
            if self.fault == "upload": return 1, "", "credential and signed URL must not leak"
            if self.fault == "late_tag":
                self.refs = [dict(ref="refs/tags/" + self.release["tag_name"], object=dict(type="commit", sha="a" * 40))]
        elif endpoint.endswith("/releases/17") and method == "PATCH":
            assert "draft=false" in argv and "prerelease=true" in argv
            self.operations.append("publish")
            self.release["draft"] = False
            result = self.release
        elif endpoint.endswith("/releases/17"):
            result = dict(self.release, assets=list(self.assets.values()))
            if self.fault == "source": result["target_commitish"] = "a" * 40
            if self.fault == "tag": result["tag_name"] = "os-pinky-pro-wrong"
            if self.fault == "prerelease": result["prerelease"] = False
            if self.fault == "id_changed": result["id"] = 18
        elif "matching-refs" in endpoint:
            result = self.refs
        elif "/releases?" in endpoint:
            result = [] if self.release is None else [dict(self.release, assets=list(self.assets.values()))]
            if "--slurp" in argv: result = [result]
        else:
            raise AssertionError(argv)
        return 0, json.dumps(result), ""


@pytest.fixture
def prepared(tmp_path):
    private, public = _keys(tmp_path / "keys", "publisher")
    directory = tmp_path / "signed"
    directory.mkdir()
    value = metadata()
    raw_bundle = b"operator-signed CMS bundle binding fixture"
    value["bundle"].update(size_bytes=len(raw_bundle), sha256=hashlib.sha256(raw_bundle).hexdigest())
    (directory / value["bundle"]["filename"]).write_bytes(raw_bundle)
    for name, record in (("os-update.json", value), ("os-rollout.json", rollout(value))):
        raw = (json.dumps(record, indent=2) + "\n").encode()
        (directory / name).write_bytes(raw)
        (directory / (name + ".sig")).write_text(sign_checksums(raw, private) + "\n", encoding="ascii")
    return directory, public, value, private


def publish(prepared, hub, **kwargs):
    directory, public, value, _ = prepared
    return module().publish(directory, public, release_id=value["release_id"],
                            source_revision=value["source_revision"], gh=hub, **kwargs)


def test_default_dry_run_has_no_github_mutations(prepared):
    hub = GitHub()
    publish(prepared, hub)
    assert not hub.calls


@pytest.mark.parametrize("size", [16 * 1024**3 + 1, 16 * 1024**3 + 2])
@pytest.mark.parametrize("apply", [False, True])
def test_signed_bundle_size_limit_is_checked_before_capture(prepared, monkeypatch, size, apply):
    directory, public, value, private = prepared
    value["bundle"]["size_bytes"] = size
    raw = json.dumps(value).encode()
    (directory / "os-update.json").write_bytes(raw)
    (directory / "os-update.json.sig").write_text(sign_checksums(raw, private))
    publisher, hub = module(), GitHub()
    capture = publisher._capture

    def checked_capture(source, target, limit):
        assert source.name != value["bundle"]["filename"], "oversized bundle must be refused before capture"
        return capture(source, target, limit)

    monkeypatch.setattr(publisher, "_capture", checked_capture)
    with pytest.raises(ValueError):
        publisher.publish(directory, public, release_id=value["release_id"],
                          source_revision=value["source_revision"], apply=apply, gh=hub)
    assert not hub.calls


def test_success_uploads_exact_captured_bytes_before_opening_engineering_prerelease(prepared):
    hub = GitHub()
    directory = prepared[0]
    expected = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
    hub.on_create = lambda: (directory / "os-update.json").write_bytes(b"changed after validation")
    publish(prepared, hub, apply=True)
    assert hub.release["draft"] is False and hub.release["prerelease"] is True
    assert {name: asset["digest"][7:] for name, asset in hub.assets.items()} == expected
    assert hub.operations == ["create", *["upload"] * 5, "publish"]


@pytest.mark.parametrize("mutate_original", [False, True])
def test_chunked_upload_preserves_signed_bytes_and_original_inputs(prepared, monkeypatch, mutate_original):
    module()
    import os_update_transport as transport
    monkeypatch.setattr(transport, "CHUNK_BYTES", 17)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 20)
    directory, _, value, _ = prepared
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    hub = GitHub()
    if mutate_original:
        hub.on_create = lambda: (directory / value["bundle"]["filename"]).write_bytes(b"changed after capture")
    result = publish(prepared, hub, apply=True)
    parts = [value["bundle"]["filename"] + f".part{number:03}" for number in range(3)]
    assert set(result["assets"]) == set(original) - {value["bundle"]["filename"]} | set(parts)
    assert [len(hub.uploaded[name]) for name in parts] == [17, 17, 8]
    assert b"".join(hub.uploaded[name] for name in parts) == original[value["bundle"]["filename"]]
    for name in set(original) - {value["bundle"]["filename"]}:
        assert hub.uploaded[name] == original[name]
    assert hub.operations == ["create", *["upload"] * 7, "publish"]
    if not mutate_original:
        assert {p.name: p.read_bytes() for p in directory.iterdir()} == original


@pytest.mark.parametrize("fault", ["missing_chunk", "corrupt_chunk"])
def test_missing_or_corrupt_uploaded_chunk_never_opens_the_draft(prepared, monkeypatch, fault):
    module()
    import os_update_transport as transport
    monkeypatch.setattr(transport, "CHUNK_BYTES", 17)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 20)
    hub = GitHub()
    hub.fault = fault
    with pytest.raises(ValueError, match="OS draft"):
        publish(prepared, hub, apply=True)
    assert hub.release["draft"] is True
    assert "publish" not in hub.operations


def test_changed_captured_bundle_is_refused_before_chunk_publication(prepared, monkeypatch):
    module()
    import os_update_transport as transport
    monkeypatch.setattr(transport, "CHUNK_BYTES", 17)
    monkeypatch.setattr(transport, "GITHUB_MAX_ASSET_BYTES", 20)
    directory, public, value, _ = prepared
    original = (directory / value["bundle"]["filename"]).read_bytes()
    publisher, hub = module(), GitHub()
    capture = publisher._capture

    def changed_capture(source, target, limit):
        result = capture(source, target, limit)
        if source.name == value["bundle"]["filename"]:
            target.write_bytes(b"X" * len(original))
        return result

    monkeypatch.setattr(publisher, "_capture", changed_capture)
    with pytest.raises(ValueError, match="changed while creating transport parts"):
        publisher.publish(directory, public, release_id=value["release_id"],
                          source_revision=value["source_revision"], apply=True, gh=hub)
    assert not hub.calls
    assert (directory / value["bundle"]["filename"]).read_bytes() == original


@pytest.mark.parametrize("fault", ["bundle", "metadata", "rollout", "signature", "unknown", "missing", "source", "release", "rollout_binding"])
def test_bad_local_inputs_never_mutate_remote(prepared, fault):
    directory, public, value, private = prepared
    hub = GitHub()
    if fault in ("bundle", "metadata", "rollout", "signature"):
        name = {"bundle": value["bundle"]["filename"], "metadata": "os-update.json", "rollout": "os-rollout.json", "signature": "os-update.json.sig"}[fault]
        with (directory / name).open("ab") as stream: stream.write(b"tampered")
    elif fault == "unknown": (directory / "operator-note").write_text("preserve")
    elif fault == "missing": (directory / "os-rollout.json.sig").unlink()
    elif fault in ("source", "release"):
        value["source_revision" if fault == "source" else "release_id"] = "a" * 40 if fault == "source" else "2026.10.26-099"
        raw = json.dumps(value).encode()
        (directory / "os-update.json").write_bytes(raw)
        (directory / "os-update.json.sig").write_text(sign_checksums(raw, private))
    else:
        record = dict(rollout(value), bundle_sha256="0" * 64)
        raw = json.dumps(record).encode()
        (directory / "os-rollout.json").write_bytes(raw)
        (directory / "os-rollout.json.sig").write_text(sign_checksums(raw, private))
    with pytest.raises(ValueError):
        module().publish(directory, public, release_id="2026.10.26-011", source_revision="b" * 40, apply=True, gh=hub)
    assert not hub.operations


def test_symlink_asset_is_refused(prepared, tmp_path):
    path = prepared[0] / "os-update.json"
    target = tmp_path / "elsewhere"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    hub = GitHub()
    with pytest.raises(ValueError): publish(prepared, hub, apply=True)
    assert hub.release is None


@pytest.mark.parametrize("existing", ["tag", "draft"])
def test_existing_tag_or_release_is_never_overwritten(prepared, existing):
    hub = GitHub()
    tag = "os-pinky-pro-" + prepared[2]["release_id"]
    if existing == "tag": hub.refs = [dict(ref="refs/tags/" + tag)]
    else: hub.release = dict(tag_name=tag, draft=True)
    with pytest.raises(ValueError): publish(prepared, hub, apply=True)
    assert not hub.operations


@pytest.mark.parametrize("fault", ["partial", "extra", "digest", "missing_digest", "size", "source", "tag", "prerelease", "upload", "late_tag", "id_missing", "id_bool", "id_string", "id_changed"])
def test_failed_remote_verification_preserves_draft(prepared, fault):
    hub = GitHub()
    hub.fault = fault
    with pytest.raises(ValueError) as error: publish(prepared, hub, apply=True)
    assert "credential and signed URL" not in str(error.value)
    assert hub.release["draft"] is True
    assert "publish" not in hub.operations


def test_tag_replacement_after_verification_cannot_publish_the_replacement(prepared):
    hub = GitHub()
    created, replacement = {}, {}

    def transport(argv):
        # The draft was verified as A; an independent actor now gives its tag to B.
        if argv[1] == "api" and "matching-refs" in argv[2] and created and not replacement:
            replacement.update(created, id=18, target_commitish="a" * 40)
            hub.release = replacement
        if argv[1] == "api" and argv[2].endswith("/releases/17"):
            if "PATCH" in argv:
                assert "draft=false" in argv and "prerelease=true" in argv
                created["draft"] = False
            return 0, json.dumps(dict(created, assets=list(hub.assets.values()))), ""
        result = hub(argv)
        if argv[1] == "api" and argv[2].endswith("/releases") and "POST" in argv:
            created.update(hub.release)
            hub.release = created
        return result

    directory, public, value, _ = prepared
    module().publish(directory, public, release_id=value["release_id"], source_revision=value["source_revision"],
                     gh=transport, apply=True)
    assert created["draft"] is False
    assert replacement["draft"] is True
