"""D-436 addendum: narrow a module's registered test directory to the test files that reach a changed .py.

A test file is kept when its static import closure (absolute and relative imports, resolved by dotted
path suffix, so it over-selects rather than misses) contains the changed file. ``narrow`` returns None
whenever that guess is unsafe and the caller keeps the whole registered directory.
"""

from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from affected_repo import _under

DYNAMIC = re.compile(r"importlib|subprocess|spec_from_file_location|runpy|__import__|exec_module|os\.system")
WHOLE_DIR_NAMES = ("conftest.py", "__init__.py")
#: Composition roots: files that wire every domain of an app together. The closure does not walk through them, so
#: a test that reaches a domain only by building the whole app is not picked for that domain's change; the
#: publish-time FULL run still covers it.
COMPOSITION_ROOTS = ("operations/fleet/fleet/server/app.py", "operations/fleet/fleet/server/bootstrap/",
                     "operations/fleet/fleet/cli.py")


def is_composition(path: str) -> bool:
    return any(path == root or (root.endswith("/") and path.startswith(root)) for root in COMPOSITION_ROOTS)


def _dotted(path: str) -> list[str]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return [".".join(parts[i:]) for i in range(len(parts))]


class Closure:
    def __init__(self, repo):
        self.repo = repo
        self._index: dict[str, set[str]] | None = None
        self._deps: dict[str, set[str]] = {}
        self._reachable: dict[str, set[str]] = {}
        self._dynamic: dict[str, bool] = {}
        self._tests = set(repo.test_files)

    @property
    def index(self) -> dict[str, set[str]]:
        if self._index is None:
            self._index = {}
            for path in self.repo.tracked:
                if path.endswith(".py"):
                    for name in _dotted(path):
                        self._index.setdefault(name, set()).add(path)
            # A folder without __init__.py inside a package is installed flat into that package (fleet/server/ledger ->
            # fleet.server, fleet._source_layout.SERVER_HOLDERS): index its modules under the parent's names too, or
            # nothing resolves "fleet.server.<module>". Extra names only add matches.
            tracked = set(self.repo.tracked)
            for path in self.repo.tracked:
                p = PurePosixPath(path)
                if path.endswith(".py") and p.stem != "__init__" and f"{p.parent}/__init__.py" not in tracked \
                        and f"{p.parent.parent}/__init__.py" in tracked:
                    for name in _dotted(f"{p.parent.parent}/{p.name}"):
                        self._index.setdefault(name, set()).add(path)
        return self._index

    def deps(self, path: str) -> set[str]:
        if path in self._deps:
            return self._deps[path]
        if is_composition(path):
            self._deps[path] = set()
            return self._deps[path]
        found: set[str] = set()
        try:
            tree = ast.parse(self.repo.text(path))
        except (SyntaxError, ValueError):
            tree = None
        if tree is None:
            self._deps[path] = {"?"}  # unparsable: caller treats as unknown
            return self._deps[path]
        pkg = _dotted(path.replace("/__init__.py", "/x.py") if path.endswith("__init__.py") else path)[0].split(".")[:-1]
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    # shortcut: relative base is resolved against the file's own directory suffix
                    keep = pkg[:len(pkg) - node.level + 1] if node.level > 1 else pkg
                    base = ".".join([*keep, *([base] if base else [])])
                names = [base, *(f"{base}.{a.name}" if base else a.name for a in node.names)]
            for name in names:
                if name:
                    found |= self.index.get(name, set())
                    # importing a.b.c runs a/__init__.py and a/b/__init__.py first
                    parts = name.split(".")
                    for i in range(1, len(parts)):
                        found |= {p for p in self.index.get(".".join(parts[:i]), ()) if p.endswith("/__init__.py")}
        found.discard(path)
        self._deps[path] = found
        return found

    def reach(self, start: str) -> set[str]:
        if start in self._reachable:
            return self._reachable[start]
        seen, todo = {start}, [start]
        while todo:
            for dep in self.deps(todo.pop()):
                if dep not in seen:
                    seen.add(dep)
                    todo.append(dep)
        self._reachable[start] = seen
        return seen

    def has_dynamic_loads(self, test: str) -> bool:
        if test not in self._dynamic:
            reached = self.reach(test)
            self._dynamic[test] = "?" in reached or any(DYNAMIC.search(self.repo.text(path)) for path in reached
                                                       if path == test or path in self._tests or "/test" in path)
        return self._dynamic[test]


def narrow(repo, changed_py: str, test_dir: str, closure: Closure, reverse: bool = False) -> list[str] | None:
    """Test files under ``test_dir`` reaching ``changed_py``; None = keep the whole directory."""
    if not changed_py.endswith(".py") or PurePosixPath(changed_py).name in WHOLE_DIR_NAMES:
        return None
    tests = repo.test_files_under(test_dir)
    if not tests:
        return None
    if any(changed_py in closure.reach(c) for c in repo.tracked if c.endswith("/conftest.py") and _under(c, test_dir)):
        return None  # a conftest runs for every test beside it
    reaching, dynamic = [], []
    for test in tests:
        reached = closure.reach(test)
        if changed_py in reached:
            reaching.append(test)
        elif closure.has_dynamic_loads(test):
            dynamic.append(test)  # dynamic loads can reach anything: keep this file too
    if reverse:  # a reverse dependent's suite: only what reaches the change, plus dynamic loaders
        return [*reaching, *dynamic]
    return [*reaching, *dynamic] if reaching else None  # nobody imports it: the whole directory
