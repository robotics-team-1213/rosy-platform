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
    #: Read files at this revision instead of the working tree (``--head``: the pushed or landed commit).
    rev: str | None = None
    _texts: dict[str, str] = field(default_factory=dict)
    _imports: dict[str, set[str]] = field(default_factory=dict)
    _tokens: dict[str, set[str]] = field(default_factory=dict)
    _importers: dict[str, list[str]] = field(default_factory=dict)
    _cat: list = field(default_factory=list)  # one `git cat-file --batch` process for `rev`

    @classmethod
    def load(cls, root: Path, rev: str | None = None) -> Repo:
        listing = _git(root, "ls-tree", "-r", "--name-only", rev) if rev else _git(root, "ls-files")
        tracked = sorted(set(listing.splitlines()))
        bare = cls(root, [], [], tracked, [p for p in tracked if TEST_FILE.search(p)], rev=rev)
        harness = yaml.safe_load(bare.text(f"{HARNESS}/harness.yaml"))
        parts = yaml.safe_load(bare.text(f"{HARNESS}/platform_parts.yaml"))
        bare.modules = list(harness.get("modules") or [])
        bare.owners = [(r["path"], tuple(r.get("import_prefix") or ())) for r in parts.get("roots") or []]
        bare.safety_roots, bare.safety_modules = list(parts.get("roots") or []), set(parts.get("safety_modules") or ())
        return bare

    def text(self, path: str) -> str:
        if path not in self._texts:
            self._texts[path] = self._blob(path) if self.rev else self._file(path)
        return self._texts[path]

    def _file(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _blob(self, path: str) -> str:
        if not self._cat:
            self._cat.append(subprocess.Popen(["git", "-C", str(self.root), "cat-file", "--batch"],
                                              stdin=subprocess.PIPE, stdout=subprocess.PIPE))
        proc = self._cat[0]
        proc.stdin.write(f"{self.rev}:{path}\n".encode("utf-8"))
        proc.stdin.flush()
        header = proc.stdout.readline()
        if header.rstrip().endswith((b" missing", b" ambiguous")):  # "<rev:path> missing" may hold spaces
            return ""
        _sha, kind, size = header.split()
        data = proc.stdout.read(int(size) + 1)[:-1]  # the batch output ends each object with a newline
        return data.decode("utf-8", errors="replace") if kind == b"blob" else ""  # a directory reads empty

    def exists(self, path: str) -> bool:
        if not self.rev:
            return (self.root / path).exists()
        if "_paths" not in vars(self):  # every tracked file and its parent directories
            self._paths = {*self.tracked, *(str(d) for p in self.tracked for d in PurePosixPath(p).parents)}
        return path in self._paths

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


    def local_importers(self, path: str, depth: int | None = None) -> set[str]:
        """Stems of the non-test modules beside ``path`` that import it (``depth`` hops; None = closure).

        A test that loads experiment_center reaches experiment_hub through it; without this the hub was
        "unknown -> full" in 17 landings on 2026-11-01, and 9 learning modules had the same gap (D-889 21)."""
        p = PurePosixPath(path)
        siblings = [t for t in self.tracked if t.endswith(".py") and PurePosixPath(t).parent == p.parent
                    and t != path and not TEST_FILE.search(t)]
        found: set[str] = set()
        frontier = {p.stem}
        hops = 0
        while frontier and (depth is None or hops < depth):
            reached: set[str] = set()
            for stem in frontier:
                for sibling in siblings:
                    name = PurePosixPath(sibling).stem
                    if name not in found and stem in self.imports(sibling):
                        found.add(name)
                        reached.add(name)
            frontier, hops = reached, hops + 1
        return found

    def dotted(self, path: str) -> str | None:
        """Runtime import name of a changed ``.py`` below its owning root (``fleet.pipeline.x``); None if unresolved."""
        if not path.endswith(".py") or PurePosixPath(path).name == "__init__.py":
            return None
        roots = [r for r in self.safety_roots if r.get("import_prefix") and path.startswith(r["path"].rstrip("/") + "/")]
        if not roots:
            return None
        root = max(roots, key=lambda r: len(r["path"]))
        rel = path[len(root["path"].rstrip("/")) + 1:-3]
        rel = rel.removeprefix("src/")
        for key, package in sorted((root.get("source_packages") or {}).items(), key=lambda kv: -len(kv[0])):
            if key == "" or rel.startswith(key.rstrip("/") + "/"):
                rest = rel[len(key):].strip("/") if key else rel
                return f"{package}.{PurePosixPath(rest).name}"  # a source package is flattened to its stem
        name = rel.replace("/", ".")
        return name if any(name == p or name.startswith(p + ".") for p in root["import_prefix"]) else None

    def _reaches(self, path: str, name: str) -> bool:
        imports = self.imports(path)
        parent, _, last = name.rpartition(".")
        return (name in imports or any(i.startswith(name + ".") for i in imports)
                or bool(parent and parent in imports and last in self.tokens(path)))

    def imports_changed(self, path: str, changed: list[str]) -> bool:
        """Does ``path`` import a changed module by name, through its parent package, or through one importer?"""
        for changed_path in changed:
            name = self.dotted(changed_path)
            if not name:
                continue
            parent, _, last = name.rpartition(".")
            if parent and parent in self.imports(path):
                init = str(PurePosixPath(changed_path).parent / "__init__.py")
                if last in self.tokens(path) or (init in self.tracked and last in self.tokens(init)):
                    return True
            if self._reaches(path, name) or any(self._reaches(path, hop) for hop in self._hops(changed_path, name)):
                return True
        return False

    def _relative(self, path: str, changed_path: str) -> bool:
        """A sibling re-exporting the changed module with ``from .x import`` (the IMPORT scan skips relative forms)."""
        if PurePosixPath(path).parent != PurePosixPath(changed_path).parent:
            return False
        last = re.escape(PurePosixPath(changed_path).stem)
        return bool(re.search(rf"^\s*from\s+\.{last}\b|^\s*from\s+\.\s+import\b.*\b{last}\b",
                              self.text(path), re.MULTILINE))

    def _hops(self, changed_path: str, name: str) -> list[str]:
        if changed_path not in self._importers:
            self._importers[changed_path] = [h for t in self.tracked if t.endswith(".py") and t != changed_path
                                             and not TEST_FILE.search(t) and (h := self.dotted(t))
                                             and (self._reaches(t, name) or self._relative(t, changed_path))]
        return self._importers[changed_path]

    def basename_unique(self, path: str) -> bool:
        name = PurePosixPath(path).name
        return sum(1 for t in self.tracked if PurePosixPath(t).name == name) == 1

    def referencing_tests(self, path: str, closure: bool = False) -> list[str]:
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
        helpers = {helper} | self.local_importers(path, None if closure else 1) if helper else set()
        found = []
        for test in self.test_files:
            if test == path:
                continue
            text = self.text(test)
            if (any(n in text for n in needles) or (helpers & self.imports(test))
                    or (parts and (all(token in self.tokens(test) for token in parts)
                                   if simple_parts
                                   else all(re.search(rf"(?<![\w.-]){re.escape(token)}(?![\w.-])", text)
                                            for token in parts)))):
                found.append(test)
        if not found and helper and not closure:  # the 2-hop chain: 2026-11-01 unknown -> full guard
            return self.referencing_tests(path, True)
        return found
