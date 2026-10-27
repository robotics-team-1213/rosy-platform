"""D-413 current import ownership and future edge canaries."""

import sys
from pathlib import Path

import yaml

from _ast_imports import _imports, _matches


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "tools" / "harness" / "platform_dependencies.yaml"

CURRENT_COMPONENTS = {
    "fleet_app_dev": ("applications/fleet/dev", "fleet_app_dev"),
    "contracts": ("contracts/foundation/core_common", "core_common"),
    "cell_process_compat": ("operations/processes/cell/rosy_cell", "rosy_cell"),
    "palletizing_process": (
        "operations/processes/palletizing/src/rosy/processes/palletizing",
        "rosy.processes.palletizing",
    ),
    "fleet_site": ("operations/fleet/fleet", "fleet"),
    "fleet_decision": ("operations/decision/src/rosy/decision", "rosy.decision"),
    "omx_device_adapter": ("middleware/devices/omx/adapter/omx_adapter", "omx_adapter"),
    "world_api": ("operations/world/src/rosy/world/api", "rosy.world.api"),
    "world_state": ("operations/world/src/rosy/world/state", "rosy.world.state"),
    "skill_contracts": ("contracts/skill/src/rosy/contracts/skill", "rosy.contracts.skill"),
    "skill_api": ("middleware/skills/api/src/rosy/skills/api", "rosy.skills.api"),
    "execution_api": ("operations/site_execution/src/rosy/execution/api", "rosy.execution.api"),
    "omx_transfer_integration": (
        "integrations/robots/omx/src/rosy/integrations/robots/omx",
        "rosy.integrations.robots.omx",
    ),
    "gateway_app": ("applications/fleet/gateway/src/rosy_gateway", "rosy_gateway"),
    "agent_app": ("middleware/devices/omx/agent/src/rosy_agent", "rosy_agent"),
}


def _policy():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def _violations(importer: str, source: str, boundaries: list[dict], *, module_name: str | None = None,
                package_name: str | None = None) -> list[str]:
    bad = []
    package_name = package_name or importer
    for name in _imports(source, package_name):
        for boundary in boundaries:
            if not _matches(importer, boundary["importer_prefix"]):
                continue
            if any(_matches(name, target) for target in boundary.get("forbidden_imports", ())):
                bad.append(name)
            elif "allowed_imports" in boundary and name.split(".")[0] not in sys.stdlib_module_names and not any(
                    _matches(name, target) for target in boundary["allowed_imports"]):
                bad.append(name)
    return bad


def test_policy_registers_only_current_components():
    policy = _policy()
    assert policy["schema"] == "rosy.platform-dependencies.v1"
    actual = {
        item["name"]: (item["path"], item["import_prefix"])
        for item in policy["components"]
    }
    assert actual == CURRENT_COMPONENTS
    assert all((ROOT / path).is_dir() for path, _ in actual.values())


def test_existing_source_obeys_declared_import_boundaries():
    policy = _policy()
    violations = []
    for component in policy["components"]:
        directory = ROOT / component["path"]
        for path in directory.rglob("*.py"):
            relative = path.relative_to(directory)
            if "test" in relative.parts or path.name.startswith("test_"):
                continue
            module_parts = [component["import_prefix"], *relative.parent.parts]
            if path.stem != "__init__":
                module_parts.append(path.stem)
            module_name = ".".join(module_parts)
            package_name = module_name if path.stem == "__init__" else ".".join(module_parts[:-1])
            found = _violations(
                component["import_prefix"],
                path.read_text(encoding="utf-8"),
                policy["boundaries"],
                module_name=module_name,
                package_name=package_name,
            )
            violations.extend(f"{path.relative_to(ROOT)} imports {name}" for name in found)
    assert violations == []


def test_injected_forbidden_imports_fail_future_boundary_canaries():
    policy = _policy()
    for boundary in policy["future_boundary_canaries"]:
        for target in boundary["forbidden_imports"]:
            injected = f"import {target}.injected\n"
            assert _violations(boundary["importer_prefix"], injected, [boundary]) == [
                f"{target}.injected"
            ]


def test_allow_list_rejects_anything_not_listed():
    rules = [b for b in _policy()["boundaries"] if b["importer_prefix"] == "rosy_agent"]
    assert "allowed_imports" in rules[0]
    source = "import json\nimport omx_adapter.action_api\nfrom . import barrier_journal\nimport fleet.db\nimport rclpy\n"
    assert _violations("rosy_agent", source, rules, package_name="rosy_agent") == ["fleet.db", "rclpy"]


def test_prefix_matching_does_not_reject_similar_unrelated_packages():
    policy = _policy()
    rules = policy["future_boundary_canaries"]
    assert _violations("rosy.execution.api", "import rosy.processes.palletizing2\n", rules) == []
    assert _violations("rosy.executionish", "import rosy.processes.palletizing\n", rules) == []
    assert _violations("rosy.execution.api", "from . import local_module\n", rules) == []
    relative_hits = _violations(
        "rosy.skills.manipulation",
        "from ...execution import api\n",
        rules,
    )
    assert "rosy.execution" in relative_hits


def test_platform_python_roots_are_not_ament_packages():
    package_xml = [
        str(path.relative_to(ROOT))
        for root in ("modules", "integrations/robots", "apps", "profiles", "operations/world",
                     "operations/processes/palletizing", "operations/site_execution",
                     "applications/fleet/gateway")
        for path in (ROOT / root).rglob("package.xml")
    ]
    assert package_xml == []
