"""Thin site delivery must preserve the signed complete desired state."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace

import pytest

from deploy.site import build_candidate as builder
from deploy.site import verify_candidate as verifier
from test_site_candidate_verifier import (
    COMMIT, TEST_KEY_ID, _image_blobs, _sha, _verify_with, candidate,
)
import test_site_autoupdate as site_tests
from test_site_autoupdate import host

NEW = "b" * 40
ROOT = Path(__file__).resolve().parents[1]


def thin_candidate(candidate, reused=("vision", "proxy", "postgres")):
    root, _, ids, _ = candidate
    manifest = json.loads((root / "release.json").read_text())
    manifest.update(manifest_version=2, base_commit="0" * 40,
                    reused_images={s: [ids[s], _sha(_image_blobs(s)[1])] for s in reused})
    with tarfile.open(root / "images.tar") as archive:
        rows = json.load(archive.extractfile("manifest.json"))
        blobs = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
    blobs["manifest.json"] = json.dumps([
        row for row in rows if not any(f"rosy-site-{s}:{COMMIT}" in row["RepoTags"] for s in reused)
    ]).encode()
    # The config-ID form is sufficient for included images in this classic Docker archive.
    blobs.pop("index.json", None)
    with tarfile.open(root / "images.tar", "w") as archive:
        for name, data in blobs.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    manifest["image_archive_sha256"] = hashlib.sha256((root / "images.tar").read_bytes()).hexdigest()
    (root / "release.json").write_text(json.dumps(manifest))
    return manifest


def test_thin_candidate_verifies_complete_loaded_set_including_reused_oci_identity(candidate):
    manifest = thin_candidate(candidate)
    ids = dict(candidate[2])
    ids["vision"] = manifest["reused_images"]["vision"][1]
    result = _verify_with(candidate, ids)
    assert set(result["verified_images"]) == {"fleet", "vision", "proxy", "postgres"}
    assert result["image_references"]["vision"] == f"rosy-site-vision:{COMMIT}"
    assert result["manifest_version"] == 2
    assert set(result["archive_services"]) == {"fleet"}


def test_missing_or_wrong_reused_image_refuses_candidate_before_switch(candidate):
    thin_candidate(candidate)
    ids = {**candidate[2], "vision": "sha256:" + "0" * 64}
    with pytest.raises(verifier.CandidateVerificationError, match="vision loaded image ID mismatch"):
        _verify_with(candidate, ids)


def test_configuration_only_candidate_has_no_image_payload(candidate):
    thin_candidate(candidate, reused=tuple(candidate[2]))
    result = _verify_with(candidate, candidate[2])
    assert result["archive_services"] == []


@pytest.mark.parametrize("value", [{"unknown": ["sha256:" + "a" * 64]},
                                   {"vision": []}, {"vision": ["untrusted"]}])
def test_invalid_reuse_proof_is_rejected(candidate, value):
    manifest = thin_candidate(candidate)
    manifest["reused_images"] = value
    (candidate[0] / "release.json").write_text(json.dumps(manifest))
    with pytest.raises(verifier.CandidateVerificationError, match="reused"):
        _verify_with(candidate, candidate[2])


@pytest.mark.parametrize("changed,expected", [
    (["applications/fleet/web/app.js"], {"fleet"}),
    (["contracts/foundation/core_common/types.py"], {"fleet", "vision"}),
    (["operations/overhead/rosy_vision/deleted.py"], {"vision"}),
    (["deploy/site/Caddyfile"], set()),
    (["deploy/site/Dockerfile.proxy"], {"proxy"}),
    (["deploy/site/Dockerfile.fleet.dockerignore"], {"fleet"}),
])
def test_builder_only_builds_and_ships_affected_images(candidate, tmp_path, changed, expected):
    repo = tmp_path / "repo"
    site = repo / "deploy/site"
    site.mkdir(parents=True)
    for name in (*builder.DEPLOY_FILES, "Dockerfile.fleet", "Dockerfile.vision", "Dockerfile.proxy"):
        shutil.copyfile(ROOT / "deploy/site" / name, site / name)
    for name in builder.DOC_FILES:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=NEW, returncode=0)
        if args[:2] == ["git", "diff"]:
            return SimpleNamespace(stdout="\0".join(changed) + "\0", returncode=0)
        if args[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout="sha256:" + "c" * 64 + "|linux|amd64", returncode=0)
        if args[1:3] == ["scout", "sbom"]:
            Path(args[args.index("--output") + 1]).write_text("new sbom")
        if args[1:3] == ["image", "save"]:
            Path(args[args.index("--output") + 1]).write_bytes(b"changed image archive")
        return SimpleNamespace(stdout="", returncode=0)

    output = tmp_path / "thin"
    manifest = builder.build_candidate(repo, output, runner=run, base_candidate=candidate[0],
                                       trusted_key_id=TEST_KEY_ID, trusted_public_key=candidate[3])
    built = {Path(c[c.index("--file") + 1]).suffix.removeprefix(".")
             for c in calls if c[:2] == ["docker", "build"]}
    assert built == expected
    assert manifest["manifest_version"] == 2
    assert set(manifest["reused_images"]) == set(candidate[2]) - expected
    saves = [c for c in calls if c[:3] == ["docker", "image", "save"]]
    assert bool(saves) == bool(expected)
    if saves:
        assert set(saves[0][5:]) == {f"rosy-site-{s}:{NEW}" for s in expected}
    assert not any(c[:2] == ["docker", "pull"] for c in calls)
    compose = (output / "deploy/site/compose.yaml").read_text()
    for s in set(candidate[2]) - expected:
        assert f"rosy-site-{s}:{COMMIT}" in compose


def test_runtime_reconciles_incremental_stack_without_down_or_restart(tmp_path):
    from deploy.site.rosy_site_autoupdate import SiteUpdater
    from deploy.site.site_update_io import Paths
    paths = Paths(tmp_path)
    paths.site_env.parent.mkdir(parents=True)
    paths.site_env.write_text(f"ROSY_SITE_IMAGE_TAG={NEW}\n")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    updater = SiteUpdater({}, paths=paths, runner=run)
    updater._incremental_commits = {NEW}
    updater._restart()
    assert not any(c[:2] == ["systemctl", "restart"] or "down" in c for c in calls)
    preflight = next(i for i, c in enumerate(calls) if "--verify-certs" in c)
    reconcile = next(i for i, c in enumerate(calls) if c[:2] == ["docker", "compose"] and "up" in c)
    assert preflight < reconcile
    assert "--no-build" in calls[reconcile] and "--force-recreate" not in calls[reconcile]


def test_signed_reused_reference_is_allowed_but_env_override_is_refused():
    from deploy.site.site_update_io import Refused, check_overrides
    refs = {s: f"rosy-site-{s}:{COMMIT}" for s in ("fleet", "vision", "proxy", "postgres")}
    run = lambda *a, **kw: SimpleNamespace(stdout="")
    def compose(env, *args, **kwargs):
        return SimpleNamespace(stdout=json.dumps({"services": {s: {"image": ref} for s, ref in refs.items()}}))
    check_overrides({}, NEW, run, compose, image_references=dict(refs))
    expected = dict(refs)
    refs["vision"] = "unapproved:latest"
    with pytest.raises(Refused, match="image override"):
        check_overrides({}, NEW, run, compose, image_references=expected)


def test_prune_protects_reused_image_in_retained_nonrunning_rollback(tmp_path):
    from deploy.site.rosy_site_autoupdate import SiteUpdater
    from deploy.site.site_update_io import Paths
    paths = Paths(tmp_path)
    rollback = paths.candidates / NEW
    rollback.mkdir(parents=True)
    ref = f"rosy-site-vision:{COMMIT}"
    (rollback / "release.json").write_text(json.dumps({
        "source_commit": NEW, "images": {"vision": {"reference": ref}}}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=ref if args[:3] == ["docker", "image", "ls"] else "",
                               stderr="", returncode=0)
    updater = SiteUpdater({"keep": 1}, paths=paths, runner=run)
    updater.prune({rollback})
    assert not any(c[:3] == ["docker", "image", "rm"] for c in calls)


@pytest.mark.parametrize("healthy", [True, False])
def test_incremental_switch_and_v1_rollback_keep_the_existing_journal_gates(host, healthy):
    st = site_tests
    releases, blobs = st._world((st.NEW, "2026-10-29"))
    fake = st.FakeHost(host.paths, healthy_tags=None if healthy else {st.OLD})
    def run(args, **kwargs):
        if args[:2] == ["systemctl", "is-active"] or "--verify-certs" in args:
            fake.calls.append(args)
            return fake._ok()
        if args[:2] == ["docker", "compose"] and "up" in args:
            fake.calls.append(args)
            fake.running = st.upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"]
            return fake._ok()
        return fake(args, **kwargs)
    updater = st._updater(host, st.FakeHttp(releases, blobs), run)
    verify = updater.verifier
    def proof(folder, **kwargs):
        result = verify(folder, **kwargs)
        if result["source_commit"] == st.NEW:
            result.update(manifest_version=2, archive_services=[])
        return result
    updater.verifier = proof
    assert updater.run() == (st.upd.EXIT_OK if healthy else st.upd.EXIT_FAILED)
    assert not any(c[:3] == ["docker", "image", "load"] for c in fake.calls)
    assert not any("down" in c for c in fake.calls)
    assert fake.running == (st.NEW if healthy else st.OLD)
    state = updater.load_state()
    assert "switch" not in state
    assert state["last_run"]["result"] == ("installed" if healthy else "rolled-back")
