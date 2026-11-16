"""D-1038 urgent lane: a small fix that must reach origin/main without waiting for the next FULL publish.

    python tools/urgent_lane.py start <short-name> <type>/<topic>   # worktree on origin/main (worktrees.py --from origin/main)
    python tools/urgent_lane.py evidence                           # after committing: remote affected + mapped browsers
    python tools/urgent_lane.py land --reason "<user's words>"     # tools/land.py --urgent onto local main
    python tools/urgent_lane.py publish --topic <topic> [--apply]  # push urgent/<topic>-<date> + merge-commit PR

``evidence`` runs the D-436 affected tier of origin/main..HEAD plus every browser file test/browser_scope.py maps to
the change (ROSY_RUN_BROWSER_TESTS=1) on the test PCs and keeps ``<git-common-dir>/rosy-urgent/<sha>.json``.
``publish`` pushes that evidence commit (never the landed merge of main) and opens the PR; without --apply it only
prints. ``publish_main.py --merge-when-green`` merges an ``urgent/`` PR with every usual check, the FULL land record
replaced by ``verified`` here. Signer rules are unchanged: it still signs only origin/main commits with green exact-main CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path[:0] = [str(TOOLS), str(TOOLS / "remote"), str(ROOT / "test")]

PREFIX = "urgent/"
MAX_COMMITS = 30  # an urgent branch is a fix, not a main sync
SUMMARY = re.compile(r"(?m)^=*\s*\d+ (passed|failed|skipped|errors?|xfailed|xpassed)\b.* in [0-9.]+s\b")
BROWSER = "ROSY_RUN_BROWSER_TESTS=1"


class Stop(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode:
        raise Stop(1, f"git {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:300]}")
    return result


def run_gh(repo: Path, *args: str) -> str:
    result = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise Stop(1, f"gh {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout


def folder(repo: Path) -> Path:
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    return common / "rosy-urgent"


def _changed(repo: Path, base: str, head: str) -> list[str]:
    return [p for p in git(repo, "diff", "--name-only", f"{base}...{head}").stdout.splitlines() if p]


def plan(repo: Path, base: str, head: str) -> list[list[str]]:
    """The affected tier of the change plus its mapped browser files as one opted-in invocation."""
    import browser_scope  # noqa: PLC0415
    changed = _changed(repo, base, head)
    result = subprocess.run([sys.executable, "tools/harness/rosy_harness.py", "affected", "--base", base,
                             "--head", head, "--json"], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise Stop(1, f"affected selector failed (exit {result.returncode}); not guessing tests")
    invocations = [list(inv) for inv in json.loads(result.stdout)["invocations"]]
    browsers = browser_scope.targets(changed)
    if browsers:
        invocations.append([BROWSER, *browsers])
    if not invocations:
        raise Stop(1, "no tests selected for this change; an urgent fix still needs evidence")
    return invocations


def _clean(inv: list[str], log: Path, code) -> bool:
    import known_failures  # noqa: PLC0415
    import land_browser  # noqa: PLC0415
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    known = known_failures.load_known((ROOT / "test/known_failures.txt").read_text(encoding="utf-8"))
    new = known_failures.compare(text, known)[0]
    return (code in (0, 1) and not new and bool(SUMMARY.search(text))
            and not (BROWSER in inv and land_browser.vacuous(inv, log)))


def collect(repo: Path, logdir: Path, runner=None) -> Path:
    """Run the plan on the test PCs for HEAD and write the evidence file; Stop(1) when anything is not clean."""
    import remote_pytest  # noqa: PLC0415
    runner = runner or remote_pytest.run
    if git(repo, "status", "--porcelain").stdout.strip():
        raise Stop(1, "uncommitted changes: evidence is about the committed tip only")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    base = git(repo, "rev-parse", "origin/main").stdout.strip()
    check_range(repo, base, head)
    invocations = plan(repo, base, head)
    logs = [logdir / f"urgent-{n}.txt" for n in range(len(invocations))]
    codes = runner(invocations, logs, head, repo=repo, label="urgent")
    bad = [" ".join(inv) for inv, log, code in zip(invocations, logs, codes) if not _clean(inv, log, code)]
    if bad:
        raise Stop(1, "urgent evidence is red or incomplete: " + "; ".join(bad))
    target = folder(repo)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{head}.json"
    path.write_text(json.dumps({
        "sha": head, "base": base, "tier": "urgent", "invocations": invocations,
        "logs": [{"path": str(log), "sha256": hashlib.sha256(log.read_bytes()).hexdigest()} for log in logs],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2) + "\n", encoding="utf-8")
    return path


def check_range(repo: Path, base: str, head: str) -> None:
    if git(repo, "merge-base", "--is-ancestor", base, head, check=False).returncode:
        raise Stop(1, "the branch is not on origin/main: start it with `urgent_lane.py start`")
    count = int(git(repo, "rev-list", "--count", f"{base}..{head}").stdout.strip() or 0)
    if count > MAX_COMMITS:
        raise Stop(1, f"{count} commits over origin/main: an urgent branch holds the fix only")


def verified(repo: Path, sha: str) -> bool:
    """True when the evidence file for sha is intact, covers the change's mapped browser files and is clean."""
    try:
        data = json.loads((folder(repo) / f"{sha}.json").read_text(encoding="utf-8"))
        import browser_scope  # noqa: PLC0415
        base = data["base"]
        if data["sha"] != sha or data["tier"] != "urgent" or not data["invocations"]:
            return False
        if git(repo, "merge-base", "--is-ancestor", base, sha, check=False).returncode:
            return False
        opted = {t for inv in data["invocations"] if BROWSER in inv for t in inv}
        if not set(browser_scope.targets(_changed(repo, base, sha))) <= opted:
            return False
        for inv, entry in zip(data["invocations"], data["logs"]):
            log = Path(entry["path"])
            if hashlib.sha256(log.read_bytes()).hexdigest() != entry["sha256"] or not _clean(inv, log, 0):
                return False
        return len(data["logs"]) == len(data["invocations"])
    except (OSError, ValueError, KeyError, TypeError, Stop):
        return False


