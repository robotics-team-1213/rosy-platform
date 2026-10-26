"""D-762 stage 0 narrowing for the ``affected`` tier (split from ``affected_tests.py``).

A ``contracts/foundation`` module may select its known test readers. Runtime consumers,
config files and CI workflows retain FULL until their downstream coverage is established.
``affected_tests.select`` calls `add_readers` for every triggered path.

`registry_readers` narrows the other way: some contract suites scan every tree a registry lists
(``shared/web/surfaces.yaml``) and never name those trees, so path matching missed them and the
D-792 camera page in ``review_app_web`` landed red on the shared/web token suites (2026-10-18).
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import PurePosixPath

import yaml

import affected_foundation  # rule 4: contracts/foundation additions proven by AST
import affected_tests as at  # attributes read at call time, so the cyclic import is safe

# D-762 stage 0 ("넓은 경로 일치가 아니라 실제 영향"): triggers whose real readers the selector can
# find. A path matching only these selects its readers (`narrowed`); no reader found -> FULL.
NARROWABLE_TRIGGERS = ("contracts/foundation/**", "test/architecture/**", "test/known_failures.txt")
FOUNDATION = "contracts/foundation"
ARCHITECTURE = "test/architecture"
#: registry file -> (top-level list key, reader module its contract tests import)
REGISTRIES = {"shared/web/surfaces.yaml": ("surfaces", "surface_registry")}
FROM_IMPORT = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(\([^)]*\)|[^\n]*)", re.MULTILINE)


def add_readers(repo: at.Repo, path: str, trigger: str, add, changed=(), base_text=None) -> str | None:
    """Select the readers of a triggered `path` through `add`: None when narrowed, else why it stays
    FULL ("" when there is nothing to add to the trigger's own reason).

    `base_text(path)`: the file at the merge base, None when it did not exist there."""
    hits = [pattern for pattern, _ in at.FULL_TRIGGERS if at._match(path, pattern)]
    if not hits or any(p not in NARROWABLE_TRIGGERS for p in hits):
        return ""
    if path == KNOWN_FAILURES:
        found, why = known_failure_tests(repo, changed, base_text)
    else:
        found, why = narrowed(repo, path), ""
        if found is None and base_text is not None:  # rule 4: additions only, proven by AST
            found, why = affected_foundation.readers(repo, path, base_text(path))
    if found is None:
        return why
    # D-762 stage 0: the readers found, not the whole tree; foundation keeps its own suite.
    if at._under(path, FOUNDATION) and not at.TEST_FILE.search(path):
        found.setdefault(f"{FOUNDATION}/test", f"module core_common ({path})")
    for test, why in found.items():
        add(test, f"{why} (narrowed from: {trigger})")
    return None


KNOWN_FAILURES = "test/known_failures.txt"


def _listed(text: str) -> set[str]:
    """Node ids of a known-failures list, parsed like test/known_failures.py load_known."""
    return {line.strip().partition("  # ")[0].strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")}


def known_failure_tests(repo: at.Repo, changed, base_text) -> tuple[dict[str, str] | None, str]:
    """Rule 7 (design 0.7): the files of the ids a known_failures edit adds or removes, or (None, why).

    A removed id runs to prove it is green. An added id runs too, but needs a person when this
    branch also changes that test or the test is safety-tagged (the list must not hide a failure
    the branch made, test/known_failures.txt header). Whether an added id really fails is
    known_failures.py's comparison on that run, not the selector's.
    flaky_quarantine.txt is a concern: safety root, so it stays FULL like every safety path.
    """
    if base_text is None:
        return None, "no base to compare"
    old, new = _listed(base_text(KNOWN_FAILURES) or ""), _listed(repo.text(KNOWN_FAILURES))
    found = {t: f"references {KNOWN_FAILURES}" for t in [*repo.referencing_tests(KNOWN_FAILURES),
                                                         "test/test_known_failures.py"] if repo.exists(t)}
    for nodeid in sorted(old ^ new):
        test = nodeid.split("::")[0]
        if nodeid in new:
            if test in changed:
                return None, f"adds {nodeid} while this branch changes {test}: needs human review"
            if at.safety_review.is_safety(test, repo.safety_roots, repo.safety_modules):
                return None, f"adds safety-tagged {nodeid}: needs human review"
            if not repo.exists(test):
                return None, f"adds {nodeid}, whose test file does not exist"
        if repo.exists(test):
            found.setdefault(test, f"{'added to' if nodeid in new else 'removed from'} {KNOWN_FAILURES}: {nodeid}")
    return found, ""


def _from_imports(repo: at.Repo, path: str) -> list[tuple[str, frozenset[str]]]:
    """Every ``from X import a, b as c`` in `path` as (absolute X, {a, b, c}); relative X resolved."""
    cache = vars(repo).setdefault("_from", {})
    if path in cache:
        return cache[path]
    found = []
    package = list(PurePosixPath(path).relative_to(FOUNDATION).parent.parts) if at._under(path, FOUNDATION) else []
    for dots, module, imported in FROM_IMPORT.findall(_code(repo, path)):
        if dots:
            if len(dots) > len(package):
                continue
            module = ".".join([*package[:len(package) - len(dots) + 1], *filter(None, [module])])
        found.append((module, frozenset(re.findall(r"\w+", imported)) - {"as"}))
    cache[path] = found
    return found


def _code(repo: at.Repo, path: str) -> str:
    return re.sub(r"#.*", "", repo.text(path))


def _uses(repo: at.Repo, src: str, dotted: str) -> bool:
    """`src` imports foundation module `dotted`, names it as a string (a mock.patch target), or
    imports its package and names the module."""
    code = _code(repo, src)
    if re.search(rf"(?<![\w.]){re.escape(dotted)}(?!\w)", code):
        return True
    leaf = dotted.rpartition(".")[2]
    for module, imported in _from_imports(repo, src):
        if module == dotted or module.startswith(dotted + "."):
            return True
        if dotted.startswith(module + ".") and dotted[len(module) + 1:].split(".")[0] in imported:
            if re.search(rf"\b{re.escape(leaf)}\b", code):  # `from pkg import mod`, `from . import mod`
                return True
    return False


def module_importers(repo: at.Repo, path: str) -> list[str]:
    """Tracked .py files that import the foundation module at `path`, directly or through another
    foundation module importing it: ``protocol.schemas`` re-exports ``protocol.power`` and composes
    its types, so every schemas user is a power user."""
    found: list[str] = []
    queue = [path]
    while queue:
        current = queue.pop()
        dotted = ".".join(PurePosixPath(current).relative_to(FOUNDATION).with_suffix("").parts).removesuffix(".__init__")
        for src in repo.tracked:
            if src.endswith(".py") and src != path and src not in found and _uses(repo, src, dotted):
                found.append(src)
                if at._under(src, f"{FOUNDATION}/core_common") and not at.TEST_FILE.search(src):
                    queue.append(src)
    return found


def narrowed(repo: at.Repo, path: str) -> dict[str, str] | None:
    """D-762 stage 0: tests that read a NARROWABLE_TRIGGERS path, or None (FULL) when unresolved.

    Structural foundation changes (a missing file, ``__init__.py`` exports, any non-module file
    no test names) stay None: unknown means everything.
    """
    if not repo.exists(path) or PurePosixPath(path).name in at.IGNORED_BASENAMES:
        return None
    if at._under(path, ARCHITECTURE):
        # Rule 6 (design 0.7): a guard rule or its data runs the whole guard directory, plus outside readers.
        return {ARCHITECTURE: f"architecture guard rules changed ({path})",
                **{t: f"references {path}" for t in repo.referencing_tests(path) if not at._under(t, ARCHITECTURE)}}
    if at.TEST_FILE.search(path):
        return {path: f"changed test file {path}"}
    if at._under(path, f"{FOUNDATION}/core_common") and path.endswith(".py"):
        importers = module_importers(repo, path)
        if not importers:
            return None
        # Runtime wrappers and broad owners need downstream coverage, not just named readers.
        if any(not at.TEST_FILE.search(src) and not at._under(src, FOUNDATION) for src in importers):
            return None
        tests = {t: f"references {path}" for t in repo.referencing_tests(path)}
        for src in importers:
            if at.TEST_FILE.search(src):
                tests.setdefault(src, f"imports {path}")
                continue
            module = repo.module_for(src)
            if module is None:
                # Outside every module: the tests importing its import root or naming it, else unknown.
                prefixes = repo.prefixes_under(src)
                users = [t for t in repo.test_files if prefixes and repo.imports_prefix(t, prefixes)]
                users += repo.referencing_tests(src)
                if not users:
                    return None
                for test in users:
                    tests.setdefault(test, f"uses {src} (imports {path})")
                continue
            suites = [t for t in module.get("tests") or [] if t not in at.BROAD_TESTS]
            if set(module.get("tests") or []) & at.BROAD_TESTS:
                suites += module.get("functional") or []
            for test in suites or ["test"]:
                tests.setdefault(test, f"module {module['name']} ({src} imports {path})")
        return tests
    if path.endswith(".py"):
        return None
    return None  # Naming a config file does not establish all consumers of its values.


def registry_readers(repo: at.Repo, path: str) -> list[str]:
    """Tests that import a registry's reader module when `path` is under a tree that registry lists."""
    cache = vars(repo).setdefault("_registry_trees", {})
    found: list[str] = []
    for registry, (key, reader) in REGISTRIES.items():
        if registry not in cache:
            data = yaml.safe_load(repo.text(registry) or "{}") or {}
            rows = data.get(key) if isinstance(data, dict) else None
            cache[registry] = [r["path"] for r in rows or [] if isinstance(r, dict) and r.get("path")]
        if any(at._under(path, tree) for tree in cache[registry]):
            found += [t for t in repo.test_files if t != path and reader in repo.imports(t) and t not in found]
    return found


HARNESS_YAML = "tools/harness/harness.yaml"
TEST_DEF = re.compile(r"^\s*(?:async\s+)?def test_", re.MULTILINE)


class UniqueKeyLoader(yaml.SafeLoader):
    """yaml.SafeLoader that rejects a repeated mapping key instead of keeping the last value."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=True) for key, _ in node.value]
        repeated = [k for i, k in enumerate(keys) if k in keys[:i]]
        if repeated:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {repeated[0]!r}", node.start_mark)
        return super().construct_mapping(node, deep)


def _uses_reference(text: str) -> bool:
    """The document has an anchor, alias or merge key anywhere (one edit could change many entries)."""
    return any(isinstance(ev, yaml.AliasEvent) or getattr(ev, "anchor", None)
               or (isinstance(ev, yaml.ScalarEvent) and ev.value == "<<" and ev.style is None)
               for ev in yaml.parse(text, Loader=UniqueKeyLoader))


def harness_modules_added(repo: at.Repo, base_text: str, head_text: str) -> tuple[list[dict], str]:
    """``harness.yaml`` changed only by added ``modules`` entries: (added, ""), else ([], why FULL).

    Parsed like ``Repo.load`` (safe loading) but a repeated key, which safe_load silently drops, is
    FULL, and so is any anchor, alias or merge key in head. Ownership is
    deepest-wins (``Repo.module_for``), so an added entry may sit anywhere in the list; what it
    must not do is take a tracked file from an existing module, so that is computed, not guessed.
    """
    try:
        if _uses_reference(head_text):  # before loading: the merge key never reaches construct_mapping
            return [], "head uses a YAML anchor, alias or merge key"
        base, head = yaml.load(base_text, UniqueKeyLoader), yaml.load(head_text, UniqueKeyLoader)
    except yaml.YAMLError as exc:
        return [], f"does not parse: {' '.join(str(exc).split())}"
    if not (isinstance(base, dict) and isinstance(head, dict)
            and isinstance(base.get("modules"), list) and isinstance(head.get("modules"), list)):
        return [], "no modules list on both sides"
    if {k: v for k, v in base.items() if k != "modules"} != {k: v for k, v in head.items() if k != "modules"}:
        return [], "a key other than modules changed"
    old, added, rest = base["modules"], [], iter(base["modules"])
    pending = next(rest, None)
    for entry in head["modules"]:  # base must be head minus the added entries, in order
        if pending is not None and entry == pending:
            pending = next(rest, None)
        else:
            added.append(entry)
    if pending is not None or not added:
        return [], "an existing module entry changed or was removed"
    names = [m.get("name") for m in added if isinstance(m, dict)]
    if len(names) != len(added) or len(set(names)) != len(names) or set(names) & {m.get("name") for m in old}:
        return [], "added module name missing or duplicated"
    for module in added:
        suites = list(module.get("tests") or []) + list(module.get("functional") or [])
        if not isinstance(module.get("path"), str) or not module.get("tests"):
            return [], f"module {module['name']} has no path or tests"
        if any(not isinstance(s, str) or not any(TEST_DEF.search(repo.text(t)) for t in repo.test_files_under(s))
               for s in suites):
            return [], f"module {module['name']}: a tests/functional path has no test function"
        sources = (module["path"], *(module.get("source_paths") or ()))
        clash = next((m["name"] for m in old for s in (m["path"], *m.get("source_paths", ())) for t in sources
                      if at._under(s, t) or at._under(t, s)), None)
        if clash:  # even with no tracked file there yet, the next file added would change owner
            return [], f"module {module['name']} path overlaps module {clash}"
    before, after = (dataclasses.replace(repo, modules=old), dataclasses.replace(repo, modules=head["modules"]))
    for path in repo.tracked:
        owner = before.module_for(path)
        if owner is not None and (after.module_for(path) or {}).get("name") != owner["name"]:
            return [], f"{path} would move from module {owner['name']}"
    # CI's nightly/main-push matrix (ci.yml runs ci_matrix in full mode): a suite only the
    # non-gating `modules` runner reaches is never enforced there, so it cannot skip FULL yet.
    # shortcut: over-strict until that runner gates (deadline 2026-11-15, test_modules_runner_gates_by_2026_11_15); then most module adds narrow on their own, recheck here.
    nightly = [e for e in at.ci_matrix(after, at.Selection("full", []))["include"] if e["kind"] == "pytest"]
    args = [p for e in nightly for inv in e["invocations"] for p in inv]
    ignored = {p.removeprefix("--ignore=") for p in args if p.startswith("--ignore=")}
    gated = [p for e in nightly if e["gating"] for inv in e["invocations"] for p in inv if not p.startswith("-")]
    for module in added:
        files = [t for s in (*module["tests"], *(module.get("functional") or [])) for t in repo.test_files_under(s)]
        if any(t in ignored or not any(at._under(t, g) for g in gated) for t in files):
            return [], f"module {module['name']}: a suite is not in CI's gating full matrix"
    return added, ""
