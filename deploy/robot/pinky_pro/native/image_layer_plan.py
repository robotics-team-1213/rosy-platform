"""Image-layer sync: allowlists, unit inventory and the install plan (D-388, D-766 split)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
import os
import re
import subprocess

from image_layer_files import _mode, _sha256
import image_layer_boot as boot

RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")


RELEASE_NATIVE = "deploy/robot/native"


IMAGE_LAYER = "image-layer"


NATIVE_RUNTIME = "opt/rosy/native-runtime"


UNIT_DIR = "etc/systemd/system"


UDEV_DIR = "etc/udev/rules.d"


MODPROBE_DIR = "etc/modprobe.d"


ALLOWED_PREFIXES = (NATIVE_RUNTIME + "/", UNIT_DIR + "/", UDEV_DIR + "/", MODPROBE_DIR + "/")


# OS boot/configuration and account state never belong to application sync.
FORBIDDEN_PREFIXES = (
    "boot/", "etc/rosy/", "opt/rosy/os-bootstrap/", "usr/local/", "lib/modules/", "usr/lib/modules/",
    "etc/sudoers", "etc/passwd", "etc/shadow", "etc/group", "etc/gshadow", "etc/systemd/system/rosy-os-rauc", "etc/systemd/system/rosy-os-motion-guard", "etc/systemd/system/rosy-os-trial-deadline", "etc/systemd/system/rosy-os-update", "etc/systemd/system/sysinit.target.d/", "etc/systemd/system.conf.d/", "etc/systemd/system/apt-daily", "etc/systemd/system/unattended-upgrades",
    *(f"etc/systemd/system/{unit}.service.d/" for unit in (
        "rosy-first-boot", "rosy-release-recover", "rosy-os-storage", "rosy-sd-provision", "rosy-os-tailnet", "rosy-core", "rosy-io", "rosy-navigation")),
)


BACKUP_ROOT = "var/lib/rosy/image-layer-backup"


BACKUP_MANIFEST = "backup-manifest.json"


# Written before the reload/enable commands, removed once they all succeed.
PENDING_FILE = BACKUP_ROOT + "/pending.json"


# After this many runs that could not finish them, pending commands are parked.
MAX_PENDING_ATTEMPTS = 3


LOCK_FILE = "var/lib/rosy/releases/native-release.lock"


DEFAULT_PUBLIC_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"


# Only these nonrecursive directory rules may be applied outside the updater's
# old mount namespace. Never run the config's z/Z ownership migrations here.
STATE_DIRECTORIES = {
    "/var/lib/rosy/maps": ("2750", "rosy-io", "rosy-core"),
    "/var/lib/rosy/models": ("0750", "root", "rosy-camera"),
    "/var/lib/rosy/pilot-recordings": ("2750", "rosy-camera", "rosy-core"),
}


STATE_CONFIG = BACKUP_ROOT + "/state-directories.conf"


# Native units plus the signed boot catalog share the fresh-image inventory.
UNITS = (
    "rosy-release-recover.service", "rosy-os-storage.service", "rosy-os-tailnet.service",
    "rosy-sd-provision.service", "rosy-core.service",
    "rosy-host-agent.service",
    "rosy-runtime.target",
    "rosy-io.service",
    "rosy-camera.service",
    "rosy-camera-healthy.service", "rosy-camera-healthy.timer", "rosy-media.service",  # D-789
    "rosy-navigation.service",
    "rosy-boot-status.service", "rosy-boot-status.timer",
    "rosy-boot-status-ready.service",
    # D-433: retired (see RETIRED_UNITS); rosy-face replaces it.
    "rosy-boot-display.service",
    "rosy-face.service",
    "rosy-config.service",
    "rosy-network.service",
    "rosy-login-code.service",
    "rosy-hw-probe.service",
    "rosy-hw-probe.path",
    "rosy-hw-test.service",
    "rosy-hw-test.path",
    # D-412: the idle-time updater; only the timer is enabled.
    "rosy-auto-update.service",
    "rosy-auto-update.timer",
    # D-418: SSH access on CORE's request (expiry timer only while a temp login is on).
    "rosy-ssh-access.service", "rosy-ssh-pairing.service",
    "rosy-ssh-access.path",
    "rosy-ssh-access-boot.service",
    "rosy-ssh-password-expire.service",
    "rosy-ssh-password-expire.timer",
    # D-477: one-shot tailnet join; condition-gated on the provisioned key file.
    "rosy-tailscale-join.service",
    *boot.FEATURE_UNITS,
)


# Of those, the ones customize-rootfs.sh enables. A unit the sync adds is
# enabled only if it is here, as a fresh image would have it.
ENABLED_UNITS = frozenset({
    "rosy-host-agent.service", "rosy-os-storage.service", "rosy-os-tailnet.service",
    "rosy-release-recover.service",
    "rosy-runtime.target",
    "rosy-boot-status.service",
    "rosy-boot-status.timer",
    "rosy-boot-status-ready.service",
    "rosy-config.service",
    "rosy-network.service",
    "rosy-face.service",
    "rosy-login-code.service",
    "rosy-hw-probe.service",
    "rosy-hw-probe.path",
    "rosy-hw-test.path",
    "rosy-auto-update.timer",
    "rosy-ssh-access.path",
    "rosy-ssh-access-boot.service",
    "rosy-tailscale-join.service",
    *boot.FEATURE_UNITS,
})


# D-433: a unit a newer one replaced. Its file is only ever REPLACED where an
# older image installed it (with a condition that keeps it from starting beside
# its successor), never installed new, and never restarted: restarting it would
# start a second owner of the same lines. A rollback's own sync restores the
# backed-up original.
RETIRED_UNITS = frozenset({"rosy-boot-display.service"})


# Never offered for a live restart, even when active and changed: the boot
# oneshots are Required by rosy-core (restarting them restarts CORE), and
# restarting network/config can drop the SSH session that runs the push.
# Their new definition takes effect at the next boot.
NEXT_BOOT_ONLY = frozenset({
    "rosy-release-recover.service", "rosy-os-storage.service", "rosy-os-tailnet.service",
    "rosy-sd-provision.service",
    "rosy-network.service",
    "rosy-config.service",
})


def _restartable(unit: str) -> bool:
    return (
        not unit.endswith(".target")
        and unit not in NEXT_BOOT_ONLY
        and unit not in RETIRED_UNITS
        and not unit.startswith("rosy-first-boot")
    )


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class SyncError(ValueError):
    pass


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)


def check_destination(relative: str) -> None:
    """Allow native image directories and the exact signed boot-support filenames."""
    if relative in {boot.BOOT_DIRECTORY + "/" + name for name in boot.BOOT_FILES}:
        return
    parts = relative.split("/")
    if (
        relative.startswith("/")
        or ".." in parts
        or "" in parts
        or not relative.startswith(ALLOWED_PREFIXES)
        or relative.startswith(FORBIDDEN_PREFIXES)
    ):
        raise SyncError(f"IMAGE_LAYER_DESTINATION: refusing to write {relative!r}")


def resolve_current(
    root: Path,
    *,
    is_link: Callable[[Path], bool] | None = None,
    readlink: Callable[[Path], str] | None = None,
) -> tuple[str, Path]:
    """The release /opt/rosy/current names, refusing anything outside releases/."""
    link = root / "opt" / "rosy" / "current"
    releases = root / "opt" / "rosy" / "releases"
    if not (is_link or os.path.islink)(link):
        raise SyncError(f"IMAGE_LAYER_CURRENT: {link} is not a symlink")
    target = Path(os.path.normpath(os.path.join(str(link.parent), (readlink or os.readlink)(link))))
    if not RELEASE_ID.fullmatch(target.name) or target.resolve().parent != releases.resolve():
        raise SyncError(f"IMAGE_LAYER_CURRENT: {link} does not point into {releases}")
    if target.is_symlink() or not target.is_dir():
        raise SyncError(f"IMAGE_LAYER_CURRENT: {target} is not a release directory")
    return target.name, target


def _entry(source: Path, destination: str, kind: str, mode: int) -> dict:
    check_destination(destination)
    return {"source": source, "destination": destination, "kind": kind, "mode": mode}


def allowlist(native: Path) -> tuple[list[dict], list[dict]]:
    """(entries, skipped) for a release's deploy/robot/native directory."""
    entries: list[dict] = []
    skipped: list[dict] = []
    for path in sorted(native.rglob("*"), key=lambda p: p.relative_to(native).as_posix()):
        relative = path.relative_to(native).as_posix()
        if "__pycache__" in relative.split("/"):
            continue
        if path.is_symlink():
            raise SyncError(f"IMAGE_LAYER_SOURCE: {relative} is a symlink")
        if path.is_dir():
            continue
        # install-native-runtime.sh copies the whole directory, so the
        # native-runtime copy mirrors every file the release carries here.
        mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
        entries.append(_entry(path, f"{NATIVE_RUNTIME}/{relative}", "runtime", mode))
    for unit in UNITS:
        source = native / unit
        if source.is_file() and not source.is_symlink():
            entries.append(_entry(source, f"{UNIT_DIR}/{unit}", "unit", 0o644))
        else:
            skipped.append({"path": f"/{UNIT_DIR}/{unit}", "reason": "not in this release"})
    for kind, folder, pattern, destination in (
        ("udev", "udev", "*.rules", UDEV_DIR),
        ("modprobe", "modprobe", "*.conf", MODPROBE_DIR),
    ):
        source_dir = native / IMAGE_LAYER / folder
        if not source_dir.is_dir():
            skipped.append({"path": f"/{destination}", "reason": f"release has no {IMAGE_LAYER}/{folder}"})
            continue
        for source in sorted(source_dir.glob(pattern)):
            if source.is_symlink() or not source.is_file():
                raise SyncError(f"IMAGE_LAYER_SOURCE: {source} is not a regular file")
            entries.append(_entry(source, f"{destination}/{source.name}", kind, 0o644))
    entries.extend(boot.catalog_entries(native))
    return entries, skipped


