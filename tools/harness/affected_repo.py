"""The static repository facts the D-436 selector reads (split from ``affected_tests.py``, D-766 2).

``Repo`` (registry, import owners, tracked tests, file texts) and the path helpers it needs;
``affected_tests`` re-exports every name, so callers keep using ``affected_tests.Repo``.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from affected_pack import IGNORED_BASENAMES, SelectionError

HARNESS = PurePosixPath("tools/harness")
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
                    re.MULTILINE)


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # `**/x` also matches `x` at the repository root.
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SelectionError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


@dataclass
class Repo:
    """Static facts the selector reads: registry, import owners, tracked tests."""

    root: Path
    modules: list[dict]
    owners: list[tuple[str, tuple[str, ...]]]  # (root path, import prefixes)
    tracked: list[str]
    test_files: list[str]
    safety_roots: list[dict] = field(default_factory=list)
    safety_modules: set[str] = field(default_factory=set)
    _texts: dict[str, str] = field(default_factory=dict)
    _imports: dict[str, set[str]] = field(default_factory=dict)
    _tokens: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Repo:
        harness = yaml.safe_load((root / HARNESS / "harness.yaml").read_text(encoding="utf-8"))
        parts = yaml.safe_load((root / HARNESS / "platform_parts.yaml").read_text(encoding="utf-8"))
        owners = [(r["path"], tuple(r.get("import_prefix") or ())) for r in parts.get("roots") or []]
        tracked = sorted(set(_git(root, "ls-files").splitlines()))
        tests = [p for p in tracked if TEST_FILE.search(p)]
        return cls(root, list(harness.get("modules") or []), owners, tracked, tests,
                   list(parts.get("roots") or []), set(parts.get("safety_modules") or ()))

    def text(self, path: str) -> str:
        if path not in self._texts:
            try:
                self._texts[path] = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._texts[path] = ""
        return self._texts[path]

    def exists(self, path: str) -> bool:
        return (self.root / path).exists()

    def module_for(self, path: str) -> dict | None:
        best = None
        best_length = -1
        for module in self.modules:
            for source in (module['path'], *module.get('source_paths', ())):
                if _under(path, source) and len(source) > best_length:
                    best, best_length = module, len(source)
        return best

    def prefixes_under(self, path: str) -> tuple[str, ...]:
        """Import prefixes owned by roots at or below `path`, or by the root owning it."""
        found: list[str] = []
        owner, owner_len = (), -1
        for root, prefixes in self.owners:
            if _under(root, path):
                found += prefixes
            elif _under(path, root) and len(root) > owner_len:
                owner, owner_len = prefixes, len(root)
        return tuple(dict.fromkeys(found or owner))

    def imports(self, path: str) -> set[str]:
        if path in self._imports:
            return self._imports[path]
        names: set[str] = set()
        for frm, imp in IMPORT.findall(self.text(path)):
            if frm:
                names.add(frm)
            else:
                names.update(n.strip().split(" ")[0] for n in imp.split(","))
        self._imports[path] = names
        return names

    def imports_prefix(self, path: str, prefixes: tuple[str, ...]) -> bool:
        return any(name == p or name.startswith(p + ".") for name in self.imports(path) for p in prefixes)

    def tokens(self, path: str) -> set[str]:
        if path not in self._tokens:
            self._tokens[path] = set(re.findall(r"[\w.-]+", self.text(path)))
        return self._tokens[path]

    def test_files_under(self, path: str) -> list[str]:
        if path.endswith(".py"):
            return [path]
        return [t for t in self.test_files if _under(t, path)]

    def test_import_names(self, path: str) -> dict[str, str]:
        """Include sibling helper imports that also populate pytest's module cache."""
        pending = list(self.test_files_under(path))
        visited: set[str] = set()
        names: dict[str, str] = {}
        while pending:
            test = pending.pop()
            if test in visited:
                continue
            visited.add(test)
            names[PurePosixPath(test).name] = test
            for name in self.imports(test):
                sibling = str(PurePosixPath(test).parent / (name.split('.')[0] + '.py'))
                if sibling in self.test_files and sibling not in visited:
                    pending.append(sibling)
        return {name: source for name, source in names.items() if name not in IGNORED_BASENAMES}


    def basename_unique(self, path: str) -> bool:
        name = PurePosixPath(path).name
        return sum(1 for t in self.tracked if PurePosixPath(t).name == name) == 1

    def referencing_tests(self, path: str) -> list[str]:
        """Test files that name `path`.

        By repo path, by a basename unique in the repository, by a helper import,
        or by path components: the basename and its parent directory both appear
        as whole tokens, which is how contract tests build paths
        (``ROOT / "deploy" / "robot" / "pinky_pro" / "compose.yaml"``) for a name
        such as ``compose.yaml`` that several directories share.
        """
        p = PurePosixPath(path)
        needles = [path]
        if p.name not in IGNORED_BASENAMES and self.basename_unique(path):
            needles.append(p.name)
        parts = None
        if p.name not in IGNORED_BASENAMES and p.parent.name:
            parts = (p.name, p.parent.name)
        simple_parts = bool(parts and all(re.fullmatch(r"[\w.-]+", token) for token in parts))
        helper = p.stem if p.suffix == ".py" and not TEST_FILE.search(path) else None
        found = []
        for test in self.test_files:
            if test == path:
                continue
            text = self.text(test)
            if (any(n in text for n in needles) or (helper and helper in self.imports(test))
                    or (parts and (all(token in self.tokens(test) for token in parts)
                                   if simple_parts
                                   else all(re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w.-])", text)
                                            for token in parts)))):
                found.append(test)
        return found
