"""D-427 wave 0 item 5: the colcon source roots live in one manifest line.

``tools/harness/platform_parts.yaml`` holds ``colcon_roots``. Shell consumers
read it through ``tools/harness/colcon_roots.py``; Python consumers import that
reader or load the same key. These tests keep every consumer on that value and
pin the ROS package names the roots must yield while folders move.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "harness" / "platform_parts.yaml"
READER = ROOT / "tools" / "harness" / "colcon_roots.py"
COLCON_OUTPUT = {"build", "install", "log"}

#: The ROS package names on 2026-10-03 (WSL `colcon list --base-paths src --names-only`).
#: D-427 moves folders, never names: a move that renames, drops or duplicates one fails here.
FROZEN_ROS_PACKAGES = frozenset({
    "bringup", "control", "core", "core_api_web", "core_common", "core_events", "core_features",
    "dashboard", "description", "emotion", "fleet", "games", "gz_sim", "imu_bno055", "interfaces",
    "isaac_sim", "lamp_control", "led", "navigation", "omx", "omx_adapter", "pilot", "pinky_pro",
    "rosy_cell", "rosy_vision", "sensor_adc", "web_common",
})

#: Every tracked file whose colcon/rosdep lines run over the ROSY colcon roots. Value: a
#: pattern each such (non-comment) line must carry, so a second, bare call cannot slip in.
CONSUMERS = {
    ".github/workflows/ci.yml": r"--base-paths \$COLCON_ROOTS\b",
    ".github/workflows/arm64-rehearsal.yml": r"--base-paths \$COLCON_ROOTS\b",
    "tools/build_wsl.sh": r"--base-paths \$COLCON_ROOTS\b",
    "tools/sync_api_restart.sh": r"--base-paths \$COLCON_ROOTS\b",
    "tools/sync_rosy.sh": r"--base-paths \$COLCON_ROOTS\b",
    "tools/sync_rosy_fast.sh": r"--base-paths \$COLCON_ROOTS\b",
    "deploy/robot/pinky_pro/image/build-native-payload.sh":
        r'(--base-paths "\$\{COLCON_ROOTS\[@\]\}"|--from-paths "\$\{ROSDEP_ROOTS\[@\]\}")',
    # The roots arrive from build-image.sh (--colcon-roots); rosdep runs over the resolver's
    # closure of them. test_image_customization_contract.py runs the copy block.
    "deploy/robot/pinky_pro/image/customize-rootfs.sh": r'--from-paths "\$\{ROSDEP_SOURCE_PATHS\[@\]\}"',
}
#: Files with an invocation-looking line that does not run over the repo's colcon roots.
EXEMPT = {
    # Container workspaces built from per-package COPY lines; moves edit those COPY sources.
    "deploy/robot/pinky_pro/Dockerfile": "per-package COPY into /opt/rosy_ws",
    "deploy/robot/omx/Dockerfile": "upstream OMX sources in /opt/omx_ws",
    "contracts/foundation/core_common/profile.py": "error-message text",
    "middleware/perception/control/web_node.py": "docstring",
    "operations/fleet/package.xml": "XML comment",
    # Tests pin consumer text; none runs colcon or rosdep.
    "test/architecture/test_colcon_roots.py": "this test",
    "test/test_ci_dependencies.py": "asserts on ci.yml",
    "test/test_image_customization_contract.py": "asserts on image scripts",
    "test/test_native_ros_payload.py": "asserts on the payload script",
    "test/test_native_systemd_contract.py": "asserts on the payload script",
    "test/test_omx_workstation.py": "asserts on the OMX Dockerfile",
    "test/test_payload_build_speed.py": "asserts on the payload script",
}
_INVOCATION = re.compile(
    r"\bcolcon\b.*\b(build|list|test)\b|rosdep\b.*--from-paths|[\"']colcon[\"']")
_COMMENT = re.compile(r"^\s*(#|//|<!--|::|REM\b|rem\b)")


def _is_evidence(name: str) -> bool:
    """Recorded text that quotes commands but never runs them."""
    return (name.endswith(".md") or name.startswith("docs/validation/")
            or "/evidence/" in name or name.endswith((".log", ".txt", ".jsonl")))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _manifest_roots() -> list[str]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["colcon_roots"]


def test_reader_matches_the_yaml_manifest_and_every_root_exists():
    roots = _manifest_roots()

    assert list(_load("colcon_roots_reader", READER).colcon_roots()) == roots
    assert roots and len(roots) == len(set(roots))
    for root in roots:
        assert (ROOT / root).is_dir(), root


def test_reader_cli_prints_the_roots_space_separated():
    completed = subprocess.run([sys.executable, str(READER)], capture_output=True,
                               text=True, check=True)

    assert completed.stdout.split() == _manifest_roots()


def _invocation_lines() -> dict[str, list[tuple[int, str]]]:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True).stdout.decode("utf-8").split("\0")
    hits: dict[str, list[tuple[int, str]]] = {}
    for name in filter(None, tracked):
        path = ROOT / name
        if _is_evidence(name) or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if _INVOCATION.search(line) and not _COMMENT.match(line):
                hits.setdefault(name, []).append((number, line.strip()))
    return hits


def test_every_colcon_invocation_is_a_consumer_or_exempt():
    hits = _invocation_lines()

    unclassified = {name: lines for name, lines in hits.items() if name not in CONSUMERS and name not in EXEMPT}
    assert unclassified == {}, "read the roots via tools/harness/colcon_roots.py or add an EXEMPT reason"
    for name, pattern in CONSUMERS.items():
        assert name in hits, f"{name} no longer invokes colcon/rosdep; drop it from CONSUMERS"
        bare = [(number, line) for number, line in hits[name] if not re.search(pattern, line)]
        assert bare == [], (name, bare)
    assert sorted(set(EXEMPT) - set(hits)) == [], "stale EXEMPT entries"


def test_every_colcon_consumer_reads_the_one_root_list():
    roots = _manifest_roots()

    for name in CONSUMERS:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "--base-paths src" not in text and "cd src\n" not in text, name
        assert "src/install" not in text and "src/build" not in text, name
        # --log-base is a global option: `colcon build ... --log-base log` is an argparse error.
        assert not re.search(r"(?<!colcon )--log-base", text), name
        if name.endswith("customize-rootfs.sh"):
            assert '--colcon-roots) COLCON_ROOTS_ARG="${2:-}"' in text
        else:
            assert "harness/colcon_roots.py" in text, name
    build = (ROOT / "deploy/robot/pinky_pro/image/build-image.sh").read_text(encoding="utf-8")
    assert "harness/colcon_roots.py" in build and '--colcon-roots "$COLCON_ROOTS"' in build
    assert "colcon_roots.py" in (ROOT / "env.sh").read_text(encoding="utf-8")

    # Python consumers.
    impact = _load("artifact_impact_roots", ROOT / "deploy/robot/pinky_pro/release/artifact_impact.py")
    assert impact.COLCON_ROOT_PREFIXES == tuple(f"{root}/" for root in roots)
    contracts = _load("robot_contracts_roots", ROOT / "test" / "robot_contracts.py")
    assert contracts.COLCON_ROOTS == tuple(roots)


def test_reader_rejects_nested_or_unsafe_roots(tmp_path):
    reader = _load("colcon_roots_reader_cases", READER)
    manifest = tmp_path / "platform_parts.yaml"
    for bad in ("[src, src/x]", "[learning/envs, learning]", "[src, src]", "[]", "[../src]", "[build]"):
        manifest.write_text(f"schema: x\ncolcon_roots: {bad}\n", encoding="utf-8")
        with pytest.raises(ValueError):
            reader.colcon_roots(manifest)
    manifest.write_text("colcon_roots: [src, src_extra, learning]\n", encoding="utf-8")
    assert reader.colcon_roots(manifest) == ("src", "src_extra", "learning")


def _package_locations() -> dict[str, list[str]]:
    locations: dict[str, list[str]] = {}
    for root in _manifest_roots():
        base = ROOT / root
        for path in base.rglob("package.xml"):
            parts = path.relative_to(base).parts
            if COLCON_OUTPUT & set(parts) or any(part.startswith(".") for part in parts):
                continue
            name = ET.parse(path).getroot().findtext("name")
            assert name, path
            locations.setdefault(name, []).append(path.parent.relative_to(ROOT).as_posix())
    return locations


def test_ros_package_names_are_frozen():
    locations = _package_locations()

    assert set(locations) == FROZEN_ROS_PACKAGES
    # Each name has exactly one source path (supersedes test_target_layout's uniqueness check).
    assert {name: paths for name, paths in locations.items() if len(paths) != 1} == {}
    # operations/ui/cam is the Rosy Cam Android app: colcon skips it (COLCON_IGNORE) and it
    # holds no package.xml, so it adds no name. The walk above does not honour
    # COLCON_IGNORE because CI drops one into gz_sim before the root suite runs.
    cam = ROOT / "operations" / "ui" / "cam"
    assert (cam / "COLCON_IGNORE").is_file()
    assert not list(cam.rglob("package.xml"))
