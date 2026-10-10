"""D-553 addendum 4: tools/release/ship.py and the robot side it sends (tools/release/ship_remote.sh).

The robot side runs for real against a scratch root (ROSY_SHIP_ROOT): the repo's
rosy-release-unpack.sh hard-links the base, native_release.py verifies the whole
rebuilt release with a test key and switches the links; only systemctl and the
CORE readiness probe are stubs.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "release"))
_SPEC = importlib.util.spec_from_file_location("ship", ROOT / "tools" / "release" / "ship.py")
ship = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ship)

CONTROL = ROOT / "middleware" / "perception" / "control"
PY = "install/lib/python3.12/site-packages/control/"


@pytest.mark.parametrize("changed, expected", [
    ([PY + "sensing/perception/learned/drivable_steer.py", PY + "line_observer_node.py", "manifest.json",
      "install/.rosy-release"], ("camera", False)),
    ([PY + "sensing/perception/learned/drivable_steer.py", PY + "sensing/body.py"], ("full", False)),
    ([PY + "ir_adc_node.py"], ("full", False)),
    (["install/share/control/launch/camera_preview.launch.py"], ("full", False)),
    (["deploy/robot/native/rosy-camera.service"], ("full", True)),
    (["manifest.json", "SHA256SUMS"], ("full", False)),
])
def test_restart_scope(changed, expected):
    assert ship.scope(changed) == expected


def _imports(module: str, seen: set[str]) -> set[str]:
    """Static closure of control.* modules a control module imports (relative or absolute)."""
    if module in seen:
        return seen
    seen.add(module)
    parts = module.split(".")[1:]
    path = CONTROL.joinpath(*parts).with_suffix(".py")
    if not path.is_file():
        path = CONTROL.joinpath(*parts, "__init__.py")
    if not path.is_file():
        return seen
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    for parent in (package[:i] for i in range(1, len(package) + 1)):
        _imports(".".join(parent), seen)
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            base = package[:len(package) - node.level + 1] if node.level else []
            target = ".".join(base + (node.module.split(".") if node.module else []))
            if target.split(".")[0] == "control":
                _imports(target, seen)
                for alias in node.names:
                    _imports(f"{target}.{alias.name}", seen)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "control":
                    _imports(alias.name, seen)
    return seen


def test_rosy_io_control_node_never_loads_camera_only_code():
    loaded = {
        PY + (m.removeprefix("control.").replace(".", "/")) + suffix
        for m in _imports("control.ir_adc_node", set()) for suffix in (".py", "/")
    }
    assert PY + "ir_adc_node.py" in loaded
    assert not [p for p in loaded if p.startswith(ship.CAMERA_ONLY)]


def test_core_never_imports_control():
    offenders = []
    for path in (ROOT / "middleware" / "core").rglob("*.py"):
        if "test" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
            offenders += [f"{path}: {n}" for n in names if n.split(".")[0] == "control"]
    assert offenders == []


def test_camera_launch_starts_every_camera_only_node():
    launch = (ROOT / "middleware" / "perception" / "launch" / "camera_preview.launch.py").read_text(encoding="utf-8")
    nodes = [p.removeprefix(PY).removesuffix(".py") for p in ship.CAMERA_ONLY if p.endswith(".py")]
    assert nodes and all(f"executable='{n}'" in launch for n in nodes)


# --- the robot side, end to end against a scratch root ---------------------

BASH = shutil.which("bash")
OPENSSL = shutil.which("openssl")
PYTHON3 = shutil.which("python3")
robot = pytest.mark.skipif(os.name == "nt" or not (BASH and OPENSSL and PYTHON3),
                           reason="needs Linux bash, openssl and python3 (the robot side)")
BASE, NEW = "2026.10.10-001", "2026.10.10-002"
STEER = PY + "sensing/perception/learned/drivable_steer.py"
RUNTIME = "1" * 64


def _signed(directory: Path, release_id: str, files: dict[str, bytes], private: Path) -> None:
    import signing
    for relative, data in files.items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_bytes(data)
    manifest = {"schema_version": 1, "release_id": release_id, "git_revision": "a" * 40,
                "target": {"board": "pinky_pro", "host": "raspberry-pi-5", "architecture": "arm64",
                           "os_family": "ubuntu-server", "os_release": "24.04"},
                "runtime": {"model": "native-systemd", "default_mode": "core"},
                "signing_key_id": "rosy-release-2026-01",
                "files": [{"path": p, "sha256": hashlib.sha256(d).hexdigest()} for p, d in sorted(files.items())]}
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    (directory / "manifest.json").write_bytes(manifest_bytes)
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {p}\n"
                   for p, d in sorted({**files, "manifest.json": manifest_bytes}.items())).encode()
    (directory / "SHA256SUMS").write_bytes(sums)
    (directory / "SHA256SUMS.sig").write_text(signing.sign_checksums(sums, private) + "\n")


@pytest.fixture
def device(tmp_path: Path):
    import make_delta_release
    keys = tmp_path / "keys"
    keys.mkdir()
    private, public = keys / "k.pem", keys / "rosy-release-2026-01.pem"
    subprocess.run([OPENSSL, "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True, capture_output=True)
    subprocess.run([OPENSSL, "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, capture_output=True)
    root = tmp_path / "root"
    files = {"install/.rosy-release": f"{BASE}\n".encode(), "rosy-packages.txt": b"core\ncontrol\n",
             "source-revision.txt": b"a" * 40 + b"\n", "python-runtime.sha256": RUNTIME.encode() + b"\n",
             "deploy/robot/native/rosy-runtime.target": b"[Unit]\n", STEER: b"old steer\n",
             PY + "sensing/body.py": b"body\n"}
    _signed(root / "opt/rosy/releases" / BASE, BASE, files, private)
    (root / "opt/rosy/current").symlink_to(root / "opt/rosy/releases" / BASE)
    (root / "usr/local/share/rosy").mkdir(parents=True)
    (root / "usr/local/share/rosy/python-runtime.sha256").write_text(RUNTIME + "\n")
    runtime = root / "opt/rosy/native-runtime"
    runtime.mkdir(parents=True)
    native = ROOT / "deploy/robot/pinky_pro/native"
    for name in ("native_release.py", "activate-release.sh"):
        shutil.copy2(native / name, runtime / name)
    shutil.copy2(ROOT / "deploy/robot/pinky_pro/release/signing.py", runtime / "signing.py")
    (runtime / "wait-core-ready.py").write_text("print('ready stub')\n")
    # The new release, then only its delta members, packed the way make_delta_release does.
    new = tmp_path / "new"
    _signed(new, NEW, {**files, "install/.rosy-release": f"{NEW}\n".encode(), STEER: b"new steer\n"}, private)
    members = ["install/.rosy-release", STEER, "manifest.json", "SHA256SUMS", "SHA256SUMS.sig"]
    marker = f"{BASE}\n{hashlib.sha256((root / 'opt/rosy/releases' / BASE / 'SHA256SUMS').read_bytes()).hexdigest()}\n"
    tarball = tmp_path / f"{NEW}.tar.gz"
    make_delta_release.pack_delta(new, members, {}, marker.encode(), tarball)
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "systemctl").write_text(
        '#!/bin/sh\necho "$*" >> "$SYSTEMCTL_LOG"\n'
        'case "$*" in show*) echo 0;; *"is-active --quiet rosy-navigation"*) exit 3;;\n'
        '  *"is-active --quiet rosy-io"*) exit 3;;\n'
        '  *"is-active --quiet rosy-camera"*) [ -z "$CAMERA_DIES" ];; esac\n')
    (stub / "systemctl").chmod(0o755)
    return tmp_path, root, public, tarball


def _ship(case, mode: str, **env) -> tuple[subprocess.CompletedProcess, list[str]]:
    tmp_path, root, public, tarball = case
    log = tmp_path / "systemctl.log"
    log.write_text("")
    stdin = ship.remote_stdin(NEW, BASE, tarball, mode, False, "ship-test")
    completed = subprocess.run([BASH, "-s"], input=stdin, capture_output=True, timeout=120, env={
        **os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "ROSY_SHIP_ROOT": str(root),
        "ROSY_RELEASE_PUBLIC_KEY": str(public), "SYSTEMCTL_LOG": str(log), **env})
    return completed, log.read_text().splitlines()


@robot
def test_camera_mode_rebuilds_on_hard_links_and_restarts_only_the_camera(device):
    completed, calls = _ship(device, "camera")
    out = completed.stdout.decode()
    assert completed.returncode == 0, out + completed.stderr.decode()
    assert f"SHIP_OK release={NEW} mode=camera" in out
    root = device[1]
    new, base = root / "opt/rosy/releases" / NEW, root / "opt/rosy/releases" / BASE
    assert (root / "opt/rosy/current").resolve() == new.resolve()
    assert (root / "opt/rosy/previous").resolve() == base.resolve()
    assert (new / STEER).read_bytes() == b"new steer\n" and (base / STEER).read_bytes() == b"old steer\n"
    assert (new / PY / "sensing/body.py").stat().st_ino == (base / PY / "sensing/body.py").stat().st_ino
    assert [c for c in calls if c not in ("is-active --quiet rosy-core.service",
                                          "is-active --quiet rosy-navigation.service")] == [
        "stop rosy-camera.service", "start rosy-camera.service", "is-active --quiet rosy-camera.service"]
    assert "PHASE unpack" in out and "PHASE activate-camera" in out


@robot
def test_a_camera_that_dies_is_rolled_back_to_the_base(device):
    completed, calls = _ship(device, "camera", CAMERA_DIES="1")
    assert completed.returncode != 0 and b"SHIP_FAILED activate (camera; rolled back)" in completed.stdout
    assert (device[1] / "opt/rosy/current").resolve() == (device[1] / "opt/rosy/releases" / BASE).resolve()
    assert calls.count("start rosy-camera.service") == 2


@robot
def test_full_mode_restarts_the_runtime_and_waits_for_core(device):
    completed, calls = _ship(device, "full")
    out = completed.stdout.decode()
    assert completed.returncode == 0, out + completed.stderr.decode()
    assert f"SHIP_OK release={NEW} mode=full" in out and "ready stub" in out
    # a280ddd30 probes rosy-io before the stop; the stub reports it down (no settle wait).
    assert [c for c in calls if not c.startswith("is-active")][0].startswith(
        "stop rosy-runtime.target rosy-core.service")
    assert "start rosy-runtime.target" in calls


@robot
def test_camera_mode_falls_back_to_full_when_the_base_is_not_current(device):
    current = device[1] / "opt/rosy/current"
    other = device[1] / "opt/rosy/releases/2026.10.10-000"
    shutil.copytree(device[1] / "opt/rosy/releases" / BASE, other)
    current.unlink()
    current.symlink_to(other)
    completed, calls = _ship(device, "camera")
    assert completed.returncode == 0, completed.stdout.decode() + completed.stderr.decode()
    assert b"NOTE current release is not the base" in completed.stdout and b"mode=full" in completed.stdout
    assert "start rosy-runtime.target" in calls
