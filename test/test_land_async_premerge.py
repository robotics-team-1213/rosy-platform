"""tools/land_async.py: a branch queued far behind main merges main first, so its landing tests the current tree."""

from __future__ import annotations

import subprocess

from test_land_async import NOW, _git, repo, tool  # the loader, the real-git fixture and its helpers


def test_a_branch_far_behind_main_merges_it_before_queueing(repo, monkeypatch):
    main, dev = repo
    monkeypatch.setattr(tool, "PREMERGE_BEHIND", 2)  # 3 commits over a small threshold, not 51 over the real 50
    for i in range(3):
        (main / f"main-{i}.txt").write_text(f"{i}\n")
        _git(main, "add", f"main-{i}.txt")
        _git(main, "commit", "-qm", f"main moves {i}")
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    for place in (tree, dev):  # the queued snapshot and the branch itself hold current main
        assert subprocess.run(["git", "-C", str(place), "merge-base", "--is-ancestor", "main", "HEAD"],
                              capture_output=True).returncode == 0
    assert _git(dev, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"  # merged in place, still the owner's branch
