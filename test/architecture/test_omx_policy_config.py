"""D-442: reserve POLICY names without enabling unguarded learned motion."""

import ast
from pathlib import Path
import subprocess

import yaml
import pytest

ROOT = Path(__file__).resolve().parents[2]

STUDY_DECLARATIONS = {
    "deploy/robot/omx/sim_pick_place_policy.py": "run",
    "deploy/robot/omx/sim_policy_install.py": "prepare_install",
}


def _study_declarations(name, tree):
    """Only the two fixed private-study config calls may opt in; duplicates fail closed."""
    matches = []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "arm_command_config"
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "profile"):
            continue
        enclosing = parents.get(call)
        while enclosing is not None and not isinstance(enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing = parents.get(enclosing)
        if (enclosing is None or enclosing.name != STUDY_DECLARATIONS.get(name)
                or parents.get(enclosing) is not tree):
            continue
        for keyword in call.keywords:
            value = keyword.value
            if (keyword.arg == "allowed_owners" and isinstance(value, ast.Tuple)
                    and len(value.elts) == 1 and isinstance(value.elts[0], ast.Constant)
                    and value.elts[0].value == "learned_policy"):
                matches.append(value)
    return matches if len(matches) == 1 else []


def _owner_expressions(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "allowed_owners":
            yield node.value
        elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in {"ALLOWED_OWNERS", "allowed_owners"}
                for target in node.targets):
            yield node.value
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and node.target.id in {"ALLOWED_OWNERS", "allowed_owners"} and node.value is not None):
            yield node.value
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [*node.args.posonlyargs, *node.args.args]
            for arg, default in [*zip(args[-len(node.args.defaults):], node.args.defaults),
                                 *zip(node.args.kwonlyargs, node.args.kw_defaults)]:
                if arg.arg == "allowed_owners" and default is not None:
                    yield default


