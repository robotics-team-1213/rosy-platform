"""D-436 change-scoped host test selection (the ``affected`` tier).

Usage (from the repository root)::

    python tools/harness/rosy_harness.py affected [--base main] [--print|--run] [--json]
    python tools/harness/rosy_harness.py affected --base SHA --ci-matrix   # GitHub job matrix

Maps every changed file (``git diff base...HEAD`` plus the working tree) to the
harness module that owns it, adds reverse dependents found through
``platform_parts.yaml`` ``import_prefix`` imports, tests that name the changed
path, and an always-on guard set. Shared foundations, CI/test configuration,
source layout and guard rules, committed folder moves and removed modules, and
files that map to nothing escalate to the full tier: unknown means everything,
never nothing. Foundation modules may narrow to known test readers; unresolved runtime consumers,
config files and CI workflows retain FULL (``affected_narrow.NARROWABLE_TRIGGERS``). ``tools/land.py`` runs a FULL selection's ``full_invocations`` on the lab PCs (D-762 stage 0). The full tier runs on GitHub Actions runners (ci.yml), never
locally by default: ``--run`` on a FULL selection runs only the guards and the
directly affected suites and says so; ``--full`` overrides. Suites whose test files share a basename run as separate pytest
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

from affected_pack import IGNORED_BASENAMES, MAX_INVOCATION_CHARS, SelectionError, pack

import yaml
import affected_narrow  # D-762 stage 0 FULL-trigger narrowing
from affected_ci import (CI_FULL_EXCLUDED, CI_FULL_MATRIX, FLEET_TEST_SECONDS, FULL_SUITES,  # noqa: F401
                         ROOT_SHARDS, SUITE_SHARDS, ci_matrix)  # the CI full-run matrix, re-exported

HARNESS = PurePosixPath("tools/harness")

# D-436 §1: always on. The 2026-10-03 D-418 merge failures all sat here.
GUARD_SET = (
    "test/test_release_boundary_guards.py",
    "test/architecture/test_module_structure.py",
    "test/test_harness_contracts.py",
    "test/test_secret_public_provenance.py",
    "middleware/core/gateway/test/test_protocol_version_alignment.py",
    "test/test_robot_literals.py",
    "test/architecture/test_platform_parts.py",
    # D-762 stage 0: Markdown under a FULL trigger is not FULL; placement still runs.
    "test/architecture/test_document_placement.py",
)

# D-436 §2: a change here can break any suite, so the full tier runs.
FULL_TRIGGERS = (
    ("contracts/foundation/**", "shared foundation (core_common)"),
    ("contracts/ros_idl/**", "shared ROS interfaces"),
    ("tools/harness/**", "harness configuration or the selector itself"),
    (".github/workflows/**", "CI workflow"),
    ("**/conftest.py", "pytest conftest"),
    ("**/pyproject.toml", "packaging / pytest configuration"),
    ("**/setup.py", "packaging"),
    ("**/setup.cfg", "packaging"),
    ("**/pytest.ini", "pytest configuration"),
    ("**/tox.ini", "pytest configuration"),
    ("**/*requirements*.txt", "pinned Python dependencies"),
    # Contract tests reach these through path constants (DEPLOY / "compose.yaml",
    # staged / "runtime/compose.yaml"), which no path match finds reliably.
    ("deploy/**/compose*.yaml", "deploy compose manifest"),
    *((f"deploy/robot/*/{area}/*.{suffix}", f"{area} manifest")
      for area in ("image", "native")
      for suffix in ("service", "timer", "path", "target", "conf", "env", "txt", "json", "yaml", "list")),
    # D-762 stage 0: source layout and guard rules.
    ("**/package.xml", "packaging"),
    ("**/_source_layout.py", "source layout"),
    ("test/architecture/**", "architecture guard rules"),
    ("test/known_failures.txt", "known failures list"),
)
# D-762 stage 0: records under a trigger change no rule, import or layout; the guards still run.
# D-766 4: lowering a ratchet row or registering a size unit is data; test_module_structure still runs.
# Gap registries are data read only by lint/generate and their own contract tests (selected as referencing tests).
# log_repairs.yaml stays FULL: it is an allow-list for the append-only log gate with no stale-entry check.
NOT_TRIGGERS = ("**/*.md", "tools/harness/adr_gaps.txt",
                "tools/harness/sim2real_gaps.yaml", "tools/harness/perception_gaps.yaml",
                "test/architecture/size_ratchet.txt", "test/architecture/size_units.txt")

# A module whose `tests` is the whole root suite is too broad to select by
# ownership; D-436 §1 narrows it to `functional` plus referencing tests.
BROAD_TESTS = frozenset({"test"})
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)*))",
                    re.MULTILINE)




@dataclass
class Selection:
    mode: str  # "affected" or "full"
    changed: list[str]
    reasons: dict[str, list[str]] = field(default_factory=dict)  # test path -> why
    escalations: list[str] = field(default_factory=list)
    invocations: list[list[str]] = field(default_factory=list)
    #: What runs locally when the selection escalated: guards + directly affected suites.
    local_invocations: list[list[str]] = field(default_factory=list)
    #: FULL only: what tools/land.py runs on the lab PCs (D-762 stage 0).
    full_invocations: list[list[str]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"mode": self.mode, "changed": self.changed, "escalations": self.escalations,
                "reasons": self.reasons, "invocations": self.invocations,
                "local_invocations": self.local_invocations,
                "full_invocations": self.full_invocations}


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


def changed_files(repo: Path, base: str, head: str | None = None) -> list[str]:
    """Committed changes since the merge base plus staged, unstaged and untracked files.

    With ``head`` (the pre-push hook's pushed commit): only ``base...head``, no working tree.
    """
    names: set[str] = set()
    names.update(_git(repo, "diff", "--name-only", "--no-renames", f"{base}...{head or 'HEAD'}").splitlines())
    if head is None:
        names.update(_git(repo, "diff", "--name-only", "--no-renames", "HEAD").splitlines())
        names.update(_git(repo, "ls-files", "--others", "--exclude-standard").splitlines())
    return sorted(n.strip() for n in names if n.strip())


def moves(repo: Path, base: str, head: str | None = None) -> list[str]:
    """D-762 stage 0: committed layout changes in ``base...head`` as escalations.

    A rename across directories or a removed non-test Python module changes import
    and path layout that the one-level selector cannot follow.
    """
    found = []
    for line in _git(repo, "diff", "--name-status", "-M", f"{base}...{head or 'HEAD'}").splitlines():
        status, *paths = line.split("\t")
        if status.startswith("R") and PurePosixPath(paths[0]).parent != PurePosixPath(paths[1]).parent:
            found.append(f"{paths[0]} -> {paths[1]}: folder move")
        elif status == "D" and paths[0].endswith(".py") and not TEST_FILE.search(paths[0]):
            found.append(f"{paths[0]}: Python module removed")
    return found


@dataclass
class Repo:
    """Static facts the selector reads: registry, import owners, tracked tests."""

    root: Path
    modules: list[dict]
    owners: list[tuple[str, tuple[str, ...]]]  # (root path, import prefixes)
    tracked: list[str]
    test_files: list[str]
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


def _full_paths(repo: Repo) -> list[str]:
    paths: list[str] = [*GUARD_SET, *FULL_SUITES]
    for module in repo.modules:
        paths += module.get("tests") or []
        paths += module.get("functional") or []
    return [p for p in dict.fromkeys(paths) if repo.exists(p)]


def lab_full_invocations(repo: Repo, local: list[list[str]] = ()) -> list[list[str]]:
    """D-762 stage 0: the full tier on the lab PCs, never fewer suites than the local selection.

    CI's full matrix (suites unsharded, root test/ whole), then every registered module
    suite (`_full_paths`) and every `local` path none of those already covers.
    """
    ci = [inv for entry in CI_FULL_MATRIX for inv in entry["invocations"]] + [["test"]]
    return ci + pack(repo, _outside_ci_matrix([*_full_paths(repo), *(p for inv in local for p in inv)]))


def _outside_ci_matrix(paths: list[str]) -> list[str]:
    """Paths no CI_FULL_MATRIX suite or the root test/ shards already run."""
    covered = [p for entry in CI_FULL_MATRIX for inv in entry["invocations"] for p in inv
               if not p.startswith("-")] + ["test"]
    return [p for p in dict.fromkeys(paths) if not any(_under(p, c) for c in covered)]




def select(repo: Repo, changed: list[str], moved: list[str] = (),
           harness_texts: tuple[str, str] | None = None) -> Selection:
    """`harness_texts`: ``harness.yaml`` at the merge base and at head; without it that file is FULL."""
    sel = Selection(mode="affected", changed=changed, escalations=list(moved))

    def add(path: str, why: str) -> None:
        if repo.exists(path):
            sel.reasons.setdefault(path, [])
            if why not in sel.reasons[path]:
                sel.reasons[path].append(why)

    for guard in GUARD_SET:
        add(guard, "guard set (D-436 1)")

    touched_modules: dict[str, dict] = {}
    broad_fallback_modules: dict[str, dict] = {}
    for path in changed:
        trigger = None if any(_match(path, p) for p in NOT_TRIGGERS) else next(
            (why for pattern, why in FULL_TRIGGERS if _match(path, pattern)), None)
        if trigger and affected_narrow.add_readers(repo, path, trigger, add):
            continue  # D-762 stage 0: a NARROWABLE_TRIGGERS path selected its readers instead
        if path == affected_narrow.HARNESS_YAML and trigger:
            added, why = affected_narrow.harness_modules_added(repo, *harness_texts) if harness_texts else (
                [], "no base to compare")
            if added:
                trigger, reason = None, f"harness.yaml: module(s) added: {', '.join(m['name'] for m in added)}"
                for test in [p for m in added for p in (*m["tests"], *(m.get("functional") or []))] + [
                        "test/test_harness_contracts.py", "test/test_affected_tests.py"]:
                    add(test, reason)
            else:  # land.py HARNESS_TRIGGER matches the suffix, so the reason goes before it
                trigger = f"({why}): {trigger}"
        if trigger:
            # Still map the path below: a FULL selection runs locally as the guards plus
            # these suites (the escalated module's own tests, its referencing tests).
            sel.escalations.append(f"{path}: {trigger}")
        if TEST_FILE.search(path):
            if repo.exists(path):
                add(path, f"changed test file {path}")
            continue
        module = repo.module_for(path)
        referencing = repo.referencing_tests(path) + affected_narrow.registry_readers(repo, path)
        for test in referencing:
            add(test, f"references {path}")
        if module:
            touched_modules[module["name"]] = module
            tests = module.get("tests") or []
            if set(tests) & BROAD_TESTS:
                if referencing:
                    narrowed = [t for t in tests if t not in BROAD_TESTS] + (module.get("functional") or [])
                    for test in narrowed:
                        add(test, f"module {module['name']} ({path}; root test/ narrowed to functional)")
                else:
                    # No test names this file: the narrowing has nothing to stand on.
                    add("test", f"module {module['name']} ({path}; no test names it, whole root suite)")
                    broad_fallback_modules[module["name"]] = module
            else:
                for test in tests:
                    add(test, f"module {module['name']} ({path})")
            continue
        prefixes = repo.prefixes_under(path)
        importing = [t for t in repo.test_files if prefixes and repo.imports_prefix(t, prefixes)]
        for test in importing:
            add(test, f"imports {'/'.join(prefixes)} ({path})")
        if referencing or importing or trigger:
            continue
        if path.endswith((".md", ".test.mjs")):
            # D-436 2: a Markdown note outside every module runs the guards only. No runner runs the three
            # test/learning/perception *.test.mjs today (web/account-session.test.mjs included: CI has no
            # node step and land.py --node only globs test/web), so FULL would add nothing.
            continue
        sel.escalations.append(f"{path}: maps to no module, import root or test (unknown -> full)")

    # Direct reverse dependents (D-436 1): modules whose shipped (non-test) code
    # imports a touched module's prefix, plus any test file importing it. One
    # level only: the transitive closure of core_features or control is nearly
    # the whole tree, and the main-push full run is the net for deeper paths.
    for module in touched_modules.values():
        prefixes = repo.prefixes_under(module["path"])
        if not prefixes:
            continue
        for other in repo.modules:
            if other["name"] == module["name"]:
                continue
            sources = [t for t in repo.tracked if t.endswith(".py") and not TEST_FILE.search(t)
                       and _under(t, other["path"]) and repo.module_for(t) is other]
            if any(repo.imports_prefix(s, prefixes) for s in sources):
                for test in other.get("tests") or []:
                    if test not in BROAD_TESTS:
                        add(test, f"reverse dependent {other['name']} imports {'/'.join(prefixes)}")
        for test in repo.test_files:
            if not _under(test, module["path"]) and repo.imports_prefix(test, prefixes):
                add(test, f"imports {'/'.join(prefixes)} (module {module['name']})")

    if sel.escalations:
        sel.mode = "full"
        # CI runs the entire root suite in parallel shards for FULL. The local
        # pre-push gate keeps the module's functional tests and all named tests,
        # rather than repeating that 15k-test CI suite in one SSH invocation.
        if "test" in sel.reasons and all("whole root suite" in why for why in sel.reasons["test"]):
            sel.reasons.pop("test", None)
            for module in broad_fallback_modules.values():
                for test in module.get("functional") or []:
                    add(test, f"module {module['name']} (FULL local functional)")
    sel.local_invocations = pack(repo, sorted(sel.reasons))
    if sel.mode == "full":
        sel.reasons = {p: ["full tier (D-436 2)"] for p in _full_paths(repo)}
        sel.full_invocations = lab_full_invocations(repo, sel.local_invocations)
    sel.invocations = pack(repo, sorted(sel.reasons))
    return sel


def pytest_command(paths: list[str], python: str = "python") -> list[str]:
    # One suite that cannot import (a wheel missing on this host) must not hide
    # the rest of a packed invocation; the collection error still fails the run.
    # Same ROS launch_testing block as CI (test/known_failures.py NO_ROS_LAUNCH_PLUGINS).
    return [python, "-m", "pytest", *paths, "-q", "--continue-on-collection-errors",
            "-pno:launch_testing", "-pno:launch_ros"]


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


def run(repo_root: Path, sel: Selection, allow_full: bool = False,
        skip: frozenset[str] = frozenset()) -> int:
    invocations = sel.invocations
    if sel.mode == "full" and not allow_full:
        # D-436 4: the full suite runs on GitHub runners, not on this machine.
        print("[affected] FULL tier runs on GitHub Actions (push, then `gh run watch`); running here"
              " only the guards and the suites mapped from the changed files (owning module, direct"
              " reverse dependents, referencing tests). --full overrides.", flush=True)
        invocations = sel.local_invocations
    if skip:
        invocations = [kept for kept in ([p for p in inv if p not in skip] for inv in invocations) if kept]
        print(f"[affected] skipping {len(skip)} path(s) the caller already ran", flush=True)
    status = 0
    for inv in invocations:
        command = pytest_command(inv, sys.executable)
        print("[affected] " + " ".join(pytest_command(inv)), flush=True)
        code = subprocess.run(command, cwd=repo_root).returncode
        # 5 = no tests collected; a selected file that only skips is not a failure.
        if code not in (0, 5):
            status = 1
    return status


def main(repo_root: Path, base: str, mode: str, as_json: bool,
         matrix: bool = False, allow_full: bool = False, skip: tuple[str, ...] = (),
         head: str | None = None) -> int:
    repo = Repo.load(repo_root)
    try:
        changed = changed_files(repo_root, base, head)
        texts = None
        if affected_narrow.HARNESS_YAML in changed:
            merge_base = _git(repo_root, "merge-base", base, head or "HEAD").strip()
            texts = (_git(repo_root, "show", f"{merge_base}:{affected_narrow.HARNESS_YAML}"),
                     _git(repo_root, "show", f"{head}:{affected_narrow.HARNESS_YAML}") if head
                     else (repo_root / affected_narrow.HARNESS_YAML).read_text(encoding="utf-8"))
        sel = select(repo, changed, moves(repo_root, base, head), texts)
    except SelectionError as exc:
        sel = Selection(mode="full", changed=[], escalations=[f"cannot diff against {base!r}: {exc}"])
        sel.reasons = {p: ["full tier (D-436 2)"] for p in _full_paths(repo)}
        sel.invocations = pack(repo, sorted(sel.reasons))
        sel.local_invocations = [list(GUARD_SET)]
        sel.full_invocations = lab_full_invocations(repo, sel.local_invocations)
    if matrix and allow_full and sel.mode != "full":
        sel.mode = "full"
        sel.escalations.append("forced (--full): CI event other than pull_request")
    if matrix:
        print(json.dumps({"mode": sel.mode, "matrix": ci_matrix(repo, sel)}, separators=(",", ":")))
        return 0
    if as_json:
        print(json.dumps(sel.to_json(), indent=2, ensure_ascii=False))
    else:
        print(render(sel), end="")
    if mode == "run":
        return run(repo_root, sel, allow_full, frozenset(skip))
    return 0
