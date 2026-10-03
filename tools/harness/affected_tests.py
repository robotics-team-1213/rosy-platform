"""D-436 change-scoped host test selection (the ``affected`` tier).

Usage (from the repository root)::

    python tools/harness/rosy_harness.py affected [--base main] [--print|--run] [--json]

Maps every changed file (``git diff base...HEAD`` plus the working tree) to the
harness module that owns it, adds reverse dependents found through
``platform_parts.yaml`` ``import_prefix`` imports, tests that name the changed
path, and an always-on guard set. Shared foundations, CI/test configuration and
files that map to nothing escalate to the full tier: unknown means everything,
never nothing. Suites whose test files share a basename run as separate pytest
invocations (gateway and sensing both ship ``test_battery.py``).

Standard library plus PyYAML, like the rest of the harness.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

HARNESS = PurePosixPath("tools/harness")

# D-436 §1: always on. The 2026-10-03 D-418 merge failures all sat here.
GUARD_SET = (
    "test/test_release_boundary_guards.py",
    "test/architecture/test_module_structure.py",
    "test/test_harness_contracts.py",
    "src/runtime/gateway/test/test_protocol_version_alignment.py",
    "test/test_robot_literals.py",
    "test/architecture/test_platform_parts.py",
)

# D-436 §2: a change here can break any suite, so the full tier runs.
FULL_TRIGGERS = (
    ("src/contracts/foundation/**", "shared foundation (core_common)"),
    ("src/contracts/interfaces/**", "shared ROS interfaces"),
    ("tools/harness/**", "harness configuration or the selector itself"),
    (".github/workflows/**", "CI workflow"),
    ("**/conftest.py", "pytest conftest"),
    ("**/pyproject.toml", "packaging / pytest configuration"),
    ("**/setup.py", "packaging"),
    ("**/setup.cfg", "packaging"),
    ("**/pytest.ini", "pytest configuration"),
    ("**/tox.ini", "pytest configuration"),
    ("**/*requirements*.txt", "pinned Python dependencies"),
)

# Whole suites the CI full run (.github/workflows/ci.yml) executes beyond the
# registered module `tests`; the printed full tier is their union.
FULL_SUITES = (
    "src/runtime/events/test",
    "src/runtime/services/test",
    "src/hmi/web_common/test",
    "src/contracts/foundation/test",
)

# A module whose `tests` is the whole root suite is too broad to select by
# ownership; D-436 §1 narrows it to `functional` plus referencing tests.
BROAD_TESTS = frozenset({"test"})
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
                    re.MULTILINE)
IGNORED_BASENAMES = frozenset({"__init__.py", "conftest.py"})


class SelectionError(RuntimeError):
    pass


@dataclass
class Selection:
    mode: str  # "affected" or "full"
    changed: list[str]
    reasons: dict[str, list[str]] = field(default_factory=dict)  # test path -> why
    escalations: list[str] = field(default_factory=list)
    invocations: list[list[str]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"mode": self.mode, "changed": self.changed, "escalations": self.escalations,
                "reasons": self.reasons, "invocations": self.invocations}


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


def changed_files(repo: Path, base: str) -> list[str]:
    """Committed changes since the merge base plus staged, unstaged and untracked files."""
    names: set[str] = set()
    names.update(_git(repo, "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines())
    names.update(_git(repo, "diff", "--name-only", "--no-renames", "HEAD").splitlines())
    names.update(_git(repo, "ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(n.strip() for n in names if n.strip())


@dataclass
class Repo:
    """Static facts the selector reads: registry, import owners, tracked tests."""

    root: Path
    modules: list[dict]
    owners: list[tuple[str, tuple[str, ...]]]  # (root path, import prefixes)
    tracked: list[str]
    test_files: list[str]
    _texts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Repo:
        harness = yaml.safe_load((root / HARNESS / "harness.yaml").read_text(encoding="utf-8"))
        parts = yaml.safe_load((root / HARNESS / "platform_parts.yaml").read_text(encoding="utf-8"))
        owners = [(r["path"], tuple(r.get("import_prefix") or ())) for r in parts.get("roots") or []]
        tracked = sorted(set(_git(root, "ls-files").splitlines()))
        tests = [p for p in tracked if TEST_FILE.search(p)]
        return cls(root, list(harness.get("modules") or []), owners, tracked, tests)

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
        for module in self.modules:
            if _under(path, module["path"]) and (best is None or len(module["path"]) > len(best["path"])):
                best = module
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
        names: set[str] = set()
        for frm, imp in IMPORT.findall(self.text(path)):
            if frm:
                names.add(frm)
            else:
                names.update(n.strip().split(" ")[0] for n in imp.split(","))
        return names

    def imports_prefix(self, path: str, prefixes: tuple[str, ...]) -> bool:
        return any(name == p or name.startswith(p + ".") for name in self.imports(path) for p in prefixes)

    def test_files_under(self, path: str) -> list[str]:
        if path.endswith(".py"):
            return [path]
        return [t for t in self.test_files if _under(t, path)]

    def basename_unique(self, path: str) -> bool:
        name = PurePosixPath(path).name
        return sum(1 for t in self.tracked if PurePosixPath(t).name == name) == 1

    def referencing_tests(self, path: str) -> list[str]:
        """Test files that name `path` (repo path, unique basename, or helper import)."""
        p = PurePosixPath(path)
        needles = [path]
        if p.name not in IGNORED_BASENAMES and self.basename_unique(path):
            needles.append(p.name)
        helper = p.stem if p.suffix == ".py" and not TEST_FILE.search(path) else None
        found = []
        for test in self.test_files:
            if test == path:
                continue
            text = self.text(test)
            if any(n in text for n in needles) or (helper and helper in self.imports(test)):
                found.append(test)
        return found


def _full_paths(repo: Repo) -> list[str]:
    paths: list[str] = [*GUARD_SET, *FULL_SUITES]
    for module in repo.modules:
        paths += module.get("tests") or []
        paths += module.get("functional") or []
    return [p for p in dict.fromkeys(paths) if repo.exists(p)]


def pack(repo: Repo, paths: list[str]) -> list[list[str]]:
    """Group test paths into pytest invocations with no duplicate test basename."""
    kept = [p for p in paths if not any(o != p and _under(p, o) for o in paths)]
    groups: list[tuple[list[str], set[str]]] = []
    for path in kept:
        names = {PurePosixPath(t).name for t in repo.test_files_under(path)} - IGNORED_BASENAMES
        for members, seen in groups:
            if not names & seen:
                members.append(path)
                seen |= names
                break
        else:
            groups.append(([path], set(names)))
    return [members for members, _ in groups]


def select(repo: Repo, changed: list[str]) -> Selection:
    sel = Selection(mode="affected", changed=changed)

    def add(path: str, why: str) -> None:
        if repo.exists(path):
            sel.reasons.setdefault(path, [])
            if why not in sel.reasons[path]:
                sel.reasons[path].append(why)

    for guard in GUARD_SET:
        add(guard, "guard set (D-436 1)")

    touched_modules: dict[str, dict] = {}
    for path in changed:
        trigger = next((why for pattern, why in FULL_TRIGGERS if _match(path, pattern)), None)
        if trigger:
            sel.escalations.append(f"{path}: {trigger}")
            continue
        if TEST_FILE.search(path):
            if repo.exists(path):
                add(path, f"changed test file {path}")
            continue
        module = repo.module_for(path)
        referencing = repo.referencing_tests(path)
        for test in referencing:
            add(test, f"references {path}")
        if module:
            touched_modules[module["name"]] = module
            tests = module.get("tests") or []
            if set(tests) & BROAD_TESTS:
                narrowed = [t for t in tests if t not in BROAD_TESTS] + (module.get("functional") or [])
                for test in narrowed:
                    add(test, f"module {module['name']} ({path}; root test/ narrowed to functional)")
                if not narrowed and not referencing:
                    add("test", f"module {module['name']} ({path}; no narrower test found)")
            else:
                for test in tests:
                    add(test, f"module {module['name']} ({path})")
            continue
        prefixes = repo.prefixes_under(path)
        importing = [t for t in repo.test_files if prefixes and repo.imports_prefix(t, prefixes)]
        for test in importing:
            add(test, f"imports {'/'.join(prefixes)} ({path})")
        if referencing or importing:
            continue
        if path.endswith(".md"):
            continue  # D-436 2: a Markdown note outside every module runs the guards only.
        sel.escalations.append(f"{path}: maps to no module, import root or test (unknown -> full)")

    # Reverse dependents, transitively, through static imports of owned prefixes.
    seen: set[str] = set()
    queue = list(touched_modules.values())
    while queue:
        module = queue.pop()
        if module["name"] in seen:
            continue
        seen.add(module["name"])
        prefixes = repo.prefixes_under(module["path"])
        if not prefixes:
            continue
        for other in repo.modules:
            if other["name"] in seen or other["name"] == module["name"]:
                continue
            sources = [t for t in repo.tracked if t.endswith(".py") and _under(t, other["path"])
                       and repo.module_for(t) is other]
            if any(repo.imports_prefix(s, prefixes) for s in sources):
                for test in other.get("tests") or []:
                    if test not in BROAD_TESTS:
                        add(test, f"reverse dependent {other['name']} imports {'/'.join(prefixes)}")
                queue.append(other)
        for test in repo.test_files:
            if not _under(test, module["path"]) and repo.imports_prefix(test, prefixes):
                add(test, f"imports {'/'.join(prefixes)} (module {module['name']})")

    if sel.escalations:
        sel.mode = "full"
        sel.reasons = {p: ["full tier (D-436 2)"] for p in _full_paths(repo)}
    sel.invocations = pack(repo, sorted(sel.reasons))
    return sel


def pytest_command(paths: list[str], python: str = "python") -> list[str]:
    # One suite that cannot import (a wheel missing on this host) must not hide
    # the rest of a packed invocation; the collection error still fails the run.
    return [python, "-m", "pytest", *paths, "-q", "--continue-on-collection-errors"]


def render(sel: Selection) -> str:
    lines = [f"affected tier (D-436): mode={sel.mode}, {len(sel.changed)} changed file(s)"]
    for path in sel.changed:
        lines.append(f"  changed  {path}")
    if sel.escalations:
        lines.append("escalated to FULL because:")
        lines += [f"  - {e}" for e in sel.escalations]
    else:
        lines.append("selected:")
        for path in sorted(sel.reasons):
            lines.append(f"  {path}")
            lines += [f"      <- {why}" for why in sel.reasons[path]]
    lines.append("pytest invocations (run each separately):")
    lines += ["  " + " ".join(pytest_command(inv)) for inv in sel.invocations]
    return "\n".join(lines) + "\n"


def run(repo_root: Path, sel: Selection) -> int:
    status = 0
    for inv in sel.invocations:
        command = pytest_command(inv, sys.executable)
        print("[affected] " + " ".join(pytest_command(inv)), flush=True)
        code = subprocess.run(command, cwd=repo_root).returncode
        # 5 = no tests collected; a selected file that only skips is not a failure.
        if code not in (0, 5):
            status = 1
    return status


def main(repo_root: Path, base: str, mode: str, as_json: bool) -> int:
    repo = Repo.load(repo_root)
    try:
        changed = changed_files(repo_root, base)
        sel = select(repo, changed)
    except SelectionError as exc:
        sel = Selection(mode="full", changed=[], escalations=[f"cannot diff against {base!r}: {exc}"])
        sel.reasons = {p: ["full tier (D-436 2)"] for p in _full_paths(repo)}
        sel.invocations = pack(repo, sorted(sel.reasons))
    if as_json:
        print(json.dumps(sel.to_json(), indent=2, ensure_ascii=False))
    else:
        print(render(sel), end="")
    if mode == "run":
        return run(repo_root, sel)
    return 0