def _yaml_owner_lists(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "allowed_owners":
                yield child
            yield from _yaml_owner_lists(child)
    elif isinstance(value, list):
        for child in value:
            yield from _yaml_owner_lists(child)


def test_no_production_config_allows_learned_policy():
    """Inspect declarations, not KNOWN_OWNERS: reservation does not authorize POLICY.

    Static check covers tracked OMX production entrypoints, parameter defaults,
    module owner lists and YAML configuration. Dynamic config/runtime overlays
    require the later envelope admission enforcement; this guard cannot prove them.
    """
    paths = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    seen, problems = 0, []
    for name in paths:
        if not (name.startswith("middleware/devices/omx/") or name.startswith("deploy/robot/omx/")):
            continue
        if any(part in {"test", "tests"} for part in Path(name).parts):
            continue
        path = ROOT / name
        if path.suffix == ".py":
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            study = _study_declarations(name, tree)
            if name in STUDY_DECLARATIONS and len(study) != 1:
                problems.append(f"{name}: exactly one private study declaration required")
            for expression in _owner_expressions(tree):
                if expression in study:
                    seen += 1
                    continue
                # These references forward the reviewed module list or profile default.
                if isinstance(expression, ast.Name) and expression.id in {"ALLOWED_OWNERS", "allowed_owners"}:
                    continue
                try:
                    owners = ast.literal_eval(expression)
                except (ValueError, TypeError):
                    problems.append(f"{name}:{expression.lineno}: review dynamic allowed_owners")
                    continue
                seen += 1
                if "learned_policy" in owners:
                    problems.append(f"{name}:{expression.lineno}: learned_policy enabled")
        elif path.suffix in {".yaml", ".yml"}:
            for owners in _yaml_owner_lists(yaml.safe_load(path.read_text(encoding="utf-8-sig"))):
                seen += 1
                if "learned_policy" in owners:
                    problems.append(f"{name}: learned_policy enabled")
    assert seen >= 3, "owner configuration scan must cover the cell, profile and pilot entrypoints"
    assert problems == [], problems


@pytest.mark.parametrize("path,function,expression,count,accepted", [
    ("deploy/robot/omx/sim_pick_place_policy.py", "run", "('learned_policy',)", 1, True),
    ("deploy/robot/omx/sim_policy_install.py", "prepare_install", "('learned_policy',)", 1, True),
    ("deploy/robot/omx/other.py", "run", "('learned_policy',)", 1, False),
    ("deploy/robot/omx/sim_pick_place_policy.py", "other", "('learned_policy',)", 1, False),
    ("deploy/robot/omx/sim_pick_place_policy.py", "run", "['learned_policy']", 1, False),
    ("deploy/robot/omx/sim_pick_place_policy.py", "run", "('learned_policy','pilot')", 1, False),
    ("deploy/robot/omx/sim_pick_place_policy.py", "run", "owners", 1, False),
    ("deploy/robot/omx/sim_pick_place_policy.py", "run", "('learned_policy',)", 2, False),
])
def test_study_exception_rejects_changed_declarations(path, function, expression, count, accepted):
    source = f"def {function}():\n" + (
        f"    profile.arm_command_config(allowed_owners={expression})\n" * count)
    tree = ast.parse(source)
    assert bool(_study_declarations(path, tree)) is accepted
    assert _study_declarations(path, ast.parse(source.replace('arm_command_config', 'other'))) == []
    assert _study_declarations(path, ast.parse(source.replace('profile.', 'other.'))) == []
    nested = "def outer():\n" + "\n".join("    " + line for line in source.splitlines())
    assert _study_declarations(path, ast.parse(nested)) == []


def _assert_study_wiring(actor, installer):
    """Wiring guard only; OS isolation, opt-in and revocation have behavior tests."""
    calls = [node for node in ast.walk(actor) if isinstance(node, ast.Call)]
    def named(name):
        return [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == name]
    assert len(named("NativeSimStudyAuthority")) == 1
    assert ast.unparse(named("NativeSimStopFence")[0]) == "NativeSimStopFence(authority)"
    session, = named("OwnerPolicySession")
    assert [ast.unparse(value) for value in session.args[:4]] == [
        "policy", "arm.owner", "fence", "authority.issue()"]
    keywords = {item.arg: ast.unparse(item.value) for item in session.keywords}
    assert keywords["enabled"] == "True"
    assert keywords["authority_current"] == "authority.current"
    assert keywords["execution_journal"] == "journal"
    assert len(named("PolicyExecutionJournal")) == 1
    assert [ast.unparse(value) for value in named("bind_sim_runtime")[0].args] == ["session", "arm"]
    inert = [node for node in ast.walk(installer) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "ArmCommandOwner"]
    assert len(inert) == 1 and ast.unparse(inert[0]) == "ArmCommandOwner(config, None)"
    assert any(isinstance(node, ast.Compare) and ast.unparse(node) == "owner_binding(owner) != expected_owner"
               for node in ast.walk(installer))


def test_private_study_retains_authority_and_inert_installation():
    _assert_study_wiring(
        ast.parse((ROOT / "deploy/robot/omx/sim_pick_place_policy.py").read_text()),
        ast.parse((ROOT / "deploy/robot/omx/sim_policy_install.py").read_text()))


@pytest.mark.parametrize("file,before,after", [
    ("sim_pick_place_policy.py", "NativeSimStudyAuthority(", "OtherAuthority("),
    ("sim_pick_place_policy.py", "NativeSimStopFence(authority)", "NativeSimStopFence(None)"),
    ("sim_pick_place_policy.py", "enabled=True", "enabled=False"),
    ("sim_pick_place_policy.py", "authority_current=authority.current", "authority_current=lambda: True"),
    ("sim_pick_place_policy.py", "execution_journal=journal", "execution_journal=None"),
    ("sim_pick_place_policy.py", "bind_sim_runtime(session,arm)", "bind_sim_runtime(None,arm)"),
    ("sim_policy_install.py", "ArmCommandOwner(config, None)", "ArmCommandOwner(config, port)"),
    ("sim_policy_install.py", "owner_binding(owner) != expected_owner", "False"),
])
def test_study_wiring_rejects_removed_boundaries(file, before, after):
    sources = {name: (ROOT / "deploy/robot/omx" / name).read_text()
               for name in ("sim_pick_place_policy.py", "sim_policy_install.py")}
    assert sources[file].count(before) == 1, "mutation must hit exactly one actual source boundary"
    sources[file] = sources[file].replace(before, after)
    with pytest.raises(AssertionError):
        _assert_study_wiring(ast.parse(sources["sim_pick_place_policy.py"]),
                             ast.parse(sources["sim_policy_install.py"]))
