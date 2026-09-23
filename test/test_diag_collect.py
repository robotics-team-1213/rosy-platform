"""L2 on-device diagnostics bundle (D-175 Task 4).

``rosy-diag collect`` builds one bounded tar.gz an operator pulls over SSH. Every
member goes through the shared redaction module, denied paths are never read,
and ``manifest.json`` carries hashes and the correlation keys. A fake command
runner and a fixture root stand in for the device; the installed-layout test
proves the tool imports from ``/opt/rosy/native-runtime`` without the repository.

Fixture secrets are assembled at runtime so this file stays clean for the
tracked-file secret scan.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "native"
sys.path.insert(0, str(ROOT / "deploy" / "release"))
from secret_scan import scan_text  # noqa: E402

BASH = shutil.which("bash")
BOOT_ID = "23fe37a5e32a4462bd07ec95dc392a06"
WIFI_VALUE = "site" + "-wifi-" + "pass-7731"
TOKEN_VALUE = "Qm7" + "x2LkT9vRw4" + "Bc8De1Fg5Hi7Jk0Lm6No9Pq2Rs"
DENIED_MARK = "denied-" + "content-4411"


def _module():
    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location("rosy_diag_collect", NATIVE / "rosy_diag_collect.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _device(tmp_path: Path) -> Path:
    root = tmp_path / "device"
    files = {
        "proc/sys/kernel/random/boot_id": BOOT_ID + "\n",
        "proc/uptime": "42.50 80.00\n",
        "etc/hostname": "rosy-pinky-e4us\n",
        "etc/rosy/device-identity.json": json.dumps({"device_name": "rosy-pinky-e4us", "device_uid": "u-18"}),
        "var/lib/rosy/provisioning/state.json": json.dumps({"state": "PROVISIONED", "wifi_" + "passphrase": WIFI_VALUE}),
        "var/lib/rosy/provisioning/result.json": json.dumps({"ok": True}),
        "var/lib/rosy/provisioning/pairing-token.json": DENIED_MARK,
        "var/lib/rosy/releases/native-activation.json": json.dumps({"schema_version": 1, "operation": "activate", "candidate": "2026.09.23-004",
                                                                   "phase": "switched"}),
        "boot/firmware/rosy-diag/latest.txt": "stage:    FAILED: rosy-release-recover\nNo module named 'signing'\n",
        "boot/firmware/rosy-diag/boot-000001-23fe37a5.json": json.dumps({"stage": "FAILED"}),
        "boot/firmware/rosy-provision/provision.json": DENIED_MARK,
        "etc/NetworkManager/system-connections/site.nmconnection": "psk=" + DENIED_MARK,
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    releases = root / "opt/rosy/releases/2026.09.23-004"
    releases.mkdir(parents=True)
    try:
        os.symlink(releases, root / "opt/rosy/current")
    except OSError:
        pass  # Windows without symlink rights: release_id is then unknown
    return root


class FakeRunner:
    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.outputs = outputs or {}

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        key = argv[0]
        if key in self.outputs:
            return 0, self.outputs[key]
        if key == "journalctl":
            return 0, (
                "[    7.964660] ubuntu recover-release.sh[504]: ModuleNotFoundError: No module named 'signing'\n"
                "[    8.1] ubuntu rosy-core[600]: Authorization: Bearer " + TOKEN_VALUE + "\n"
                "[    8.2] ubuntu rosy-sd-provision[300]: applying p" + "sk=" + WIFI_VALUE + "\n"
            )
        if key == "systemctl":
            return 3, "x rosy-release-recover.service - ROSY release recovery\n   Active: failed (Result: exit-code)\n"
        if key == "nmcli":
            return 0, "yes:RosySite:74\n"
        if key == "ip":
            return 0, "wlan0 UP 192.168.1.201/24\n"
        if key == "dmesg":
            return 0, "".join(f"[{n}.0] line {n}\n" for n in range(2000))
        return 127, f"{key}: command not found\n"


def _members(bundle: Path) -> dict[str, str]:
    with tarfile.open(bundle, "r:gz") as archive:
        return {
            member.name: archive.extractfile(member).read().decode("utf-8")
            for member in archive.getmembers() if member.isfile()
        }


def test_the_bundle_has_every_planned_member_and_the_root_cause(tmp_path):
    module = _module()
    bundle = module.collect(_device(tmp_path), FakeRunner(), tmp_path / "out")

    members = _members(bundle)

    for name in ("manifest.json", "journal/rosy-units.txt", "systemd/status.txt", "systemd/units.txt",
                 "provisioning/state.json", "provisioning/result.json", "release/native-activation.json",
                 "kernel/dmesg-tail.txt", "network/addresses.txt", "network/devices.txt", "network/wifi.txt",
                 "blackbox/latest.txt", "blackbox/boot-000001-23fe37a5.json"):
        assert name in members, name
    assert "No module named 'signing'" in members["journal/rosy-units.txt"]
    assert "FAILED: rosy-release-recover" in members["blackbox/latest.txt"]
    assert "RosySite" in members["network/wifi.txt"]
    assert members["kernel/dmesg-tail.txt"].count("\n") <= module.DMESG_LINES + 1
    assert "line 1999" in members["kernel/dmesg-tail.txt"]


def test_every_member_is_redacted_and_passes_the_repository_scanner(tmp_path):
    bundle = _module().collect(_device(tmp_path), FakeRunner(), tmp_path / "out")

    for name, text in _members(bundle).items():
        assert WIFI_VALUE not in text, name
        assert TOKEN_VALUE not in text, name
        assert DENIED_MARK not in text, name
        assert scan_text(f"evidence/{name}", text) == [], name


def test_denied_paths_are_never_read_and_are_listed(tmp_path, monkeypatch):
    module = _module()
    root = _device(tmp_path)
    opened: list[str] = []
    real = Path.read_bytes

    def spy(self):
        opened.append(self.as_posix())
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    bundle = module.collect(root, FakeRunner(), tmp_path / "out")
    monkeypatch.undo()

    assert not [path for path in opened if "pairing-token" in path or "rosy-provision" in path
                or "NetworkManager" in path]
    manifest = json.loads(_members(bundle)["manifest.json"])
    assert "/var/lib/rosy/provisioning/pairing-token.json" in manifest["denied"]


def test_the_manifest_hashes_members_and_carries_the_correlation_keys(tmp_path):
    bundle = _module().collect(_device(tmp_path), FakeRunner(), tmp_path / "out")

    members = _members(bundle)
    manifest = json.loads(members["manifest.json"])

    correlation = manifest["correlation"]
    assert correlation["boot_id"] == BOOT_ID
    assert correlation["device_name"] == "rosy-pinky-e4us"
    linked = (tmp_path / "device/opt/rosy/current").is_symlink()
    assert correlation["release_id"] == ("2026.09.23-004" if linked else None)
    assert correlation["uptime_s"] == 42.5
    listed = {item["name"]: item for item in manifest["members"]}
    assert set(listed) == set(members) - {"manifest.json"}
    for name, item in listed.items():
        assert item["sha256"] == hashlib.sha256(members[name].encode("utf-8")).hexdigest(), name
    assert listed["systemd/status.txt"]["returncode"] == 3
    assert bundle.name.startswith(f"rosy-diag-rosy-pinky-e4us-{BOOT_ID[:8]}-")
    assert bundle.name.endswith(".tar.gz")


def test_a_missing_command_is_recorded_not_fatal(tmp_path):
    runner = FakeRunner()
    bundle = _module().collect(_device(tmp_path), lambda argv: (127, "not found") if argv[0] == "dmesg"
                               else runner(argv), tmp_path / "out")

    manifest = json.loads(_members(bundle)["manifest.json"])
    dmesg = next(item for item in manifest["members"] if item["name"] == "kernel/dmesg-tail.txt")
    assert dmesg["returncode"] == 127


def test_the_bundle_is_bounded_and_keeps_the_newest_journal_lines(tmp_path, monkeypatch):
    module = _module()
    assert module.TOTAL_CAP_BYTES == 50 * 1024 * 1024
    monkeypatch.setattr(module, "TOTAL_CAP_BYTES", 256 * 1024)
    monkeypatch.setattr(module, "MEMBER_CAP_BYTES", 128 * 1024)
    monkeypatch.setattr(module, "MANIFEST_RESERVE_BYTES", 16 * 1024)
    journal = "".join(f"[{n}.0] rosy-core[1]: ordinary line {n:07d}\n" for n in range(40000))
    runner = FakeRunner({"journalctl": journal, "dmesg": "x\n" * 10})

    bundle = module.collect(_device(tmp_path), runner, tmp_path / "out")

    members = _members(bundle)
    assert sum(len(text.encode("utf-8")) for text in members.values()) <= 256 * 1024
    assert len(members["manifest.json"].encode("utf-8")) <= 16 * 1024
    assert "ordinary line 0039999" in members["journal/rosy-units.txt"]
    assert "ordinary line 0000000" not in members["journal/rosy-units.txt"]
    manifest = json.loads(members["manifest.json"])
    journal_item = next(item for item in manifest["members"] if item["name"] == "journal/rosy-units.txt")
    assert journal_item["truncated"] is True


def test_an_existing_bundle_is_never_overwritten(tmp_path, monkeypatch):
    module = _module()
    root = _device(tmp_path)
    first = module.collect(root, FakeRunner(), tmp_path / "out")
    before = first.read_bytes()

    monkeypatch.setattr(module, "_bundle_name", lambda *args: first.name)
    with pytest.raises(FileExistsError):
        module.collect(root, FakeRunner(), tmp_path / "out")
    assert first.read_bytes() == before


def test_the_journal_is_the_current_boot_of_rosy_units_only(tmp_path):
    runner = FakeRunner()
    _module().collect(_device(tmp_path), runner, tmp_path / "out")

    journal = next(call for call in runner.calls if call[0] == "journalctl")
    assert "-b" in journal and "rosy-*" in journal
    assert not any("-s" == part or "--show-secrets" in part for call in runner.calls for part in call)


def test_the_cli_prints_the_bundle_and_its_correlation(tmp_path):
    root = _device(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-B", str(NATIVE / "rosy_diag_collect.py"), "collect", "--root", str(root),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert Path(result["bundle"]).is_file()
    assert result["boot_id"] == BOOT_ID
    assert result["device_name"] == "rosy-pinky-e4us"


def test_the_rosy_diag_wrapper_runs_the_collector_without_bytecode():
    text = (NATIVE / "rosy-diag").read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env bash\n")
    assert "\r" not in text
    assert 'exec python3 -B "$SCRIPT_DIR/rosy_diag_collect.py" "$@"' in text
    assert "readlink -f" in text  # works through a symlink on PATH


def test_the_collector_uses_only_the_standard_library_and_the_shared_redaction():
    import ast

    tree = ast.parse((NATIVE / "rosy_diag_collect.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module}
    allowed = set(sys.stdlib_module_names) | {"rosy_diag_redact", "__future__"}
    assert imported <= allowed, imported - allowed
    assert "rosy_diag_redact" in imported


@pytest.mark.skipif(BASH is None, reason="bash is required to run the installer")
def test_the_collector_runs_from_the_installed_native_runtime(tmp_path):
    runtime = tmp_path / "device/opt/rosy/native-runtime"
    completed = subprocess.run(
        [BASH, (NATIVE / "install-native-runtime.sh").as_posix(), runtime.as_posix()],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    root = _device(tmp_path / "fixture")
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONNOUSERSITE"] = "1"

    completed = subprocess.run(
        [sys.executable, "-B", str(runtime / "rosy_diag_collect.py"), "collect", "--root", str(root),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=tmp_path, env=env,
    )

    assert "No module named" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    assert (runtime / "rosy-diag").is_file()
    assert not list(runtime.rglob("__pycache__"))
    bundle = Path(json.loads(completed.stdout)["bundle"])
    with tarfile.open(bundle, "r:gz") as archive:
        assert "manifest.json" in archive.getnames()


def test_members_are_plain_files_with_safe_names(tmp_path):
    bundle = _module().collect(_device(tmp_path), FakeRunner(), tmp_path / "out")

    with tarfile.open(bundle, "r:gz") as archive:
        for member in archive.getmembers():
            assert member.isfile(), member.name
            assert not member.name.startswith("/") and ".." not in member.name.split("/")
            assert member.mode == 0o644


@pytest.mark.skipif(BASH is None or os.name == "nt", reason="needs a POSIX bash with readlink -f")
def test_the_wrapper_resolves_its_own_directory_through_a_symlink(tmp_path):
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "python3").write_text('#!/bin/sh\necho "$@"\n', encoding="utf-8")
    (shim / "python3").chmod(0o755)
    link = tmp_path / "rosy-diag"
    link.symlink_to(NATIVE / "rosy-diag")

    completed = subprocess.run([BASH, str(link), "collect", "--out", "/tmp/x"], capture_output=True, text=True,
                               env={**os.environ, "PATH": f"{shim}:{os.environ.get('PATH', '')}"})

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["-B", str(NATIVE.resolve() / "rosy_diag_collect.py"), "collect", "--out",
                                        "/tmp/x"]
