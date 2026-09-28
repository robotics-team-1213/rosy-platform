"""Prepare a native Linux/ARM64 ROSY release payload without signing it."""

from __future__ import annotations

import re
import json
import hashlib
import os
import argparse
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from manifest import validate_manifest


_REVISION = re.compile(r"^[0-9a-f]{40}$")
_PINNED_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
_KEY_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class BuildError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class BuildRequest:
    repo_root: Path
    output: Path
    release_id: str
    signing_key_id: str
    ros_image: str
    os_suite: str = "trixie"


@dataclass(frozen=True)
class ValidatedBuild:
    request: BuildRequest
    revision: str


@dataclass(frozen=True)
class BuiltImage:
    name: str
    tag: str
    image_id: str
    os: str
    architecture: str
    revision: str


def validate_request(
    request: BuildRequest, *, machine: str, system: str, revision: str, status: str
) -> ValidatedBuild:
    if system != "Linux":
        raise BuildError("BUILD_HOST_OS", f"native Linux required, got {system!r}")
    if machine != "aarch64":
        raise BuildError("BUILD_HOST_ARCH", f"native aarch64 required, got {machine!r}")
    if status.strip():
        raise BuildError("SOURCE_DIRTY", "release source worktree must be clean")
    if not _REVISION.fullmatch(revision):
        raise BuildError("SOURCE_REVISION", "a full lowercase 40-hex Git revision is required")
    if not _PINNED_IMAGE.fullmatch(request.ros_image):
        raise BuildError("ROS_IMAGE_PIN", "ROS base image must use name@sha256:<64-hex>")
    if not _RELEASE_ID.fullmatch(request.release_id):
        raise BuildError("RELEASE_ID", "release ID must be YYYY.MM.DD-NNN")
    if not _KEY_ID.fullmatch(request.signing_key_id):
        raise BuildError("SIGNING_KEY_ID", "signing key ID is malformed")
    if request.os_suite not in {"bookworm", "trixie"}:
        raise BuildError("OS_SUITE", "device updater supports only bookworm or trixie")

    repo_root = request.repo_root.resolve()
    output = request.output.resolve()
    if request.output.exists():
        raise BuildError("OUTPUT_EXISTS", f"refusing to replace {request.output}")
    if output == repo_root or repo_root in output.parents:
        raise BuildError("OUTPUT_LOCATION", "release payload must be outside the source checkout")
    return ValidatedBuild(request=request, revision=revision)


def validate_build_daemon(architecture: str) -> None:
    if architecture.strip().lower() not in {"aarch64", "arm64"}:
        raise BuildError(
            "BUILD_DAEMON_ARCH",
            f"native ARM64 Docker daemon required, got {architecture.strip()!r}",
        )