def _compare_modes() -> bool:
    # A Windows test host has no POSIX modes to compare; the robot does.
    return os.name == "posix"


def plan(root: Path, native: Path) -> dict:
    entries, skipped = allowlist(native)
    result = {"changed": [], "new": [], "unchanged": [], "skipped": skipped, "_work": []}
    for entry in entries:
        destination = root / entry["destination"]
        shown = "/" + entry["destination"]
        if destination.is_symlink():
            # A unit linked to /dev/null is masked; replacing it would unmask it.
            skipped.append({"path": shown, "reason": "destination is a symlink (masked?)"})
            continue
        if not destination.exists() and entry["kind"] == "unit" and Path(entry["destination"]).name in RETIRED_UNITS:
            skipped.append({"path": shown, "reason": "retired unit, not installed here (D-433)"})
            continue
        if not destination.exists():
            result["new"].append(shown)
            result["_work"].append({**entry, "state": "new"})
            continue
        if not destination.is_file():
            raise SyncError(f"IMAGE_LAYER_DESTINATION: {shown} is not a regular file")
        same = _sha256(destination) == _sha256(entry["source"])
        if same and (not _compare_modes() or _mode(destination) == entry["mode"]):
            result["unchanged"].append(shown)
            continue
        result["changed"].append(shown)
        result["_work"].append({**entry, "state": "changed"})
    return result


def affected_units(root: Path, work: list[dict]) -> list[str]:
    """Units whose file changed, or whose unit file runs a changed runtime script."""
    touched_units = {Path(item["destination"]).name for item in work if item["kind"] == "unit"}
    touched_scripts = {
        "/" + item["destination"] for item in work if item["kind"] == "runtime"
    }
    affected = set(touched_units)
    for unit in UNITS:
        installed = root / UNIT_DIR / unit
        if unit in affected or installed.is_symlink() or not installed.is_file():
            continue
        text = installed.read_text(encoding="utf-8", errors="replace")
        if any(re.search(re.escape(script) + r"(\s|$)", text) for script in touched_scripts):
            affected.add(unit)
    return sorted(affected)


def active_units(units: list[str], runner: Runner) -> list[str]:
    active = []
    for unit in units:
        completed = runner(["systemctl", "is-active", "--quiet", unit])
        if completed.returncode == 0:
            active.append(unit)
    return active
