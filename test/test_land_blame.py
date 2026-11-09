"""tools/land_blame.py: the landings between the id's last passing landing and the red main, file touchers first."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_blame  # noqa: E402
import land_mainred as mr  # noqa: E402

ID = "pkg/test/test_a.py::test_a"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def land(repo: Path, rel: str, text: str) -> str:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", rel)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """main: A (its run passed pkg/test), then B edits the test file, C edits pkg/x.py, D elsewhere; red at D."""
    git(tmp_path, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t")):
        git(tmp_path, "config", key, value)
    land(tmp_path, "pkg/test/test_a.py", "def test_a(): pass\n")
    shas = {name: land(tmp_path, rel, f"{name}\n") for name, rel in
            (("A", "a.txt"), ("B", "pkg/test/test_a.py"), ("C", "pkg/test/data.txt"), ("D", "docs/d.md"))}
    rows = [{"event": "tests", "branch": "land/a", "argv": ["pkg/test"], "verdict": "pass"},
            {"event": "tests", "branch": "land/d", "argv": ["docs"], "verdict": "pass"},
            {"event": "tests", "branch": "land/c", "argv": ["pkg", "--ignore=pkg/test"], "verdict": "pass"}]
    rows += [{"event": "landed", "branch": f"land/{n.lower()}", "sha": s} for n, s in shas.items()]
    (tmp_path / ".git" / land_blame.EVENTS).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path, shas


def test_suspects_are_the_landings_after_the_last_pass_file_touchers_first(repo):
    wt, shas = repo
    found = land_blame.suspects(wt, ID, shas["D"])
    assert found["green"] == shas["A"] and found["green_branch"] == "land/a"
    assert [(s["branch"], s["touches"]) for s in found["suspects"]] == [
        ("land/b", "file"), ("land/c", "folder"), ("land/d", "")]
    assert "land/b*" in land_blame.line(ID, found) and "land/c+" in land_blame.line(ID, found)


def test_a_red_on_an_earlier_main_never_names_a_later_landing(repo):
    wt, shas = repo
    assert [s["branch"] for s in land_blame.suspects(wt, ID, shas["B"])["suspects"]] == ["land/b"]


def test_a_close_newer_than_the_pass_moves_the_anchor(repo):
    wt, shas = repo
    found = land_blame.suspects(wt, ID, shas["D"], closes=[shas["B"]])
    assert found["green"] == shas["B"] and found["green_branch"] is None
    assert [s["branch"] for s in found["suspects"]] == ["land/c", "land/d"]


def test_a_browser_id_needs_a_pass_with_its_opt_in(repo):
    wt, shas = repo
    found = land_blame.suspects(wt, ID, shas["D"], env=["ROSY_RUN_BROWSER_TESTS=1"])
    assert found["green"] is None and len(found["suspects"]) == 4


@pytest.mark.parametrize("argv,env,ok", [
    (["pkg/test/test_a.py"], [], True), ([ID], [], True), (["pkg"], [], True), (["test"], [], False),
    (["pkg/test/test_a.py::test_b"], [], False), (["pkg", "--ignore=pkg/test/test_a.py"], [], False),
    (["pkg"], ["ROSY_RUN_BROWSER_TESTS=1"], False), (["ROSY_RUN_BROWSER_TESTS=1", "pkg"], ["ROSY_RUN_BROWSER_TESTS=1"], True)])
def test_covers(argv, env, ok):
    assert land_blame.covers(argv, ID, env) is ok


def test_red_records_the_suspects_and_a_broken_log_never_loses_the_red(repo, monkeypatch):
    wt, shas = repo
    mr.red(wt, shas["D"], [ID], "", [], "nightly")
    assert [r["suspects"] for r in mr.read(wt) if r["event"] == "red"] == [["land/b", "land/c", "land/d"]]
    monkeypatch.setattr(land_blame, "suspects", lambda *a, **k: 1 / 0)
    mr.red(wt, shas["D"], [ID], "", [], "nightly")
    assert [r["suspects"] for r in mr.read(wt) if r["event"] == "red"][-1] is None
