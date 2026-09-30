"""The development CORE image must contain its declared ROS package closure."""

from pathlib import Path
import runpy
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from robot_contracts import ROOT, source_manifests


DOCKERFILE = ROOT / "deploy" / "robot" / "pinky_pro" / "Dockerfile"
PROBE = ROOT / "deploy" / "robot" / "pinky_pro" / "probe-core-image.py"
EXPECTED_PACKAGES = {
    "core",
    "core_api_web",
    "core_common",
    "core_events",
    "core_features",
    "dashboard",
    "interfaces",
    "pilot",
    "pinky_pro",
    "web_common",
}


def _source_packages() -> dict[str, tuple[Path, set[str]]]:
    packages = {}
    for manifest in source_manifests():
        root = ET.parse(manifest).getroot()
        name = root.findtext("name")
        assert name and name not in packages, manifest
        dependencies = {
            element.text for element in root
            if element.tag.endswith("depend") and element.text
        }
        packages[name] = (manifest.parent, dependencies)
    return packages


def _core_build_section() -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    return text.split("FROM core-runtime AS core-build\n", 1)[1].split(
        "FROM core-runtime AS core\n", 1
    )[0]


def _core_final_section() -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    return text.split("FROM core-runtime AS core\n", 1)[1].split(
        "FROM runtime-common AS io-runtime\n", 1
    )[0]


def test_core_build_copies_its_declared_package_closure():
    packages = _source_packages()
    required = set()
    pending = ["core", "pinky_pro"]
    while pending:
        name = pending.pop()
        if name in required:
            continue
        required.add(name)
        pending.extend(packages[name][1] & packages.keys() - required)

    assert required == EXPECTED_PACKAGES
    build = _core_build_section()
    copied = {
        ROOT / line.split()[1] for line in build.splitlines()
        if line.startswith("COPY src/")
    }
    assert copied == {packages[name][0] for name in required}
    assert "--packages-up-to core pinky_pro web_common dashboard pilot" in build

    admitted = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    for source in copied:
        assert source.is_dir(), source
        relative = source.relative_to(ROOT).as_posix()
        parts = relative.split("/")
        allowed_by_tree = any(
            f"!{'/'.join(parts[:depth])}/**" in admitted
            for depth in range(2, len(parts) + 1)
        )
        assert allowed_by_tree, relative


def test_core_build_probes_imports_and_installed_web_assets(tmp_path):
    final = _core_final_section()
    assert "COPY deploy/robot/pinky_pro/probe-core-image.py /tmp/probe-core-image.py" in final
    assert "python3 /tmp/probe-core-image.py" in final

    verify_assets = runpy.run_path(str(PROBE))["verify_assets"]
    dashboard = tmp_path / "dashboard"
    common = tmp_path / "web_common"
    for root, names in (
        (dashboard, ("index.html", "panels.yaml", "shell/shell.js")),
        (common, ("tokens.css", "ui.js")),
    ):
        for name in names:
            asset = root / name
            asset.parent.mkdir(parents=True, exist_ok=True)
            asset.write_text("asset", encoding="utf-8")

    verify_assets(dashboard, common)
    (common / "ui.js").unlink()
    with pytest.raises(FileNotFoundError, match="web_common.*ui.js"):
        verify_assets(dashboard, common)


def test_core_probe_skips_included_routers_without_a_path():
    verify_dashboard_route = runpy.run_path(str(PROBE))["verify_dashboard_route"]
    included_router = SimpleNamespace(routes=[SimpleNamespace(path="/api/v1")])
    verify_dashboard_route(SimpleNamespace(routes=[included_router, SimpleNamespace(path="/dashboard")]))

    with pytest.raises(RuntimeError, match="dashboard route"):
        verify_dashboard_route(SimpleNamespace(routes=[included_router]))
