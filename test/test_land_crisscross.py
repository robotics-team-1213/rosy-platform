"""land_merge with criss-cross history: git's virtual merge base holds conflict markers (2026-10-28)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import ENTRY, commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


def test_logs_md_resolves_against_a_real_base_in_criss_cross_history(repos):
    """2026-10-28: two merge bases make git's stage 1 a virtual base holding conflict markers; every base entry
    then looked dropped and the auto-resolve refused (isaac3-environment-repair, publish-pinned-hook)."""
    main, wt = repos
    base = "# docs logs\n" + ENTRY.format(who="base")
    commit(main, {"docs/logs.md": base}, "base log")
    git(wt, "merge", "-q", "main")
    both = base + ENTRY.format(who="peer1") + ENTRY.format(who="branch1")
    commit(main, {"docs/logs.md": base + ENTRY.format(who="peer1")}, "peer1")
    peer1 = git(main, "rev-parse", "HEAD")
    commit(wt, {"docs/logs.md": base + ENTRY.format(who="branch1")}, "branch1")
    branch1 = git(wt, "rev-parse", "HEAD")
    for cwd, other in ((main, branch1), (wt, peer1)):  # each side merges the other's first entry by hand
        subprocess.run(["git", "-C", str(cwd), "merge", "-q", "--no-edit", other], capture_output=True)
        commit(cwd, {"docs/logs.md": both}, "merged by hand")
    assert len(git(wt, "merge-base", "--all", "HEAD", "main").split()) == 2, "criss-cross: two merge bases"
    commit(main, {"docs/logs.md": both + ENTRY.format(who="peer2")}, "peer2")
    commit(wt, {"docs/logs.md": both + ENTRY.format(who="branch2")}, "branch2")
    assert land.main(["--tests", "none", "--skip-reason", "fixture"]) == 0
    text = (main / "docs/logs.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert text == both + ENTRY.format(who="peer2") + ENTRY.format(who="branch2")
