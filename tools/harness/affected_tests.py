"""D-436 change-scoped host test selection (the ``affected`` tier).

Usage (from the repository root)::

    python tools/harness/rosy_harness.py affected [--base main] [--print|--run] [--json]
    python tools/harness/rosy_harness.py affected --base SHA --ci-matrix   # GitHub job matrix

Maps every changed file (``git diff base...HEAD`` plus the working tree) to the
harness module that owns it, adds reverse dependents found through
``platform_parts.yaml`` ``import_prefix`` imports, tests that name the changed
path, and an always-on guard set. Shared foundations, CI/test configuration and
files that map to nothing escalate to the full tier: unknown means everything,
never nothing. The full tier runs on GitHub Actions runners (ci.yml), never
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

import yaml

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
)

# Whole suites the CI full run (.github/workflows/ci.yml) executes beyond the
# registered module `tests`; the printed full tier is their union.
FULL_SUITES = (
    "learning/training/pinky/test",
    "learning/registry/policy/test",
    "learning/training/omx/test",
    "learning/curation/omx/test",
    "learning/curation/pinky/test",
    "middleware/core/events/test",
    "middleware/core/services/test",
    "shared/web/test",
    "contracts/foundation/test",
)

# D-436 4: the GitHub full run as parallel matrix entries. Each entry is one
# runner; its `invocations` run in order (suites sharing a test basename stay in
# separate invocations: gateway and sensing both ship test_battery.py, vision and
# games test_preview.py). `ros`: none (host conditions), base (/opt/ros) or
# overlay (+ colcon install, which also builds). `gating: False` reports only.
ROOT_SHARDS = 3
CI_FULL_MATRIX = (
    {"name": "learning-policy", "invocations": [
        ["learning/registry/policy/test"], ["learning/training/omx/test"], ["learning/training/pinky/test"],
        ["learning/curation/omx/test"], ["learning/curation/pinky/test"]], "ros": "none"},
    {"name": "core-domain", "invocations": [[
        "middleware/core/gateway/test", "middleware/core/events/test", "middleware/core/services/test",
        "shared/web/test", "contracts/foundation/test",
        "middleware/apps/device/pinky/profile/test", "middleware/apps/device/omx/profile/test"]], "ros": "none"},
    # Never ran in CI before D-436 (D-191 follow-up); reports until its first green run.
    {"name": "sensing", "invocations": [["middleware/perception/test"]], "ros": "none", "gating": False},
    {"name": "fleet", "invocations": [["operations/fleet/test"]], "ros": "none"},
    {"name": "site-vision-cell", "invocations": [
        ["operations/vision/test"], ["operations/processes/cell/test"],
        ["test/test_platform_palletizing_compat.py", "test/test_platform_cell_submission.py",
         "test/architecture/test_platform_dependency_boundaries.py"]], "ros": "none"},
    {"name": "gz-sim", "invocations": [["integrations/simulation/gazebo/test"]], "ros": "overlay"},
    {"name": "hardware-safety", "invocations": [[
        "middleware/apps/device/pinky/bringup/test", "middleware/drivers/pinky_adc/test",
        "middleware/perception/test/test_ir_adc_lock.py",
        "--ignore=middleware/apps/device/pinky/bringup/test/test_flake8.py",
        "--ignore=middleware/apps/device/pinky/bringup/test/test_pep257.py",
        "--ignore=middleware/apps/device/pinky/bringup/test/test_copyright.py"]], "ros": "base"},
)

# A module whose `tests` is the whole root suite is too broad to select by
# ownership; D-436 §1 narrows it to `functional` plus referencing tests.
BROAD_TESTS = frozenset({"test"})
# Keep path arguments below SSH/Tailscale's remote command limit. The remote
# runner adds its script and options after this budget.
MAX_INVOCATION_CHARS = 3000
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
    #: What runs locally when the selection escalated: guards + directly affected suites.
    local_invocations: list[list[str]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"mode": self.mode, "changed": self.changed, "escalations": self.escalations,
                "reasons": self.reasons, "invocations": self.invocations,
                "local_invocations": self.local_invocations}


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


def pack(repo: Repo, paths: list[str]) -> list[list[str]]:
    """Group tests without duplicate basenames or oversized remote commands."""
    kept = [p for p in paths if not any(o != p and _under(p, o) for o in paths)]
    groups: list[tuple[list[str], set[str]]] = []
    for path in kept:
        if len(path) + 1 > MAX_INVOCATION_CHARS:
            raise SelectionError(f"test path exceeds remote command budget: {path}")
        names = {PurePosixPath(t).name for t in repo.test_files_under(path)} - IGNORED_BASENAMES
        for members, seen in groups:
            if not names & seen and sum(len(p) + 1 for p in members) + len(path) + 1 <= MAX_INVOCATION_CHARS:
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
    broad_fallback_modules: dict[str, dict] = {}
    for path in changed:
        trigger = next((why for pattern, why in FULL_TRIGGERS if _match(path, pattern)), None)
        if trigger:
            # Still map the path below: a FULL selection runs locally as the guards plus
            # these suites (the escalated module's own tests, its referencing tests).
            sel.escalations.append(f"{path}: {trigger}")
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
        if path.endswith(".md"):
            continue  # D-436 2: a Markdown note outside every module runs the guards only.
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
    sel.invocations = pack(repo, sorted(sel.reasons))
    return sel


def ci_matrix(repo: Repo, sel: Selection) -> dict:
    """The GitHub job matrix: CI_FULL_MATRIX plus root test/ shards, or one entry per invocation."""
    if sel.mode == "full":
        root_tests = sorted(t for t in repo.test_files if _under(t, "test"))
        entries = [dict(e) for e in CI_FULL_MATRIX]
        for i in range(ROOT_SHARDS):
            entries.append({"name": f"root-test-{i + 1}of{ROOT_SHARDS}",
                            "invocations": [root_tests[i::ROOT_SHARDS]], "ros": "overlay"})
    else:
        entries = [{"name": f"affected-{i + 1}", "invocations": [inv]}
                   for i, inv in enumerate(sel.invocations)]
    entries.append({"name": "build-smoke", "kind": "smoke", "invocations": []})
    for entry in entries:
        entry.setdefault("kind", "pytest")
        entry.setdefault("gating", True)
        entry.setdefault("ros", "overlay")
    return {"include": entries}


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
        sel = select(repo, changed)
    except SelectionError as exc:
        sel = Selection(mode="full", changed=[], escalations=[f"cannot diff against {base!r}: {exc}"])
        sel.reasons = {p: ["full tier (D-436 2)"] for p in _full_paths(repo)}
        sel.invocations = pack(repo, sorted(sel.reasons))
        sel.local_invocations = [list(GUARD_SET)]
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
