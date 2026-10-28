"""tools/land_mainred.py: robot-56's conditions for main-red carry-over, each with the mutation that must stop it."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_mainred as mr  # noqa: E402

ID = "pkg/test/test_a.py::test_a[x]"
LOG = """_________________________________ test_a[x] _________________________________

    def test_a(x):
>       assert seen == 2
E       assert 1 == 2

pkg/test/test_a.py:7: AssertionError
=========================== short test summary info ============================
FAILED pkg/test/test_a.py::test_a[x] - assert 1 == 2
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """main with one red commit, and a branch that merged it and changed an unrelated module."""
    monkeypatch.delenv(mr.SWITCH, raising=False)
    mr.CARRIED.clear()
    mr.PASSES.clear()
    git(tmp_path, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git(tmp_path, "config", key, value)
    (tmp_path / "pkg/test").mkdir(parents=True)
    (tmp_path / "pkg/test/test_a.py").write_text("def test_a(): pass\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "red main")
    git(tmp_path, "checkout", "-q", "-b", "feat/x")
    (tmp_path / "other.py").write_text("y = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "unrelated")
    main, head = git(tmp_path, "rev-parse", "main"), git(tmp_path, "rev-parse", "HEAD")
    mr.red(tmp_path, main, [ID], LOG, [], "fix/elsewhere")
    mr.write(tmp_path, "own", id=ID, owner="robot-fix")
    return tmp_path, main, head


def carry(repo_, text=LOG, *, safety=lambda ids: [], sel=None, now=None):
    wt, _, head = repo_
    return mr.carry(wt, [ID], text, head, "feat/x", safety=safety, now=now,
                    select=lambda base, h: sel or {"mode": "affected", "invocations": [["other_test"]]})


def test_all_conditions_hold_carries_and_records_why(repo):
    ids, why = carry(repo)
    assert ids == [ID] and [c[0] for c in mr.CARRIED] == [ID] and "owners ['robot-fix']" in why
    assert [r["event"] for r in mr.read(repo[0])] == ["red", "own"], "nothing recorded before the fast-forward"
    assert mr.landed(repo[0], repo[2], "feat/x") == [ID]
    assert [r["event"] for r in mr.read(repo[0])] == ["red", "own", "carry"]


def test_1_a_different_fingerprint_stops(repo):
    assert not carry(repo, LOG.replace("assert 1 == 2", "assert 3 == 2"))[0]
    assert not carry(repo, LOG.replace(":7: AssertionError", ":8: AssertionError"))[0]
    assert not carry(repo, LOG.replace("AssertionError", "TimeoutError"))[0]
    wt = repo[0]
    mr.path(wt).write_text("")
    mr.write(wt, "red", id=ID, main="0" * 40, fp=mr.fingerprint(LOG, ID), env=[], by="x")
    mr.write(wt, "own", id=ID, owner="robot-fix")
    assert not carry(repo)[0], "red recorded on another main only, not the one this candidate merged"


def test_2_a_selection_that_reaches_the_id_or_is_full_stops(repo):
    assert not carry(repo, sel={"mode": "affected", "invocations": [["pkg/test"]]})[0]
    assert not carry(repo, sel={"mode": "affected", "invocations": [["pkg/test/test_a.py"]]})[0]
    assert not carry(repo, sel={"mode": "full", "invocations": [["other_test"]]})[0]
    assert not carry(repo, sel={"mode": "affected", "invocations": [["pkg/test/test_a.py::test_a", "-k", "x"]]})[0]
    assert carry(repo, sel={"mode": "affected", "invocations": [["pkg/test_other"]]})[0], "a prefix is not a parent"


def test_3_a_collection_or_setup_error_never_carries(repo):
    assert not carry(repo, LOG + f"ERROR {ID} - fixture boom\n")[0]
    wt, _, head = repo
    assert not mr.carry(wt, ["pkg/test/test_a.py"], LOG, head, "feat/x", safety=lambda ids: [],
                        select=lambda b, h: {"mode": "affected", "invocations": []})[0]


def test_4_safety_and_arm_ids_never_carry(repo):
    assert not carry(repo, safety=lambda ids: ids)[0]
    wt, _, head = repo
    for arm in ("middleware/devices/omx/adapter/test/test_x.py::test_a", "operations/world/test/test_omx_geometry.py::t",
                "test/learning/perception/test_omx_web.py::t", "learning/training/omx/test/test_x.py::t"):
        assert not mr.carry(wt, [arm], LOG, head, "feat/x", safety=lambda ids: [],
                            select=lambda b, h: {"mode": "affected"})[0], arm


def test_5_age_count_and_owner_limits_stop(repo):
    now = time.time()
    assert not carry(repo, now=now + mr.MAX_AGE_S + 60)[0]
    wt, main, head = repo
    for n in range(mr.MAX_CARRIES):
        mr.write(wt, "carry", id=ID, main=main, sha=f"{n:040d}", branch=f"b{n}", why="")
    assert not carry(repo, now=now)[0]
    mr.path(wt).write_text("")
    mr.red(wt, main, [ID], LOG, [], "x")
    assert not carry(repo)[0], "no owner"


def test_6_open_ids_run_in_every_selection_and_close_only_with_the_carry_in_history(repo):
    wt, main, head = repo
    assert mr.extra(wt) == [], "a red nobody carried does not burden other landings"
    assert carry(repo)[0] and mr.extra(wt) == [], "a carry of a landing that never landed burdens no one"
    mr.landed(wt, head, "feat/x")
    mr.CARRIED.clear()
    assert mr.extra(wt) == [["-rA", ID]]
    fix_alone = git(wt, "commit-tree", git(wt, "rev-parse", "main^{tree}"), "-p", main, "-m", "fix only")
    assert mr.close(wt, f"PASSED {ID}\n", fix_alone) == [ID]
    assert not [r for r in mr.read(wt) if r["event"] == "close"], "a PASSED landing that then stops leaves no close"
    mr.landed(wt, fix_alone, "fix/only")
    assert mr.extra(wt) == [["-rA", ID]], "a run without the carried landing covers nothing"
    mr.PASSES.clear()
    assert mr.close(wt, f"SKIPPED [1] {ID}\n", head) == [] and mr.extra(wt), "skipped closes nothing"
    mr.close(wt, f"PASSED {ID}\n", head)
    mr.landed(wt, head, "feat/y")
    assert mr.extra(wt) == [] and mr.state(wt) == {}


def test_a_carry_that_reached_main_after_the_pass_is_not_covered(repo):
    """robot-56: round 1 passed the id on (branch + main M1); a carry L landed on main before round 2."""
    wt, main, head = repo
    mr.CARRIED.append((ID, main, "why", ()))
    mr.landed(wt, head, "feat/l")  # L = head carried the id
    mr.CARRIED.clear()
    mr.close(wt, f"PASSED {ID}\n", main)  # the pass happened on a tree without L
    mr.landed(wt, head, "feat/x")  # this landing's final commit holds both
    assert mr.extra(wt) == [["-rA", ID]], "L is not covered by a pass that never had L in its tree"


def test_a_later_round_that_passes_the_invocation_voids_its_carry(repo):
    wt, _, head = repo
    assert mr.carry(wt, [ID], LOG, head, "feat/x", safety=lambda ids: [], inv=["pkg/test"],
                    select=lambda b, h: {"mode": "affected", "invocations": [["other_test"]]})[0]
    mr.passed(["other_test"])
    assert mr.CARRIED, "another invocation's pass does not void it"
    mr.passed(["pkg/test"])
    assert mr.CARRIED == [] and mr.landed(wt, head, "feat/x") == []


def test_the_switch_turns_carrying_and_the_extra_runs_off(repo, monkeypatch):
    assert carry(repo)[0]
    monkeypatch.setenv(mr.SWITCH, "0")
    assert mr.extra(repo[0]) == [] and not carry(repo)[0]


def test_fingerprint_is_none_when_absent_or_ambiguous():
    assert mr.fingerprint(LOG, ID) == "AssertionError|pkg/test/test_a.py:7|E       assert 1 == 2"
    assert mr.fingerprint(LOG + LOG, ID) is None
    assert mr.fingerprint("", ID) is None and mr.fingerprint(LOG, "pkg/test/test_a.py") is None
