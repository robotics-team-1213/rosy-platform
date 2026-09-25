"""D-73: every harness module owns a functional test of its own shipped code.

Shared compose/Nav2 slice contracts may appear in ``tests:`` (generated
index) but must not be a module's only ``functional`` surface.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "harness" / "harness.yaml"
KINDS = {"pytest", "host-contract", "interface-only", "records"}
SHARED_SLICE = "test/test_nav2_hardware_slice.py"


def _catalog() -> list[dict]:
    data = yaml.safe_load(HARNESS.read_text(encoding="utf-8"))
    return list(data["modules"])


def test_every_harness_module_declares_a_functional_kind_and_paths():
    modules = _catalog()
    assert modules, "harness.yaml has no modules"
    for module in modules:
        name = module["name"]
        kind = module.get("functional_kind")
        assert kind in KINDS, f"{name}: unknown functional_kind {kind!r}"
        paths = module.get("functional") or []
        assert paths, f"{name}: empty functional list"
        assert SHARED_SLICE not in paths, (
            f"{name}: shared Nav2 slice is not this module's functional surface"
        )
        for raw in paths:
            path = ROOT / raw
            assert path.exists(), f"{name}: missing functional path {raw}"
            if path.is_file():
                assert path.stat().st_size > 0, f"{name}: empty file {raw}"


def test_interface_only_modules_declare_their_own_artifacts():
    for module in _catalog():
        if module.get("functional_kind") != "interface-only":
            continue
        artifacts = module.get("artifacts") or []
        assert artifacts, f"{module['name']}: interface-only needs artifacts"
        for raw in artifacts:
            path = ROOT / raw
            assert path.is_file(), f"{module['name']}: missing artifact {raw}"
            assert path.stat().st_size > 0


def test_core_docking_is_not_the_dock_firmware_surface():
    dock = next(item for item in _catalog() if item["name"] == "dock")
    core = next(item for item in _catalog() if item["name"] == "core")
    assert "src/runtime/core_features/test/test_docking.py" not in (dock.get("functional") or [])
    assert "test/test_dock_contract.py" in (dock.get("functional") or [])
    assert "src/runtime/core/test" in (core.get("functional") or [])


def test_functional_paths_belong_to_the_module():
    for module in _catalog():
        name = module["name"]
        root = Path(module["path"]).as_posix()
        for raw in module.get("functional") or []:
            text = Path(raw).as_posix()
            owned = (
                text == root
                or text.startswith(root + "/")
                or name.replace("_", "-") in text
                or name in text
            )
            # repo-root tests may still be the module's surface if they import it;
            # they must mention the module path or name.
            if not owned:
                body = (ROOT / raw).read_text(encoding="utf-8").replace("\\", "/")
                assert name in body or root in body, (
                    f"{name}: {raw} does not mention the module"
                )
