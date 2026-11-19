"""land_checks: the auto-stash before --ff-only and the module-grouped alone rerun (2026-11-17)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_checks  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


def test_stash_main_collisions_stashes_only_colliding_dirty_and_untracked_files(repos, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n", "new.txt": "branch adds\n"}, "candidate")
    candidate, main_sha = git(wt, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD")
    (main / "pkg/a.py").write_text("peer dirty\n")      # colliding: tracked and modified
    (main / "new.txt").write_text("peer untracked\n")    # colliding: untracked, and the candidate adds it
    (main / "keep.txt").write_text("disjoint dirty\n")   # disjoint: the candidate does not touch it
    assert land_checks.stash_main_collisions(main, main_sha, candidate) == ["new.txt", "pkg/a.py"]
    assert "auto-stashed 2 colliding file(s)" in capsys.readouterr().out
    assert (main / "pkg/a.py").read_text() == "x = 1\n"  # the stash restored the committed content
    assert not (main / "new.txt").exists()                # the untracked colliding file went to the stash
    assert (main / "keep.txt").read_text() == "disjoint dirty\n"  # a disjoint dirty file stays
    assert f"land-auto-stash-{candidate[:10]}" in git(main, "stash", "list")


def test_a_clean_main_checkout_is_left_alone(repos):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "candidate")
    assert land_checks.stash_main_collisions(main, git(main, "rev-parse", "HEAD"),
                                             git(wt, "rev-parse", "HEAD")) == []


def test_twentytwo_parametrized_ids_of_one_file_rerun_as_that_file_alone(repos, tmp_path):
    main, wt = repos
    commit(wt, {"test/test_os_rauc.py": "import pytest\n\n\n@pytest.mark.parametrize('n', range(1, 23))\n"
                                        "def test_case(n):\n    assert True\n"}, "rauc")
    ids = [f"test/test_os_rauc.py::test_case[{n}]" for n in range(1, 23)]
    (tmp_path / "original.txt").write_text("".join(f"FAILED {i}\n" for i in ids) + "22 failed\n", encoding="utf-8")
    sent = []

    def run(invocations, logs, *args, **kwargs):
        sent.extend(invocations)
        for log in logs:
            log.write_text("22 passed\n", encoding="utf-8")
        return [0] * len(invocations)

    got, why = land_checks._rerun_alone(wt, ["test"], tmp_path / "original.txt",
                                        "".join(f"NEW {i}\n" for i in ids), tmp_path, "grp",
                                        sys.executable, run, tested_sha=git(wt, "rev-parse", "HEAD"))
    assert why == "" and got == ids
    assert sent == [["test/test_os_rauc.py"]]  # the one file alone, not 22 parametrized jobs
    candidates = (main / ".git" / land_checks.CANDIDATES).read_text(encoding="utf-8")
    assert candidates.count(" # LOAD-FLAKY ") == 22 and candidates.startswith(ids[0])
