"""FULL evidence survives permitted record corrections in a clean main merge."""

from test_land import LOG, commit, git, land, repos  # noqa: F401


def test_clean_merge_with_spaced_record_path_keeps_full_pass(repos):
    main, wt = repos
    base = git(main, "rev-parse", "HEAD")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    candidate = git(wt, "rev-parse", "HEAD")
    land.land_full.save(wt, "feat/x", candidate, base, "full", [["pkg/test"]])
    commit(main, {"lib/peer.py": "peer = 1\n"}, "peer")
    git(wt, "merge", "--no-commit", "--no-ff", "main")
    commit(wt, {LOG: (wt / LOG).read_bytes() + b"| D-3 | resolved record | Accepted |\r\n"},
           "merge main with ADR record resolution")

    assert land.land_full.bridge(wt, candidate, base, "HEAD", "main")
    assert land.land_full.restore(wt, "feat/x") == base
