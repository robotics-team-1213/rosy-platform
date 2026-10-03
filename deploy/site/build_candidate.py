"""Build a commit-pinned, SBOM-bearing Ubuntu site Fleet delivery candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_FILES = (
    "compose.yaml", "Caddyfile", ".env.example", "README.md",
    "robots.yaml.example", "site-cameras.yaml.example", "site-users.yaml.example",
    "mdns-bridge.py", "rosy-mdns-bridge.service", "rosy-mdns-bridge.timer",
    "fleet-mdns.py", "rosy-fleet-advertise.service", "rosy-overhead-advertise.service",
    "rosy-site-stack.service", "site-firewall.py", "rosy-site-firewall.service",
    "rosy-site-firewall-failclosed.service", "rosy-site-firewall-check.service",
    "rosy-site-firewall-check.timer",
    "discovery-token.template.txt", "site_db.py", "candidate_signing.py",
    "compose.pairing.yaml", "pairing-sync-token.template.txt",
    "sign_candidate.py", "verify_candidate.py",
)
DOC_FILES = ("docs/reference/site-lan-discovery-profile.md",)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
SBOM_TOOLS = ("scout", "syft")
# deploy/site is the proxy image build context, so ignored files there reach
# the Docker daemon. Python caches from local test runs carry no secrets.
_HARMLESS_IGNORED = ("__pycache__/", ".pytest_cache/")
Runner = Callable[..., subprocess.CompletedProcess]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_output(root: Path, output_dir: Path) -> Path:
    root = root.resolve()
    output = output_dir.resolve()
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ValueError("candidate output must be outside the source checkout")
    if output.exists() and any(output.iterdir()):
        raise ValueError("candidate output directory must be empty")
    return output


def _sbom_command(tool: str, reference: str, sbom_path: Path) -> list[str]:
    # Both tools write SPDX JSON to the same sbom/<service>.spdx path, so the
    # manifest and the host verifier do not depend on which one ran (D-437).
    if tool == "scout":
        return ["docker", "scout", "sbom", "--format", "spdx", "--output",
                str(sbom_path), f"local://{reference}"]
    if tool == "syft":
        return ["syft", "scan", f"docker:{reference}", "--output",
                f"spdx-json={sbom_path}"]
    raise ValueError(f"unsupported SBOM tool: {tool}")


def build_candidate(root: Path, output_dir: Path, *, runner: Runner = subprocess.run,
                    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                    sbom_tool: str = "scout") -> dict:
    if sbom_tool not in SBOM_TOOLS:
        raise ValueError(f"unsupported SBOM tool: {sbom_tool}")
    root = root.resolve()
    site = root / "deploy" / "site"
    output = _candidate_output(root, output_dir)
    status = runner(["git", "status", "--porcelain", "--untracked-files=all"],
                    cwd=root, check=True, capture_output=True, text=True).stdout
    if status.strip():
        raise ValueError("a clean Git worktree is required to build a candidate")
    ignored = runner(["git", "ls-files", "--others", "--ignored", "--exclude-standard",
                      "--directory", "--", "deploy/site"],
                     cwd=root, check=True, capture_output=True, text=True).stdout
    unsafe = [line for line in ignored.splitlines()
              if line.strip() and not line.endswith(_HARMLESS_IGNORED)]
    if unsafe:
        raise ValueError("ignored files under deploy/site (real secrets or config?) would "
                         "enter the image build context; move them out first: "
                         + ", ".join(sorted(unsafe)))
    commit = runner(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                    capture_output=True, text=True).stdout.strip()
    if not _COMMIT.fullmatch(commit):
        raise ValueError("git HEAD must be a full 40-character commit")

    tag = commit
    output.mkdir(parents=True, exist_ok=True)
    deploy_dir = output / "deploy" / "site"
    sbom_dir = output / "sbom"
    deploy_dir.mkdir(parents=True)
    sbom_dir.mkdir(parents=True)

    for name in DEPLOY_FILES:
        source = site / name
        target = deploy_dir / name
        shutil.copyfile(source, target)
    for name in DOC_FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    env_path = deploy_dir / ".env.example"
    env_text = env_path.read_text(encoding="utf-8")
    env_path.write_text(env_text.replace("ROSY_SITE_IMAGE_TAG=local",
                                         f"ROSY_SITE_IMAGE_TAG={tag}"),
                        encoding="utf-8")

    images: dict[str, dict[str, str]] = {}
    references: list[str] = []
    services = {
        "fleet": (site / "Dockerfile.fleet", root),
        "vision": (site / "Dockerfile.vision", root),
        "proxy": (site / "Dockerfile.proxy", site),
    }
    for service, (dockerfile, context) in services.items():
        reference = f"rosy-site-{service}:{tag}"
        runner(["docker", "build", "--pull", "--platform", "linux/amd64",
                "--tag", reference, "--file", str(dockerfile), str(context)],
               cwd=root, check=True)
        inspect = runner(["docker", "image", "inspect", "--format",
                          "{{.Id}}|{{.Os}}|{{.Architecture}}", reference],
                         cwd=root, check=True, capture_output=True, text=True).stdout.strip()
        parts = inspect.split("|")
        if len(parts) != 3 or not parts[0].startswith("sha256:"):
            raise RuntimeError(f"Docker returned invalid image identity for {service}")
        image_id, image_os, architecture = parts
        if (image_os, architecture) != ("linux", "amd64"):
            raise RuntimeError(f"{service} image is {image_os}/{architecture}, expected linux/amd64")

        sbom_path = sbom_dir / f"{service}.spdx"
        runner(_sbom_command(sbom_tool, reference, sbom_path), cwd=root, check=True)
        if not sbom_path.is_file() or sbom_path.stat().st_size == 0:
            raise RuntimeError(f"{sbom_tool} did not produce the {service} SBOM")
        images[service] = {
            "reference": reference,
            "image_id": image_id,
            "platform": "linux/amd64",
            "sbom": str(sbom_path.relative_to(output)).replace("\\", "/"),
            "sbom_sha256": _sha256(sbom_path),
        }
        references.append(reference)

    archive = output / "images.tar"
    runner(["docker", "image", "save", "--output", str(archive), *references],
           cwd=root, check=True)
    if not archive.is_file() or archive.stat().st_size == 0:
        raise RuntimeError("Docker did not produce a non-empty image archive")

    config_hashes = {
        name: _sha256(deploy_dir / name)
        for name in DEPLOY_FILES
    }
    config_hashes.update({name: _sha256(output / name) for name in DOC_FILES})
    manifest = {
        "manifest_version": 1,
        "source_commit": commit,
        "image_tag": tag,
        "platform": "linux/amd64",
        "created_at": clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
        "images": images,
        "image_archive": "images.tar",
        "image_archive_sha256": _sha256(archive),
        "deployment_file_sha256": config_hashes,
        "deployment_command": "docker compose --env-file <private-site-env> "
                              "-f deploy/site/compose.yaml up -d --no-build",
    }
    (output / "release.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="empty destination outside the source checkout")
    parser.add_argument("--sbom-tool", choices=SBOM_TOOLS, default="scout",
                        help="SPDX JSON SBOM generator: Docker Scout (local default) "
                             "or anchore syft (CI runners, no Docker Hub login)")
    args = parser.parse_args(argv)
    try:
        manifest = build_candidate(ROOT, args.output_dir, sbom_tool=args.sbom_tool)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(f"site candidate: {manifest['source_commit']} -> {args.output_dir.resolve()}")
    print(f"image archive SHA-256: {manifest['image_archive_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
