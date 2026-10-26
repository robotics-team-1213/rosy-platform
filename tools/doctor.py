"""One read-only look at the landing/publishing pipeline before ``tools/land.py`` or a publish.

    python tools/doctor.py [--hosts]

Each check prints ``OK``, ``WARN`` or ``FAIL`` with one line and, when something is off, the command
that fixes it. Exit 1 on any FAIL. Nothing is changed: the installed pre-push hook against
``tools/hooks/pre-push`` at HEAD (CR ignored), ``rosy.publishOnly``, worktree slots (main included,
15 by docs/reference/shared-checkout.md) and how many ``tools/worktrees.py prune --apply`` would
remove, local ``main`` against ``origin/main`` and the age of the last fetch (``update_status.ref_state``),
and the ``tools/land.py`` queue (tickets, holder, dead or stale tickets; ``land_queue`` removes those
on its next read, this tool does not), and ``land_isolation`` records still open after a night (FAIL). ``--hosts`` also reads each lab PC's
``~/rosy-test/maintenance/last-report.json`` and ``~/rosy-jobs/disk-low`` over ssh. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path[:0] = [str(TOOLS), str(TOOLS / "remote")]

import lab_hosts  # noqa: E402
import land_isolation  # noqa: E402
import land_queue  # noqa: E402
import update_status  # noqa: E402
import worktrees  # noqa: E402

SLOTS = 15  # docs/reference/shared-checkout.md: worktrees, main included (worktrees.CAP is the hard stop)
HOST_SCRIPT = ("cat ~/rosy-test/maintenance/last-report.json 2>/dev/null; echo;"
               " [ -e ~/rosy-jobs/disk-low ] && echo ROSY-DISK-LOW=1 || echo ROSY-DISK-LOW=0")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def check_hook(repo: Path) -> list[tuple]:
    fix = "bash tools/hooks/install.sh"
    source = _git(repo, "show", "HEAD:tools/hooks/pre-push")
    if source.returncode:
        return [("WARN", "pre-push: tools/hooks/pre-push is not in HEAD", None)]
    hooks = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
    installed = (hooks if hooks.is_absolute() else repo / hooks) / "pre-push"
    if not installed.is_file():
        return [("FAIL", f"pre-push: not installed at {installed}", fix)]
    if installed.read_bytes().replace(b"\r", b"") != source.stdout.encode("utf-8").replace(b"\r", b""):
        return [("FAIL", "pre-push: installed hook differs from tools/hooks/pre-push at HEAD", fix)]
    return [("OK", "pre-push: installed hook matches HEAD", None)]


def check_publish_only(repo: Path) -> list[tuple]:
    value = _git(repo, "config", "--bool", "rosy.publishOnly").stdout.strip() or "unset"
    return [("OK", f"rosy.publishOnly: {value}", None)]


def check_worktrees(repo: Path) -> list[tuple]:
    rows = worktrees.scan(repo)[1]
    removable = worktrees.prune(repo, quiet=True, say=lambda *_: None)  # dry run: lists, removes nothing
    text = f"worktrees: {len(rows) + 1} of {SLOTS} slots (main included), {removable} removable"
    if len(rows) + 1 <= SLOTS:
        return [("OK", text, None)]
    return [("WARN", text, worktrees.SWEEP if removable else "python tools/worktrees.py status")]


def check_main(repo: Path, now: float) -> list[tuple]:
    state = update_status.ref_state(repo, now, 12)
    counts = _git(repo, "rev-list", "--left-right", "--count", "main...origin/main")
    if counts.returncode:
        return [("WARN", "main: cannot compare main with origin/main", "git fetch origin")]
    ahead, behind = counts.stdout.split()
    text = f"main: {ahead} ahead, {behind} behind origin/main; last fetch {state['fetched_h']}h ago"
    if state["verdict"] != "ok":
        return [("WARN", f"{text} ({state['problem']})", "git fetch origin")]
    if behind != "0":
        return [("WARN", text, "in the main checkout: git merge --ff-only origin/main (D-868)")]
    return [("OK", text, None)]


def check_queue(repo: Path, now: float) -> list[tuple]:
    qdir = land_queue.queue_dir(repo)
    live, dead = [], []
    for path in sorted(qdir.glob("[0-9]*.json")):
        try:
            age = now - path.stat().st_mtime
            info = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            info = None
        branch = (info or {}).get("branch", "?")
        why = land_queue._stale(info, age)  # the reader's own rule; it only judges, removal is in ahead()
        if why:
            dead.append(f"{path.name} ({branch}: {why})")
        else:
            live.append(branch)
    text = (f"land queue: {len(live) + len(dead)} ticket(s), holder {live[0] if live else 'none'}"
            f", {len(dead)} dead or stale")
    if dead:
        return [("WARN", f"{text}: {'; '.join(dead)}", "the next tools/land.py run removes them")]
    return [("OK", text, None)]


def check_hosts(now: float) -> list[tuple]:
    hosts = lab_hosts.test_hosts()
    if not hosts:
        return [("WARN", "hosts: no test_hosts in private/lab-hosts.json", None)]
    found = []
    for host in hosts:
        try:
            done = subprocess.run([*update_status.SSH, host, HOST_SCRIPT], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        except (OSError, subprocess.TimeoutExpired):
            done = None
        if done is None or done.returncode == 255:
            found.append(("WARN", f"host {host}: unreachable over ssh", None))
            continue
        body, _, flag = done.stdout.rpartition("ROSY-DISK-LOW=")
        low = flag.strip() == "1"
        try:
            report = json.loads(body.strip() or "null") or {}
        except ValueError:
            report = {}
        free = report.get("free_after_GiB")
        text = (f"host {host}: {'?' if free is None else free} GiB free at last maintenance"
                f"{'' if report else ' (no last-report.json)'}, disk-low {'present' if low else 'absent'}")
        found.append(("WARN", text, "docs/solutions/workflow-issues/read-only-test-dirs-fill-lab-disks-2026-10-26.md")
                     if low else ("OK", text, None))
    return found


def check_isolation(repo: Path, now: float) -> list[tuple]:
    """Landed alone runs cut by the budget or skipped (--no-queue) whose files nothing ran alone since."""
    found = land_isolation.open_entries(repo, now)
    if not found:
        return [("OK", "isolation: no landed test files left unrun alone past a night", None)]
    return [("FAIL", f"isolation: {rec['kind']} {rec.get('branch', '?')} {rec['candidate'][:10]} ({rec.get('at', '?')}):"
             f" {len(left)} file(s) never run alone: {', '.join(left[:5])}{' ...' if len(left) > 5 else ''}",
             f"python tools/land_isolation.py close {' '.join(left)}") for rec, left in found]


def run(repo: Path, hosts: bool = False, now: float | None = None, out=print) -> int:
    now = time.time() if now is None else now
    checks = [lambda: check_hook(repo), lambda: check_publish_only(repo), lambda: check_worktrees(repo),
              lambda: check_main(repo, now), lambda: check_queue(repo, now), lambda: check_isolation(repo, now)]
    if hosts:
        checks.append(lambda: check_hosts(now))
    failed = False
    for check in checks:
        try:
            results = check()
        except Exception as exc:  # one broken check must not hide the others
            results = [("FAIL", f"check crashed: {exc!r}", None)]
        for level, text, fix in results:
            failed |= level == "FAIL"
            out(f"{level:<4} {text}" + (f"\n     fix: {fix}" if fix else ""))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hosts", action="store_true", help="also read each lab PC's maintenance report over ssh")
    args = parser.parse_args(argv)
    top = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    if top.returncode:
        print("FAIL not inside a git checkout")
        return 1
    return run(Path(top.stdout.strip()), args.hosts)


if __name__ == "__main__":
    sys.exit(main())
