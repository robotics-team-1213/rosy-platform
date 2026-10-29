"""Mounted configuration changes must invalidate only their consumer."""

import hashlib
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import yaml

from deploy.site.build_candidate import DEPLOY_FILES, DOC_FILES, build_candidate
from test_site_candidate_verifier import TEST_KEY_ID, candidate


def test_changed_mounted_caddy_config_recreates_proxy_without_image_transfer(candidate, tmp_path):
    repo = tmp_path / "repo"
    source = Path(__file__).resolve().parents[1]
    site = repo / "deploy/site"
    site.mkdir(parents=True)
    for name in (*DEPLOY_FILES, "Dockerfile.fleet", "Dockerfile.vision", "Dockerfile.proxy"):
        shutil.copyfile(source / "deploy/site" / name, site / name)
    for name in DOC_FILES:
        dest = repo / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, dest)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        value = ""
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            value = "b" * 40
        if args[:2] == ["git", "diff"]:
            value = "deploy/site/Caddyfile\0deploy/site/Caddyfile.account\0"
        return SimpleNamespace(stdout=value, returncode=0)
    configs = []
    for index in range(2):
        (site / "Caddyfile").write_text(f"signed proxy config {index}")
        (site / "Caddyfile.account").write_text(f"signed account config {index}")
        out = tmp_path / f"candidate-{index}"
        manifest = build_candidate(repo, out, runner=run, base_candidate=candidate[0],
                                   trusted_key_id=TEST_KEY_ID, trusted_public_key=candidate[3])
        assert len(manifest["reused_images"]) == 4
        docs = [yaml.safe_load((out / "deploy/site" / name).read_text())
                for name in ("compose.yaml", "compose.account.yaml")]
        for config, name in zip(docs, ("Caddyfile", "Caddyfile.account")):
            expected = hashlib.sha256((site / name).read_bytes()).hexdigest()
            assert expected in config["services"]["proxy"]["labels"].values()
        combined = {**docs[0]["services"]["proxy"]["labels"],
                    **docs[1]["services"]["proxy"]["labels"]}
        assert len(combined) == 2  # Account must preserve the base config change signal.
        configs.append(docs)
    assert configs[0][0]["services"]["fleet"] == configs[1][0]["services"]["fleet"]
    assert configs[0][0]["services"]["vision"] == configs[1][0]["services"]["vision"]
    assert configs[0][0]["services"]["proxy"] != configs[1][0]["services"]["proxy"]
    assert configs[0][1]["services"]["proxy"] != configs[1][1]["services"]["proxy"]
    assert not any(c[:2] == ["docker", "build"] or c[:3] == ["docker", "image", "save"] for c in calls)


def test_retaining_one_reused_image_does_not_retain_unreferenced_siblings(tmp_path):
    from deploy.site.rosy_site_autoupdate import SiteUpdater
    from deploy.site.site_update_io import Paths
    paths = Paths(tmp_path)
    rollback = paths.candidates / ("b" * 40)
    rollback.mkdir(parents=True)
    kept = "rosy-site-vision:" + "a" * 40
    obsolete = "rosy-site-fleet:" + "a" * 40
    (rollback / "release.json").write_text(json.dumps({
        "source_commit": "b" * 40, "images": {"vision": {"reference": kept}}}))
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=f"{kept}\n{obsolete}" if args[:3] == ["docker", "image", "ls"] else "",
                               stderr="", returncode=0)
    SiteUpdater({"keep": 1}, paths=paths, runner=run).prune({rollback})
    assert ["docker", "image", "rm", obsolete] in calls
    assert ["docker", "image", "rm", kept] not in calls
