"""Publish local main to origin as a merge-commit PR (D-868 2), dry run unless --apply.

    python tools/publish_main.py [--min-hours 6] [--force-blocked "<reason>"] [--apply]
    python tools/publish_main.py --merge-when-green <PR> [--apply]

Publish mode:
1. ``git fetch origin``. If origin/main is not an ancestor of local main, ``git merge-tree`` (no checkout
   is touched) decides: conflicts only in ``SYNC_RECORDS`` (content conflicts) -> exit 4 and the sync
   landing commands; anything else (code, add/add, rename/delete) -> exit 3 "sync needs 동기화·게시 담당". This
   version never performs a sync landing itself.
2. Publish SHA: the newest commit of ``--topo-order --ancestry-path origin/main..main`` (contains
   origin/main, is in local main) with a green FULL land record. Not ``--first-parent``: a land.py landing
   is a merge with the topic branch as first parent, so the main tips that hold records sit on second
   parents. **Green FULL** = ``tools/hooks/land_record.py`` holds a record for exactly that SHA (land.py
   writes one only after a fast-forward of that very candidate with 0 NEW, no LOAD-FLAKY and no pass
   borrowed from another tree), its base is an ancestor of the SHA, and its tier is ``full``: the
   record's ``tier`` field when present, else (older records) one invocation exactly ``["test"]`` (root
   test/ whole: only ``lab_full_invocations``, the FULL tier, runs it; the affected tier names root test
   files one by one). If records exist in the range but none has a ``tier`` string or an ``invocations``
   list of lists, the format is unknown: exit 8, never a silent "nothing to publish".
3. Due when the last publish (newest ``origin/publish/main-YYYYMMDD[-HH]`` by name; with --apply also
   merged ``publish/main-`` PRs from gh) is older than --min-hours, or ``--force-blocked`` names a waiting PR.
4. --apply: refuse if a publish PR is open; check the Safety-Review range (``safety_review.py origin/main
   <sha>`` at that SHA) and push ``<sha>:refs/heads/publish/main-YYYYMMDD-HH`` (UTC) from a temporary
   detached worktree at that SHA under ``<git-common-dir>/rosy-publish/`` (pre-push selects tests from the
   working tree), never --no-verify or force; ``gh pr create`` with the publish facts (lag = landings on
   main after the SHA that this PR leaves out); remove the worktree (``worktree_rules`` tombstone when a
   held handle keeps the folder).

Merge mode (``--merge-when-green``): the PR must be an open ``publish/main-`` PR whose head still has a
green FULL record, ``mergeable`` MERGEABLE, ``mergeStateStatus`` not DIRTY/BEHIND, and check ``ci-result``
SUCCESS; --apply then runs ``gh pr merge --merge --match-head-commit <head>``, fetches, and prints the
sync-back: origin/main is now M(old origin, SHA) and local main has usually moved past the SHA, so a
fast-forward is impossible; ``git merge origin/main`` in a fresh worktree and ``land.py`` (exit 3 instead
when merge-tree finds code conflicts). PRs are never closed, reopened or force-pushed.

Exit codes: 0 done, planned (dry run), nothing to publish or not due | 1 git/gh failure, Safety-Review
range red, ci-result failed or a refusal (branch exists, PR not a publish PR) | 2 usage | 3 sync needs
동기화·게시 담당 | 4 clean sync landing needed first | 5 not ready yet (ci-result pending, mergeable UNKNOWN) |
6 PR not mergeable: sync needed | 7 a publish PR is already open | 8 land record format not recognised |
9 secret scan hit in origin/main..SHA (commit, path and rule printed, never the value).

Secret scan (D-889 5): a merge-commit publish ships every commit, so before planning a publish the lines
each commit in origin/main..SHA adds (``git log -p --cc -U0``: plain diffs, and lines a merge adds that
no parent has) go through the repository scanner ``deploy/robot/pinky_pro/release/secret_scan.py``
(``scan_text`` with ``public_provenance.json`` and the ``scan_files`` fixture/prose excuses). A value added
and removed inside the range is still caught; the tip tree alone would miss it. Hits reviewed as not secrets
are listed by (commit, path, rule), never by value, in ``BASELINE``; only an exact triple is skipped.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS / "hooks"))
import land_record  # noqa: E402  (green land.py results per landed commit)
sys.path.insert(0, str(TOOLS))
import worktree_rules  # noqa: E402  (tombstone for a removed worktree folder a handle still holds)
SCANNER = TOOLS.parent / "deploy" / "robot" / "pinky_pro" / "release"
sys.path.insert(0, str(SCANNER))
import secret_scan  # noqa: E402  (the one repository secret scanner: tokens, keys, PSKs, SHA-256 rows)
BASELINE = "deploy/robot/pinky_pro/release/publish_secret_baseline.json"

SYNC_RECORDS = frozenset({"docs/logs.md", "docs/index.md", "tools/harness/adr_gaps.txt"})
PREFIX = "publish/main-"
STAMP = re.compile(r"publish/main-(\d{8})(?:-(\d{2}))?")
D868 = "docs/adr/D-868-local-main-first-merge-commit-publish.md"
GENERATED_BY = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"


class Stop(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise Stop(1, f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}")
    return result


def run_gh(repo: Path, *args: str) -> str:
    result = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    if result.returncode != 0:
        raise Stop(1, f"gh {' '.join(args[:3])} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def ancestor(repo: Path, a: str, b: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def sync_conflicts(repo: Path) -> list[str] | None:
    """None when origin/main merges into main with only SYNC_RECORDS content conflicts, else what blocks."""
    tree = git(repo, "merge-tree", "--write-tree", "--name-only", "main", "origin/main", check=False)
    if tree.returncode not in (0, 1):
        raise Stop(1, f"git merge-tree failed ({tree.returncode}): {tree.stderr.strip()}")
    files, _, messages = tree.stdout.partition("\n\n")
    blocking = [p for p in files.splitlines()[1:] if p not in SYNC_RECORDS]
    for line in messages.splitlines():
        content = re.fullmatch(r"CONFLICT \(content\): Merge conflict in (.+)", line)
        if line.startswith("CONFLICT") and not (content and content[1] in SYNC_RECORDS):
            blocking.append(line)
    return sorted(set(blocking)) or None


def sync_commands(now: datetime) -> str:
    name = f"sync-origin-{now:%Y%m%d-%H}"
    return ("\n  python tools/worktrees.py new {0} fix/{0}\n  cd .worktrees/{0}\n  git merge origin/main"
            "   # clean or records only: logs.md/adr_gaps.txt union, index.md by rosy_harness.py generate\n"
            "  python tools/land.py --tests auto").format(name)


def tier(record: dict) -> str | None:
    """The record's tier, or None when neither the ``tier`` field nor the invocations can tell."""
    if isinstance(record.get("tier"), str):
        return record["tier"]
    invocations = record.get("invocations")
    if isinstance(invocations, list) and all(isinstance(inv, list) for inv in invocations):
        return "full" if ["test"] in invocations else "affected"
    return None


