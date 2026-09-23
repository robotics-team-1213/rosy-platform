"""D-179 bench overlay stays on the allowlist and off the release tree."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "deploy" / "robot" / "core_dev_overlay.py"

import importlib.util

SPEC = importlib.util.spec_from_file_location("core_dev_overlay", OVERLAY)
assert SPEC and SPEC.loader
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)

CORE = "/opt/rosy_ws/install/lib/python3.12/site-packages/core"
SHARE = "/opt/rosy_ws/install/share/web_common"
NATIVE_CORE = "/opt/rosy/current/install/lib/python3.12/site-packages/core"
NATIVE_SHARE = "/opt/rosy/current/install/share/web_common"


def _tar(tmp_path: Path, members: dict[str, bytes | None]) -> Path:
    path = tmp_path / "overlay.tar"
    with tarfile.open(path, "w") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            if payload is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "somewhere"
                tar.addfile(info)
            else:
                data = payload
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return path


def _good(tmp_path: Path) -> Path:
    return _tar(tmp_path, {"python/core/__init__.py": b"overlay\n", "share/web_common/tokens.css": b"ok"})


def test_stage_writes_only_allowlisted_files(tmp_path: Path):
    dest = tmp_path / "var" / "lib" / "rosy-dev"
    written = overlay.stage_overlay(_good(tmp_path), dest)
    assert written == ["python/core/__init__.py", "share/web_common/tokens.css"]
    assert (dest / "python" / "core" / "__init__.py").read_bytes() == b"overlay\n"


@pytest.mark.parametrize(
    "name,payload",
    [
        ("python/core/__pycache__/__init__.cpython-312.pyc", b"pyc"),
        ("python/core/node.pyc", b"pyc"),
        ("deploy/robot/.env", b"TOKEN=1\n"),
        ("etc/rosy/rosy.yaml", b"token: 1\n"),
        ("python/interfaces/Foo.srv", b"string x\n"),
        ("../etc/passwd", b"root\n"),
        ("/tmp/core/__init__.py", b"x"),
        ("python/not_core/__init__.py", b"x"),
    ],
)
def test_bad_member_writes_nothing(tmp_path: Path, name: str, payload: bytes):
    dest = tmp_path / "rosy-dev"
    archive = _tar(tmp_path, {"python/core/__init__.py": b"keep", name: payload})
    with pytest.raises(overlay.OverlayError):
        overlay.stage_overlay(archive, dest)
    assert not dest.exists()


def test_symlink_member_writes_nothing(tmp_path: Path):
    dest = tmp_path / "rosy-dev"
    archive = _tar(tmp_path, {"python/core/__init__.py": b"keep", "python/core/link.py": None})
    with pytest.raises(overlay.OverlayError):
        overlay.stage_overlay(archive, dest)
    assert not dest.exists()


@pytest.mark.parametrize("dest", [Path("/opt/rosy"), Path("/opt/rosy/rosy-dev"), Path("/tmp/other")])
def test_destination_outside_rosy_dev_is_refused(tmp_path: Path, dest: Path):
    with pytest.raises(overlay.OverlayError):
        overlay.stage_overlay(_good(tmp_path), dest)


def test_marker_is_schema_1_without_secrets(tmp_path: Path):
    document = overlay.build_marker(backend="docker", git_revision="uncommitted", dirty=True, synced_at="2026-09-23T00:00:00+00:00")
    path = tmp_path / "dev-overlay.json"
    overlay.write_marker(path, document)
    assert set(document) == set(overlay.MARKER_FIELDS)
    with pytest.raises(overlay.OverlayError):
        overlay.validate_marker({**document, "admin_token": "nope"})
    assert "admin_token" not in path.read_text(encoding="utf-8")


def test_bind_pairs_follow_the_running_install():
    pairs = dict(overlay.bind_pairs(CORE, SHARE))
    assert pairs[f"{overlay.DEV_ROOT}/python/core"] == CORE
    assert pairs[f"{overlay.DEV_ROOT}/python/core_features"].endswith("/site-packages/core_features")
    assert pairs[f"{overlay.DEV_ROOT}/share/web_common/tokens.css"] == f"{SHARE}/tokens.css"
    native = dict(overlay.bind_pairs(NATIVE_CORE, NATIVE_SHARE))
    assert native[f"{overlay.DEV_ROOT}/python/core_api_web"].startswith("/opt/rosy/current/install/")


@pytest.mark.parametrize(
    "core_dir,share",
    [
        ("/tmp/site-packages/core", "/tmp/share/web_common"),
        ("/home/rosy/install/lib/python3.12/site-packages/core", "/home/rosy/install/share/web_common"),
        ("/opt/rosy/site-packages/core", "/opt/rosy/share/web_common"),
        ("/opt/rosy_ws/install/lib/python3.12/site-packages/core_features", "/opt/rosy_ws/install/share/web_common"),
        (CORE, "/opt/rosy/current/install/share/web_common"),
    ],
)
def test_bind_discovery_rejects_foreign_prefixes(core_dir: str, share: str):
    with pytest.raises(overlay.OverlayError):
        overlay.bind_pairs(core_dir, share)


def test_confirm_loaded_accepts_only_the_staged_hash(tmp_path: Path):
    staged = tmp_path / "__init__.py"
    staged.write_bytes(b"overlay\n")
    digest = hashlib.sha256(b"overlay\n").hexdigest()

    def good(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(command, 0, f"{digest}  file\n", "")

    overlay.confirm_loaded(staged, f"{CORE}/__init__.py", "core-container", good)

    def bad(command, **kwargs):
        del kwargs
        return subprocess.CompletedProcess(command, 0, f"{'ab' * 32}  file\n", "")

    with pytest.raises(overlay.OverlayError):
        overlay.confirm_loaded(staged, f"{CORE}/__init__.py", "core-container", bad)


def test_success_is_the_file_bytes_not_the_path():
    assert overlay.overlay_bytes_match(b"same", b"same")
    assert not overlay.overlay_bytes_match(b"overlay", b"image")


def test_compose_fragment_keeps_the_product_project():
    pairs = overlay.bind_pairs(CORE, SHARE)
    text = overlay.render_compose_yaml(pairs)
    assert "name:" not in text
    assert "compose.override.yaml" not in text
    fresh = overlay.compose_argv(binds_attached=False, motor_or_hardware_running=False)
    again = overlay.compose_argv(binds_attached=True, motor_or_hardware_running=False)
    assert fresh[:8] == [
        "docker", "compose", "--env-file", overlay.ENV_FILE,
        "-p", "rosy-runtime", "-f", overlay.COMPOSE_FILE,
    ]
    assert fresh[8:10] == ["-f", overlay.DEV_COMPOSE]
    assert fresh[-5:] == ["up", "-d", "--no-build", "--no-deps", "rosy-core"]
    assert again[-2:] == ["restart", "rosy-core"]
    assert "up" not in again
    joined = " ".join(fresh + again)
    assert "verify-pi.sh" not in joined
    assert "--require-internet" not in joined
    assert "90" not in joined
    with pytest.raises(overlay.OverlayError):
        overlay.compose_argv(binds_attached=True, motor_or_hardware_running=True)


def test_runtime_mode_does_not_load_the_dev_compose():
    text = (ROOT / "deploy" / "robot" / "runtime-mode.sh").read_text(encoding="utf-8")
    assert "core-dev" not in text
    assert "compose.override.yaml" not in text


def test_native_dropin_does_not_replace_the_product_exec():
    text = overlay.render_native_dropin(overlay.bind_pairs(NATIVE_CORE, NATIVE_SHARE))
    assert "BindReadOnlyPaths=/var/lib/rosy-dev/python/core:" in text
    assert "ExecStart=" not in text
    assert "WorkingDirectory=" not in text
    unit = (ROOT / "deploy" / "robot" / "native" / "rosy-core.service").read_text(encoding="utf-8")
    assert "rosy-dev" not in unit
    assert "BindReadOnlyPaths" not in unit


def test_clear_removes_only_the_overlay_files(tmp_path: Path):
    root = tmp_path
    marker = root / "etc" / "rosy" / "dev-overlay.json"
    dropin = root / "etc" / "systemd" / "system" / "rosy-core.service.d" / "dev-overlay.conf"
    compose = root / "var" / "lib" / "rosy-dev" / "compose.dev.yaml"
    env = root / "opt" / "rosy" / "deploy" / "robot" / ".env"
    config = root / "etc" / "rosy" / "rosy.yaml"
    for path, text in ((marker, "{}\n"), (dropin, "[Service]\n"), (compose, "services:\n"), (env, "TOKEN=1\n"), (config, "ok\n")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    removed = overlay.clear_overlay(root)
    assert marker.name in "".join(removed)
    assert not marker.exists()
    assert not dropin.exists()
    assert not compose.exists()
    assert env.read_text(encoding="utf-8") == "TOKEN=1\n"
    assert config.read_text(encoding="utf-8") == "ok\n"


def test_windows_sync_script_is_the_narrow_transport():
    text = (ROOT / "deploy" / "robot" / "sync-core-dev.ps1").read_text(encoding="utf-8")
    assert "-PiHost" in text and "-PiUser" in text and "-Backend" in text
    assert "RobotNumber" not in text
    for forbidden in (
        "install-pi.sh",
        "apt-get",
        "docker compose build",
        "reboot",
        "git pull",
        "StrictHostKeyChecking=no",
        "rsync --delete",
    ):
        assert forbidden not in text


def test_shell_wrappers_only_call_the_python_module():
    apply = (ROOT / "deploy" / "robot" / "apply-core-dev.sh").read_text(encoding="utf-8")
    clear = (ROOT / "deploy" / "robot" / "clear-core-dev.sh").read_text(encoding="utf-8")
    for text in (apply, clear):
        assert "python3 -B" in text
        assert "core_dev_overlay.py" in text
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("echo ") or stripped.startswith("#"):
                continue
            assert "reboot" not in stripped
            assert "systemctl restart rosy-runtime" not in stripped
    assert overlay.REBOOT_NOTE in apply
    assert "render_native_dropin" not in apply
    assert "--backend" in apply or "core_dev_overlay.py" in apply
