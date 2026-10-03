"""D-427 §6 (C): part ownership manifest and §2 import direction.

``tools/harness/platform_parts.yaml`` maps every tracked source root to one
D-427 part. These tests keep that map complete and evaluate the §2 import
table over the Python files of each part.

KNOWN_VIOLATIONS is checked by set equality (D-168 P5 convention): a new edge
fails, and so does a listed edge that no longer occurs. The list only shrinks;
remove an entry in the change that removes the import.

Honest holes, not oversights:
- Only static ``import`` / ``from`` statements are seen. ``sys.path`` script
  imports resolve only when the imported name is a registered ``import_prefix``.
- Test code (``test``/``tests`` folders, ``test_*.py``, ``conftest.py``) is skipped,
  as in test_platform_dependency_boundaries.py.
- ``shared_web`` is allowed for every middleware/operations root, not only ui roots.
- Third-party imports are ignored except §2's training stack in middleware.
- Edges are per root pair, so a second import along a listed edge is not new.
"""

import ast
import importlib.util
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "harness" / "platform_parts.yaml"

_spec = importlib.util.spec_from_file_location(
    "_d413_dependency_boundaries", Path(__file__).with_name("test_platform_dependency_boundaries.py")
)
_d413 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_d413)
_imports = _d413._imports
_matches = _d413._matches

#: Frozen §2 violations as (importer root, imported root or "external:<name>") -> reason.
KNOWN_VIOLATIONS = {
    ("apps/agent", "modules/processes/palletizing"): (
        "middleware -> operations: the OMX cell owner loads palletizing cell documents and the compiler"
    ),
    ("integrations/robots/omx", "modules/skills/api"): (
        "integrations -> middleware: the OMX transfer provider implements the Skill API in place"
    ),
    ("integrations/robots/omx", "modules/skills/manipulation"): (
        "integrations -> middleware: the OMX transfer provider binds the manipulation transfer Skill"
    ),
    ("integrations/robots/omx", "src/products/omx/adapter"): (
        "integrations -> middleware: cell_workflow reuses the adapter pick-place journal"
    ),
    ("modules/execution/src/rosy/execution/api", "modules/execution/src/rosy/execution/local"): (
        "operations -> middleware: PlanBundle embeds local receipt identity types"
    ),
    ("modules/execution/src/rosy/execution/api", "modules/skills/api"): (
        "operations -> middleware: PlanBundle steps carry SkillInvocation (Skill envelope belongs in contracts)"
    ),
    ("modules/processes/palletizing", "modules/skills/api"): (
        "operations -> middleware: palletizing builds SkillInvocation steps (Skill envelope belongs in contracts)"
    ),
    ("src/products/omx/adapter", "external:lerobot"): (
        "middleware -> lerobot training stack: lerobot_export.py is learning/curation code still in the adapter"
    ),
    ("tools/perception", "src/runtime/sensing"): (
        "learning -> middleware: dataset tools reuse control.recording topics and perception helpers"
    ),
}


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _tracked() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("D-427 ownership checks need a git checkout")
    done = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return [line for line in done.stdout.splitlines() if line and (ROOT / line).exists()]


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _owner(path: str, roots: list[dict]) -> dict | None:
    hits = [root for root in roots if _under(path, root["path"])]
    return max(hits, key=lambda root: len(root["path"]), default=None)


def _is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        bool({"test", "tests"} & set(pure.parts[:-1]))
        or pure.name.startswith("test_")
        or pure.name == "conftest.py"
    )


def _package_of(path: str, root: dict) -> str:
    """Dotted package of ``path``, used to resolve relative imports."""
    relative = PurePosixPath(path).relative_to(root["path"])
    for prefix in root.get("import_prefix") or ():
        if root["path"].endswith("/" + prefix.replace(".", "/")):
            return ".".join([prefix, *relative.parent.parts])
    parts = relative.parent.parts
    if parts[:1] == ("src",):
        parts = parts[1:]
    return ".".join(parts)


def _prefix_owners(roots: list[dict]) -> list[tuple[str, dict]]:
    pairs = [(prefix, root) for root in roots for prefix in root.get("import_prefix") or ()]
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _target_of(name: str, owners: list[tuple[str, dict]]) -> dict | None:
    return next((root for prefix, root in owners if _matches(name, prefix)), None)


def _allowed(importer: dict, target: dict, rules: dict) -> bool:
    if target is importer:
        return True
    source_part, target_part = importer["part"], target["part"]
    if source_part == "integrations":
        return target_part == "contracts"
    if target_part == source_part:
        return True
    if target_part not in rules:
        return True  # tools/test/deploy/profiles/docs are outside §2
    rule = rules[source_part]
    if target_part in rule.get("allow", ()):
        return True
    if target_part == "integrations":
        kind = target.get("integration", "")
        return any(_under(kind, allowed) for allowed in rule.get("integrations", ()))
    return False


