from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site.build_candidate import DOC_FILES, DEPLOY_FILES, build_candidate
from deploy.site.verify_candidate import REQUIRED_DEPLOYMENT_FILES, REQUIRED_DOCUMENT_FILES

COMMIT = "9541086c550c0c1142f7aefecc903987e149f9e2"


def test_site_candidate_is_commit_tagged_and_contains_sbom_and_image_hash(tmp_path):
    root = tmp_path / "repo"
    output = tmp_path / "release"
    site = root / "deploy" / "site"
    site.mkdir(parents=True)
    profile = root / "docs/reference/site-lan-discovery-profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("discovery profile fixture", encoding="utf-8")
    for name in ("compose.yaml", "Caddyfile", "README.md",
                 "robots.yaml.example", "site-cameras.yaml.example", "site-users.yaml.example",
                 "mdns-bridge.py", "rosy-mdns-bridge.service", "rosy-mdns-bridge.timer",
                 "fleet-mdns.py", "rosy-fleet-advertise.service",
                 "rosy-overhead-advertise.service",
                 "rosy-site-stack.service",
                 "site-firewall.py", "rosy-site-firewall.service", "rosy-site-firewall-failclosed.service",
                 "rosy-site-firewall-check.service", "rosy-site-firewall-check.timer",
                 "candidate_signing.py", "sign_candidate.py",
                 "verify_candidate.py",
                 "discovery-token.template.txt", "site_db.py",
                 "compose.pairing.yaml", "pairing-sync-token.template.txt"):
        (site / name).write_text(f"fixture:{name}", encoding="utf-8")
    (site / "rosy-site-stack.service").write_text(
        "Requires=docker.service\n"
        "After=docker.service network-online.target\n"
        "WantedBy=multi-user.target\n"
        "ExecStart=/usr/bin/docker compose --project-name rosy-site "
        "--env-file /etc/rosy/site/site.env -f "
        "/opt/rosy/candidate/deploy/site/compose.yaml up -d --no-build\n"
        "ExecStop=/usr/bin/docker compose --project-name rosy-site "
        "--env-file /etc/rosy/site/site.env -f "
        "/opt/rosy/candidate/deploy/site/compose.yaml down\n",
        encoding="utf-8")
    (site / ".env.example").write_text("ROSY_SITE_IMAGE_TAG=local\n", encoding="utf-8")
    (site / "Dockerfile.fleet").write_text("FROM ubuntu", encoding="utf-8")
    (site / "Dockerfile.vision").write_text("FROM ubuntu", encoding="utf-8")
    (site / "Dockerfile.proxy").write_text("FROM caddy", encoding="utf-8")

    def runner(args, **kwargs):
        if args[:2] == ["git", "status"]:
            return SimpleNamespace(stdout="")
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{COMMIT}\n")
        if args[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout="sha256:" + "a" * 64 + "|linux|amd64\n")
        if args[1:3] == ["scout", "sbom"]:
            sbom_path = Path(args[args.index("--output") + 1])
            sbom_path.write_text("spdx fixture", encoding="utf-8")
            return SimpleNamespace(stdout="")
        if args[1:3] == ["image", "save"]:
            Path(args[args.index("--output") + 1]).write_bytes(b"docker-save-fixture")
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="")

    manifest = build_candidate(
        root, output, runner=runner,
        clock=lambda: datetime(2026, 9, 27, tzinfo=timezone.utc),
    )

    assert manifest["source_commit"] == COMMIT
    assert manifest["image_tag"] == COMMIT
    assert manifest["platform"] == "linux/amd64"
    assert len(manifest["images"]) == 3
    assert all(item["image_id"].startswith("sha256:") for item in manifest["images"].values())
    assert all(item["sbom_sha256"] for item in manifest["images"].values())
    assert manifest["image_archive_sha256"]
    assert (output / "release.json").is_file()
    assert (output / "images.tar").is_file()
    assert (output / "deploy" / "site" / "compose.yaml").is_file()
    assert (output / "deploy" / "site" / "compose.yaml").read_text(encoding="utf-8") == \
        "fixture:compose.yaml"
    assert f"ROSY_SITE_IMAGE_TAG={COMMIT}" in (output / "deploy" / "site" / ".env.example").read_text(
        encoding="utf-8")
    assert (output / "sbom" / "fleet.spdx").read_text(encoding="utf-8") == "spdx fixture"
    assert (output / "docs/reference/site-lan-discovery-profile.md").read_text(
        encoding="utf-8") == "discovery profile fixture"
    assert "docs/reference/site-lan-discovery-profile.md" in manifest["deployment_file_sha256"]
    packaged_names = {path.name for path in (output / "deploy" / "site").iterdir()}
    assert packaged_names == {
        "compose.yaml", "Caddyfile", ".env.example", "README.md",
        "robots.yaml.example", "site-cameras.yaml.example",
        "site-users.yaml.example", "mdns-bridge.py", "rosy-mdns-bridge.service",
        "rosy-mdns-bridge.timer", "fleet-mdns.py", "rosy-fleet-advertise.service",
        "rosy-overhead-advertise.service",
        "rosy-site-stack.service",
        "site-firewall.py", "rosy-site-firewall.service", "rosy-site-firewall-failclosed.service",
        "rosy-site-firewall-check.service", "rosy-site-firewall-check.timer",
        "verify_candidate.py",
        "candidate_signing.py", "sign_candidate.py",
        "discovery-token.template.txt", "site_db.py",
                 "compose.pairing.yaml", "pairing-sync-token.template.txt",
    }
    stack_unit = (output / "deploy" / "site" / "rosy-site-stack.service").read_text(
        encoding="utf-8")
    assert "Requires=docker.service" in stack_unit
    assert "After=docker.service network-online.target" in stack_unit
    assert "WantedBy=multi-user.target" in stack_unit
    assert "--project-name rosy-site" in stack_unit
    assert "up -d --no-build" in stack_unit
    assert " down\n" in stack_unit
    assert "--volumes" not in stack_unit
    assert not list(output.rglob("*.key"))