def green_full(repo: Path, sha: str) -> bool:
    record = land_record.read(repo, sha)
    return bool(record) and tier(record) == "full" and ancestor(repo, record["base"], sha)


def publish_sha(repo: Path) -> str | None:
    seen = known = 0
    for sha in git(repo, "rev-list", "--topo-order", "--ancestry-path", "origin/main..main").stdout.split():
        record = land_record.read(repo, sha)
        if record is None:
            continue
        seen += 1
        known += tier(record) is not None
        if green_full(repo, sha):
            return sha
    if seen and not known:
        raise Stop(8, f"{seen} land record(s) past origin/main, none with a known format (tier field or"
                      " invocations): fix publish_main.tier before publishing")
    return None


def _scan_file(commit: str, path: str, added: list[str], provenance) -> list[tuple[str, str, str]]:
    name = path.rsplit("/", 1)[-1]
    if not added or name in secret_scan.DEFAULT_EXCLUDED_NAMES \
            or "." + name.rsplit(".", 1)[-1].lower() in secret_scan.DEFAULT_EXCLUDED_SUFFIXES:
        return []
    in_fixtures = path.startswith(secret_scan.FIXTURE_ROOT) or "/test/" in f"/{path}"  # as scan_files
    quotes = secret_scan.KNOWN_PROSE_QUOTES.get(path, frozenset())
    return [(commit, path, f.kind) for f in secret_scan.scan_text(path, "\n".join(added), public_provenance=provenance)
            if not (in_fixtures and any(v in f.excerpt for v in secret_scan.KNOWN_FIXTURES))
            and not any(q in f.excerpt for q in quotes)]


