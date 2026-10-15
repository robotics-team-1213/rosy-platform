"""D-762 stage 0 narrowing for the ``affected`` tier (split from ``affected_tests.py``).

A ``contracts/foundation`` module may select its known test readers. Runtime consumers,
config files and CI workflows retain FULL until their downstream coverage is established.
``affected_tests.select`` calls `add_readers` for every triggered path.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import affected_tests as at  # attributes read at call time, so the cyclic import is safe

# D-762 stage 0 ("넓은 경로 일치가 아니라 실제 영향"): triggers whose real readers the selector can
# find. A path matching only these selects its readers (`narrowed`); no reader found -> FULL.
NARROWABLE_TRIGGERS = ("contracts/foundation/**",)
FOUNDATION = "contracts/foundation"
FROM_IMPORT = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(\([^)]*\)|[^\n]*)", re.MULTILINE)


def add_readers(repo: at.Repo, path: str, trigger: str, add) -> bool:
    """Select the readers of a triggered `path` through `add`; False (FULL) when it cannot narrow."""
    hits = [pattern for pattern, _ in at.FULL_TRIGGERS if at._match(path, pattern)]
    found = narrowed(repo, path) if hits and all(p in NARROWABLE_TRIGGERS for p in hits) else None
    if found is None:
        return False
    # D-762 stage 0: the readers found, not the whole tree; foundation keeps its own suite.
    if at._under(path, FOUNDATION) and not at.TEST_FILE.search(path):
        found.setdefault(f"{FOUNDATION}/test", f"module core_common ({path})")
    for test, why in found.items():
        add(test, f"{why} (narrowed from: {trigger})")
    return True


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