def test_site_candidate_refuses_dirty_source_and_existing_output(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "release"

    def dirty_runner(args, **kwargs):
        if args[:2] == ["git", "status"]:
            return SimpleNamespace(stdout=" M tracked.py\n")
        return SimpleNamespace(stdout=f"{COMMIT}\n")

    with pytest.raises(ValueError, match="clean Git worktree"):
        build_candidate(root, output, runner=dirty_runner)
    assert not output.exists()

    output.mkdir()
    (output / "keep.txt").write_text("operator data", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        build_candidate(root, output, runner=dirty_runner)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "operator data"


def test_site_candidate_refuses_non_amd64_images_and_output_inside_checkout(tmp_path):
    root = tmp_path / "repo"
    site = root / "deploy" / "site"
    site.mkdir(parents=True)
    profile = root / "docs/reference/site-lan-discovery-profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("discovery profile fixture", encoding="utf-8")
    for name in ("compose.yaml", "Caddyfile", ".env.example", "README.md",
                 "robots.yaml.example", "site-cameras.yaml.example", "site-users.yaml.example",
                 "mdns-bridge.py", "rosy-mdns-bridge.service", "rosy-mdns-bridge.timer",
                 "fleet-mdns.py", "rosy-fleet-advertise.service",
                 "rosy-overhead-advertise.service",
                 "site-firewall.py", "rosy-site-firewall.service", "rosy-site-firewall-failclosed.service",
                 "rosy-site-firewall-check.service", "rosy-site-firewall-check.timer",
                 "candidate_signing.py", "sign_candidate.py", "verify_candidate.py",
                 "discovery-token.template.txt", "site_db.py",
                 "compose.pairing.yaml", "pairing-sync-token.template.txt",
                 "Dockerfile.fleet", "Dockerfile.vision", "Dockerfile.proxy"):
        (site / name).write_text("fixture", encoding="utf-8")
    (site / "rosy-site-stack.service").write_text("fixture", encoding="utf-8")

    def wrong_arch_runner(args, **kwargs):
        if args[:2] == ["git", "status"]:
            return SimpleNamespace(stdout="")
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=f"{COMMIT}\n")
        if args[1:3] == ["image", "inspect"]:
            return SimpleNamespace(stdout="sha256:" + "b" * 64 + "|linux|arm64\n")
        return SimpleNamespace(stdout="")

    with pytest.raises(ValueError, match="outside the source checkout"):
        build_candidate(root, root / "candidate", runner=wrong_arch_runner)
    with pytest.raises(RuntimeError, match="expected linux/amd64"):
        build_candidate(root, tmp_path / "release", runner=wrong_arch_runner)
    assert not (tmp_path / "release" / "release.json").exists()


def test_candidate_builder_and_host_verifier_share_required_bundle_inventory():
    assert set(DEPLOY_FILES) | {"verify_candidate.py"} == set(REQUIRED_DEPLOYMENT_FILES)
    assert set(DOC_FILES) == set(REQUIRED_DOCUMENT_FILES)


def test_host_runbook_verifies_site_signature_before_docker_load():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "deploy/site/README.md").read_text(encoding="utf-8")
    adr = (root / "docs/adr/D-301-site-candidate-signatures.md").read_text(encoding="utf-8")
    adr_log = (root / "docs/reference/ROSY ADR Log.md").read_text(encoding="utf-8")

    signature_check = readme.index("--signature-only")
    docker_load = readme.index("docker image load --input images.tar")
    full_check = readme.index("python3 /usr/local/lib/rosy-site/verify_candidate.py", docker_load)
    assert signature_check < docker_load < full_check
    assert "Do not run the verifier copied from the candidate" in readme
    assert "/etc/rosy/site/trust/site-release-ed25519.pub.pem" in readme
    assert "separate from the Pinky runtime release key" in adr
    assert "| D-301 |" in adr_log