def _command(runner: Callable, argv: list[str], *, cwd: Path):
    result = runner(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise BuildError(
            "BUILD_COMMAND",
            f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed with exit {result.returncode}",
        )
    return result


def _inspect_image(raw: str, *, name: str, tag: str, revision: str) -> BuiltImage:
    try:
        decoded = json.loads(raw)
        image = decoded[0]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise BuildError("IMAGE_INSPECT", f"Docker returned invalid metadata for {name}") from exc
    if image.get("Os") != "linux":
        raise BuildError("IMAGE_OS", f"{name} is not a Linux image")
    if image.get("Architecture") != "arm64":
        raise BuildError("IMAGE_ARCH", f"{name} is not an ARM64 image")
    image_id = image.get("Id")
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        raise BuildError("IMAGE_ID", f"{name} has no immutable Docker image ID")
    labels = image.get("Config", {}).get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != revision:
        raise BuildError("IMAGE_REVISION", f"{name} does not identify the source revision")
    return BuiltImage(
        name=name,
        tag=tag,
        image_id=image_id,
        os=image["Os"],
        architecture=image["Architecture"],
        revision=revision,
    )


def build_images(
    selected: ValidatedBuild, *, runner: Callable = subprocess.run
) -> dict[str, BuiltImage]:
    request = selected.request
    repo = request.repo_root.resolve()
    result: dict[str, BuiltImage] = {}
    for name, target in (("rosy_core", "core"), ("rosy_io", "io")):
        tag = f"local/{name.replace('_', '-')}:{request.release_id}-{selected.revision[:12]}"
        build = [
            "docker", "buildx", "build",
            "--platform", "linux/arm64",
            "--load",
            "--target", target,
            "--build-arg", f"ROS_IMAGE={request.ros_image}",
            "--label", f"org.opencontainers.image.revision={selected.revision}",
            "--label", f"org.opencontainers.image.version={request.release_id}",
            "--tag", tag,
            "--file", "deploy/robot/pinky_pro/Dockerfile",
            ".",
        ]
        _command(runner, build, cwd=repo)
        inspected = _command(
            runner, ["docker", "image", "inspect", tag], cwd=repo
        )
        result[name] = _inspect_image(
            inspected.stdout,
            name=name,
            tag=tag,
            revision=selected.revision,
        )
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_runtime(repo: Path, destination: Path) -> None:
    source = repo / "deploy" / "robot" / "pinky_pro"
    compose = source / "compose.yaml"
    config = source / "config"
    if not compose.is_file() or not config.is_dir():
        raise BuildError("RUNTIME_SOURCE", "deploy/robot/pinky_pro compose or config tree is missing")
    candidates = [compose, *config.rglob("*")]
    if any(path.is_symlink() for path in candidates):
        raise BuildError("RUNTIME_SYMLINK", "runtime payload source must not contain symlinks")
    destination.mkdir(parents=True)
    shutil.copy2(compose, destination / "compose.yaml")
    shutil.copytree(config, destination / "config")


def assemble_payload(
    selected: ValidatedBuild,
    images: dict[str, BuiltImage],
    *,
    runner: Callable = subprocess.run,
    created_at: str,
    docker_version: str,
) -> Path:
    request = selected.request
    output = request.output.resolve()
    if output.exists():
        raise BuildError("OUTPUT_EXISTS", f"refusing to replace {output}")
    for key in ("rosy_core", "rosy_io"):
        image = images.get(key)
        if image is None or image.name != key:
            raise BuildError("IMAGE_MISSING", f"{key} was not built")
        if image.os != "linux":
            raise BuildError("IMAGE_OS", f"{key} is not a Linux image")
        if image.architecture != "arm64":
            raise BuildError("IMAGE_ARCH", f"{key} is not an ARM64 image")
        if image.revision != selected.revision:
            raise BuildError("IMAGE_REVISION", f"{key} does not identify the source revision")
        if not _IMAGE_ID.fullmatch(image.image_id):
            raise BuildError("IMAGE_ID", f"{key} has no immutable Docker image ID")
    if images["rosy_core"].image_id == images["rosy_io"].image_id:
        raise BuildError("IMAGE_COLLISION", "core and io must be distinct image artifacts")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _copy_runtime(request.repo_root.resolve(), staging / "runtime")
        image_dir = staging / "images"
        image_dir.mkdir()
        for key, filename in (
            ("rosy_core", "rosy-core.oci.tar"),
            ("rosy_io", "rosy-io.oci.tar"),
        ):
            if key not in images:
                raise BuildError("IMAGE_MISSING", f"{key} was not built")
            _command(
                runner,
                [
                    "docker", "image", "save",
                    "--output", str(image_dir / filename),
                    images[key].image_id,
                ],
                cwd=request.repo_root.resolve(),
            )
            if not (image_dir / filename).is_file():
                raise BuildError("IMAGE_ARCHIVE", f"Docker did not create {filename}")

        provenance = {
            "schema_version": 1,
            "release_id": request.release_id,
            "source_revision": selected.revision,
            "created_at": created_at,
            "build_architecture": "arm64",
            "docker_version": docker_version,
            "ros_base_image": request.ros_image,
            "images": {
                key: {"tag": image.tag, "image_id": image.image_id}
                for key, image in sorted(images.items())
            },
        }
        (staging / "build-provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        files = [
            {
                "path": path.relative_to(staging).as_posix(),
                "sha256": _sha256(path),
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "schema_version": 1,
            "release_id": request.release_id,
            "git_revision": selected.revision,
            "created_at": created_at,
            "target": {
                "board": "raspberry-pi-5",
                "architecture": "arm64",
                "os_family": "raspberry-pi-os-lite",
                "os_suite": request.os_suite,
            },
            "runtime": {
                "config_schema": 1,
                "data_schema": 1,
                "minimum_bootloader": None,
            },
            "containers": {
                "rosy_core": images["rosy_core"].image_id,
                "rosy_io": images["rosy_io"].image_id,
            },
            "defaults": {"runtime_mode": "core"},
            "signing_key_id": request.signing_key_id,
            "requires_recommissioning": True,
            "files": files,
        }
        rejected = validate_manifest(manifest)
        if rejected:
            raise BuildError("MANIFEST", str(rejected[0]))
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output)
        return output
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(
    argv: list[str] | None = None,
    *,
    machine: str | None = None,
    system: str | None = None,
    runner: Callable = subprocess.run,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--ros-image", required=True,
                        help="digest-pinned base, for example name@sha256:<64-hex>")
    parser.add_argument("--os-suite", default="trixie")
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    try:
        revision = _command(
            runner, ["git", "rev-parse", "HEAD"], cwd=repo
        ).stdout.strip()
        status = _command(
            runner, ["git", "status", "--porcelain"], cwd=repo
        ).stdout
        request = BuildRequest(
            repo_root=repo,
            output=args.output,
            release_id=args.release_id,
            signing_key_id=args.signing_key_id,
            ros_image=args.ros_image,
            os_suite=args.os_suite,
        )
        selected = validate_request(
            request,
            machine=machine or platform.machine(),
            system=system or platform.system(),
            revision=revision,
            status=status,
        )
        docker_version = _command(
            runner,
            ["docker", "version", "--format", "{{.Server.Version}}"],
            cwd=repo,
        ).stdout.strip()
        daemon_architecture = _command(
            runner,
            ["docker", "info", "--format", "{{.Architecture}}"],
            cwd=repo,
        ).stdout.strip()
        validate_build_daemon(daemon_architecture)
        images = build_images(selected, runner=runner)
        instant = clock() if clock else datetime.now(timezone.utc)
        created_at = instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        output = assemble_payload(
            selected,
            images,
            runner=runner,
            created_at=created_at,
            docker_version=docker_version,
        )
    except BuildError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail}))
        return 1

    print(json.dumps({
        "ok": True,
        "output": str(output),
        "release_id": request.release_id,
        "git_revision": selected.revision,
        "signed": False,
    }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
