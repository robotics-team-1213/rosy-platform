#!/usr/bin/env python3
"""Bench-only CORE overlay. D-179.

Stages an allowlisted Python tree under /var/lib/rosy-dev and describes the
read-only bind that makes the running core load those bytes. It does not
reinstall /opt/rosy, rebuild images, or change the product unit file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


class OverlayError(ValueError):
    """The overlay request would leave the bench or the release boundary."""


PACKAGES = ("core", "core_common", "core_events", "core_features", "core_api_web")
SHARE_FILES = ("tokens.css", "core_ui_logic.js")
MARKER_FIELDS = ("schema_version", "backend", "git_revision", "dirty", "synced_at", "packages")
INSTALL_ROOTS = ("/opt/rosy_ws/install", "/opt/rosy/current/install")
DEV_ROOT = "/var/lib/rosy-dev"
COMPOSE_FILE = "/opt/rosy/deploy/robot/compose.yaml"
DEV_COMPOSE = f"{DEV_ROOT}/compose.dev.yaml"
ENV_FILE = "/opt/rosy/deploy/robot/.env"
PROJECT = "rosy-runtime"
REBOOT_NOTE = (
    "재부팅과 rosy-runtime 재시작은 이미지 코드로 돌아가고 마커 HOLD가 남으니, "
    "같은 동기화를 다시 실행한다."
)
_SENSITIVE_FIELD = re.compile(r"token|password|secret|psk|authorization", re.IGNORECASE)
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _posix(name: str) -> PurePosixPath:
    if not name or name.startswith("/") or "\\" in name or re.match(r"^[A-Za-z]:", name):
        raise OverlayError(f"archive member is absolute: {name}")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise OverlayError(f"archive member escapes: {name}")
    return path


def member_allowed(name: str) -> bool:
    """True when a tar member is one of the D-179 allowlisted files."""

    path = _posix(name)
    parts = path.parts
    if any(part == "__pycache__" or part.endswith(".pyc") for part in parts):
        raise OverlayError(f"bytecode is not an overlay member: {name}")
    if any(part in {".env", "rosy.yaml"} or part.endswith(".srv") for part in parts):
        raise OverlayError(f"member is outside the overlay allowlist: {name}")
    if "interfaces" in parts:
        raise OverlayError(f"message definitions are outside the overlay: {name}")
    if len(parts) >= 2 and parts[0] == "python" and parts[1] in PACKAGES and len(parts) > 2:
        return True
    if parts == ("share", "web_common", "tokens.css") or parts == ("share", "web_common", "core_ui_logic.js"):
        return True
    raise OverlayError(f"member is outside the overlay allowlist: {name}")


def _is_opt_rosy(path: Path) -> bool:
    posix = path.as_posix().rstrip("/")
    return posix == "/opt/rosy" or posix.startswith("/opt/rosy/")


def stage_overlay(archive_path: Path, dest: Path) -> list[str]:
    """Extract an allowlisted tar under dest. A bad member writes nothing."""

    if dest.name != "rosy-dev" or _is_opt_rosy(dest):
        raise OverlayError("overlay destination must be the rosy-dev directory outside /opt/rosy")
    with tarfile.open(archive_path, "r:*") as tar:
        members = [member for member in tar.getmembers() if member.name not in {"", "."}]
        files = []
        for member in members:
            if member.issym() or member.islnk():
                raise OverlayError(f"archive member is a link: {member.name}")
            if member.isdir():
                member_allowed(member.name.rstrip("/") + "/keep")
                continue
            if not member.isfile():
                raise OverlayError(f"archive member is not a regular file: {member.name}")
            member_allowed(member.name)
            files.append(member)
        written: list[str] = []
        dest.mkdir(parents=True, exist_ok=True)
        for member in files:
            relative = _posix(member.name)
            target = dest.joinpath(*relative.parts)
            if dest.resolve() not in target.resolve().parents:
                raise OverlayError(f"archive member escapes: {member.name}")
            stream = tar.extractfile(member)
            if stream is None:
                raise OverlayError(f"archive member is unreadable: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.read())
            written.append(relative.as_posix())
    if not written:
        raise OverlayError("overlay archive has no files")
    return written


def validate_marker(document: dict) -> dict:
    if not isinstance(document, dict) or set(document) != set(MARKER_FIELDS):
        raise OverlayError("marker fields must be exactly the schema 1 set")
    for key in document:
        if _SENSITIVE_FIELD.search(key):
            raise OverlayError("marker must not carry a secret field")
    if document["schema_version"] != 1:
        raise OverlayError("marker schema_version must be 1")
    if document["backend"] not in {"docker", "native"}:
        raise OverlayError("marker backend must be docker or native")
    revision = document["git_revision"]
    if revision != "uncommitted" and not (isinstance(revision, str) and _REVISION.fullmatch(revision)):
        raise OverlayError("marker git_revision must be uncommitted or a commit id")
    if not isinstance(document["dirty"], bool):
        raise OverlayError("marker dirty must be a boolean")
    if not isinstance(document["synced_at"], str) or "T" not in document["synced_at"]:
        raise OverlayError("marker synced_at must be an ISO timestamp")
    if document["packages"] != list(PACKAGES) + ["web_common/tokens.css", "web_common/core_ui_logic.js"]:
        raise OverlayError("marker packages must be the fixed allowlist")
    return document


def build_marker(*, backend: str, git_revision: str, dirty: bool, synced_at: str | None = None) -> dict:
    document = {
        "schema_version": 1,
        "backend": backend,
        "git_revision": git_revision,
        "dirty": dirty,
        "synced_at": synced_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "packages": list(PACKAGES) + ["web_common/tokens.css", "web_common/core_ui_logic.js"],
    }
    return validate_marker(document)


def write_marker(path: Path, document: dict) -> None:
    clean = validate_marker(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _install_root(core_package_dir: str) -> str:
    normalized = core_package_dir.rstrip("/")
    for root in INSTALL_ROOTS:
        prefix = f"{root}/"
        marker = "/site-packages/core"
        if normalized.startswith(prefix) and normalized.endswith(marker):
            middle = normalized[len(prefix) : -len(marker)]
            if middle and ".." not in middle.split("/"):
                return root
    raise OverlayError(f"core package is not an installed site-packages path: {core_package_dir}")


def bind_pairs(core_package_dir: str, web_common_share: str) -> list[tuple[str, str]]:
    """Map the dev tree onto the install paths discovered from the running core."""

    root = _install_root(core_package_dir)
    share = web_common_share.rstrip("/")
    if share != f"{root}/share/web_common":
        raise OverlayError(f"web_common share is not under the same install: {web_common_share}")
    site = str(Path(core_package_dir).parent).replace("\\", "/")
    pairs = [(f"{DEV_ROOT}/python/{name}", f"{site}/{name}") for name in PACKAGES]
    for filename in SHARE_FILES:
        pairs.append((f"{DEV_ROOT}/share/web_common/{filename}", f"{share}/{filename}"))
    return pairs


def overlay_bytes_match(observed: bytes, staged: bytes) -> bool:
    """Success is one SHA-256 of file bytes. Path strings are not an input."""

    return hashlib.sha256(observed).digest() == hashlib.sha256(staged).digest()


def discover_install(prefix: str) -> tuple[str, str]:
    """Find the one installed core package and the web_common share beside it."""

    root = Path(prefix)
    cores = sorted(path.parent for path in root.glob("lib/python3.*/site-packages/core/__init__.py"))
    if len(cores) != 1:
        raise OverlayError(f"expected one installed core package under {prefix}")
    share = root / "share" / "web_common"
    if not share.is_dir():
        raise OverlayError(f"web_common share is missing under {prefix}")
    return cores[0].as_posix(), share.as_posix()


def rosy_core_container(run=subprocess.run) -> str:
    listed = run(
        [
            "docker", "compose", "--env-file", ENV_FILE, "-p", PROJECT,
            "-f", COMPOSE_FILE, "ps", "-q", "rosy-core",
        ],
        capture_output=True, text=True, check=False,
    )
    container = [line.strip() for line in (listed.stdout or "").splitlines() if line.strip()]
    if listed.returncode != 0 or len(container) != 1:
        raise OverlayError("rosy-core container is not running")
    return container[0]


def confirm_loaded(staged: Path, installed: str, container: str, run=subprocess.run) -> None:
    """The running file must hash to the staged core/__init__.py. Paths do not count."""

    expected = hashlib.sha256(staged.read_bytes()).hexdigest()
    probed = run(
        ["docker", "exec", container, "sha256sum", installed],
        capture_output=True, text=True, check=False,
    )
    observed = ((probed.stdout or "").split() or [""])[0]
    if probed.returncode != 0 or observed != expected:
        raise OverlayError("running core did not load the overlay bytes")


def discover_docker(run=subprocess.run) -> tuple[str, str]:
    """Read core.__file__ and the web_common share from the running container."""

    container = rosy_core_container(run)
    probed = run(
        [
            "docker", "exec", container, "python3", "-c",
            "import core; from pathlib import Path; "
            "from ament_index_python.packages import get_package_share_directory; "
            "print(Path(core.__file__).resolve().parent.as_posix()); "
            "print(get_package_share_directory('web_common'))",
        ],
        capture_output=True, text=True, check=False,
    )
    lines = [line.strip() for line in (probed.stdout or "").splitlines() if line.strip()]
    if probed.returncode != 0 or len(lines) != 2:
        raise OverlayError("running core did not report its package paths")
    return lines[0], lines[1]


def render_compose_yaml(pairs: list[tuple[str, str]]) -> str:
    lines = [
        "services:",
        "  rosy-core:",
        "    environment:",
        '      ROSY_DEV_OVERLAY: "1"',
        '      PYTHONDONTWRITEBYTECODE: "1"',
        "    volumes:",
    ]
    lines.extend(f"      - {source}:{dest}:ro" for source, dest in pairs)
    text = "\n".join(lines) + "\n"
    if re.search(r"(?m)^name\s*:", text):
        raise OverlayError("dev compose fragment must not set a project name")
    return text


def choose_binds_attached(*, explicit: bool, execute: bool, probe) -> bool:
    """The first apply attaches mounts. A later apply only restarts the process."""

    if explicit:
        return True
    if not execute:
        return False
    return bool(probe())


def overlay_mounts_attached(run=subprocess.run) -> bool:
    try:
        container = rosy_core_container(run)
    except OverlayError:
        return False
    inspected = run(
        ["docker", "inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", container],
        capture_output=True, text=True, check=False,
    )
    if inspected.returncode != 0:
        return False
    return f"{DEV_ROOT}/python/core" in (inspected.stdout or "")


def hardware_slice_running(run=subprocess.run) -> bool:
    """Refuse when the motor or hardware slice cannot be shown to be down."""

    listed = run(
        [
            "docker", "compose", "--env-file", ENV_FILE, "-p", PROJECT, "-f", COMPOSE_FILE,
            "--profile", "motor", "--profile", "hardware", "ps", "-q", "rosy-motor", "rosy-io",
        ],
        capture_output=True, text=True, check=False,
    )
    if listed.returncode != 0:
        raise OverlayError("cannot tell whether motor or hardware is running")
    return bool((listed.stdout or "").strip())


def service_main_pid(run=subprocess.run) -> str:
    shown = run(
        ["systemctl", "show", "-p", "MainPID", "--value", "rosy-core.service"],
        capture_output=True, text=True, check=False,
    )
    pid = (shown.stdout or "").strip()
    if shown.returncode != 0 or pid in {"", "0"}:
        raise OverlayError("rosy-core is not running")
    return pid


def confirm_native_loaded(staged: Path, installed: str, run=subprocess.run) -> None:
    """Hash the file inside the service mount namespace, where the drop-in bind is visible."""

    expected = hashlib.sha256(staged.read_bytes()).hexdigest()
    probed = run(
        ["nsenter", "-t", service_main_pid(run), "-m", "sha256sum", installed],
        capture_output=True, text=True, check=False,
    )
    observed = ((probed.stdout or "").split() or [""])[0]
    if probed.returncode != 0 or observed != expected:
        raise OverlayError("running core did not load the overlay bytes")


def restart_native(run=subprocess.run) -> None:
    """Reload units first: a new or changed drop-in is ignored until daemon-reload.

    2026-09-24 on rosy-pinky-e4us: restart without reload left NeedDaemonReload=yes
    and the running core had none of the binds.
    """
    for command in (["systemctl", "daemon-reload"], ["systemctl", "restart", "rosy-core.service"]):
        if run(command, check=False).returncode != 0:
            raise OverlayError(f"{' '.join(command)} failed")


def confirm_native_binds(pairs: list[tuple[str, str]], run=subprocess.run) -> None:
    """Every bind target must be a mount point in the running core's namespace.

    A hash of one file cannot prove this alone: core/__init__.py can be byte-equal
    between the image and the overlay (it was, 2026-09-24), so an unloaded overlay
    passed the old check.
    """
    pid = service_main_pid(run)
    shown = run(["cat", f"/proc/{pid}/mountinfo"], capture_output=True, text=True, check=False)
    if shown.returncode != 0:
        raise OverlayError("cannot read the running core's mounts")
    mounted = set()
    for line in (shown.stdout or "").splitlines():
        fields = line.split()
        if len(fields) > 4:
            mounted.add(fields[4].replace("\\040", " "))
    # /opt/rosy/current is a symlink to the release: the kernel records the
    # resolved path (/opt/rosy/releases/<id>/...), so resolve before comparing.
    def resolved(target: str) -> str:
        shown = run(["readlink", "-f", target], capture_output=True, text=True, check=False)
        return (shown.stdout or "").strip() if shown.returncode == 0 else target

    missing = [target for _source, target in pairs
               if target not in mounted and resolved(target) not in mounted]
    if missing:
        raise OverlayError(f"running core is missing overlay binds: {', '.join(missing)}")


def compose_argv(*, binds_attached: bool, motor_or_hardware_running: bool) -> list[str]:
    if motor_or_hardware_running:
        raise OverlayError("refuse to overlay while motor or hardware is running")
    command = [
        "docker", "compose",
        "--env-file", ENV_FILE,
        "-p", PROJECT,
        "-f", COMPOSE_FILE,
        "-f", DEV_COMPOSE,
    ]
    if binds_attached:
        return [*command, "restart", "rosy-core"]
    return [*command, "up", "-d", "--no-build", "--no-deps", "rosy-core"]


def render_native_dropin(pairs: list[tuple[str, str]]) -> str:
    lines = [
        "[Service]",
        "Environment=ROSY_DEV_OVERLAY=1",
        "Environment=PYTHONDONTWRITEBYTECODE=1",
    ]
    lines.extend(f"BindReadOnlyPaths={source}:{dest}" for source, dest in pairs)
    text = "\n".join(lines) + "\n"
    if "ExecStart=" in text or "WorkingDirectory=" in text:
        raise OverlayError("native drop-in must not replace ExecStart or WorkingDirectory")
    return text


def clear_overlay(root: Path) -> list[str]:
    """Remove the marker, drop-in, and dev compose file. Leave the release tree."""

    relative = (
        "etc/rosy/dev-overlay.json",
        "etc/systemd/system/rosy-core.service.d/dev-overlay.conf",
        "var/lib/rosy-dev/compose.dev.yaml",
    )
    removed = []
    for name in relative:
        path = root / name
        if path.is_file() and not path.is_symlink():
            path.unlink()
            removed.append(name)
    return removed


def pack_repo(repo: Path, output: Path) -> None:
    """Tar the allowlisted source tree. Bytecode and foreign paths stay out."""

    mapping = {
        "python/core": repo / "src" / "runtime" / "gateway" / "core",
        "python/core_common": repo / "src" / "contracts" / "foundation" / "core_common",
        "python/core_events": repo / "src" / "runtime" / "events" / "core_events",
        "python/core_features": repo / "src" / "runtime" / "services" / "core_features",
        "python/core_api_web": repo / "src" / "runtime" / "api_web" / "core_api_web",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        for arc_root, source in mapping.items():
            for path in sorted(source.rglob("*")):
                if not path.is_file() or path.suffix == ".pyc" or "__pycache__" in path.parts:
                    continue
                arcname = f"{arc_root}/{path.relative_to(source).as_posix()}"
                member_allowed(arcname)
                tar.add(path, arcname=arcname, recursive=False)
        for filename in SHARE_FILES:
            source = repo / "src" / "hmi" / "web" / filename
            arcname = f"share/web_common/{filename}"
            member_allowed(arcname)
            tar.add(source, arcname=arcname, recursive=False)


def _parse_apply(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="core_dev_overlay")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--archive", type=Path)
    apply_parser.add_argument("--dest", type=Path, default=Path(DEV_ROOT))
    apply_parser.add_argument("--backend", choices=("docker", "native"), required=True)
    apply_parser.add_argument("--core-package")
    apply_parser.add_argument("--web-common-share")
    apply_parser.add_argument("--discover", action="store_true")
    apply_parser.add_argument("--git-revision", default="uncommitted")
    apply_parser.add_argument("--dirty", action="store_true")
    apply_parser.add_argument("--binds-attached", action="store_true")
    apply_parser.add_argument("--motor-running", action="store_true")
    apply_parser.add_argument("--execute", action="store_true")
    apply_parser.add_argument("--marker", type=Path, default=Path("/etc/rosy/dev-overlay.json"))
    apply_parser.add_argument("--dropin", type=Path, default=Path("/etc/systemd/system/rosy-core.service.d/dev-overlay.conf"))

    clear_parser = sub.add_parser("clear")
    clear_parser.add_argument("--root", type=Path, default=Path("/"))

    pack_parser = sub.add_parser("pack")
    pack_parser.add_argument("--repo", type=Path, required=True)
    pack_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "pack":
        pack_repo(args.repo, args.output)
        return 0
    if args.command == "clear":
        clear_overlay(args.root)
        return 0
    if args.motor_running or (
        args.execute and args.backend == "docker" and hardware_slice_running()
    ):
        raise OverlayError("refuse to overlay while motor or hardware is running")
    if args.archive is not None:
        stage_overlay(args.archive, args.dest)
    if args.discover:
        if args.backend == "docker":
            core_package, web_share = discover_docker()
        else:
            core_package, web_share = discover_install("/opt/rosy/current/install")
    elif args.core_package and args.web_common_share:
        core_package, web_share = args.core_package, args.web_common_share
    else:
        raise OverlayError("pass --discover or both install paths")
    pairs = bind_pairs(core_package, web_share)
    if args.backend == "docker":
        command = compose_argv(
            binds_attached=choose_binds_attached(
                explicit=args.binds_attached,
                execute=args.execute,
                probe=overlay_mounts_attached,
            ),
            motor_or_hardware_running=False,
        )
        compose_path = args.dest / "compose.dev.yaml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_path.write_text(render_compose_yaml(pairs), encoding="utf-8")
        print(json.dumps(command))
    else:
        args.dropin.parent.mkdir(parents=True, exist_ok=True)
        args.dropin.write_text(render_native_dropin(pairs), encoding="utf-8")
        command = None
    write_marker(
        args.marker,
        build_marker(backend=args.backend, git_revision=args.git_revision, dirty=args.dirty),
    )
    if args.execute and command is not None:
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise OverlayError("core restart failed")
        confirm_loaded(
            args.dest / "python" / "core" / "__init__.py",
            f"{core_package.rstrip('/')}/__init__.py",
            rosy_core_container(),
        )
    elif args.execute:
        restart_native()
        confirm_native_binds(pairs)
        confirm_native_loaded(
            args.dest / "python" / "core" / "__init__.py",
            f"{core_package.rstrip('/')}/__init__.py",
        )
    print(REBOOT_NOTE)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _parse_apply(sys.argv[1:] if argv is None else argv)
    except OverlayError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
