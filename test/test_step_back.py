"""Step-back check (tools/harness/step_back.py) on throwaway git repositories built with real git."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import step_back  # noqa: E402

A_PY = "".join(f"line_{i:02d} = 'value number {i:02d}'\n" for i in range(1, 11))


def g(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], msg: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8", newline="\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", msg)


def pr(repo: Path, n: int, files: dict[str, str]) -> None:
    """A queue-style PR: topic branch from main, one commit, merge --no-ff with the GitHub subject."""
    g(repo, "checkout", "-q", "-b", f"pr{n}", "main")
    commit(repo, files, f"change {n}")
    g(repo, "checkout", "-q", "main")
    g(repo, "merge", "--no-ff", "-q", "-m", f"Merge pull request #{n} from team/pr{n}", f"pr{n}")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
        g(repo, "config", k, v)
    commit(repo, {"a.py": A_PY, "docs/logs.md": "old log\n"}, "base")
    pr(repo, 1, {"a.py": A_PY + "feature_one = compute_the_first_thing(10)\n", "docs/logs.md": "old log\nrecent log row of PR one\n"})
    pr(repo, 2, {"b.py": "second_feature = compute_the_second_thing(20)\n"})
    return repo


def branch(repo: Path, name: str = "feat") -> None:
    g(repo, "checkout", "-q", "-b", name, "main")


def test_rewriting_a_recent_line_is_info_not_block(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"a.py": A_PY + "feature_one = compute_the_first_thing(99)\n"}, "rewrite")
    hits = step_back.report(repo, "main", "feat")
    assert [(h["level"], h["pr"], h["path"]) for h in hits] == [("info", 1, "a.py")]
    assert step_back.blocking(hits, "") == []


def test_a_moved_line_and_record_files_are_not_hits(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    moved = "feature_one = compute_the_first_thing(10)\n" + A_PY
    commit(repo, {"a.py": moved, "docs/logs.md": "old log\n"}, "move the line, edit a record file")
    assert step_back.report(repo, "main", "feat") == []


def test_a_merge_of_main_that_keeps_the_branch_side_blocks_until_named(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)  # feat and main both rewrite one line of b.py: a real conflict
    commit(repo, {"b.py": "second_feature = the_branch_version(1)\n"}, "own edit")
    g(repo, "checkout", "-q", "main")
    pr(repo, 3, {"b.py": "second_feature = the_main_version_of_pr_three(3)\n"})
    g(repo, "checkout", "-q", "feat")
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "-m", "merge main", "main"], capture_output=True)
    g(repo, "checkout", "--ours", "b.py")
    g(repo, "add", "b.py")
    g(repo, "commit", "-q", "-m", "merge main, keep mine")
    hits = step_back.report(repo, "main", "feat")
    blocks = [h for h in hits if h["level"] == "block"]
    assert [(h["pr"], h["path"]) for h in blocks] == [(3, "b.py")]
    assert step_back.blocking(hits, "Replaces: #3 (the branch rewrote this function)") == []
    assert step_back.blocking(hits, "Replaces: #3 ()") == blocks


def test_a_deletion_that_arrives_with_no_own_commit_blocks(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"c.py": "own_work_of_the_branch = True\n"}, "own work")
    g(repo, "checkout", "-q", "main")
    pr(repo, 4, {"b.py": "second_feature = compute_the_second_thing(20)\nanother_line_of_pr_four = 4000\n"})
    g(repo, "checkout", "-q", "feat")
    g(repo, "merge", "-q", "-s", "ours", "-m", "merge main, take nothing", "main")
    hits = step_back.report(repo, "main", "feat")
    assert [(h["level"], h["pr"], h["path"]) for h in hits if h["level"] == "block"] == [("block", 4, "b.py")]


def test_acknowledged_reads_replaces_and_step_back_lines():
    ack = step_back.acknowledged
    assert ack("Replaces: #1, #2 (why)\n", {1, 2, 3}) == {1, 2}
    assert ack("- Replaces: #7 and #8 (rewritten)", {7, 8}) == {7, 8}
    assert ack("Replaces: #1", {1}) == set() and ack("Replaces: #1 ()", {1}) == set() and ack("Replaces: 1 (x)", {1}) == set()
    assert ack("Step-Back: none (generated)", {1, None}) == {1, None}
    assert ack("Step-Back: none", {1}) == set()


def test_too_big_is_a_block_hit_naming_the_size(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"a.py": "x = 1\n"}, "gut the file")
    hits = step_back.report(repo, "main", "feat", max_lines=3)
    assert hits[0]["level"] == "block" and "too big to check: 11 deleted lines, 1 changed files" in hits[0]["path"]
    assert step_back.blocking(hits, "Step-Back: none (generated)") == []


def merge_main_keeping_branch_side(repo: Path, path: str) -> None:
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "-m", "merge main", "main"], capture_output=True)
    g(repo, "checkout", "--ours", path)
    g(repo, "add", path)
    g(repo, "commit", "-q", "-m", "merge main, keep mine")


def test_a_merge_that_dropped_lines_the_branch_later_put_back_does_not_block(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"b.py": "second_feature = the_branch_version(1)\n"}, "own edit")
    g(repo, "checkout", "-q", "main")
    pr(repo, 3, {"b.py": "second_feature = the_main_version_of_pr_three(3)\n"})
    g(repo, "checkout", "-q", "feat")
    merge_main_keeping_branch_side(repo, "b.py")
    commit(repo, {"b.py": "second_feature = the_main_version_of_pr_three(3)\n"}, "repair: bring main's line back")
    assert [h for h in step_back.report(repo, "main", "feat") if h["level"] == "block"] == []


def test_a_clean_merge_of_main_in_the_same_file_does_not_block(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"a.py": "first_line_of_the_branch = 1\n" + A_PY + "feature_one = compute_the_first_thing(10)\n"}, "own edit at the top")
    g(repo, "checkout", "-q", "main")
    pr(repo, 3, {"a.py": A_PY + "feature_one = compute_the_first_thing(10)\nappended_by_pr_three = 3\n"})
    g(repo, "checkout", "-q", "feat")
    g(repo, "merge", "-q", "-m", "merge main", "main")
    assert step_back.report(repo, "main", "feat") == []


def test_a_git_failure_is_loud_not_a_pass(tmp_path, capsys):
    repo = make_repo(tmp_path)
    assert step_back.main(["--repo", str(repo), "--base", "main", "--head", "no-such-ref"]) == 2
    assert "scan incomplete" in capsys.readouterr().err
    g(repo, "checkout", "-q", "--orphan", "island")
    commit(repo, {"z.py": "unrelated_history = 1\n"}, "island")
    assert step_back.main(["--repo", str(repo), "--base", "main", "--head", "island"]) == 2


def test_a_blame_failure_warns_and_keeps_the_confirmed_blocks(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {"c.py": "own_work_of_the_branch = True\n"}, "own work")
    g(repo, "checkout", "-q", "main")
    pr(repo, 4, {"b.py": "second_feature = compute_the_second_thing(20)\nanother_line_of_pr_four = 4000\n", "a.py": A_PY + "feature_one = compute_the_first_thing(10)\nlast_line_of_pr_four = 4\n"})
    g(repo, "checkout", "-q", "feat")
    g(repo, "merge", "-q", "-s", "ours", "-m", "merge main, take nothing", "main")
    real = step_back.blame_commits

    def flaky(repo_, rev, path, nums):
        if path == "a.py":
            raise step_back.ScanError("git blame failed (128): boom")
        return real(repo_, rev, path, nums)
    monkeypatch.setattr(step_back, "blame_commits", flaky)
    hits = step_back.report(repo, "main", "feat")
    assert [(h["pr"], h["path"]) for h in hits if h["level"] == "block"] == [(4, "b.py")]
    assert any(h["level"] == "warn" and "a.py" in h["path"] for h in hits)


def test_size_limits_block_each_over_the_limit_and_the_exception_line_passes(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo)
    commit(repo, {f"src/f{i}.py": f"value_{i} = {i}\n" for i in range(31)}, "many files")
    assert step_back.size_violations(repo, "main", "feat") == ["31 changed files (limit 30)"]
    for i in range(21):
        commit(repo, {"one.py": f"x = {i}\n"}, f"c{i}")
    assert len(step_back.size_violations(repo, "main", "feat")) == 2
    assert "merge-base is 9 days old" in step_back.size_violations(repo, "main", "feat", now=time.time() + 9 * 86400)[-1]
    assert step_back.size_excepted("x\nSize-Exception: one rename sweep")
    assert step_back.size_excepted("- Size-Exception: one rename sweep")
    assert not step_back.size_excepted("Size-Exception:   ")
    assert not step_back.size_excepted("Size-Exception:")


def test_size_limits_exempt_nothing_by_name_but_not_records_or_pure_renames(tmp_path):
    repo = make_repo(tmp_path)
    branch(repo, "publish/main-20261121-10")
    commit(repo, {f"src/f{i}.py": f"value_{i} = {i}\n" for i in range(31)}, "many files")
    assert step_back.size_violations(repo, "main", "publish/main-20261121-10") != []  # no branch is exempt by name
    g(repo, "checkout", "-q", "main")
    branch(repo, "bot/records-x")
    commit(repo, {f"src/f{i}.py": f"value_{i} = {i}\n" for i in range(31)}, "many files")
    assert step_back.size_violations(repo, "main", "bot/records-x") != []
    g(repo, "checkout", "-q", "main")
    branch(repo, "recs")
    commit(repo, {f"docs/logs/2026/11/r{i}.md": f"record {i}\n" for i in range(40)} | {"docs/reference/api-changes/x.md": "x\n"}, "records")
    assert step_back.size_violations(repo, "main", "recs") == []  # record and generated paths do not count
    g(repo, "checkout", "-q", "main")
    commit(repo, {f"mv/f{i}.py": f"moved_{i} = {i} # padding to keep similarity\n" for i in range(35)}, "add files")
    branch(repo, "renames")
    (repo / "mv2").mkdir()
    for i in range(35):
        g(repo, "mv", f"mv/f{i}.py", f"mv2/f{i}.py")
    g(repo, "commit", "-q", "-m", "pure renames")
    assert step_back.size_violations(repo, "main", "renames") == []
