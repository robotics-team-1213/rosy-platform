"""D-442(b) trusted-process first net; dynamic reflection remains review-only."""

import ast

import pytest

from test_safety_separation import CMD_VEL_SCOPE_EXCLUDED, ROOT, _is_test_file, _tracked


ALLOWED_GUARD = {("middleware/core/gateway/core/bridge/cmd_vel.py", "cmd_vel_cycle"),
                 ("middleware/apps/device/omx/adapter/omx_adapter/command_owner.py", "ArmCommandOwner.submit")}
ALLOWED_BINDING = {("middleware/core/gateway/core/bridge/cmd_vel.py", "cmd_vel_cycle")}


def _construction_sites(tree):
    aliases = {"GuardedMotion": "rosy.contracts.motion.GuardedMotion", "PinkyTwistPort": "PinkyTwistPort"}
    result = set()

    def name(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return name(node.value) + "." + node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return aliases.get(node.value, node.value)
        return ""

    def guard_type(node):
        return name(node).endswith(".GuardedMotion")

    def visit(node, scope, guarded):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = (node.module or "") + "." + item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = ".".join(filter(None, (scope, node.name)))
            guarded = set(guarded)
            if not isinstance(node, ast.ClassDef):
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                    if guard_type(arg.annotation):
                        guarded.add(arg.arg)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    resolved = name(value)
                    if resolved:
                        aliases[target.id] = resolved
                    if (isinstance(value, ast.Name) and value.id in guarded
                            or isinstance(value, ast.Call) and guard_type(value.func)
                            or isinstance(node, ast.AnnAssign) and guard_type(node.annotation)):
                        guarded.add(target.id)
        if isinstance(node, ast.Call):
            resolved = name(node.func)
            if guard_type(node.func):
                result.add((scope, "guard"))
            if resolved.rsplit(".", 1)[-1] == "PinkyTwistPort":
                result.add((scope, "binding"))
            if resolved in {"dataclasses.replace", "copy.copy", "copy.deepcopy"} and node.args:
                value = node.args[0]
                if (isinstance(value, ast.Name) and value.id in guarded
                        or isinstance(value, ast.Call) and guard_type(value.func)):
                    result.add((scope, "guard"))
        for child in ast.iter_child_nodes(node):
            visit(child, scope, guarded)

    visit(tree, "", set())
    return result


@pytest.mark.parametrize("source", [
    "from rosy.contracts.motion import GuardedMotion\ndef bypass():\n return GuardedMotion(payload, revision, token)",
    "from rosy.contracts.motion import GuardedMotion as G\ndef bypass():\n return G(payload, revision, token)",
    "import rosy.contracts.motion as m\ndef bypass():\n return m.GuardedMotion(payload, revision, token)",
    "from rosy.contracts.motion import GuardedMotion\nG=GuardedMotion\n"
    "def bypass():\n return G(payload, revision, token)",
    "from rosy.contracts.motion import GuardedMotion\nfrom dataclasses import replace as clone\n"
    "def bypass(cmd: GuardedMotion):\n return clone(cmd)",
    "from rosy.contracts.motion import GuardedMotion\nimport copy\n"
    "def bypass(cmd: GuardedMotion):\n return copy.copy(cmd)",
])
def test_constructor_and_copy_aliases_are_found_outside_allowed_symbols(source):
    assert ("bypass", "guard") in _construction_sites(ast.parse(source))


def test_guard_and_binding_construction_stay_inside_allowed_writer_symbols():
    guards, bindings = set(), set()
    scanned = 0
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path) or path.startswith(tuple(CMD_VEL_SCOPE_EXCLUDED)):
            continue
        scanned += 1
        for symbol, kind in _construction_sites(ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))):
            (guards if kind == "guard" else bindings).add((path, symbol))
    assert scanned > 500
    assert guards and guards <= ALLOWED_GUARD, guards - ALLOWED_GUARD
    assert bindings == ALLOWED_BINDING, bindings
