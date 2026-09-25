"""Rosy Control must be owned and importable from the Rosy OS source tree."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "runtime" / "sensing"


def test_control_package_is_part_of_the_os_workspace() -> None:
    assert (PACKAGE / "package.xml").is_file()
    assert (PACKAGE / "setup.py").is_file()
    assert (PACKAGE / "resource" / "control").is_file()


def test_control_package_imports_without_the_legacy_checkout() -> None:
    module = PACKAGE / "control" / "__init__.py"
    spec = importlib.util.spec_from_file_location("absorbed_control", module)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert Path(loaded.__file__).resolve().is_relative_to(PACKAGE.resolve())


def test_control_tests_are_owned_by_the_os_workspace() -> None:
    tests = list((PACKAGE / "test").glob("test_*.py"))
    assert len(tests) >= 100


def test_os_source_catalog_owns_the_absorbed_package() -> None:
    catalog = (REPO / "src" / "AGENTS.md").read_text(encoding="utf-8")
    assert "`control`" in catalog


def test_absorbed_metadata_and_device_guide_keep_core_command_authority() -> None:
    package_xml = (PACKAGE / "package.xml").read_text(encoding="utf-8")
    setup_py = (PACKAGE / "setup.py").read_text(encoding="utf-8")
    root_readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "core owns the final cmd_vel publisher" in package_xml
    assert "forward/back control node" not in setup_py
    assert "install-pi.sh" in root_readme
    assert "echo 'ROS_DOMAIN_ID=" not in root_readme


def test_absorbed_guides_use_the_rosy_os_device_path() -> None:
    for name in ("CLAUDE.md", "STEPS.txt"):
        guide = (PACKAGE / name).read_text(encoding="utf-8")
        assert "install-pi.sh" in guide
        assert "verify-pi.sh" in guide
        assert "device-readback.sh --json" in guide
        assert "/home/pinky/dev_ws" not in guide
        assert "/home/pinky/pinky_pro" not in guide
