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
        return "union"
    if path == "tools/harness/adr_gaps.txt":
        return "union-dedupe"
    # progress.md is hand-written lint input (gates), not generated: a human resolves it.
    if name == "index.md" or path in GENERATED:
        return "generated"
    return None


def _stage(wt: Path, n: int, path: str) -> bytes:
    # --filters gives the working-tree form (CRLF under core.autocrlf), so the
    # union below keeps the file's line endings and `git add` cleans it as usual.
    result = subprocess.run(["git", "-C", str(wt), "cat-file", "--filters", f":{n}:{path}"],
                            capture_output=True)
    return result.stdout if result.returncode == 0 else b""


def union(base: bytes, ours: bytes, theirs: bytes) -> bytes:
    """Both sides' added lines, ours then theirs (git merge-file --union)."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            files.append(Path(tmp, name))
            files[-1].write_bytes(data)
        return subprocess.run(["git", "merge-file", "-p", "--union", *map(str, files)],
                              capture_output=True).stdout


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


def resolve(wt: Path, paths: list[str], python: str) -> None:
    """Resolve auto-resolvable conflicted paths in place and stage them."""
    generated = False
    for path in paths:
        kind = resolver(path)
        if kind == "generated":
            data = _stage(wt, 3, path)
            generated = True
        else:
            data = union(_stage(wt, 1, path), _stage(wt, 2, path), _stage(wt, 3, path))
            if kind == "adr-log":
                data = sort_adr_rows(data)
            elif kind == "union-dedupe":
                data = b"".join(dict.fromkeys(data.splitlines(keepends=True)))
        (wt / path).write_bytes(data)
        git(wt, "add", "--", path)
    if generated and (wt / HARNESS).is_file():
        step(wt, [python, HARNESS, "generate"], None, "generate")
        # The worktree was clean before the merge, so every unstaged change is generate's.
        changed = lines(wt, "diff", "--name-only")
        if changed:
            git(wt, "add", "--", *changed)


def merge(wt: Path, main_sha: str, branch: str, python: str, dry_run: bool) -> list[str]:
    """Merge main_sha into HEAD; return the auto-resolved paths. Stop on anything else."""
    if dry_run:
        tree = git(wt, "merge-tree", "--write-tree", "--name-only", "--no-messages", "HEAD", main_sha,
                   check=False)
        conflicted = [p for p in tree.stdout.splitlines()[1:] if p] if tree.returncode == 1 else []
        manual = [p for p in conflicted if not resolver(p)]
        print(f"[plan] merge main {main_sha[:10]}: "
              + (f"conflicts {conflicted}, needs a human: {manual}" if conflicted else "no conflicts"))
        if manual:
            raise Stop(f"merge would conflict outside the auto-resolvable set: {manual}")
        return conflicted
    result = git(wt, "merge", "--no-edit", "-m", f"Merge branch 'main' into {branch}", main_sha, check=False)
    if result.returncode == 0:
        return []
    conflicted = lines(wt, "diff", "--name-only", "--diff-filter=U")
    manual = [p for p in conflicted if not resolver(p)]
    if not conflicted or manual:
        git(wt, "merge", "--abort", check=False)
        raise Stop("merge aborted; resolve by hand in the worktree:\n  "
                   + "\n  ".join(manual or [result.stdout + result.stderr]))
    resolve(wt, conflicted, python)
    git(wt, "commit", "--no-edit")
    print(f"[merge] auto-resolved {conflicted}")
    return conflicted


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


def scopes(invocations: list[list[str]]) -> list[str]:
    """Source+test roots the selected tests cover: the dir above each test/ dir."""
    found = []
    for path in (p for inv in invocations for p in inv):
        own = _test_dir(path)
        # ponytail: a root test/ file scopes only itself (guards read the whole repo);
        # a main delta that breaks a root guard elsewhere is caught by lint/CI, not here.
        scope = own.rsplit("/", 1)[0] if own and "/" in own else path
        found.append(scope)
    return found


def touches(delta: list[str], scope_list: list[str]) -> bool:
    return any(p == s or p.startswith(s.rstrip("/") + "/") for p in delta for s in scope_list)


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
    if main_co.resolve() == wt.resolve():
        raise Stop("this is the shared main checkout; run from .worktrees/<topic>")
    dirty = git(wt, "status", "--porcelain").stdout.strip()
    if dirty:
        raise Stop(f"worktree is dirty; commit or remove first:\n{dirty}")
    python = sys.executable
    logdir = tmp_dir(branch)
    summary: list[str] = []
    tested_main: str | None = None
    tested_scopes: list[str] = []
    start = out(wt, "rev-parse", "main")

    for round_no in range(1, args.max_rounds + 1):
        main_sha = out(wt, "rev-parse", "main")
        print(f"== round {round_no}: main {main_sha[:10]}, branch {branch}")
        if git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
            resolved = merge(wt, main_sha, branch, python, args.dry_run)
            summary.append(f"round {round_no}: merged main {main_sha[:10]}"
                           + (f", auto-resolved {resolved}" if resolved else ""))
        if args.tests == "none":
            invocations: list[list[str]] = []
        elif args.tests == "auto":
            invocations = select(wt, main_sha, python)
        else:
            invocations = [shlex.split(args.tests)]
        if args.dry_run:
            print("[plan] lint, then pytest invocations:")
            print("\n".join("  " + " ".join(inv) for inv in invocations) or "  (none)")
            print(f"[plan] then git -C {main_co} merge --ff-only {branch}")
            return 0

        delta = lines(wt, "diff", "--name-only", tested_main, main_sha) if tested_main else []
        if tested_main and not touches(delta, tested_scopes):
            summary.append(f"round {round_no}: main delta ({len(delta)} file(s)) outside tested scopes,"
                           " lint only")
            invocations = []
        elif args.tests == "none":
            summary.append(f"round {round_no}: tests skipped (--tests none)")
        summary += [f"round {round_no}: {s}" for s in run_tests(wt, args, invocations, logdir, round_no)]
        if invocations or tested_main is None:
            tested_main, tested_scopes = main_sha, scopes(invocations)

        if out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved during the round; merging again")
            continue
        ff = git(main_co, "merge", "--ff-only", branch, check=False)
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
