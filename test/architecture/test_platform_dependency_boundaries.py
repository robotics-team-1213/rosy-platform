"""D-413 current import ownership and future edge canaries."""

import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "tools" / "harness" / "platform_dependencies.yaml"

CURRENT_COMPONENTS = {
    "contracts": ("src/contracts/foundation/core_common", "core_common"),
    "cell_process_compat": ("src/site/cell/rosy_cell", "rosy_cell"),
    "palletizing_process": (
        "modules/processes/palletizing/src/rosy/processes/palletizing",
        "rosy.processes.palletizing",
    ),
    "fleet_site": ("src/site/fleet/fleet", "fleet"),
    "omx_device_adapter": ("src/products/omx/adapter/omx_adapter", "omx_adapter"),
    "world_api": ("modules/world/src/rosy/world/api", "rosy.world.api"),
    "skill_api": ("modules/skills/api/src/rosy/skills/api", "rosy.skills.api"),
    "execution_api": ("modules/execution/src/rosy/execution/api", "rosy.execution.api"),
    "omx_transfer_integration": (
        "integrations/robots/omx/src/rosy/integrations/robots/omx",
        "rosy.integrations.robots.omx",
    ),
    "gateway_app": ("apps/gateway/src/rosy_gateway", "rosy_gateway"),
    "agent_app": ("apps/agent/src/rosy_agent", "rosy_agent"),
}


def _policy():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _imports(source: str, package_name: str) -> list[str]:
    tree = ast.parse(source)
    imported = []
    package_parts = package_name.split(".") if package_name else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                ascend = node.level - 1
                base = package_parts[:max(0, len(package_parts) - ascend)]
                prefix = ".".join(base)
            else:
                prefix = ""
            if node.module:
                imported.append(".".join(part for part in (prefix, node.module) if part))
                for alias in node.names:
                    if alias.name != "*":
                        imported.append(".".join(part for part in (prefix, node.module, alias.name) if part))
            elif node.level:
                for alias in node.names:
                    if alias.name != "*":
                        imported.append(".".join(part for part in (prefix, alias.name) if part))
    return imported


def _violations(importer: str, source: str, boundaries: list[dict], *, module_name: str | None = None,
                package_name: str | None = None) -> list[str]:
    bad = []
    package_name = package_name or importer
    for name in _imports(source, package_name):
        for boundary in boundaries:
            if _matches(importer, boundary["importer_prefix"]):
                if any(_matches(name, target) for target in boundary["forbidden_imports"]):
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
        for root in ("modules", "integrations", "apps", "profiles")
        for path in (ROOT / root).rglob("package.xml")
    ]
    assert package_xml == []
