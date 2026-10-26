"""Owned ARM SYSTEM install scenario; synthetic firmware/payload/policy are not device acceptance."""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

WORK = Path("/work/update")
RELEASE = "2026.10.26-002"
ADMITTED = False


def run(argv, *, timeout=300):
    result = subprocess.run([str(p) for p in argv], capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError("SYSTEM install command failed: " + result.stderr.decode(errors="replace")[-6000:])
    return result.stdout


def admit(instance):
    global ADMITTED
    ADMITTED = False
    if os.environ.get("ROSY_OS_GUEST") != "1" or os.geteuid() != 0:
        raise ValueError("SYSTEM install requires an explicitly owned guest")
    if (not isinstance(instance, str) or not instance.startswith("rosy-system-")
            or str(uuid.UUID(instance.removeprefix("rosy-system-"))) != instance.removeprefix("rosy-system-")
            or Path("/var/lib/cloud/data/instance-id").read_text().strip() != instance
            or os.uname().machine != "aarch64"):
        raise ValueError("SYSTEM install owned guest identity differs")
    if (run(["blockdev", "--getsize64", "/dev/vdc"]).strip() != str(12 * 1024**3).encode()
            or "virtio" not in str(Path("/sys/class/block/vdc/device").resolve())
            or run(["findmnt", "-n", "-o", "SOURCE", "/work"]).strip() != b"/dev/vdb"):
        raise ValueError("SYSTEM install dedicated guest volumes differ")
    ADMITTED = True


def snapshot(instance, source_slot="a"):
    admit(instance)
    from os_system_card import _guest
    _guest()  # The original cloud boot, with the six-GPT card entirely unmounted.
    from test_ab_image_layout import module
    ab = module()
    layout = ab.validate_layout(json.loads(Path("/work/card/layout.json").read_bytes()))
    with open("/dev/vdc", "rb", buffering=0) as stream:
        def read_at(offset, count):
            stream.seek(offset)
            return stream.read(count)
        if ab.parse_gpt(read_at, 12 * 1024**3, "bootstrap") != layout:
            raise ValueError("SYSTEM snapshot physical GPT differs")
    WORK.mkdir(mode=0o700)
    source = WORK / "source"
    source.mkdir(mode=0o700)
    for role, filename in (("root_" + source_slot, "rootfs.ext4"), ("boot_" + source_slot, "boot.vfat")):
        part = next(p for p in layout["partitions"] if p["role"] == role)
        destination = source / filename
        run(["dd", "if=/dev/vdc" + str(part["number"]), "of=" + str(destination),
             "bs=8M", "status=none", "conv=excl,fsync"], timeout=900)
        if destination.stat().st_size != part["size_lba"] * 512:
            raise ValueError("SYSTEM snapshot size differs")
    return {"snapshot": True}


def _bundle():
    from os_bundle import _manifest, _metadata
    from os_rauc import _spki
    from signing import sign_checksums, sha256_file
    source = WORK / "source"
    descriptor = json.loads(run(["debugfs", "-R", "cat /etc/rosy/os-factory-release.json", source / "rootfs.ext4"]))
    value = dict(release_id=RELEASE, source_revision="c" * 40,  # Synthetic SYSTEM fixture provenance only.
                 native_factory={k: descriptor[k] for k in ("release_id", "checksums_sha256")},
                 state_schema=dict(read_min=1, read_max=1, write=1),
                 images={p.name: dict(size_bytes=p.stat().st_size) for p in source.iterdir()})
    (source / "manifest.raucm").write_text(_manifest(value))
    certificate = Path("/work/card/cms/fixture.cert.pem")
    configuration = WORK / "creator.conf"
    configuration.write_text("[system]\ncompatible=rosy-pinky-pro-ab-v2\nbootloader=noop\nbundle-formats=verity\n"
                             f"[keyring]\npath={certificate}\ncheck-purpose=codesign\nuse-bundle-signing-time=false\n")
    bundle = WORK / f"rosy-os-pinky-pro-{RELEASE}-arm64.raucb"
    run(["/usr/bin/rauc", "--conf", configuration, "--cert", certificate,
         # gzip level 9 dominated TCG time; level 1 preserves the exact image bytes and verity checks.
         "--key", "/work/card/cms/fixture.key.pem", "--mksquashfs-args=-processors 1 -comp gzip -Xcompression-level 1",
         "bundle", source, bundle], timeout=1800)
    metadata = _metadata(value, _spki(certificate.read_bytes()),
                         dict(filename=bundle.name, sha256=sha256_file(bundle), size_bytes=bundle.stat().st_size))
    raw = json.dumps(metadata, sort_keys=True).encode()
    signature = sign_checksums(raw, Path("/work/card/keys/factory.private.pem"))
    stage = Path("/var/lib/rosy-device/os-update/staging")
    stage.mkdir(mode=0o700, exist_ok=True)
    stage = stage / RELEASE
    stage.mkdir(mode=0o700)
    target = stage / bundle.name
    shutil.copyfile(bundle, target)
    target.chmod(0o400)
    return target, raw, signature


def _device_policy(media):
    """Open only: probe the real daemon cgroup without modifying any block bytes."""
    target = "b" if media["slot"] == "a" else "a"
    mounted = set(run(["findmnt", "-rn", "-o", "MAJ:MIN"]).decode().split())
    assert {media["partitions"][role]["device"] for role in ("bootstrap", "data", "boot_" + media["slot"])} <= mounted
    assert not {media["partitions"][role]["device"] for role in ("root_" + target, "boot_" + target)} & mounted
    probes = [("disk_read", "/dev/block/" + media["disk_device"], os.O_RDONLY, True),
              ("disk_write", "/dev/block/" + media["disk_device"], os.O_WRONLY, False)]
    for role, part in media["partitions"].items():
        probes.append((role, part["path"], os.O_WRONLY, role in {"root_" + target, "boot_" + target}))
    reader, writer = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(reader)
        try:
            Path("/sys/fs/cgroup/system.slice/rosy-os-rauc.service/cgroup.procs").write_text(str(os.getpid()))
            observed = {}
            for name, path, flags, allowed in probes:
                try:
                    descriptor = os.open(path, flags | os.O_CLOEXEC | os.O_NONBLOCK)  # No O_TRUNC or writes.
                    os.close(descriptor)
                    observed[name] = True
                except OSError as exc:
                    if exc.errno not in (errno.EPERM, errno.EACCES):
                        raise
                    observed[name] = False
                if observed[name] != allowed:
                    raise ValueError("device grant differs for " + name)
            result = dict(probes=observed, mounted_devices=sorted(mounted))
        except Exception as exc:
            result = dict(error=str(exc))
        os.write(writer, json.dumps(result).encode())
        os.close(writer)
        os._exit(0)
    os.close(writer)
    try:
        result = json.loads(os.read(reader, 8192))
    finally:
        os.close(reader)
        os.waitpid(pid, 0)
    if "error" in result:
        raise ValueError("SYSTEM DeviceAllow probe failed: " + result["error"])
    return result


def install(instance, source_slot="a"):
    admit(instance)
    from os_media import capture
    from os_rauc import verify_bundle
    from os_update_controller import _locks
    from os_update_state import locked, read_state
    from os_bootloader import boot_facts
    from os_motion_guard import reconcile, require_inhibited
    import os_rauc_service
    import rosy_claim
    root = Path("/")
    media = capture(root)
    expected_root = b"/dev/vdc4" if source_slot == "a" else b"/dev/vdc5"
    if media["slot"] != source_slot or run(["findmnt", "-n", "-o", "SOURCE", "/"]).strip() != expected_root:
        raise ValueError("SYSTEM installer requires its prepared source slot")
    target_slot = "b" if source_slot == "a" else "a"
    bundle, raw, signature = _bundle()
    verified = verify_bundle(root, bundle, raw, signature)
    transaction, boot = str(uuid.uuid4()), boot_facts(root)["boot_id"]
    observations = {}
    with _locks(root):
        with locked(root) as store:
            store.begin(verified, media, boot, transaction)
        holder = "os-update:" + transaction
        rosy_claim.acquire(root, holder, "synthetic SYSTEM RAUC admission", 10800)
        try:
            assert reconcile(root) is True  # An already-active oneshot will not rerun after pending changes.
            with locked(root) as store:
                store.transition(transaction, "INSTALLING", boot)
            require_inhibited(root)
            run(["systemctl", "start", "rosy-os-motion-guard.service"])
            bootstrap = media["partitions"]["bootstrap"]["path"]
            before = run(["sha256sum", bootstrap]).split()[0]
            def authorize():
                # Policy/CORE telemetry remain fixtures; cgroup device grants are actual kernel evidence.
                observations.update(_device_policy(media))
            report = os_rauc_service.install(root, bundle, raw, signature, authorize=authorize)
            assert report["installed"] is True
            assert report["report"]["target_slot"] == target_slot
            assert run(["sha256sum", bootstrap]).split()[0] == before
            assert capture(root) == media
            assert read_state(root)["pending"]["phase"] == "INSTALLING"
            assert not Path("/" + os_rauc_service.RUNTIME).exists()
            assert not Path("/" + os_rauc_service.DROPIN).exists()
            assert run(["systemctl", "show", "--value", "-p", "MainPID", os_rauc_service.SERVICE]).strip() == b"0"
            return dict(installed=True, device_policy=observations, receipt=report["report"])
        finally:
            rosy_claim.release(root, holder)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "install"))
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--source-slot", choices=("a", "b"), default="a")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    for relative in ("", "test", "deploy/robot/pinky_pro/native", "deploy/robot/pinky_pro/release"):
        sys.path.insert(0, str(source / relative))
    if args.command == "install":
        sys.path.insert(0, "/opt/rosy/os-bootstrap/native-runtime")
    try:
        result = snapshot(args.instance_id, args.source_slot) if args.command == "snapshot" else install(args.instance_id, args.source_slot)
    except Exception:
        if args.command == "install" and ADMITTED:
            diagnostic = subprocess.run(["journalctl", "-b", "--no-pager", "-n", "45",
                "-u", "rosy-os-rauc.service", "-u", "rosy-os-storage.service", "-u", "rosy-os-motion-guard.service"],
                capture_output=True, timeout=20)
            print(diagnostic.stdout.decode(errors="replace")[-6000:], file=sys.stderr)
        raise
    print(json.dumps(result, sort_keys=True))