def scan_range(repo: Path, base: str, head: str) -> tuple[int, list[tuple[str, str, str]]]:
    """(commits read, hits as (commit, path, rule)) over the lines every commit in base..head adds."""
    policy = repo / "deploy/robot/pinky_pro/release/public_provenance.json"
    provenance = secret_scan.load_public_provenance(policy) if policy.is_file() else frozenset()
    proc = subprocess.Popen(["git", "-C", str(repo), "-c", "core.quotePath=false", "log", "-p", "--cc", "-U0",
                             "--no-color", "--no-ext-diff", "--format=%x00%H", f"{base}..{head}"],
                            stdout=subprocess.PIPE, encoding="utf-8", errors="replace")
    commits, hits = 0, []
    commit = path = ""
    width, added, hunk = 1, [], False
    for line in proc.stdout:  # streamed: the first publish reads ~2,700 commits
        line = line.rstrip("\n")
        if line.startswith("\0") or line.startswith("diff --"):
            hits += _scan_file(commit, path, added, provenance)
            path, added, hunk = "", [], False
            if line.startswith("\0"):
                commit, commits = line[1:], commits + 1
            else:
                width = 1 if line.startswith("diff --git") else 2
        elif line.startswith("@@"):
            width, hunk = len(line) - len(line.lstrip("@")) - 1, True  # @@ plain, @@@ two parents, ...
        elif line.startswith("+++ ") and not hunk:
            path = line[6:] if line.startswith("+++ b/") else ""
        elif path and line[:width] == "+" * width:  # every parent lacks it: new in this commit
            added.append(line[width:])
    hits += _scan_file(commit, path, added, provenance)
    if proc.wait() != 0:
        raise Stop(1, f"git log -p {base}..{head} failed ({proc.returncode})")
    return commits, hits


def load_baseline(repo: Path) -> frozenset[tuple[str, str, str]]:
    """Reviewed (commit, path, rule) hits that are not secrets; holds no values. Malformed -> Stop."""
    path = repo / BASELINE
    if not path.is_file():
        return frozenset()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["schema"] == "rosy.publish-secret-baseline/1" and set(doc) == {"schema", "reviewer", "records"}
        assert isinstance(doc["reviewer"], str) and doc["reviewer"].startswith("agent review")  # who reviewed, not a sign-off
        entries = set()
        for row in doc["records"]:
            assert set(row) == {"commit", "path", "rule", "verdict", "reviewed"}
            assert re.fullmatch(r"[0-9a-f]{40}", row["commit"]) and row["verdict"] == "reviewed: not a secret"
            entries.add((row["commit"], row["path"], row["rule"]))
        return frozenset(entries)
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        raise Stop(1, f"{BASELINE} is malformed ({exc!r}); not publishing") from exc


def secret_gate(repo: Path, sha: str) -> str:
    commits, found = scan_range(repo, "origin/main", sha)
    baseline = load_baseline(repo)
    hits = [hit for hit in found if hit not in baseline]  # a new commit or another rule still stops
    if hits:
        shown = "\n".join(f"  {c[:10]} {p} [{rule}]" for c, p, rule in hits[:50])
        raise Stop(9, f"secret scan: {len(hits)} hit(s) in origin/main..{sha[:10]} (values redacted); not"
                      f" publishing:\n{shown}" + ("\n  ..." if len(hits) > 50 else ""))
    skipped = f", {len(found)} reviewed baseline hit(s) skipped" if found else ""
    return f"secret scan: {commits} commits' added lines clean{skipped}"


def _stamp(name: str) -> datetime | None:
    match = STAMP.search(name)
    if not match:
        return None
    return datetime.strptime(match[1] + (match[2] or "00"), "%Y%m%d%H").replace(tzinfo=timezone.utc)


