"""Passed pytest invocations of tools/land.py, kept across land.py runs so a retry skips them.

On 2026-10-18 one large merge was landed in five tries (a network drop, a one-line fix of a NEW
failure, main moving); each try re-ran the whole ~11,000-test FULL tier. Each invocation that
passes (test/known_failures.py: 0 NEW, no LOAD-FLAKY rerun, its own evidence usable: finished, host
not lost) is appended, also when another invocation of the run failed or lost its host, to ``<git-common-dir>/rosy-land-cache.jsonl``,
which every worktree of the clone shares. A later run skips an invocation when

* exact: the same argv passed on the same git tree with the same test environment (the hash of
  the CI install inputs ``remote_pytest.deps`` builds the remote venv from), or
* narrow (``--tests auto`` only): the same argv passed on an ancestor commit, and the D-436
  selector run over ``ancestor..candidate`` (the D-762 stage 0 rule land.py already uses for
  main's delta inside one run) selects none of its paths, is not FULL, deletes or renames
  nothing, and leaves the known-failure lists alone (a shorter list can turn an old pass NEW).

Lint, safety-review, size-range and node never come from here. Bad lines are ignored; the file
is trimmed to its last ``KEEP`` lines past ``MAX_LINES``. ``--no-cache`` turns it off.
Standard library only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "remote"))
import remote_pytest  # noqa: E402  (deps: the test-environment identity)

CACHE = "rosy-land-cache.jsonl"
MAX_LINES, KEEP = 2000, 1000
NARROW_COMMITS = 3  # ancestor commits tried for narrow reuse: one selector call each
NARROW = "reused across trees"  # land.py: a narrow reuse is not this candidate's own run (land record)
LISTS = ("test/known_failures.py", "test/known_failures.txt", "test/flaky_quarantine.txt")
OID = re.compile(r"[0-9a-f]{40,64}")
ENV_TOKEN = re.compile(r"^[A-Z_][A-Z0-9_]*=")


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def path(wt: Path) -> Path:
    return Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / CACHE


def env_id(wt: Path, sha: str) -> str | None:
    """The remote venv's identity at sha; None (cache off) when it cannot be computed."""
    try:
        return remote_pytest.deps(wt, sha)[0]
    except (subprocess.CalledProcessError, SystemExit, OSError, IndexError):
        return None


def _valid(entry) -> bool:
    return (isinstance(entry, dict) and all(OID.fullmatch(str(entry.get(k, ""))) for k in ("tree", "commit"))
            and isinstance(entry.get("env"), str) and isinstance(entry.get("argv"), list)
            and all(isinstance(a, str) for a in entry["argv"]))


def entries(wt: Path) -> list[dict]:
    """Valid cache lines, oldest first; unreadable or malformed lines are skipped."""
    try:
        text = path(wt).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if _valid(entry):
            found.append(entry)
    return found


def record(wt: Path, commit: str, tree: str, env: str, inv: list[str], log: Path) -> None:
    target = path(wt)
    line = json.dumps({"tree": tree, "commit": commit, "env": env, "argv": inv, "log": str(log),
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    with open(target, "a", encoding="utf-8") as out:
        out.write(line + "\n")
    if len(target.read_text(encoding="utf-8", errors="replace").splitlines()) > MAX_LINES:
        # shortcut: a peer's append racing this rewrite can be dropped; it only costs that peer a rerun.
        temporary = target.with_suffix(".new")
        temporary.write_text("".join(json.dumps(e) + "\n" for e in entries(wt)[-KEEP:]), encoding="utf-8")
        temporary.replace(target)


def unusable(code: int | None, log: Path) -> str | None:
    """Why a pytest exit gives no verdict (interrupted, lost host, no FAILED lines); None when it does."""
    # 2/3/4 (interrupted, internal error, usage/path error), 5 (nothing collected) and a lost host
    # print no FAILED lines, so known_failures would wave them through.
    if code not in (0, 1):
        return f"exited {code}"
    if code == 1:
        report = log.read_text(encoding="utf-8-sig", errors="replace") if log.is_file() else ""
        if ("[tailscale-ssh: process died: signal:" in report
                or not any(re.match(r"^FAILED \S", line.strip()) for line in report.splitlines())):
            return "exited 1 without usable failure evidence"
    return None


def _paths(inv: list[str]) -> list[str] | None:
    """The test paths of inv; None when it carries pytest options (no path mapping then)."""
    paths = [a.split("::")[0].rstrip("/") for a in inv if not ENV_TOKEN.match(a)]
    return None if any(p.startswith("-") for p in paths) else paths


def _overlap(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _delta_paths(wt: Path, base: str, head: str, python: str, select) -> list[str] | None:
    """Paths the selector picks for base..head; None when narrow reuse is not sound there."""
    if _git(wt, "merge-base", "--is-ancestor", base, head).returncode != 0:
        return None
    status = _git(wt, "diff", "--name-status", "--no-renames", base, head)
    rows = [row.split("\t") for row in status.stdout.splitlines() if row]
    if status.returncode or any(r[0] not in ("M", "A") or r[-1] in LISTS for r in rows):
        return None
    print(f"[cache] selecting for {base[:10]}..{head[:10]} to see what it touches", flush=True)
    try:
        invocations, full = select(wt, base, python, head=head)
    except Exception as exc:  # a selector failure only means no narrow reuse
        print(f"[cache] selector failed ({exc}); no narrow reuse from {base[:10]}")
        return None
    picked = [_paths(inv) for inv in invocations]
    return None if full or None in picked else [p for paths in picked for p in paths]


def split(wt: Path, args, invocations: list[list[str]], head: str, python: str, select):
    """(summary lines of reused invocations, invocations still to run, record(inv, log) for each pass)."""
    def skip(inv, log):
        return None
    if getattr(args, "no_cache", False):
        print("[cache] off (--no-cache)")
        return [], invocations, skip
    env = env_id(wt, head)
    if env is None:
        print("[cache] off: the test-environment hash (remote_pytest.deps) is unavailable here")
        return [], invocations, skip
    tree = _git(wt, "rev-parse", f"{head}^{{tree}}").stdout.strip()
    known = [e for e in entries(wt) if e["env"] == env]
    exact = {tuple(e["argv"]) for e in known if e["tree"] == tree}
    reused, todo = [], []
    for inv in invocations:
        if tuple(inv) in exact:
            reused.append(f"pytest {' '.join(inv)} reused: passed on this tree {tree[:10]} (env {env})")
        else:
            todo.append(inv)
    if todo and args.tests == "auto" and (wt / "tools/harness/affected_tests.py").is_file():
        wanted = {tuple(inv) for inv in todo}
        commits = list(dict.fromkeys(e["commit"] for e in reversed(known) if tuple(e["argv"]) in wanted))
        for commit in commits[:NARROW_COMMITS]:
            delta = _delta_paths(wt, commit, head, python, select)
            if delta is None:
                continue
            passed = {tuple(e["argv"]) for e in known if e["commit"] == commit}
            for inv in [i for i in todo if tuple(i) in passed]:
                paths = _paths(inv)
                if paths and not any(_overlap(p, d) for p in paths for d in delta):
                    todo.remove(inv)
                    reused.append(f"pytest {' '.join(inv)} {NARROW}: passed on {commit[:10]}; the selector for"
                                  f" {commit[:10]}..{head[:10]} picks none of its paths (env {env})")
    for line in reused:
        print(f"[cache] {line}")

    def keep(inv, log):
        record(wt, head, tree, env, inv, log)
    return reused, todo, keep
