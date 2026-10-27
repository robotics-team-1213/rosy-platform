"""Prepare a six-GPT SYSTEM card inside the owned ARM guest; not a product image builder."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

CURRENT = "2026.10.26-001"


def run(argv, *, data=None, timeout=300):
    result = subprocess.run([str(p) for p in argv], input=data, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError("SYSTEM card command failed: " + result.stderr.decode(errors="replace")[-3000:])
    return result.stdout


def _guest():
    marker = Path("/run/rosy-system-guest")
    if os.environ.get("ROSY_OS_GUEST") != "1" or os.geteuid() != 0 or not marker.is_file():
        raise ValueError("SYSTEM card requires an explicitly owned guest")
    if marker.read_text().strip() != Path("/var/lib/cloud/data/instance-id").read_text().strip():
        raise ValueError("SYSTEM card guest instance differs")
    if (run(["uname", "-m"]).strip() != b"aarch64"
            or run(["blockdev", "--getsize64", "/dev/vdc"]).strip() != str(12 * 1024**3).encode()
            or "virtio" not in str(Path("/sys/class/block/vdc/device").resolve())):
        raise ValueError("SYSTEM card must be the dedicated guest virtio disk")
    mounted = subprocess.run(["findmnt", "-rn", "-o", "SOURCE"], capture_output=True, check=True).stdout.decode()
    if any(line.strip().startswith("/dev/vdc") for line in mounted.splitlines()):
        raise ValueError("SYSTEM card already has mounted filesystems")


def prepare_card(work: Path, *, initial_slot="a") -> dict:
    if initial_slot not in ("a", "b"):
        raise ValueError("invalid SYSTEM initial slot")
    _guest()  # Before looking at or writing any supplied work/device path.
    work = Path(work).absolute()
    if work.exists() or work.is_symlink() or not work.is_relative_to(Path("/work")):
        raise ValueError("SYSTEM card needs a new directory on the owned work volume")
    work.mkdir(mode=0o700)
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / "deploy/robot/pinky_pro/release"))
    from test_ab_image_assembly import module as assembler_module
    from test_ab_image_layout import module as layout_module
    from test_os_factory_release import _factory
    from test_factory_release_signature import _keys
    from test_os_frozen_firstboot import _prefix, _stage
    from test_os_ab_root_configuration import _configurer
    from os_rauc_fakes import signer
    ab, assembler = layout_module(), assembler_module()
    from os_state_layout import COMMON, SHARED_BINDINGS
    from os_state_accounts import ACCOUNT_IDS, CALIBRATION_GROUP_ID
    from os_ssh_hostkeys import FILES as HOST_KEY_FILES, _keys as validate_host_keys
    from os_bootloader import autoboot
    layout, start = ab.plan(), 2048
    for part, mib in zip(layout["partitions"], (64, 64, 64, 4096, 4096, 3072)):
        part.update(start_lba=start, size_lba=mib * 2048)
        start += mib * 2048
    layout["raw_size_bytes"] = 12 * 1024**3
    layout = ab.validate_layout(layout)
    run(["sfdisk", "/dev/vdc"], data=ab.sfdisk_script(layout).encode())
    run(["udevadm", "settle"])
    private, public = _keys(work / "keys", "factory")
    _, certificate = signer(work / "cms")
    resources, volumes = assembler.ImageResources(), {}
    try:
        for part in layout["partitions"]:
            device = "/dev/vdc" + str(part["number"])
            if part["number"] <= 3:
                run(["mkfs.vfat", "-F", "32", "-n", part["role"].upper(), device])
            else:
                run(["mkfs.ext4", "-F", "-q", "-E", "lazy_itable_init=0,lazy_journal_init=0", "-m", "0", device])
            target = work / part["role"]
            resources.mount(device, target, filesystem="vfat" if part["number"] <= 3 else "ext4")
            volumes[part["role"]] = target
        ab.initialize_data(volumes["data"], str(uuid.uuid4()), CURRENT)
        # A synthetic B baseline exercises reverse writes; it does not prove a healthy A→B commit.
        state_path = volumes["data"] / "os-update/state.json"
        initial = json.loads(state_path.read_bytes())
        initial["committed"]["slot"] = initial_slot
        from os_update_state import _validate
        ab._json_atomic(state_path, _validate(initial), 0o600)
        # Pin the owned guest's existing SSH identity before storage projects the common pair.
        host_keys = volumes["data"] / "ssh-hostkeys"
        host_keys.mkdir(mode=0o700)
        for name, mode in HOST_KEY_FILES.items():
            path = host_keys / name
            path.write_bytes((Path("/etc/ssh") / name).read_bytes())
            path.chmod(mode)
        validate_host_keys(host_keys, 0)
        for slot in ("a", "b"):
            root, boot = volumes["root_" + slot], volumes["boot_" + slot]
            # Only a disposable guest is cloned; packages, native payload and firmware remain test fixtures.
            run(["rsync", "-aHAXx", "--numeric-ids", "--exclude=/work/***", "--exclude=/proc/***",
                 "--exclude=/sys/***", "--exclude=/dev/***", "--exclude=/run/***", "--exclude=/mnt/***",
                 "--exclude=/tmp/***", "--exclude=/var/log/***", "/", str(root) + "/"], timeout=600)
            for relative in ("proc", "sys", "dev", "run", "tmp", "var/log", "var/log/journal", COMMON, "boot/firmware",
                             "run/rosy-provision-boot", "var/lib/rosy/releases", *SHARED_BINDINGS):
                (root / relative).mkdir(parents=True, exist_ok=True)
            (root / "tmp").chmod(0o1777)
            if any((root / "var/log/journal").iterdir()):
                raise ValueError("SYSTEM trial journal must start empty before its snapshot")
            probe = root / "opt/rosy-system/trial-probe.py"
            probe.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).with_name("os_system_trial.py"), probe)
            (root / "etc/rosy-system-guest-id").write_text(Path("/var/lib/cloud/data/instance-id").read_text())
            journal_config = root / "etc/systemd/journald.conf.d/90-rosy-system.conf"
            journal_config.parent.mkdir(parents=True, exist_ok=True)
            journal_config.write_text("[Journal]\nStorage=persistent\nSystemMaxUse=16M\n")
            unit = root / "etc/systemd/system/rosy-system-trial-probe.service"
            unit.write_text("[Unit]\nDescription=Owned SYSTEM trial boot observations\nDefaultDependencies=no\n"
                            "Requires=rosy-os-storage.service systemd-journal-flush.service\n"
                            "After=rosy-os-storage.service systemd-journal-flush.service\nBefore=basic.target\n"
                            "[Service]\nType=oneshot\nEnvironment=ROSY_OS_GUEST=1\n"
                            "ExecStart=/usr/bin/python3 -I -B /opt/rosy-system/trial-probe.py\n"
                            "TimeoutStartSec=60\nSyslogIdentifier=rosy-system-trial-probe\n")
            wanted = root / "etc/systemd/system/basic.target.wants"
            wanted.mkdir(parents=True, exist_ok=True)
            (wanted / unit.name).symlink_to("../" + unit.name)
            # The Ubuntu cloud fixture lacks the fixed accounts created by customize-rootfs.sh.
            run(["groupadd", "--root", root, "--gid", CALIBRATION_GROUP_ID, "rosy-calib"])
            for name, identity in ACCOUNT_IDS.items():
                run(["groupadd", "--root", root, "--gid", identity, name])
                run(["useradd", "--root", root, "--uid", identity, "--gid", identity,
                     "--no-create-home", "--home-dir", "/home/rosy" if name == "rosy" else "/nonexistent",
                     "--shell", "/bin/bash" if name == "rosy" else "/usr/sbin/nologin", name])
            _factory(root, CURRENT, private, public, signed=True)
            prefix = _prefix(root)
            _stage(prefix)
            parts = ab.render_files(layout, slot, "root=LABEL=writable console=ttyAMA0")
            for name, text in parts.items():
                target = (boot if name == "cmdline.txt" else root) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            ring = root / "etc/rauc/keyring.pem"
            ring.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(certificate, ring)
            current = root / "opt/rosy/current"
            current.symlink_to("/opt/rosy/releases/" + CURRENT, target_is_directory=True)
            for name in ("rosy-os-storage.service",):
                destination = root / "etc/systemd/system" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(prefix / "native-runtime" / name, destination)
            _configurer().configure(root, CURRENT)
            run([sys.executable, "-I", "-B", str(ab.BASE / "native/os_state_accounts.py"), "--root", root])
        ab._write_atomic(volumes["bootstrap"] / "autoboot.txt", autoboot(initial_slot).decode(), 0o644)
        ab._write_atomic(volumes["bootstrap"] / "config.txt", "# synthetic ARM SYSTEM firmware\n", 0o644)
        resources.close()
    finally:
        resources.close()
    with open("/dev/vdc", "rb", buffering=0) as source:
        def read_at(offset, size):
            source.seek(offset)
            return source.read(size)
        if ab.parse_gpt(read_at, 12 * 1024**3, "bootstrap") != layout:
            raise ValueError("SYSTEM card GPT readback differs")
    (work / "layout.json").write_text(json.dumps(layout, sort_keys=True))
    return layout


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--initial-slot", choices=("a", "b"), default="a")
    args = parser.parse_args()
    print(json.dumps(prepare_card(args.work, initial_slot=args.initial_slot), sort_keys=True))
