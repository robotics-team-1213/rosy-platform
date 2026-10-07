"""Land a topic branch on local main: merge main, test, fast-forward, repeat.

Run from a topic worktree (never the shared main checkout)::

    python tools/land.py [--main-checkout PATH] [--tests auto|none|"<pytest args>"]
                         [--node] [--browser] [--max-rounds N] [--dry-run]

Each round merges the current local ``main`` into the branch, auto-resolves the
append-only/generated conflicts (ADR Log, logs.md, adr_gaps.txt, index.md,
STATUS.md), runs the selected tests, compares them with
``test/known_failures.py``, and fast-forwards main only if main is still the
commit that was tested. A failing step stops the tool: landing is never chained
after a failure. Any other conflict aborts the merge and lists the paths.
Never pushes, stashes, resets or cleans. Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

ADR_LOG = "docs/reference/ROSY ADR Log.md"
ADR_ROW = re.compile(rb"^\| D-(\d+) \|")
GENERATED = {"STATUS.md", "docs/reference/sim2real-gaps.md"}
HARNESS = "tools/harness/rosy_harness.py"
# Every child gets UTF-8 stdio (Korean paths and log text on a cp949 console).
ENV = {**os.environ, "PYTHONUTF8": "1"}


class Stop(Exception):
    """A step failed; the message says why. Exit 1."""


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(cwd), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed:\n{result.stdout}{result.stderr}".rstrip())
    return result


def out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.strip()


def lines(cwd: Path, *args: str) -> list[str]:
    return [line for line in out(cwd, *args).splitlines() if line]


# --- conflict resolution ------------------------------------------------------

def resolver(path: str) -> str | None:
    """How a conflicted path is auto-resolved, or None when a human must decide."""
    name = PurePosixPath(path).name
    if path == ADR_LOG:
        return "adr-log"
    if name == "logs.md":
        return "append"
    if path == "tools/harness/adr_gaps.txt":
        return "union-dedupe"
    # progress.md is hand-written lint input (gates), not generated: a human resolves it.
    if name == "index.md" or path in GENERATED:
        return "generated"
    return None


def _blob(wt: Path, oid: str, path: str) -> bytes:
    # --filters gives the working-tree form (CRLF under core.autocrlf), so the
    # result keeps the file's line endings and `git add` cleans it as usual.
    return subprocess.run(["git", "-C", str(wt), "cat-file", "--filters", f"--path={path}", oid],
                          capture_output=True, check=True, env=ENV).stdout


def conflict_stages(text: str) -> dict[str, dict[int, str]]:
    """`<mode> <oid> <stage>\\t<path>` lines (ls-files -u, merge-tree) -> {path: {stage: oid}}."""
    found: dict[str, dict[int, str]] = {}
    for line in text.splitlines():
        match = re.match(r"^\d+ ([0-9a-f]+) ([123])\t(.+)$", line)
        if match:
            found.setdefault(match.group(3), {})[int(match.group(2))] = match.group(1)
    return found


def union(base: bytes, ours: bytes, theirs: bytes) -> bytes:
    """Both sides' added lines, ours then theirs (git merge-file --union)."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            files.append(Path(tmp, name))
            files[-1].write_bytes(data)
        return subprocess.run(["git", "merge-file", "-p", "--union", *map(str, files)],
                              capture_output=True, env=ENV).stdout


def clashes_are_insertions(base: bytes, ours: bytes, theirs: bytes) -> bool:
    """True when every change touching the other side's change only adds lines.

    A side that rewrote or dropped a base line next to the other side's append
    would come back from a line union with the old line resurrected.
    """
    b = base.splitlines(keepends=True)

    def changes(side: bytes) -> list[tuple[str, int, int]]:
        ops = difflib.SequenceMatcher(None, b, side.splitlines(keepends=True), autojunk=False).get_opcodes()
        return [(op, i1, i2) for op, i1, i2, _, _ in ops if op != "equal"]

    mine, other = changes(ours), changes(theirs)
    for side, against in ((mine, other), (other, mine)):
        for op, i1, i2 in side:
            # Adjacent (touching) ranges conflict in git too, hence <= on both ends.
            if op != "insert" and any(i1 <= j2 and j1 <= i2 for _, j1, j2 in against):
                return False
    return True


def append_blocks(base: bytes, ours: bytes, theirs: bytes) -> bytes | None:
    """logs.md: base + ours' appended block + theirs' appended block, each kept whole.

    Line union would fold lines both entries share ("- 결정: 없음"). None unless
    both sides only appended at the end.
    """
    if not (ours.startswith(base) and theirs.startswith(base)):
        return None
    mine, other = ours[len(base):], theirs[len(base):]
    if mine == other or not other:
        return ours
    if not mine:
        return theirs
    eol = b"\r\n" if b"\r\n" in ours + theirs else b"\n"
    if mine and not mine.endswith(b"\n"):
        mine += eol
    gap = b"" if mine.endswith(eol + eol) or other.startswith((b"\n", b"\r\n")) else eol
    return base + mine + gap + other