def _edges(manifest: dict, tracked: list[str]) -> dict[tuple[str, str], list[str]]:
    roots, rules = manifest["roots"], manifest["import_rules"]
    owners = _prefix_owners(roots)
    edges: dict[tuple[str, str], list[str]] = {}
    for path in tracked:
        if not path.endswith(".py") or _is_test_file(path):
            continue
        importer = _owner(path, roots)
        if importer is None or importer["part"] not in rules:
            continue
        source = (ROOT / path).read_text(encoding="utf-8")
        forbidden_external = rules[importer["part"]].get("forbidden_external", ())
        for name in _imports(source, _package_of(path, importer)):
            target = _target_of(name, owners)
            if target is not None:
                if _allowed(importer, target, rules):
                    continue
                key = (importer["path"], target["path"])
            elif name.split(".")[0] in forbidden_external:
                key = (importer["path"], "external:" + name.split(".")[0])
            else:
                continue
            found = f"{path} imports {name}"
            if found not in edges.setdefault(key, []):
                edges[key].append(found)
    return edges


def test_manifest_shape_and_paths():
    manifest = _manifest()
    assert manifest["schema"] == "rosy.platform-parts.v1"
    parts = set(manifest["parts"])
    assert set(manifest["import_rules"]) <= parts
    paths = [root["path"] for root in manifest["roots"]]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    assert duplicates == [], f"one entry per root: {duplicates}"
    for root in manifest["roots"]:
        assert root["part"] in parts, root
        assert root.get("d427_target"), root
        assert (ROOT / root["path"]).exists(), f"missing root: {root['path']}"
        assert (root["part"] == "integrations") == ("integration" in root), root
    prefixes = [prefix for root in manifest["roots"] for prefix in root.get("import_prefix") or ()]
    assert len(prefixes) == len(set(prefixes)), "an import_prefix names one owner"


def test_nested_roots_change_part_or_target():
    roots = _manifest()["roots"]
    for root in roots:
        parent = _owner(str(PurePosixPath(root["path"]).parent), roots)
        if parent is not None:
            assert (parent["part"], parent["d427_target"]) != (root["part"], root["d427_target"]), (
                f"{root['path']} repeats its parent {parent['path']}"
            )


def test_every_tracked_file_has_exactly_one_owner():
    roots = _manifest()["roots"]
    orphans = []
    for path in _tracked():
        pure = PurePosixPath(path)
        if len(pure.parts) == 1:
            continue  # repository root files
        if _owner(path, roots) is None and pure.suffix != ".md":
            orphans.append(path)
    assert orphans == [], f"add these to tools/harness/platform_parts.yaml: {orphans[:20]}"


def test_import_rules_only_shrink():
    edges = _edges(_manifest(), _tracked())
    actual = set(edges)
    new = sorted(actual - set(KNOWN_VIOLATIONS))
    stale = sorted(set(KNOWN_VIOLATIONS) - actual)
    assert not new and not stale, (
        "new D-427 §2 violations: "
        + "; ".join(f"{key}: {edges[key][:3]}" for key in new)
        + f" | stale KNOWN_VIOLATIONS (remove them): {stale}"
    )


def _root(path: str, part: str, **extra) -> dict:
    return {"path": path, "part": part, "d427_target": part, **extra}


def test_rules_reject_injected_edges_and_accept_allowed_ones():
    rules = _manifest()["import_rules"]
    middleware = _root("m", "middleware")
    operations = _root("o", "operations")
    learning = _root("l", "learning")
    contracts = _root("c", "contracts")
    robots = _root("ir", "integrations", integration="robots")
    models = _root("im", "integrations", integration="models")
    gazebo = _root("ig", "integrations", integration="simulation/gazebo")
    tools = _root("t", "tools")
    assert not _allowed(middleware, operations, rules)
    assert not _allowed(middleware, learning, rules)
    assert not _allowed(middleware, models, rules)
    assert not _allowed(operations, middleware, rules)
    assert not _allowed(operations, robots, rules)
    assert not _allowed(learning, middleware, rules)
    assert not _allowed(contracts, middleware, rules)
    assert not _allowed(robots, models, rules)
    assert not _allowed(robots, middleware, rules)
    assert _allowed(middleware, contracts, rules)
    assert _allowed(middleware, robots, rules)
    assert _allowed(middleware, gazebo, rules)
    assert _allowed(operations, models, rules)
    assert _allowed(learning, gazebo, rules)
    assert _allowed(robots, contracts, rules)
    assert _allowed(operations, tools, rules)
    assert _allowed(middleware, _root("m2", "middleware"), rules)
