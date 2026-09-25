"""D-62: CORE is required; other slices are opt-in presets."""

import ast
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from robot_contracts import DEPLOY, ROOT, board, board_caps, hardware_packages

CORE = ROOT / "src" / "core"
FORBIDDEN = ("omx_adapter", "control.camera", "moveit")
sys.path.insert(0, str(ROOT / "src" / "contracts" / "core_common"))


def test_core_is_the_only_required_slice():
    data = board()
    assert data["slices"]["required"] == ["core"]
    available = set(data["slices"]["available"])
    assert available >= {"motor", "io", "nav", "vision", "omx", "ai"}
    assert "core" not in available


def test_core_slice_fallback_matches_board_presets():
    from core_common.domain.model import _SLICES_BY_MODE, slices_from_config

    presets = board()["presets"]
    default = yaml.safe_load(
        (ROOT / "src" / "runtime" / "core" / "config" / "rosy_default.yaml").read_text(encoding="utf-8")
    )
    yaml_presets = default["runtime"]["presets"]
    for mode, slices in presets.items():
        expected = tuple(slices)
        assert _SLICES_BY_MODE[mode] == expected
        assert tuple(yaml_presets[mode]) == expected
        assert slices_from_config({"runtime": {"mode": mode, "presets": yaml_presets}}) == expected


def test_presets_match_current_runtime_modes():
    presets = board()["presets"]
    assert presets["core"] == ["core"]
    assert presets["motor"] == ["core", "motor"]
    assert presets["hardware"] == ["core", "motor", "io", "nav"]
    for extra in ("vision", "omx", "ai"):
        assert extra not in presets["core"]
        assert extra not in presets["motor"]
        assert extra not in presets["hardware"]


def test_core_capabilities_do_not_advertise_optional_slices():
    caps = board_caps("core")
    assert caps["navigation"]["goal_navigation"] is False
    assert caps["swarm"]["follow"] is False
    vision = caps.get("vision") or {}
    omx = caps.get("omx") or {}
    ai = caps.get("ai") or {}
    assert vision.get("enabled", False) is False
    assert omx.get("enabled", False) is False
    assert ai.get("enabled", False) is False


def test_core_package_does_not_import_optional_slice_code():
    for path in CORE.rglob("*.py"):
        if "test" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        for name in names:
            for banned in FORBIDDEN:
                assert name != banned and not name.startswith(banned + "."), f"{path.name} imports {name}"


ALLOWED_CONTROL_IMPORTS = {"control_sensor_adapter.py"}


def test_only_control_sensor_adapter_imports_control():
    control_root = (CORE / "control").resolve()
    for path in CORE.rglob("*.py"):
        if "test" in path.parts or control_root in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names)
        hits = [n for n in names if n == "control" or n.startswith("control.")]
        if hits and path.name not in ALLOWED_CONTROL_IMPORTS:
            raise AssertionError(f"{path.relative_to(CORE)} imports {hits}")


def test_core_and_io_images_do_not_copy_hardware_packages():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    core = text.split("FROM runtime-common AS io-runtime")[0]
    assert "omx_adapter" not in core
    packages = hardware_packages()
    assert packages, "board.yaml hardware_packages is empty"
    for package in packages:
        assert package not in core
        assert f"COPY src/{package}" not in text


def test_core_dockerfile_does_not_copy_control_or_opencv():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    core = text.split("FROM runtime-common AS io-runtime")[0]
    assert "COPY src/runtime/control" not in core
    assert "python3-opencv" not in core


def _find_usable_bash():
    candidates = []
    if os.name == "nt":
        candidates.extend(
            (
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
            )
        )
    which = shutil.which("bash")
    if which:
        candidates.append(which)
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if os.name == "nt" and not Path(candidate).is_file():
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "true"],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


BASH = _find_usable_bash()
bash_only = pytest.mark.skipif(
    BASH is None,
    reason="bash required to source resolve-mode.sh",
)

RESOLVE_MODE = DEPLOY / "config" / "resolve-mode.sh"
INSTALLER = DEPLOY / "install-pi.sh"