def sort_adr_rows(data: bytes) -> bytes:
    """Sort each run of ``| D-n |`` rows by number and drop identical rows; BOM/EOL kept."""
    rows = data.splitlines(keepends=True)
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    result: list[bytes] = []
    i = 0
    while i < len(rows):
        if not ADR_ROW.match(rows[i]):
            result.append(rows[i])
            i += 1
            continue
        j = i
        while j < len(rows) and ADR_ROW.match(rows[j]):
            j += 1
        run = [r.rstrip(b"\r\n") for r in rows[i:j]]
        run = sorted(dict.fromkeys(run), key=lambda r: int(ADR_ROW.match(r).group(1)))
        last_eol = rows[j - 1][len(rows[j - 1].rstrip(b"\r\n")):]
        result += [r + eol for r in run[:-1]] + [run[-1] + last_eol]
        i = j
    return b"".join(result)


def plan(wt: Path, conflicts: dict[str, dict[int, str]]) -> tuple[dict[str, bytes], list[str]]:
    """Resolved bytes per auto-resolvable path, and `path: why` for the rest. Touches nothing."""
    resolved: dict[str, bytes] = {}
    manual: list[str] = []
    for path, stage in conflicts.items():
        kind = resolver(path)
        if not kind:
            manual.append(f"{path}: not in the auto-resolvable set")
            continue
        if set(stage) != {1, 2, 3}:
            manual.append(f"{path}: modify/delete or add/add (stages {sorted(stage)})")
            continue
        base, ours, theirs = (_blob(wt, stage[n], path) for n in (1, 2, 3))
        if kind == "generated":
            data: bytes | None = theirs
        elif kind == "append":
            data = append_blocks(base, ours, theirs)
        elif clashes_are_insertions(base, ours, theirs):
            data = union(base, ours, theirs)
            if kind == "adr-log":
                data = sort_adr_rows(data)
            else:
                data = b"".join(dict.fromkeys(data.splitlines(keepends=True)))
        else:
            data = None
        if data is None:
            manual.append(f"{path}: a side changed existing lines, not only appended")
        else:
            resolved[path] = data
    return resolved, manual


def merge(wt: Path, main_sha: str, branch: str, python: str, dry_run: bool) -> list[str]:
    """Merge main_sha into HEAD; return the auto-resolved paths. Stop on anything else."""
    if dry_run:
        tree = git(wt, "merge-tree", "--write-tree", "--no-messages", "HEAD", main_sha, check=False)
        conflicts = conflict_stages(tree.stdout) if tree.returncode == 1 else {}
        resolved, manual = plan(wt, conflicts)
        print(f"[plan] merge main {main_sha[:10]}: "
              + (f"auto-resolve {sorted(resolved)}, needs a human: {manual}" if conflicts else "no conflicts"))
        if manual:
            raise Stop("merge would conflict outside the auto-resolvable set:\n  " + "\n  ".join(manual))
        return sorted(resolved)
    result = git(wt, "merge", "--no-edit", "-m", f"Merge branch 'main' into {branch}", main_sha, check=False)
    if result.returncode == 0:
        return []
    try:
        conflicts = conflict_stages(out(wt, "ls-files", "-u"))
        resolved, manual = plan(wt, conflicts)
    except (Stop, OSError, subprocess.CalledProcessError) as exc:
        git(wt, "merge", "--abort", check=False)
        raise Stop(f"reading the conflict stages failed, merge aborted:\n{exc}") from exc
    if not conflicts or manual:
        git(wt, "merge", "--abort", check=False)
        raise Stop("merge aborted; resolve by hand in the worktree:\n  "
                   + "\n  ".join(manual or [result.stdout + result.stderr]))
    try:
        for path, data in resolved.items():
            (wt / path).write_bytes(data)
            git(wt, "add", "--", path)
        if any(resolver(p) == "generated" for p in resolved) and (wt / HARNESS).is_file():
            step(wt, [python, HARNESS, "generate"], None, "generate")
            # The worktree was clean before the merge, so every unstaged change is generate's.
            changed = lines(wt, "diff", "--name-only")
            if changed:
                git(wt, "add", "--", *changed)
        git(wt, "commit", "--no-edit")
    except (Stop, OSError, subprocess.CalledProcessError) as exc:
        git(wt, "merge", "--abort", check=False)
        raise Stop(f"auto-resolve of {sorted(resolved)} failed, merge aborted:\n{exc}") from exc
    print(f"[merge] auto-resolved {sorted(resolved)}")
    return sorted(resolved)


# --- test selection -------------------------------------------------------------

