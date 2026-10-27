#!/usr/bin/env python3
"""Assemble a new GPT A/B image from a customized, device-neutral factory image."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

SCRIPT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT))
import ab_image_layout as ab
from os_state_layout import COMMON, SHARED_BINDINGS
from os_bootloader import autoboot


def _run(command: list[str], *, timeout=180, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, check=True, timeout=timeout, **kwargs)


class ImageResources:
    """Only loop devices allocated here may be formatted or detached."""

    def __init__(self):
        self.loops, self.mounts = [], []
        self.images = {}

    def _bound(self, loop: str) -> None:
        rows = json.loads(_run(["losetup", "--json", "--output", "NAME,BACK-FILE", loop]).stdout)["loopdevices"]
        if len(rows) != 1 or rows[0]["name"] != loop or not os.path.samefile(rows[0]["back-file"], self.images[loop]):
            raise ValueError("loop device is not bound to the owned image")

    def loop(self, image: Path, *, readonly=False) -> str:
        options = ["--read-only"] if readonly else []
        loop = _run(["losetup", "--find", "--show", "--partscan", *options, str(image)]).stdout.strip()
        if not re.fullmatch(r"/dev/loop[0-9]+", loop):
            raise ValueError("losetup returned an unexpected device")
        self.loops.append(loop)
        self.images[loop] = image
        self._bound(loop)
        _run(["udevadm", "settle"])
        return loop

    def mount(self, device: str, target: Path, *, readonly=False, filesystem="ext4") -> None:
        target.mkdir(mode=0o700)
        options = "ro,noload" if readonly and filesystem == "ext4" else "ro" if readonly else "rw,nodev,nosuid"
        if filesystem == "vfat":
            options += ",fmask=0133,dmask=0022"
        _run(["mount", "-t", filesystem, "-o", options, device, str(target)])
        self.mounts.append(target)

    def unmount_all(self) -> None:
        remaining = []
        for target in reversed(self.mounts):
            try:
                _run(["umount", "--", str(target)])
            except (OSError, subprocess.SubprocessError):
                remaining.append(target)
        self.mounts = list(reversed(remaining))
        if self.mounts:
            raise OSError("could not unmount owned image; preserve workspace")

    def close(self) -> None:
        self.unmount_all()
        remaining = []
        for loop in reversed(self.loops):
            try:
                self._bound(loop)
                _run(["losetup", "--detach", loop])
            except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
                remaining.append(loop)
        self.loops = list(reversed(remaining))
        if self.loops:
            raise OSError("could not detach owned image; preserve workspace")


def checked_inputs(source: Path, output: Path, work: Path) -> tuple[Path, Path, Path]:
    source, output = Path(source).absolute(), Path(output).absolute()
    work = ab._offline_directory(work)
    ab._offline_directory(source.parent)
    ab._offline_directory(output.parent)
    if source.suffix != ".img" or source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular prepared .img")
    info = source.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_nlink != 1:
        raise ValueError("source image owner/permissions/links differ")
    if output.suffix != ".img" or source == output:
        raise ValueError("a distinct new .img output is required")
    for target in (output, output.with_suffix(".layout.json"), output.with_suffix(".capacity.json")):
        if target.exists() or target.is_symlink():
            raise ValueError("refusing to overwrite existing assembly output")
    return source, output, work


def _publish(source: Path, destination: Path) -> None:
    # Same-directory staging permits an atomic no-overwrite publication.
    os.link(source, destination, follow_symlinks=False)
    source.unlink()
    ab.sync_directory(destination.parent)


def _json_sidecar(destination: Path, value: dict) -> None:
    temporary = destination.with_name(destination.name + ".part." + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fchmod(handle.fileno(), 0o644)
        os.fsync(handle.fileno())
    _publish(temporary, destination)


def _require_native() -> None:
    if platform.machine() != "aarch64" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise ValueError("A/B release assembly requires root on native arm64")


def assemble(source: Path, output: Path, work: Path, release_id: str) -> dict:
    _require_native()
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}", release_id):
        raise ValueError("invalid factory release ID")
    source, output, work = checked_inputs(source, output, work)
    for command in ("losetup", "udevadm", "blkid", "mount", "umount", "sfdisk", "mkfs.vfat", "mkfs.ext4",
                    "rsync", "du", "e2fsck", "fsck.vfat"):
        if shutil.which(command) is None:
            raise ValueError("required assembly command is missing: " + command)
    workspace = Path(tempfile.mkdtemp(prefix="rosy-ab-image.", dir=work))
    partial = output.with_name(output.name + ".part." + uuid.uuid4().hex)
    resources = ImageResources()
    published = False
    try:
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(descriptor, ab.RAW_MIB * ab.MIB)
        finally:
            os.close(descriptor)
        layout = ab.plan()
        _run(["sfdisk", str(partial)], input=ab.sfdisk_script(layout))
        source_loop = resources.loop(source, readonly=True)
        for number, expected in ((1, "vfat"), (2, "ext4")):
            actual = _run(["blkid", "-p", "-s", "TYPE", "-o", "value", source_loop + f"p{number}"]).stdout.strip()
            if actual != expected:
                raise ValueError("prepared source filesystem differs")
        source_root, source_boot = workspace / "source-root", workspace / "source-boot"
        resources.mount(source_loop + "p2", source_root, readonly=True)
        resources.mount(source_loop + "p1", source_boot, readonly=True, filesystem="vfat")
        factory = ab._offline_directory(source_root / "opt/rosy/releases" / release_id)
        allocated = int(_run(["du", "-sx", "-B1", str(factory)]).stdout.split()[0])
        apparent = int(_run(["du", "-sx", "-B1", "--apparent-size", str(factory)]).stdout.split()[0])
        payload_bytes = max(allocated, apparent)
        loop = resources.loop(partial)
        for part in layout["partitions"]:
            device = loop + f"p{part['number']}"
            if part["number"] <= 3:
                _run(["mkfs.vfat", "-F", "32", "-n", part["role"].upper(), device])
            else:
                _run(["mkfs.ext4", "-F", "-q", "-E", "lazy_itable_init=0,lazy_journal_init=0",
                      "-m", "0" if part["role"] == "data" else "1", "-L", part["role"], device], timeout=600)
        volumes = {}
        for part in layout["partitions"]:
            target = workspace / part["role"]
            resources.mount(loop + f"p{part['number']}", target,
                            filesystem="vfat" if part["number"] <= 3 else "ext4")
            volumes[part["role"]] = target
        ab.initialize_data(volumes["data"], str(uuid.uuid4()), release_id)
        capacity = dict(schema_version=1, raw_size_bytes=layout["raw_size_bytes"], roots={})
        for slot in ("a", "b"):
            root, boot = volumes["root_" + slot], volumes["boot_" + slot]
            _run(["rsync", "-aHAXx", "--numeric-ids", str(source_root) + "/", str(root) + "/"], timeout=1800)
            _run(["rsync", "-rt", "--no-perms", "--no-owner", "--no-group", str(source_boot) + "/", str(boot) + "/"], timeout=600)
            for relative in (COMMON, "boot/firmware", "run/rosy-provision-boot", *SHARED_BINDINGS):
                (root / relative).mkdir(parents=True, exist_ok=True)
            ab.configure_slot(root, boot, layout, slot)
            _run([sys.executable, "-I", "-B", str(SCRIPT / "configure-ab-root.py"),
                  "--root", str(root), "--release-id", release_id])
            _run([sys.executable, "-I", "-B", str(SCRIPT.parent / "native/os_state_accounts.py"), "--root", str(root)])
            free = os.statvfs(root)
            capacity["roots"][slot] = ab.capacity_report(free.f_bavail * free.f_frsize, payload_bytes)
        ab._write_atomic(volumes["bootstrap"] / "autoboot.txt",
            autoboot("a").decode("ascii"), 0o644)
        ab._write_atomic(volumes["bootstrap"] / "config.txt", "# ROSY Pinky Pi 5 A/B bootstrap\n", 0o644)
        resources.unmount_all()
        for number in range(1, 7):
            _run(["fsck.vfat", "-n", loop + f"p{number}"] if number <= 3 else
                 ["e2fsck", "-fn", loop + f"p{number}"], timeout=600)
        with partial.open("rb") as handle:
            def read_at(offset, length):
                handle.seek(offset)
                return handle.read(length)
            if ab.parse_gpt(read_at, partial.stat().st_size, layout["provision_role"]) != layout:
                raise ValueError("assembled GPT differs from the planned snapshot")
        resources.close()
        partial.chmod(0o644)
        with partial.open("rb") as handle:
            os.fsync(handle.fileno())
        _json_sidecar(output.with_suffix(".layout.json"), layout)
        _json_sidecar(output.with_suffix(".capacity.json"), capacity)
        _publish(partial, output)
        published = True
        return dict(image=str(output), layout=str(output.with_suffix(".layout.json")),
                    capacity=str(output.with_suffix(".capacity.json")))
    finally:
        try:
            resources.close()
        except (OSError, subprocess.SubprocessError):
            print(f"AB_IMAGE_CLEANUP_HOLD workspace={workspace} image={partial}", file=sys.stderr)
            raise
        else:
            if not published:
                partial.unlink(missing_ok=True)
            shutil.rmtree(workspace)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output-image", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(assemble(args.source_image, args.output_image, args.work_root, args.release_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    def interrupt(signum, _frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupt)
    raise SystemExit(main())