def _resolve_slices(spec: str) -> subprocess.CompletedProcess:
    """Source the real resolver beside board.yaml.

    Windows drive paths are not something WSL/Git Bash can `source`; the
    runtime wrapper also loads resolve-mode.sh from this directory.
    """
    return subprocess.run(
        [
            BASH,
            "-c",
            f'source ./resolve-mode.sh; resolve_slices_to_mode "{spec}" ./board.yaml',
        ],
        cwd=str(RESOLVE_MODE.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@bash_only
def test_slices_core_motor_resolve_to_motor_mode():
    result = _resolve_slices("core,motor")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "motor"


@bash_only
def test_slices_motor_core_order_does_not_matter():
    result = _resolve_slices("motor,core")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "motor"


@bash_only
def test_slices_core_resolves_to_core_mode():
    result = _resolve_slices("core")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "core"


@bash_only
def test_slices_core_motor_io_nav_resolve_to_hardware_mode():
    result = _resolve_slices("nav,io,motor,core")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hardware"


@bash_only
def test_slices_missing_core_fail():
    result = _resolve_slices("motor")
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    assert "core" in result.stderr.lower()


@bash_only
def test_slices_core_omx_fail_as_not_installable():
    result = _resolve_slices("core,omx")
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    err = result.stderr.lower()
    assert "slice not installable yet" in err or "unknown slice" in err


@bash_only
def test_slices_unknown_name_is_refused():
    result = _resolve_slices("core,not-a-slice")
    assert result.returncode != 0
    assert result.stdout.strip() == ""
    err = result.stderr.lower()
    assert "slice not installable yet" in err or "unknown slice" in err


def test_installer_accepts_preset_and_slices_mutually_exclusive():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "--preset" in text
    assert "--slices" in text
    assert "mutually exclusive" in text
    assert "resolve_slices_to_mode" in text
    assert "resolve_runtime_mode" in text
    assert "ROSY_REQUESTED_PRESET" in text
    assert "ROSY_REQUESTED_SLICES" in text
    assert "write_install_runtime_selection" in text

    helper = text[
        text.index("write_install_runtime_selection() {") : text.index(
            "write_runtime_environment() {"
        )
    ]
    assert 'set_env_value "$env_file" ROSY_RUNTIME_MODE core' in helper
    assert "ROSY_REQUESTED_PRESET" in helper
    assert "ROSY_REQUESTED_SLICES" in helper
    assert "INSTALL_RUNTIME_MODE" not in helper

    env_fn = text[
        text.index("write_runtime_environment() {") : text.index("build_and_start_core() {")
    ]
    assert "write_install_runtime_selection" in env_fn
    assert "INSTALL_RUNTIME_MODE" not in env_fn

    start_fn = text[
        text.index("build_and_start_core() {") : text.index("enable_boot_service() {")
    ]
    assert 'ROSY_RUNTIME_MODE=core "$runtime_dir/runtime-mode.sh" down' in start_fn
    assert 'ROSY_RUNTIME_MODE=core "$runtime_dir/runtime-mode.sh" up' in start_fn

    main = text[text.index("main() {"):]
    assert "parse_install_cli" in main
    assert main.index("parse_install_cli") < main.index("write_runtime_environment")
    assert "PASS: Rosy core-only runtime is installed and healthy" in main
    assert "hardware runtime is installed" not in main.lower()


def _drive_install_cli(*args: str) -> subprocess.CompletedProcess:
    """Parse installer CLI and write the runtime-selection keys to a temp env."""
    quoted = " ".join(shlex.quote(a) for a in args)
    script = f"""
    set -euo pipefail
    lib="$(mktemp)"
    sed '$d' ./install-pi.sh > "$lib"
    # shellcheck disable=SC1090
    source "$lib"
    SCRIPT_DIR="$(pwd)"
    parse_install_cli {quoted}
    env_file="$(mktemp)"
    write_install_runtime_selection "$env_file"
    cat "$env_file"
    """
    return subprocess.run(
        [BASH, "-c", script],
        cwd=str(DEPLOY),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _env_map(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


@bash_only
def test_installer_preset_hardware_keeps_runtime_core_and_records_request():
    result = _drive_install_cli("--preset", "hardware")
    assert result.returncode == 0, result.stderr
    env = _env_map(result.stdout)
    assert env.get("ROSY_RUNTIME_MODE") == "core"
    assert env.get("ROSY_REQUESTED_PRESET") == "hardware"
    assert "ROSY_REQUESTED_SLICES" not in env


@bash_only
def test_installer_slices_core_motor_keep_runtime_core_and_record_slices():
    result = _drive_install_cli("--slices", "core,motor")
    assert result.returncode == 0, result.stderr
    env = _env_map(result.stdout)
    assert env.get("ROSY_RUNTIME_MODE") == "core"
    assert env.get("ROSY_REQUESTED_SLICES") == "core,motor"
    assert env.get("ROSY_RUNTIME_MODE") != "motor"


@bash_only
def test_installer_still_rejects_slices_without_core():
    result = _drive_install_cli("--slices", "motor")
    assert result.returncode != 0
    assert "core" in result.stderr.lower()


@bash_only
def test_installer_still_rejects_omx_slice():
    result = _drive_install_cli("--slices", "core,omx")
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "slice not installable yet" in err or "unknown slice" in err