def _test_dir(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    return "/".join(parts[: parts.index("test") + 1]) if "test" in parts else None


def fallback_targets(wt: Path, changed: list[str]) -> list[str]:
    """Nearest ancestor ``test/`` dir per changed file; test files map to themselves."""
    targets: list[str] = []
    for path in changed:
        name = PurePosixPath(path).name
        own = _test_dir(path)
        if own:
            target = path if name.startswith("test_") and name.endswith(".py") else own
        else:
            target = next((f"{p}/test".lstrip("./") for p in map(str, PurePosixPath(path).parents)
                           if (wt / p / "test").is_dir()), None)
        if target and (wt / target).exists() and target not in targets:
            targets.append(target)
    return targets


def pack(wt: Path, paths: list[str]) -> list[list[str]]:
    """Split paths into pytest invocations so no two test files share a basename."""
    groups: list[tuple[list[str], set[str]]] = []
    for path in paths:
        root = wt / path
        names = {root.name} if root.is_file() else {p.name for p in root.rglob("test_*.py")}
        for members, seen in groups:
            if not names & seen:
                members.append(path)
                seen |= names
                break
        else:
            groups.append(([path], set(names)))
    return [members for members, _ in groups]


def select(wt: Path, base: str, python: str) -> list[list[str]]:
    """pytest invocations for the branch delta (base...HEAD).

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
    """
    if (wt / "tools/harness/affected_tests.py").is_file():
        result = subprocess.run([python, HARNESS, "affected", "--base", base, "--json"], cwd=wt,
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            sel = json.loads(result.stdout)
            if sel["mode"] == "full":
                # D-436 4: the full tier runs on GitHub runners, as `affected --run` does.
                print("[tests] selector escalated to FULL (" + "; ".join(sel["escalations"][:3])
                      + "); running the guards and mapped suites here, full tier is CI's")
                return sel["local_invocations"]
            return sel["invocations"]
        print(f"[tests] affected selector failed, using nearest test/ dirs:\n{result.stderr.strip()}")
    changed = lines(wt, "diff", "--name-only", f"{base}...HEAD")
    return pack(wt, fallback_targets(wt, changed))


def record_only(path: str) -> bool:
    """Non-code records: a main delta made only of these cannot change a test result."""
    name = PurePosixPath(path).name
    return (name in ("logs.md", "index.md", "progress.md") or path == "tools/harness/adr_gaps.txt"
            or (path.startswith("docs/") and path.endswith(".md")))


# --- running --------------------------------------------------------------------

def step(wt: Path, command: list[str], log: Path | None, label: str, env: dict | None = None,
         allow_fail: bool = False) -> tuple[int, str]:
    print(f"[{label}] {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=wt, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env)
    text = result.stdout + result.stderr
    if log:
        log.write_text(text, encoding="utf-8")
    if result.returncode != 0 and not allow_fail:
        raise Stop(f"{label} failed (exit {result.returncode}):\n{text[-3000:]}")
    return result.returncode, text


def run_tests(wt: Path, args, invocations: list[list[str]], logdir: Path, round_no: int) -> list[str]:
    """Run lint + pytest (+ node); return a summary line per step. Stop on any NEW failure."""
    python = sys.executable
    done = []
    if (wt / HARNESS).is_file():
        step(wt, [python, HARNESS, "lint"], logdir / f"lint-{round_no}.txt", "lint")
        done.append("lint ok")
    env = dict(os.environ)
    if args.browser:
        env.update(ROSY_RUN_BROWSER_TESTS="1", ROSY_BROWSER_TESTS="1")
    for i, inv in enumerate(invocations, 1):
        log = logdir / f"run-{round_no}-{i}.txt"
        code, _ = step(wt, [python, "-m", "pytest", *inv, "-q", "-rfE", "-p", "no:cacheprovider"], log,
                       "pytest", env, allow_fail=True)
        # 2/3/4 (interrupted, internal error, usage/path error) and 5 (nothing collected)
        # print no FAILED lines, so known_failures would wave them through.
        if code not in (0, 1):
            raise Stop(f"pytest {' '.join(inv)} exited {code} (log {log}); not landing")
        check = subprocess.run([python, "test/known_failures.py", str(log)], cwd=wt,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(check.stdout, end="")
        if check.returncode != 0:
            raise Stop(f"NEW failure in {' '.join(inv)} (log {log}); not landing")
        done.append(f"pytest {' '.join(inv)} ok ({log.name})")
    if args.node:
        mjs = sorted(str(p.relative_to(wt).as_posix()) for inv in invocations for t in inv
                     if _test_dir(t) for p in (wt / _test_dir(t) / "web").glob("**/*.mjs"))
        mjs = list(dict.fromkeys(mjs))
        if mjs:
            step(wt, ["node", "--test", *mjs], logdir / f"node-{round_no}.txt", "node")
            done.append(f"node --test {len(mjs)} file(s) ok")
        else:
            done.append("node skipped: no web/*.mjs under the selected test dirs")
    return done


def main_checkout(wt: Path) -> Path:
    path = None
    for line in out(wt, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == "branch refs/heads/main" and path:
            return Path(path)
    raise Stop("no worktree has main checked out; pass --main-checkout")


def on_main(main_co: Path) -> None:
    head = git(main_co, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    if head != "refs/heads/main":
        raise Stop(f"{main_co} has {head or 'a detached HEAD'} checked out, not refs/heads/main")


def tmp_dir(branch: str) -> Path:
    base = os.environ.get("ROSY_LAND_TMP") or ("X:/DevTemp/land" if os.name == "nt" else "/tmp/rosy-land")
    path = Path(base) / branch.replace("/", "-")
    path.mkdir(parents=True, exist_ok=True)
    return path


def land(args) -> int:
    wt = Path(out(Path.cwd(), "rev-parse", "--show-toplevel"))
    branch = out(wt, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("main", "HEAD"):
        raise Stop(f"run from a topic worktree, not on {branch!r}")
    main_co = Path(args.main_checkout) if args.main_checkout else main_checkout(wt)
    on_main(main_co)
    if main_co.resolve() == wt.resolve():
        raise Stop("this is the shared main checkout; run from .worktrees/<topic>")
    dirty = git(wt, "status", "--porcelain").stdout.strip()
    if dirty:
        raise Stop(f"worktree is dirty; commit or remove first:\n{dirty}")
    python = sys.executable
    logdir = tmp_dir(branch)
    summary: list[str] = []
    tested_main: str | None = None
    start = out(wt, "rev-parse", "main")

    for round_no in range(1, args.max_rounds + 1):
        main_sha = out(wt, "rev-parse", "main")
        print(f"== round {round_no}: main {main_sha[:10]}, branch {branch}")
        if git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
            resolved = merge(wt, main_sha, branch, python, args.dry_run)
            summary.append(f"round {round_no}: merged main {main_sha[:10]}"
                           + (f", auto-resolved {resolved}" if resolved else ""))
        candidate = out(wt, "rev-parse", "HEAD")  # the commit the checks below vouch for
        if args.tests == "none":
            invocations: list[list[str]] = []
        elif args.tests == "auto":
            invocations = select(wt, main_sha, python)
        else:
            invocations = [shlex.split(args.tests)]
        if args.dry_run:
            print("[plan] lint, then pytest invocations:")
            print("\n".join("  " + " ".join(inv) for inv in invocations) or "  (none)")
            print(f"[plan] then git -C {main_co} merge --ff-only {candidate}  ({branch})")
            return 0

        delta = lines(wt, "diff", "--name-only", tested_main, main_sha) if tested_main else []
        if tested_main and all(map(record_only, delta)):
            summary.append(f"round {round_no}: main delta ({len(delta)} file(s)) is records only"
                           " (docs/logs/index/progress), lint only")
            invocations = []
        elif args.tests == "none":
            summary.append(f"round {round_no}: tests skipped (--tests none)")
        summary += [f"round {round_no}: {s}" for s in run_tests(wt, args, invocations, logdir, round_no)]
        if invocations or tested_main is None:
            tested_main = main_sha

        if out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved during the round; merging again")
            continue
        tip = out(wt, "rev-parse", f"refs/heads/{branch}")
        if tip != candidate or out(wt, "rev-parse", "HEAD") != candidate:
            raise Stop(f"{branch} moved to {tip[:10]} during the checks; {candidate[:10]} was tested, not that")
        on_main(main_co)
        ff = git(main_co, "merge", "--ff-only", candidate, check=False)
        if ff.returncode == 0:
            landed = out(main_co, "rev-parse", "HEAD")
            count = out(wt, "rev-list", "--count", f"{start}..{landed}")
            print("\n".join(["== landed (not pushed)", *summary,
                             f"rounds: {round_no}", f"commits merged onto main: {count}",
                             f"main is now {landed}"]))
            return 0
        if out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved before the fast-forward; merging again")
            continue
        raise Stop(f"git merge --ff-only refused in {main_co} (left as is):\n{ff.stdout}{ff.stderr}")
    raise Stop(f"main kept moving: gave up after {args.max_rounds} rounds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--main-checkout", help="path of the worktree that has main checked out")
    parser.add_argument("--tests", default="auto", help='auto | none | "<pytest args>"')
    parser.add_argument("--node", action="store_true", help="also node --test the selected test dirs' web/*.mjs")
    parser.add_argument("--browser", action="store_true", help="set ROSY_RUN_BROWSER_TESTS=1 ROSY_BROWSER_TESTS=1")
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args(argv)
    try:
        return land(args)
    except Stop as exc:
        print(f"[land] STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