def last_publish(repo: Path, apply: bool) -> datetime | None:
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/remotes/origin/{PREFIX}*").stdout
    times = [t for t in map(_stamp, refs.split()) if t]
    if apply:
        merged = json.loads(run_gh(repo, "pr", "list", "--state", "merged", "--search", f"head:{PREFIX}",
                                   "--json", "headRefName,mergedAt", "--limit", "20") or "[]")
        times += [datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")) for pr in merged if pr.get("mergedAt")]
    return max(times, default=None)


def safety_range(worktree: Path, sha: str) -> str:
    """The Safety-Review check of origin/main..sha with that SHA's own script; Stop when a trailer is missing."""
    run = subprocess.run([sys.executable, "tools/harness/safety_review.py", "origin/main", sha], cwd=worktree,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise Stop(1, f"Safety-Review range origin/main..{sha[:10]} is red:\n{run.stdout}{run.stderr}".rstrip())
    checked = re.search(r"(\d+) commit\(s\) checked", run.stdout)
    return f"{checked[1] if checked else '?'} commits checked, 0 missing"


def pr_body(repo: Path, sha: str, why: str, safety: str) -> str:
    count = lambda rng: git(repo, "rev-list", "--count", rng).stdout.strip()  # noqa: E731
    landings = sum(land_record.read(repo, c) is not None for c in git(repo, "rev-list", f"{sha}..main").stdout.split())
    remote = git(repo, "remote", "get-url", "origin").stdout.strip().removesuffix(".git")
    link = f"{remote}/blob/main/{D868}" if remote.startswith("https://") else D868
    return "\n".join([
        "## 무엇을, 왜", "",
        f"D-868 게시: 로컬 main의 녹색 FULL 착지 커밋을 merge commit으로 올린다 ({why}). [D-868]({link})", "",
        "## 게시 사실", "",
        f"- 게시 SHA: `{sha}` (FULL 착지 기록 {land_record.read(repo, sha)['at']})",
        f"- `origin/main..SHA` 커밋 수: {count(f'origin/main..{sha}')}",
        f"- 지연(lag): 이 SHA 뒤 main에 착지했지만 이 PR에 없는 착지 {landings}건 (커밋 {count(f'{sha}..main')}개)",
        "- origin/main is ancestor: yes",
        "- IP·호스트 규칙 미검사 (secret_scan에 규칙 없음)",
        f"- Safety-Review 범위 (`safety_review.py origin/main {sha[:10]}`): {safety}", "",
        "## 병합", "",
        f"`ci-result`가 녹색일 때만 merge commit으로 병합한다 (squash·rebase 금지): "
        f"`gh pr merge <PR> --merge --match-head-commit {sha}` 또는 "
        "`python tools/publish_main.py --merge-when-green <PR> --apply`.", "",
        GENERATED_BY])


def publish(repo: Path, args: argparse.Namespace, now: datetime) -> str:
    git(repo, "fetch", "origin")
    if not ancestor(repo, "origin/main", "main"):
        blocking = sync_conflicts(repo)
        if blocking:
            raise Stop(3, "sync needs 동기화·게시 담당: " + ", ".join(blocking))
        raise Stop(4, "origin/main is not in local main; the merge is clean or records-only. Sync first:"
                      + sync_commands(now))
    sha = publish_sha(repo)
    if sha is None:
        return "nothing to publish: no commit past origin/main has a green FULL land record"
    last = last_publish(repo, args.apply)
    due = last is None or now - last >= timedelta(hours=args.min_hours)
    when = last.isoformat(timespec="minutes") if last else "never"
    if not due and not args.force_blocked:
        return f"not due: last publish {when}, --min-hours {args.min_hours}; would publish {sha[:10]}"
    scanned = secret_gate(repo, sha)
    branch = PREFIX + now.strftime("%Y%m%d-%H")
    why = f"forced: {args.force_blocked}" if args.force_blocked else f"last publish {when}"
    if not args.apply:
        return f"dry run: would push {sha} to {branch} and open a PR ({why}; {scanned}); rerun with --apply"
    if json.loads(run_gh(repo, "pr", "list", "--state", "open", "--search", f"head:{PREFIX}",
                         "--json", "number") or "[]"):
        raise Stop(7, "a publish PR is already open: use --merge-when-green <PR>")
    if git(repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", check=False).returncode == 0:
        raise Stop(1, f"origin already has {branch}; never force-pushed, try next hour")
    holder = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()) / "rosy-publish"
    name = branch.replace("/", "-")
    worktree_rules.clear_tombstone(holder, name)  # an earlier run's folder a handle kept
    temp = holder / name
    git(repo, "worktree", "add", "--detach", str(temp), sha)
    try:
        safety = safety_range(temp, sha)
        push = git(temp, "push", "origin", f"{sha}:refs/heads/{branch}", check=False)
        if push.returncode != 0:
            raise Stop(1, f"push refused (pre-push or remote):\n{push.stdout}{push.stderr}".rstrip())
    finally:
        git(repo, "worktree", "remove", "--force", str(temp), check=False)
        note = worktree_rules.leave_tombstone(temp) if temp.exists() else ""
        if note:
            print(f"[publish] {temp}:{note}", file=sys.stderr)
    url = run_gh(repo, "pr", "create", "--base", "main", "--head", branch,
                 "--title", f"publish: local main {sha[:10]} ({now:%Y-%m-%d %H} UTC)",
                 "--body", pr_body(repo, sha, why, safety)).strip()
    return f"pushed {sha} to {branch}; PR {url}"


def merge_when_green(repo: Path, pr: str, apply: bool, now: datetime) -> str:
    view = json.loads(run_gh(repo, "pr", "view", pr, "--json",
                             "state,headRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup"))
    head = view["headRefOid"]
    if view["state"] != "OPEN" or not view["headRefName"].startswith(PREFIX):
        raise Stop(1, f"PR {pr} is not an open {PREFIX} PR ({view['state']} {view['headRefName']})")
    if not green_full(repo, head):
        raise Stop(1, f"PR {pr} head {head[:10]} has no green FULL land record here; not merging")
    if view["mergeable"] == "CONFLICTING" or view["mergeStateStatus"] in ("DIRTY", "BEHIND"):
        raise Stop(6, f"sync needed: PR {pr} is {view['mergeable']}/{view['mergeStateStatus']}")
    if view["mergeable"] != "MERGEABLE":
        raise Stop(5, f"PR {pr} mergeable is {view['mergeable']}; retry later")
    checks = [c for c in view.get("statusCheckRollup") or [] if c.get("name") == "ci-result"]
    state = (checks[0].get("conclusion") or checks[0].get("status") or "") if checks else "MISSING"
    if state != "SUCCESS":
        if state in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            raise Stop(1, f"ci-result {state} on PR {pr}; not merging")
        raise Stop(5, f"ci-result is {state} on PR {pr}; retry later")
    if not apply:
        return f"dry run: PR {pr} is mergeable and ci-result is green; would merge {head[:10]} with --apply"
    run_gh(repo, "pr", "merge", pr, "--merge", "--match-head-commit", head)
    git(repo, "fetch", "origin")
    merged = f"merged PR {pr} at {head[:10]} (merge commit)"
    if ancestor(repo, "origin/main", "main"):
        return f"{merged}; local main already contains origin/main"
    blocking = sync_conflicts(repo)
    if blocking:
        raise Stop(3, f"{merged}; sync needs 동기화·게시 담당: " + ", ".join(blocking))
    return f"{merged}. Sync origin/main back into local main (no fast-forward: main moved past the SHA):" \
           + sync_commands(now)


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="push/open the PR or merge (default: dry run)")
    parser.add_argument("--min-hours", type=float, default=6.0)
    parser.add_argument("--force-blocked", metavar="REASON", help="publish now: a teammate PR waits on it")
    parser.add_argument("--merge-when-green", metavar="PR")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    try:
        if args.merge_when_green:
            message = merge_when_green(args.repo, args.merge_when_green, args.apply, now)
        else:
            message = publish(args.repo, args, now)
    except Stop as stop:
        print(f"[publish] {stop}", file=sys.stderr)
        return stop.code
    print(f"[publish] {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
