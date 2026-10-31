"""tools/land_gc.py: leftovers of stopped or landed land_async landings go only when nothing is lost (2026-11-01)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import land_gc  # noqa: E402

OLD = time.time() - 30 * 86400


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def hidden(repo, holder, branch, extra=False, log_age=OLD):
    name = branch.replace("/", "-")
    git(repo, "worktree", "add", "-q", "-b", branch, str(holder / name), "main")
    if extra:
        (holder / name / "x.txt").write_text("unlanded\n")
        git(holder / name, "add", "x.txt")
        git(holder / name, "commit", "-q", "-m", "unlanded")
    for suffix in (".log", ".stopped", ".land_async.py"):
        path = holder / f"{name}{suffix}"
        path.write_text("x\n")
        os.utime(path, (log_age, log_age))
    return holder / name


def test_only_landings_with_nothing_unique_and_no_live_ticket_are_removed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder = common / "rosy-land-wt"
    holder.mkdir()
    landed = hidden(repo, holder, "land/feat/landed-20261101000001")
    unlanded = hidden(repo, holder, "land/feat/unlanded-20261101000002", extra=True)
    alive = hidden(repo, holder, "land/feat/alive-20261101000003", extra=True)
    fresh = hidden(repo, holder, "land/feat/fresh-20261101000004", log_age=time.time())
    git(repo, "branch", "land/v2-hand-made")  # not a land_async snapshot: never touched
    (common / "rosy-land-queue").mkdir()
    (common / "rosy-land-queue" / "01-1.json").write_text(json.dumps(
        {"pid": os.getpid(), "branch": "land/feat/alive-20261101000003", "worktree": str(alive), "status": "pending"}))
    gone = holder / "land-feat-gone-1.log"
    gone.write_text("STOP\n")
    os.utime(gone, (OLD, OLD))

    rows = land_gc.plan(repo, time.time(), 7)
    verdict = {(t.name if t else items[0]): (action, reason) for action, reason, t, items in rows}
    assert verdict["land-feat-landed-20261101000001"][0] == "remove"
    assert verdict["land-feat-unlanded-20261101000002"] == ("keep", "unlanded work (1 commit(s) not in main)")
    assert verdict["land-feat-alive-20261101000003"] == ("keep", "live ticket")
    assert verdict["land-feat-fresh-20261101000004"] == ("keep", "log written in the last hour")
    assert verdict[str(gone)][0] == "log"

    assert land_gc.apply(repo, rows) == []
    assert not landed.exists() and not git(repo, "branch", "--list", "land/feat/landed-20261101000001")
    assert not (holder / "land-feat-landed-20261101000001.stopped").exists()
    assert (holder / "land-feat-landed-20261101000001.log").exists(), "the log stays for its owner"
    assert unlanded.exists() and alive.exists() and fresh.exists() and not gone.exists()
    assert git(repo, "branch", "--list", "land/v2-hand-made")
    assert "land-v2-hand-made" not in verdict
