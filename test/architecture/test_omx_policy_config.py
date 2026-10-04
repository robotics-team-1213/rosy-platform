"""D-442: reserve POLICY names without enabling unguarded learned motion."""

import ast
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


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
        if not (name.startswith("middleware/apps/device/omx/") or name.startswith("deploy/robot/omx/")):
            continue
        if any(part in {"test", "tests"} for part in Path(name).parts):
            continue
        path = ROOT / name
        if path.suffix == ".py":
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for expression in _owner_expressions(tree):
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
