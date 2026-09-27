"""The development IO image must install its declared local ROS dependencies."""

from pathlib import Path
import re
import runpy
import xml.etree.ElementTree as ET

import pytest

from robot_contracts import ROOT


DOCKERFILE = ROOT / "deploy" / "robot" / "Dockerfile"
PROBE = ROOT / "deploy" / "robot" / "probe-io-image.py"


def _source_packages() -> dict[str, tuple[Path, set[str]]]:
    packages = {}
    for manifest in (ROOT / "src").rglob("package.xml"):
        xml = ET.parse(manifest).getroot()
        name = xml.findtext("name")
        assert name and name not in packages, manifest
        dependencies = {
            element.text for element in xml
            if element.tag.endswith("depend") and element.text
        }
        packages[name] = (manifest.parent, dependencies)
    return packages


def _stage(start: str, end: str | None = None) -> str:
    text = DOCKERFILE.read_text(encoding="utf-8").split(start + "\n", 1)[1]
    return text.split(end + "\n", 1)[0] if end else text


def test_io_build_copies_and_selects_its_internal_dependency_closure():
    packages = _source_packages()
    build = _stage("FROM io-runtime AS io-build", "FROM io-runtime AS io")
    selected_line = re.search(r"--packages-select ([^\\\n]+)", build)
    assert selected_line
    selected = set(selected_line.group(1).split()) & packages.keys()

    required = set()
    pending = list(selected)
    while pending:
        name = pending.pop()
        if name in required:
            continue
        required.add(name)
        pending.extend(packages[name][1] & packages.keys() - required)
    assert selected == required, sorted(required - selected)
    assert "web_common" in selected

    copied = {
        ROOT / line.split()[1] for line in build.splitlines()
        if line.startswith("COPY src/")
    }
    assert copied == {packages[name][0] for name in selected}
    admitted = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    for source in copied:
        assert source.is_dir(), source
        parts = source.relative_to(ROOT).as_posix().split("/")
        allowed_by_tree = any(
            f"!{'/'.join(parts[:depth])}/**" in admitted
            for depth in range(2, len(parts) + 1)
        )
        assert allowed_by_tree, source


def test_final_io_image_checks_installed_web_assets(tmp_path):
    final = _stage("FROM io-runtime AS io")
    assert "COPY deploy/robot/probe-io-image.py /tmp/probe-io-image.py" in final
    assert "python3 /tmp/probe-io-image.py" in final

    verify_web_common = runpy.run_path(str(PROBE))["verify_web_common"]
    share = tmp_path / "share" / "web_common"
    for name in ("tokens.css", "components.css", "template.html", "core_ui_logic.js", "ui.js"):
        asset = share / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("asset", encoding="utf-8")

    verify_web_common(share, share)
    with pytest.raises(RuntimeError, match="outside installed share"):
        verify_web_common(share, tmp_path / "source-fallback")
    (share / "ui.js").unlink()
    with pytest.raises(FileNotFoundError, match="ui.js"):
        verify_web_common(share, share)
