"""D-375: a payload push brings the image layer up to the active release.

sync-image-layer.py ships in the release's deploy/robot/native and copies the
allowlisted files (native-runtime scripts, rosy units, udev rules, modprobe
options) from /opt/rosy/current to where a fresh image puts them. Every test
runs against a fake device root and a recording runner: nothing here calls a
real systemctl or udevadm.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from signing import sign_checksums


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
SCRIPT = NATIVE / "sync-image-layer.py"
INSTALLER = NATIVE / "install-native-runtime.sh"
PAYLOAD_BUILDER = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "build-native-payload.sh"
CUSTOMIZE = ROOT / "deploy" / "robot" / "pinky_pro" / "image" / "customize-rootfs.sh"
BASH = shutil.which("bash")
OLD_ID = "2026.09.27-010"
NEW_ID = "2026.09.30-008"
needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required to run the installer")


def _load():
    spec = importlib.util.spec_from_file_location("sync_image_layer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_mod = _load()


class Runner:
    def __init__(self, active: set[str] = frozenset()) -> None:
        self.calls: list[list[str]] = []
        self.active = set(active)

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        code = 0
        if argv[:2] == ["systemctl", "is-active"]:
            code = 0 if argv[-1] in self.active else 3
        return subprocess.CompletedProcess(argv, code, "", "")

    def mutating(self) -> list[list[str]]:
        return [call for call in self.calls if call[:2] != ["systemctl", "is-active"]]


_INSTALLED: list[Path] = []


def _install(destination: Path) -> None:
    """Copy what install-native-runtime.sh produced; the real run is slow on Windows."""
    if not _INSTALLED:
        import atexit
        import tempfile

        scratch = tempfile.mkdtemp(prefix="rosy-native-")
        atexit.register(shutil.rmtree, scratch, True)
        once = Path(scratch) / "native"
        completed = subprocess.run([BASH, INSTALLER.as_posix(), once.as_posix()],
                                   capture_output=True, text=True, cwd=ROOT)
        assert completed.returncode == 0, completed.stderr
        _INSTALLED.append(once)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_INSTALLED[0], destination)


def _fresh_image_layer(device: Path, native: Path) -> None:
    """What customize-rootfs.sh leaves outside the release, from one native copy."""
    shutil.copytree(native, device / "opt/rosy/native-runtime")
    units = device / "etc/systemd/system"
    units.mkdir(parents=True)
    for unit in sync_mod.UNITS:
        shutil.copy2(native / unit, units / unit)
    for folder, destination in (("udev", "etc/udev/rules.d"), ("modprobe", "etc/modprobe.d")):
        (device / destination).mkdir(parents=True)
        for source in (native / "image-layer" / folder).iterdir():
            shutil.copy2(source, device / destination / source.name)


def _links(device: Path, release_id: str):
    link = device / "opt/rosy/current"

    def is_link(path: Path) -> bool:
        return Path(path) == link

    def readlink(path: Path) -> str:
        return f"releases/{release_id}"

    return is_link, readlink


def _tree(device: Path) -> dict[str, str]:
    return {
        path.relative_to(device).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in device.rglob("*") if path.is_file()
    }


def _sync(device: Path, release_id: str, runner: Runner, *, dry_run: bool, verified: list | None = None):
    is_link, readlink = _links(device, release_id)
    return sync_mod.sync(device, dry_run=dry_run, verify=(verified.append if verified is not None else (lambda _: None)),
                         runner=runner, is_link=is_link, readlink=readlink)


@pytest.fixture
def device(tmp_path: Path) -> Path:
    """A robot flashed with OLD_ID that has just activated NEW_ID from this repo."""
    if BASH is None:
        pytest.skip("bash is required to run the installer")
    device = tmp_path / "device"
    new_native = device / "opt/rosy/releases" / NEW_ID / "deploy/robot/native"
    _install(new_native)
    _fresh_image_layer(device, new_native)
    # Drift the image layer back to what an older image carried (2026-09-30).
    (device / "etc/systemd/system/rosy-io.service").write_text("[Service]\nExecStart=/bin/old\n", encoding="utf-8")
    (device / "opt/rosy/native-runtime/mapping_approval.py").unlink()
    (device / "etc/udev/rules.d/99-rosy-lamp.rules").unlink()
    (device / "etc/systemd/system/rosy-hw-test.path").unlink()
    (device / "etc/systemd/system/rosy-camera.service").unlink()
    # Files the sync must never touch.
    for relative in ("etc/rosy/runtime.env", "boot/firmware/config.txt", "etc/sudoers.d/60-rosy-operator",
                     "usr/local/share/rosy/python-runtime.sha256", "etc/systemd/system/unrelated.service",
                     sync_mod.LOCK_FILE):
        path = device / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep\n", encoding="utf-8")
    return device


# --- the allowlist is what a fresh image installs --------------------------------


def test_unit_allowlist_is_what_build_native_payload_puts_in_systemd():
    text = PAYLOAD_BUILDER.read_text(encoding="utf-8")
    copied = re.findall(r'cp "\$NATIVE_RUNTIME_SOURCE/([^"]+)" "\$OVERLAY/etc/systemd/system/"', text)

    assert copied
    assert sorted(copied) == sorted(sync_mod.UNITS)


def test_units_the_sync_enables_are_the_ones_customize_rootfs_enables():
    text = CUSTOMIZE.read_text(encoding="utf-8")
    block = re.search(r'systemctl --root "\$ROOT" enable (.*?)\n\s*#', text, re.S).group(1)
    enabled = set(re.findall(r"[\w@.-]+\.(?:service|timer|path|target)", block))

    assert sync_mod.ENABLED_UNITS == enabled & set(sync_mod.UNITS)


@needs_bash
def test_udev_and_modprobe_allowlist_is_what_the_image_overlay_carries(tmp_path):
    text = PAYLOAD_BUILDER.read_text(encoding="utf-8")
    rules = set(re.findall(r'="\$WORKSPACE/deploy/robot/pinky_pro/udev/([^"]+\.rules)"', text))
    confs = set(re.findall(r'="\$WORKSPACE/deploy/robot/pinky_pro/modprobe/([^"]+\.conf)"', text))
    native = tmp_path / "native"
    _install(native)

    entries, _ = sync_mod.allowlist(native)
    udev = {Path(e["destination"]).name for e in entries if e["kind"] == "udev"}
    modprobe = {Path(e["destination"]).name for e in entries if e["kind"] == "modprobe"}

    assert rules and udev == rules
    assert confs and modprobe == confs
    for name in rules:
        assert (native / "image-layer/udev" / name).read_bytes() == (ROOT / "deploy/robot/pinky_pro/udev" / name).read_bytes()


@needs_bash
def test_native_runtime_mapping_is_exactly_what_the_installer_installs(tmp_path):
    native = tmp_path / "release-native"
    image_copy = tmp_path / "device/opt/rosy/native-runtime"
    _install(native)
    _install(image_copy)

    entries, _ = sync_mod.allowlist(native)
    runtime = {e["destination"] for e in entries if e["kind"] == "runtime"}
    installed = {
        "opt/rosy/native-runtime/" + path.relative_to(image_copy).as_posix()
        for path in image_copy.rglob("*") if path.is_file()
    }

    assert runtime == installed
    assert "opt/rosy/native-runtime/sync-image-layer.py" in runtime
    assert "opt/rosy/native-runtime/image-layer/udev/99-rosy-motor.rules" in runtime


@needs_bash
def test_a_fresh_image_is_already_in_sync(tmp_path):
    device = tmp_path / "device"
    native = device / "opt/rosy/releases" / NEW_ID / "deploy/robot/native"
    _install(native)
    _fresh_image_layer(device, native)
    runner = Runner(active={"rosy-core.service", "rosy-io.service"})

    result = _sync(device, NEW_ID, runner, dry_run=False)

    assert result["changed"] == [] and result["new"] == []
    assert result["restart_units"] == [] and result["backup_dir"] is None
    assert runner.mutating() == []


# --- dry run, apply, backup, idempotency -----------------------------------------


def test_dry_run_reports_the_plan_and_writes_nothing(device):
    before = _tree(device)
    runner = Runner(active={"rosy-io.service", "rosy-navigation.service"})

    result = _sync(device, NEW_ID, runner, dry_run=True)

    assert result["ok"] and result["dry_run"] and result["release_id"] == NEW_ID
    assert result["changed"] == ["/etc/systemd/system/rosy-io.service"]
    assert set(result["new"]) == {
        "/opt/rosy/native-runtime/mapping_approval.py",
        "/etc/udev/rules.d/99-rosy-lamp.rules",
        "/etc/systemd/system/rosy-hw-test.path",
        "/etc/systemd/system/rosy-camera.service",
    }
    assert "/etc/systemd/system/rosy-core.service" in result["unchanged"]
    # rosy-navigation's ExecCondition runs the new mapping_approval.py.
    assert "rosy-navigation.service" in result["units_affected"]
    assert result["restart_units"] == ["rosy-io.service", "rosy-navigation.service"]
    assert _tree(device) == before
    assert runner.mutating() == []
    assert not (device / sync_mod.BACKUP_ROOT).exists()


def test_apply_backs_up_installs_reloads_and_enables_like_the_image(device):
    runner = Runner(active={"rosy-io.service", "rosy-core.service"})
    old_io = (device / "etc/systemd/system/rosy-io.service").read_bytes()
    now = dt.datetime(2026, 9, 30, 12, 0, 0, tzinfo=dt.timezone.utc)
    is_link, readlink = _links(device, NEW_ID)

    result = sync_mod.sync(device, dry_run=False, verify=lambda _: None, runner=runner,
                           is_link=is_link, readlink=readlink)
    native = device / "opt/rosy/releases" / NEW_ID / "deploy/robot/native"
    sources = {entry["destination"]: entry["source"] for entry in sync_mod.allowlist(native)[0]}

    assert len(result["changed"]) + len(result["new"]) == 5
    for shown in result["changed"] + result["new"]:
        relative = shown.lstrip("/")
        assert (device / relative).read_bytes() == sources[relative].read_bytes(), shown
    backup = device / result["backup_dir"].lstrip("/")
    assert backup.name.endswith("-" + NEW_ID)
    assert (backup / "etc/systemd/system/rosy-io.service").read_bytes() == old_io
    manifest = json.loads((backup / sync_mod.BACKUP_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["complete"] is True and manifest["release_id"] == NEW_ID
    recorded = {entry["path"]: entry for entry in manifest["files"]}
    assert recorded["/etc/systemd/system/rosy-io.service"]["backup"] == "etc/systemd/system/rosy-io.service"
    assert recorded["/opt/rosy/native-runtime/mapping_approval.py"]["state"] == "new"
    assert runner.mutating() == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "rosy-hw-test.path"],
        ["udevadm", "control", "--reload"],
    ]
    # rosy-camera.service is shipped but not enabled by the image.
    assert result["enabled"] == ["rosy-hw-test.path"]
    assert result["restart_units"] == ["rosy-io.service"]


def test_a_second_run_is_a_no_op(device):
    _sync(device, NEW_ID, Runner(), dry_run=False)
    backups = sorted((device / sync_mod.BACKUP_ROOT).iterdir())
    before = _tree(device)
    runner = Runner(active={"rosy-io.service"})

    again = _sync(device, NEW_ID, runner, dry_run=False)

    assert again["changed"] == [] and again["new"] == []
    assert again["restart_units"] == [] and again["commands"] == [] and again["backup_dir"] is None
    assert runner.calls == []
    assert sorted((device / sync_mod.BACKUP_ROOT).iterdir()) == backups
    assert _tree(device) == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_mode_drift_counts_as_a_change(device):
    _sync(device, NEW_ID, Runner(), dry_run=False)
    script = device / "opt/rosy/native-runtime/rosy-boot-status.py"
    os.chmod(script, 0o644)

    result = _sync(device, NEW_ID, Runner(), dry_run=True)

    assert result["changed"] == ["/opt/rosy/native-runtime/rosy-boot-status.py"]


def test_a_failed_install_puts_every_file_back(device, monkeypatch):
    before = _tree(device)
    real = sync_mod._install
    calls = {"n": 0}

    def flaky(source, destination, mode):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        real(source, destination, mode)

    monkeypatch.setattr(sync_mod, "_install", flaky)
    runner = Runner()

    with pytest.raises(OSError):
        _sync(device, NEW_ID, runner, dry_run=False)

    after = {k: v for k, v in _tree(device).items() if not k.startswith(sync_mod.BACKUP_ROOT)}
    assert after == before
    assert runner.mutating() == []


# --- refusals ------------------------------------------------------------------------


def test_refuses_when_current_is_not_a_symlink(device):
    (device / "opt/rosy/current").mkdir(parents=True)

    with pytest.raises(sync_mod.SyncError, match="not a symlink"):
        sync_mod.sync(device, dry_run=True, verify=lambda _: None, runner=Runner())


@pytest.mark.parametrize("target", [
    "../../tmp/evil", "/opt/rosy/releases/2026.09.30-008", "releases/not-a-release",
    "releases/2026.09.30-008/deploy", "native-runtime",
])
def test_refuses_when_current_leaves_the_release_store(device, target):
    before = _tree(device)
    link = device / "opt/rosy/current"

    with pytest.raises(sync_mod.SyncError, match="IMAGE_LAYER_CURRENT"):
        sync_mod.sync(device, dry_run=False, verify=lambda _: None, runner=Runner(),
                      is_link=lambda path: Path(path) == link, readlink=lambda _: target)
    assert _tree(device) == before


def test_refuses_a_release_shaped_directory_outside_the_release_store(device):
    # Named like a release and complete, but not under /opt/rosy/releases.
    outside = device / "opt" / NEW_ID
    shutil.copytree(device / "opt/rosy/releases" / NEW_ID, outside)
    before = _tree(device)
    link = device / "opt/rosy/current"

    with pytest.raises(sync_mod.SyncError, match="does not point into"):
        sync_mod.sync(device, dry_run=False, verify=lambda _: None, runner=Runner(),
                      is_link=lambda path: Path(path) == link, readlink=lambda _: f"../{NEW_ID}")
    assert _tree(device) == before


def test_refuses_a_release_that_does_not_verify(device):
    before = _tree(device)

    def reject(release_id):
        raise ValueError(f"SIGNATURE_INVALID: {release_id}")

    is_link, readlink = _links(device, NEW_ID)
    with pytest.raises(ValueError, match="SIGNATURE_INVALID"):
        sync_mod.sync(device, dry_run=False, verify=reject, runner=Runner(),
                      is_link=is_link, readlink=readlink)
    assert _tree(device) == before


def test_verifies_the_release_current_names(device):
    verified: list[str] = []

    _sync(device, NEW_ID, Runner(), dry_run=True, verified=verified)

    assert verified == [NEW_ID]


@pytest.mark.parametrize("relative", [
    "etc/rosy/runtime.env", "etc/rosy/defaults.yaml", "boot/firmware/config.txt", "usr/local/bin/x",
    "lib/modules/6.8.0/extra/rp1_ws281x_pwm.ko", "etc/sudoers.d/60-rosy-operator", "etc/passwd",
    "etc/systemd/system/../../rosy/runtime.env", "/etc/systemd/system/rosy-io.service",
    "opt/rosy/current/x", "etc/systemd/journald.conf.d/60-rosy.conf",
])
def test_never_writes_outside_the_four_image_directories(relative):
    with pytest.raises(sync_mod.SyncError, match="IMAGE_LAYER_DESTINATION"):
        sync_mod.check_destination(relative)


def test_apply_touches_only_allowlisted_paths_and_its_backup(device):
    before = _tree(device)

    _sync(device, NEW_ID, Runner(), dry_run=False)

    after = _tree(device)
    touched = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    allowed = sync_mod.ALLOWED_PREFIXES + (sync_mod.BACKUP_ROOT + "/",)
    assert touched and all(path.startswith(allowed) for path in touched), sorted(touched)
    for keep in ("etc/rosy/runtime.env", "boot/firmware/config.txt", "etc/sudoers.d/60-rosy-operator",
                 "usr/local/share/rosy/python-runtime.sha256", "etc/systemd/system/unrelated.service"):
        assert after[keep] == before[keep]


def _symlinks_work(tmp_path: Path) -> bool:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    return True


def test_a_masked_unit_is_skipped_not_unmasked(device, tmp_path):
    if not _symlinks_work(tmp_path):
        pytest.skip("symlinks are not available")
    unit = device / "etc/systemd/system/rosy-io.service"
    unit.unlink()
    unit.symlink_to("/dev/null")

    result = _sync(device, NEW_ID, Runner(), dry_run=False)

    assert unit.is_symlink()
    assert {"path": "/etc/systemd/system/rosy-io.service",
            "reason": "destination is a symlink (masked?)"} in result["skipped"]


def test_real_current_symlink_is_resolved(device, tmp_path):
    if not _symlinks_work(tmp_path):
        pytest.skip("symlinks are not available")
    (device / "opt/rosy/current").symlink_to(f"releases/{NEW_ID}", target_is_directory=True)

    release_id, _ = sync_mod.resolve_current(device)

    assert release_id == NEW_ID


def test_an_older_release_without_image_layer_files_skips_them(device):
    shutil.rmtree(device / "opt/rosy/releases" / NEW_ID / "deploy/robot/native/image-layer")

    result = _sync(device, NEW_ID, Runner(), dry_run=True)

    reasons = {entry["path"]: entry["reason"] for entry in result["skipped"]}
    assert reasons["/etc/udev/rules.d"] == "release has no image-layer/udev"
    assert reasons["/etc/modprobe.d"] == "release has no image-layer/modprobe"
    assert not any(path.startswith("/etc/udev/") for path in result["new"] + result["changed"])


# --- the real CLI against a signed release -------------------------------------------


def _signed_release(tmp_path: Path, device: Path) -> Path:
    from build_payload_release import build_release

    private = tmp_path / "keys/test.key"
    public = device / sync_mod.DEFAULT_PUBLIC_KEY
    private.parent.mkdir(parents=True)
    public.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    payload = tmp_path / "payload"
    for relative, content in {
        "install/.rosy-release": NEW_ID + "\n",
        "rosy-packages.txt": "core\n",
        "source-revision.txt": "b" * 40 + "\n",
        "python-runtime.sha256": "1" * 64 + "\n",
    }.items():
        (payload / relative).parent.mkdir(parents=True, exist_ok=True)
        (payload / relative).write_text(content, encoding="utf-8")
    _install(payload / "deploy/robot/native")
    release = device / "opt/rosy/releases" / NEW_ID
    if release.exists():
        shutil.rmtree(release)
    build_release(payload, NEW_ID, release, signing_key_id=public.stem)
    sums = (release / "SHA256SUMS").read_bytes()
    (release / "SHA256SUMS.sig").write_text(sign_checksums(sums, private) + "\n", encoding="ascii")
    return release


def _main(device: Path, *argv: str, runner: Runner) -> tuple[int, dict]:
    import contextlib
    import io

    is_link, readlink = _links(device, NEW_ID)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = sync_mod.main(["--root", str(device), *argv], runner=runner, is_link=is_link, readlink=readlink)
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


def test_cli_verifies_the_signed_release_then_syncs(device, tmp_path):
    release = _signed_release(tmp_path, device)

    code, plan = _main(device, "--dry-run", runner=Runner())
    assert code == 0, plan
    assert plan["release_id"] == NEW_ID and plan["new"]
    code, applied = _main(device, runner=Runner())
    assert code == 0, applied
    assert applied["backup_dir"]
    # The sync imported native_release/signing from the release: no bytecode left there.
    assert not list(release.rglob("__pycache__"))


def test_cli_refuses_a_tampered_release_and_writes_nothing(device, tmp_path):
    release = _signed_release(tmp_path, device)
    unit = release / "deploy/robot/native/rosy-io.service"
    unit.write_text(unit.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    before = _tree(device)

    code, result = _main(device, runner=Runner())

    assert code == 1 and result["ok"] is False
    assert _tree(device) == before


# --- the payload carries the image-layer sources -------------------------------------


@needs_bash
def test_payload_release_carries_udev_and_modprobe_and_old_verify_accepts_it(tmp_path):
    from deploy.robot.pinky_pro.native.native_release import NativeReleaseManager

    device = tmp_path / "device"
    device.mkdir()
    release = _signed_release(tmp_path, device)
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    listed = {entry["path"] for entry in manifest["files"]}

    for name in ("99-rosy-motor.rules", "99-rosy-display.rules", "99-rosy-lamp.rules"):
        assert f"deploy/robot/native/image-layer/udev/{name}" in listed
    assert "deploy/robot/native/image-layer/modprobe/rosy-ws281x.conf" in listed
    assert "deploy/robot/native/sync-image-layer.py" in listed
    assert not any(Path(path).name in {"manifest.json", "SHA256SUMS", "SHA256SUMS.sig"} for path in listed)
    # The robot's image-resident native_release.py hashes every non-metadata file.
    key = device / sync_mod.DEFAULT_PUBLIC_KEY
    NativeReleaseManager(root=device, public_key=key).verify(NEW_ID)
