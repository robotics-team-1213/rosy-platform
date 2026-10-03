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

#: Every tracked file that runs colcon or rosdep over the ROSY sources reads the roots
#: through the reader. Value: how its colcon/rosdep lines must name them.
SHELL_CONSUMERS = {
    ".github/workflows/ci.yml": "--base-paths $COLCON_ROOTS",
    ".github/workflows/arm64-rehearsal.yml": "--base-paths $COLCON_ROOTS",
    "tools/build_wsl.sh": "--base-paths $COLCON_ROOTS",
    "tools/sync_api_restart.sh": "--base-paths $COLCON_ROOTS",
    "tools/sync_rosy.sh": "--base-paths $COLCON_ROOTS",
    "tools/sync_rosy_fast.sh": "--base-paths $COLCON_ROOTS",
    "deploy/robot/pinky_pro/image/build-native-payload.sh": '--base-paths "${COLCON_ROOTS[@]}"',
    "deploy/robot/pinky_pro/image/build-image.sh": '--colcon-roots "$COLCON_ROOTS"',
}
#: Files that run colcon/rosdep but not over the repo's colcon roots.
NOT_ROOT_CONSUMERS = {
    # Container workspaces built from per-package COPY lines; moves edit those COPY sources.
    "deploy/robot/pinky_pro/Dockerfile",
    # Upstream OMX sources fetched into /opt/omx_ws; no ROSY package.
    "deploy/robot/omx/Dockerfile",
    # Receives the roots from build-image.sh (--colcon-roots); checked in
    # test_image_customization_contract.py by running its copy block.
    "deploy/robot/pinky_pro/image/customize-rootfs.sh",
    # Documents the command in a comment; checked below.
    "env.sh",
}
_INVOCATION = re.compile(r"colcon (build|list)|rosdep install --from-paths")


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


def test_every_colcon_consumer_reads_the_one_root_list():
    roots = _manifest_roots()
    tracked = subprocess.run(["git", "ls-files", "--", ".github", "deploy", "tools", "env.sh"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    invoking = set()
    for name in tracked:
        if name.endswith(".md") or "/test/" in name:
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        if any(_INVOCATION.search(line) and not line.lstrip().startswith("#") for line in text.splitlines()):
            invoking.add(name)

    assert invoking - set(SHELL_CONSUMERS) - NOT_ROOT_CONSUMERS == set()
    for name, base_paths in SHELL_CONSUMERS.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "harness/colcon_roots.py" in text, name
        assert base_paths in text, name
        assert "--base-paths src" not in text and "cd src\n" not in text, name
        assert "src/install" not in text and "src/build" not in text, name
    assert "colcon_roots.py" in (ROOT / "env.sh").read_text(encoding="utf-8")

    # Python consumers.
    impact = _load("artifact_impact_roots", ROOT / "deploy/robot/pinky_pro/release/artifact_impact.py")
    assert impact.COLCON_ROOT_PREFIXES == tuple(f"{root}/" for root in roots)
    contracts = _load("robot_contracts_roots", ROOT / "test" / "robot_contracts.py")
    assert contracts.COLCON_ROOTS == tuple(roots)


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
    # src/site/cam is the Rosy Cam Android app: colcon skips it (COLCON_IGNORE) and it
    # holds no package.xml, so it adds no name. The walk above does not honour
    # COLCON_IGNORE because CI drops one into gz_sim before the root suite runs.
    cam = ROOT / "src" / "site" / "cam"
    assert (cam / "COLCON_IGNORE").is_file()
    assert not list(cam.rglob("package.xml"))
