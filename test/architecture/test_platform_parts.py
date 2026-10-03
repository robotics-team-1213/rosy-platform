"""D-427 §6 (C): part ownership manifest and §2 import direction.

``tools/harness/platform_parts.yaml`` maps every tracked source root to one
D-427 part. These tests keep that map complete and evaluate the §2 import
table over the Python files of each part.

Step B migration fields (docs/plans/2026-10-03-d427-source-migration.md, wave 0):
``wave`` names the wave that moves a root (``none`` when it is already in place),
``deferred`` names the follow-up that splits a root out of the parent package it
moves with (Q2). See ``_state`` for moved / partly moved / pending.

KNOWN_VIOLATIONS is checked by set equality (D-168 P5 convention): a new edge
fails, and so does a listed edge that no longer occurs. The list only shrinks;
remove an entry in the change that removes the import.

Honest holes, not oversights:
- Only static ``import`` / ``from`` statements are seen. ``sys.path`` script
  imports resolve only when the imported name is a registered ``import_prefix``.
- Test code (files under ``test``/``tests`` folders, and ``conftest.py``) is skipped.
- ``shared_web`` is allowed for every middleware/operations root, not only ui roots.
- middleware may import ``integrations/simulation`` from any root; §2's
  "sim owner only" limit is not enforced.
- contracts' "no external runtime dependency" rule is not checked; only imports
  of other manifest roots are.
- Third-party imports are ignored except §2's training stack in middleware.
- Edges are per root pair, so a second import along a listed edge is not new.
"""

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest
import yaml

from _ast_imports import _imports, _matches

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tools" / "harness" / "platform_parts.yaml"

# Both tables are keyed by ``d427_target``, which a move commit does not change,
# so moving a root only edits its manifest ``path``.

#: Roots (by target) whose folder is itself a package dir, so their dotted package starts at the prefix.
PACKAGE_DIR_ROOTS = {
    "operations/execution/api",
    "middleware/execution/local",
    "operations/execution/site",
}

#: Frozen §2 violations as (importer target, imported target or "external:<name>") -> reason.
KNOWN_VIOLATIONS = {
    ("middleware/apps/device/omx/agent", "operations/processes/palletizing"): (
        "middleware -> operations: the OMX cell owner loads palletizing cell documents and the compiler"
    ),
    ("integrations/robots/omx", "middleware/skills/api"): (
        "integrations -> middleware: the OMX transfer provider implements the Skill API in place"
    ),
    ("integrations/robots/omx", "middleware/skills/manipulation"): (
        "integrations -> middleware: the OMX transfer provider binds the manipulation transfer Skill"
    ),
    ("integrations/robots/omx", "middleware/apps/device/omx/adapter"): (
        "integrations -> middleware: cell_workflow reuses the adapter pick-place journal"
    ),
    ("operations/execution/api", "middleware/execution/local"): (
        "operations -> middleware: PlanBundle embeds local receipt identity types"
    ),
    ("operations/execution/api", "middleware/skills/api"): (
        "operations -> middleware: PlanBundle steps carry SkillInvocation (Skill envelope belongs in contracts)"
    ),
    ("operations/processes/palletizing", "middleware/skills/api"): (
        "operations -> middleware: palletizing builds SkillInvocation steps (Skill envelope belongs in contracts)"
    ),
    ("middleware/apps/device/omx/adapter", "external:lerobot"): (
        "middleware -> lerobot training stack: lerobot_export.py is learning/curation code still in the adapter"
    ),
    ("learning/training/perception", "middleware/perception"): (
        "learning -> middleware: dataset tools reuse control.recording topics and perception helpers"
    ),
}


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _tracked() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        if os.environ.get("CI"):
            pytest.fail("D-427 ownership checks need a git checkout in CI")
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
    return bool({"test", "tests"} & set(pure.parts[:-1])) or pure.name == "conftest.py"


def _package_of(path: str, root: dict) -> str:
    """Dotted package of ``path``, used to resolve relative imports."""
    relative = PurePosixPath(path).relative_to(root["path"])
    if root["d427_target"] in PACKAGE_DIR_ROOTS:
        (prefix,) = root["import_prefix"]
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
        # Deliberately stricter than the other parts: an adapter may not reach
        # tools/test/deploy either, only contracts.
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
        source = (ROOT / path).read_text(encoding="utf-8-sig")
        forbidden_external = rules[importer["part"]].get("forbidden_external", ())
        for name in _imports(source, _package_of(path, importer)):
            target = _target_of(name, owners)
            if target is not None:
                if _allowed(importer, target, rules):
                    continue
                key = (importer["d427_target"], target["d427_target"])
            elif name.split(".")[0] in forbidden_external:
                key = (importer["d427_target"], "external:" + name.split(".")[0])
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


def _is_package_root(root: dict) -> bool:
    folder = ROOT / root["path"]
    return (folder / "package.xml").is_file() or (folder / "pyproject.toml").is_file()


def test_package_targets_are_leaf_unique():
    """A package folder cannot hold another package (D-310 ``profile/``), so two
    package roots may not share a target or nest one target in the other.
    Container targets such as ``middleware/core`` are not packages and may hold them."""
    packages = [root for root in _manifest()["roots"] if _is_package_root(root)]
    assert len(packages) > 30, "package root scan found too few package.xml/pyproject.toml roots"
    clashes = [
        f"{a['path']} -> {a['d427_target']} vs {b['path']} -> {b['d427_target']}"
        for a in packages for b in packages
        if a is not b and _under(b["d427_target"], a["d427_target"])
    ]
    assert clashes == [], f"package targets must be one folder per package: {clashes}"