def publish(repo: Path, sha: str, topic: str, apply: bool, now: datetime) -> str:
    if not verified(repo, sha):
        raise Stop(1, f"no clean urgent evidence for {sha[:10]}: run `urgent_lane.py evidence` on that commit first")
    base = json.loads((folder(repo) / f"{sha}.json").read_text(encoding="utf-8"))["base"]
    check_range(repo, base, sha)
    branch = f"{PREFIX}{topic}-{now.strftime('%Y%m%d')}"
    if not re.fullmatch(r"urgent/[a-z0-9][a-z0-9-]*-\d{8}", branch):
        raise Stop(2, f"topic must be lowercase letters, digits and '-': {topic!r}")
    if not apply:
        return f"dry run: would push {sha[:10]} to {branch} and open a merge-commit PR to main; --apply to do it"
    git(repo, "push", "origin", f"{sha}:refs/heads/{branch}")
    subject = git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
    url = run_gh(repo, "pr", "create", "--base", "main", "--head", branch, "--title", f"urgent: {subject}",
                 "--body", f"Urgent lane (D-1038). Evidence: rosy-urgent/{sha}.json (affected tier plus mapped browser"
                           f" files on the test PCs). Merge with a merge commit via"
                           f" `publish_main.py --merge-when-green <PR> --apply`; never squash.").strip()
    return f"pushed {sha[:10]} to {branch}; PR {url}"


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("name")
    start.add_argument("branch")
    ev = sub.add_parser("evidence")
    ev.add_argument("--log-dir", type=Path, required=True)
    land = sub.add_parser("land")
    land.add_argument("--reason", required=True, help="the user's words for the urgent landing")
    pub = sub.add_parser("publish")
    pub.add_argument("--topic", required=True)
    pub.add_argument("--sha", help="default: HEAD")
    pub.add_argument("--apply", action="store_true", help="push and open the PR (default: dry run)")
    args = parser.parse_args(argv)
    repo, now = args.repo, now or datetime.now(timezone.utc)
    try:
        if args.command == "start":
            return subprocess.run([sys.executable, str(TOOLS / "worktrees.py"), "new", args.name, args.branch,
                                   "--from", "origin/main"], cwd=repo).returncode
        if args.command == "evidence":
            args.log_dir.mkdir(parents=True, exist_ok=True)
            print(f"[urgent] evidence {collect(repo, args.log_dir)}")
            return 0
        if args.command == "land":
            head = git(repo, "rev-parse", "HEAD").stdout.strip()
            if not verified(repo, head):
                raise Stop(1, "land only a tip that has clean urgent evidence; run `urgent_lane.py evidence`")
            print(f"[urgent] land {head}; then publish --sha {head} (the landed merge of main is not pushed)")
            return subprocess.run([sys.executable, str(TOOLS / "land.py"), "--urgent", args.reason], cwd=repo).returncode
        sha = git(repo, "rev-parse", args.sha or "HEAD").stdout.strip()
        print(f"[urgent] {publish(repo, sha, args.topic, args.apply, now)}")
        return 0
    except Stop as stop:
        print(f"[urgent] {stop}", file=sys.stderr)
        return stop.code


if __name__ == "__main__":
    sys.exit(main())
