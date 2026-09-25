"""`RosBridge` must implement every member the executor contracts declare.

This is the test that would have caught D-32 at its root. `NavExecutor` and
`DockingExecutor` are `typing.Protocol`s and `RosBridge` declares no base class,
so conformance is duck-typed and nothing — not the type system, not CI, not the
host suite — notices when a member is missing. `reset_mapping` was absent for
the whole life of the endpoint that called it, hidden behind a `hasattr` probe;
removing the probe removes the hiding place but not the underlying exposure. Add
a member to a Protocol, forget the bridge, call it as `self.executor.foo()`, and
you have reproduced D-32 with no `hasattr` anywhere for C6 to find.

`bridge/AGENTS.md` records why an import-based check is not available here: host
pytest cannot import `ros_bridge.py`, because rclpy is not installed on the dev
machine and is optional in the core image. So this reads the source with `ast`,
the same technique and for the same reason as `test_module_criteria.py`.

That makes it a structural check, not a behavioural one: it proves the method
exists, never that it does the right thing. `RosBridge.reset_mapping` is still
verified by nothing on either platform — it is unreachable on all three deploy
overlays, which are `slam: false`. This test closes the omission, not the gap.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FEATURES = Path(__file__).resolve().parents[2] / "services" / "core_features"
PACKAGE = Path(__file__).resolve().parents[1] / "core"

#: (contract module, Protocol class) -> the class expected to implement it.
#: Contract Protocols moved to core_features at the domain regroup (D-125);
#: the implementer — the bridge — stayed in the kernel.
#: DockingExecutor moved out of `ros_bridge.py` into the ROS-free
#: `bridge/docking_executor.py` (D-168 P6 file budget); RosBridge wires it.
CONTRACTS = [
    ("navigation/manager.py", "NavExecutor", ("bridge/ros_bridge.py", "RosBridge")),
    ("docking/model.py", "DockingExecutor",
     ("bridge/docking_executor.py", "BridgeDockingExecutor")),
]


def _class_def(base: Path, relative: str, name: str) -> ast.ClassDef:
    tree = ast.parse((base / relative).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {relative}")


def _methods(node: ast.ClassDef) -> set[str]:
    return {
        member.name
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not member.name.startswith("_")
    }


@pytest.mark.parametrize("relative,protocol,implementer", CONTRACTS,
                         ids=[c[1] for c in CONTRACTS])
def test_ros_bridge_implements_every_declared_contract_member(relative, protocol, implementer):
    declared = _methods(_class_def(FEATURES, relative, protocol))
    implemented = _methods(_class_def(PACKAGE, *implementer))
    missing = declared - implemented

    assert not missing, (
        f"RosBridge does not implement {sorted(missing)}, declared by {protocol} "
        f"in {relative}.\n"
        "The Protocol is structural and RosBridge declares no base, so nothing "
        "else catches this: the call fails at runtime with AttributeError, which "
        "api/errors.py does not handle, so the endpoint answers 500 — the 일반 "
        "실패 CAP-003 forbids. Implement the member, or remove it from the "
        "contract. If the runtime genuinely cannot honour it, implement it and "
        "raise CAPABILITY_NOT_SUPPORTED, as reset_mapping does (D-32)."
    )


#: The providers `RosBridge._setup_diagnostics` registers, recorded in
#: `bridge/AGENTS.md` as the baseline any refactor of that file must reproduce.
DIAGNOSTICS_PROVIDERS = {"core", "cpu", "memory", "disk", "odom_topic"}


def _registered_diagnostics() -> set[str]:
    """String literals passed to `self.diagnostics.register(...)` in the bridge.

    Read statically for the same reason as everything else here: host pytest
    cannot import `ros_bridge.py`, so `GET /api/v1/diagnostics` cannot be asked
    on this machine. A dropped provider surfaces as a missing key rather than an
    error, which is exactly the failure a Pi run would have to notice by eye.
    """
    tree = ast.parse((PACKAGE / "bridge/ros_bridge.py").read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_diagnostics_provider_set_matches_the_recorded_baseline():
    registered = _registered_diagnostics()

    assert registered == DIAGNOSTICS_PROVIDERS, (
        "RosBridge._setup_diagnostics no longer registers the set recorded in "
        "bridge/AGENTS.md.\n"
        f"  dropped: {sorted(DIAGNOSTICS_PROVIDERS - registered)}\n"
        f"  added:   {sorted(registered - DIAGNOSTICS_PROVIDERS)}\n"
        "A dropped provider is invisible at runtime — /api/v1/diagnostics simply "
        "stops carrying the key. Update AGENTS.md and this literal together, or "
        "put the provider back."
    )


def _bridge_json_usage() -> tuple[set[str], bool]:
    """`json.<attr>` calls in the bridge and whether `import json` exists.

    Read statically for the same reason as everything else here: host pytest
    cannot import `ros_bridge.py`, so a missing import surfaces only as
    NameError inside a live ROS callback — on the robot, never here. The
    2026-09-22 road/observation defect (`json.loads` and
    `json.JSONDecodeError` with no `import json`) is what this pins shut.
    """
    tree = ast.parse((PACKAGE / "bridge/ros_bridge.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    used = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    }
    return used, "json" in imported


def test_bridge_json_calls_are_backed_by_a_module_import():
    used, imported = _bridge_json_usage()

    assert used, (
        "ros_bridge.py no longer calls json; if the usage is really gone, "
        "update this contract too."
    )
    assert imported, (
        f"ros_bridge.py calls json.{', '.join(f'json.{name}' for name in sorted(used))} "
        "without `import json`. NameError from this is invisible to host pytest "
        "and fires only inside a live ROS callback — the 2026-09-22 "
        "road/observation defect. Import json at module top, or drop the use."
    )