WAVES = {"1", "2c", "3a", "3b", "3c", "4a", "4b", "4c", "4d", "4e"}


def _parent(root: dict, roots: list[dict]) -> dict | None:
    return _owner(str(PurePosixPath(root["path"]).parent), roots)


def _state(root: dict, roots: list[dict]) -> str:
    """D-427 migration state of a root.

    moved: ``path == d427_target``. partly moved: carries ``deferred`` (the
    follow-up that splits it out) and sits inside its moved parent package.
    pending: anything else, including a deferred root whose parent has not moved.
    """
    if root["path"] == root["d427_target"]:
        return "moved"
    parent = _parent(root, roots)
    if root.get("deferred") and parent is not None and parent["path"] == parent["d427_target"]:
        return "partly_moved"
    return "pending"


def test_every_root_has_a_wave_and_pending_roots_name_theirs():
    roots = _manifest()["roots"]
    bad = []
    for root in roots:
        wave = root.get("wave")
        state = _state(root, roots)
        if wave not in WAVES | {"none"}:
            bad.append(f"{root['path']}: wave {wave!r} not in {sorted(WAVES)} or none")
        elif state == "pending" and wave == "none":
            bad.append(f"{root['path']}: pending root needs the wave that moves it")
        elif wave == "none" and root.get("deferred"):
            bad.append(f"{root['path']}: a deferred root moves in its parent's wave")
    assert bad == [], bad
    assert {root["wave"] for root in roots} >= WAVES, "every wave moves at least one root"


def test_deferred_roots_ride_inside_their_parent_package():
    """A deferred root moves with its parent package and keeps its own target, so its
    path is always inside the parent's path (old location before, parent target after)."""
    roots = _manifest()["roots"]
    deferred = [root for root in roots if "deferred" in root]
    assert len(deferred) >= 3, "Q2 starts with fleet web and gz_sim launch/scripts deferred"
    for root in deferred:
        assert isinstance(root["deferred"], str) and root["deferred"].strip(), root
        assert root["path"] != root["d427_target"], f"{root['path']}: moved roots drop deferred"
        parent = _parent(root, roots)
        assert parent is not None and _is_package_root(parent), (
            f"{root['path']}: deferred needs an enclosing package root"
        )
        assert root["wave"] == parent["wave"], f"{root['path']} moves in {parent['path']}'s wave"
        assert not _under(root["d427_target"], parent["d427_target"]), (
            f"{root['path']}: a target inside the parent package is not a split; drop the root"
        )


def test_root_states_follow_path_target_and_deferred():
    parent = {"path": "a/pkg", "d427_target": "x/pkg", "part": "middleware"}
    child = {"path": "a/pkg/web", "d427_target": "y/web", "part": "operations", "deferred": "T9"}
    roots = [parent, child]
    assert _state(parent, roots) == "pending"
    assert _state(child, roots) == "pending"
    moved_parent = {**parent, "path": "x/pkg"}
    moved_child = {**child, "path": "x/pkg/web"}
    roots = [moved_parent, moved_child]
    assert _state(moved_parent, roots) == "moved"
    assert _state(moved_child, roots) == "partly_moved"
    assert _state({**moved_child, "deferred": None}, roots) == "pending"
    assert _state({**moved_child, "path": "y/web"}, [moved_parent, {**moved_child, "path": "y/web"}]) == "moved"


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


def test_every_tools_subfolder_has_its_own_root():
    """The bare ``tools`` root holds loose scripts only, so new learning code under
    ``tools/<new>/`` cannot hide inside the tools part."""
    roots = _manifest()["roots"]
    unowned = sorted({
        "/".join(PurePosixPath(path).parts[:2])
        for path in _tracked()
        if path.startswith("tools/") and len(PurePosixPath(path).parts) > 2
        and _owner(path, roots)["path"] == "tools"
    })
    assert unowned == [], f"add a platform_parts.yaml root for: {unowned}"


def test_roots_with_python_packages_declare_their_import_prefix():
    roots = _manifest()["roots"]
    tracked = _tracked()
    package_dirs = {
        str(PurePosixPath(path).parent) for path in tracked
        if PurePosixPath(path).name == "__init__.py" and not _is_test_file(path)
    }
    missing = []
    for directory in sorted(package_dirs):
        if str(PurePosixPath(directory).parent) in package_dirs:
            continue  # only top-level packages
        root = _owner(directory + "/__init__.py", roots)
        if root is None:
            continue
        package = _package_of(directory + "/__init__.py", root)
        if not any(_matches(package, prefix) for prefix in root.get("import_prefix") or ()):
            missing.append(f"{root['path']}: {package}")
    assert missing == [], f"declare import_prefix for: {missing}"


def test_violation_and_package_dir_keys_name_one_root_each():
    targets = [root["d427_target"] for root in _manifest()["roots"]]
    keys = {name for pair in KNOWN_VIOLATIONS for name in pair if not name.startswith("external:")}
    keys |= PACKAGE_DIR_ROOTS
    assert sorted(key for key in keys if targets.count(key) != 1) == []


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
