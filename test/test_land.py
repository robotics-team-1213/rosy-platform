"""tools/land.py against throwaway git repos: a main checkout plus one topic worktree."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402

LOG = "docs/reference/ROSY ADR Log.md"
BOM = b"\xef\xbb\xbf"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(cwd: Path, files: dict[str, bytes | str], message: str) -> None:
    for name, data in files.items():
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
    git(cwd, "add", "--", *files)
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def repos(tmp_path, monkeypatch, request):
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", getattr(request, "param", "false"))):
        git(main, "config", key, value)
    rows = b"".join(b"| D-%d | t%d | Accepted |\r\n" % (n, n) for n in (1, 2))
    commit(main, {
        LOG: BOM + b"# ROSY ADR Log\r\n\r\n| ID | t | s |\r\n|---|---|---|\r\n" + rows,
        "test/known_failures.py": (ROOT / "test/known_failures.py").read_bytes(),
        "test/known_failures.txt": "",
        "pkg/a.py": "x = 1\n",
        "pkg/test/test_a.py": "def test_a():\n    assert True\n",
    }, "init")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", str(wt), "-b", "feat/x", "main")
    monkeypatch.chdir(wt)
    monkeypatch.setenv("ROSY_LAND_TMP", str(tmp_path / "logs"))
    return main, wt


@pytest.mark.parametrize("repos", ["false", "true"], indirect=True)  # core.autocrlf
def test_log_conflict_keeps_both_rows_sorted_with_bom_crlf(repos):
    main, wt = repos
    base = (main / LOG).read_bytes()
    commit(wt, {LOG: base + b"| D-4 | branch | Proposed |\r\n"}, "branch row")
    commit(main, {LOG: base + b"| D-3 | peer | Proposed |\r\n"}, "peer row")
    assert land.main(["--tests", "none"]) == 0
    data = (main / LOG).read_bytes()
    assert data.startswith(BOM)
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert [line.split(b" | ")[0] for line in data.splitlines() if line.startswith(b"| D-")] == [
        b"| D-1", b"| D-2", b"| D-3", b"| D-4"]
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


def test_non_auto_conflict_aborts_merge(repos):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    commit(main, {"pkg/a.py": "x = 3\n"}, "peer")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 1
    assert not (Path(git(wt, "rev-parse", "--git-dir")) / "MERGE_HEAD").exists()
    assert git(wt, "status", "--porcelain") == ""
    assert git(main, "rev-parse", "HEAD") == before


def test_failing_test_stops_before_ff(repos):
    main, wt = repos
    commit(wt, {"pkg/test/test_bad.py": "def test_bad():\n    assert False\n"}, "red")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto"]) == 1
    assert git(main, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("peer_path, second_round", [
    ("docs/adr/D-9.md", []),             # records only: module suite skipped
    ("lib/util.py", [["pkg/test"]]),     # code the tests may import: full rerun
])
def test_main_moved_retests_unless_records_only(repos, monkeypatch, peer_path, second_round):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    real, calls = land.run_tests, []

    def run_tests(wt_, args, invocations, logdir, round_no):
        calls.append(invocations)
        if round_no == 1:  # a peer lands while our tests run
            commit(main, {peer_path: "peer = 1\n"}, "peer")
        return real(wt_, args, invocations, logdir, round_no)

    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "auto"]) == 0
    assert calls == [[["pkg/test"]], second_round]
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")
    assert (main / "pkg/a.py").read_text() == "x = 2\n"


def test_dirty_worktree_refused(repos):
    main, wt = repos
    (wt / "pkg/a.py").write_text("dirty\n")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 1
    assert git(main, "rev-parse", "HEAD") == before


def test_dry_run_changes_nothing(repos, capsys):
    main, wt = repos
    base = (main / LOG).read_bytes()
    commit(wt, {LOG: base + b"| D-4 | branch | Proposed |\r\n"}, "branch row")
    commit(main, {LOG: base + b"| D-3 | peer | Proposed |\r\n"}, "peer row")
    head, before = git(wt, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD")
    assert land.main(["--dry-run"]) == 0
    assert LOG in capsys.readouterr().out
    assert (git(wt, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD")) == (head, before)


def test_shared_main_checkout_refused(repos, monkeypatch):
    main, _ = repos
    monkeypatch.chdir(main)
    assert land.main(["--tests", "none"]) == 1


@pytest.mark.parametrize("target", ["pkg/a.py", "pkg/missing_test.py"])  # exit 5 (none collected), 4 (no path)
def test_pytest_exit_without_failed_lines_stops(repos, target):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", target]) == 1
    assert git(main, "rev-parse", "HEAD") == before


def no_merge_left(wt: Path) -> bool:
    gitdir = Path(git(wt, "rev-parse", "--absolute-git-dir"))
    return not (gitdir / "MERGE_HEAD").exists() and git(wt, "status", "--porcelain") == ""


ENTRY = "\n## 2026-10-07 · uncommitted · {who}\n- 변경: {who}\n- 증거: 없음\n- gate 변화: 없음\n- 결정: 없음\n- 교훈: 없음\n"


def test_logs_md_appends_with_shared_trailing_lines_stay_whole(repos):
    main, wt = repos
    base = "# docs logs\n" + ENTRY.format(who="base")
    commit(main, {"docs/logs.md": base}, "base log")
    git(wt, "merge", "-q", "main")
    commit(wt, {"docs/logs.md": base + ENTRY.format(who="branch")}, "branch entry")
    commit(main, {"docs/logs.md": base + ENTRY.format(who="peer")}, "peer entry")
    assert land.main(["--tests", "none"]) == 0
    text = (main / "docs/logs.md").read_text(encoding="utf-8")
    # main's entry landed first, so it stays first (lint wants log dates in order).
    assert text == base + ENTRY.format(who="peer") + ENTRY.format(who="branch")


def test_logs_md_edit_next_to_append_is_manual(repos):
    main, wt = repos
    commit(main, {"docs/logs.md": "a\nb\n"}, "base log")
    git(wt, "merge", "-q", "main")
    commit(wt, {"docs/logs.md": "a\nb\nc\n"}, "branch append")
    commit(main, {"docs/logs.md": "a\nB\n"}, "peer rewrites b")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 1
    assert no_merge_left(wt)
    assert git(main, "rev-parse", "HEAD") == before


def test_adr_log_row_rewrite_next_to_append_is_manual(repos):
    main, wt = repos
    base = (main / LOG).read_bytes()
    commit(wt, {LOG: base + b"| D-3 | branch | Proposed |\r\n"}, "branch row")
    commit(main, {LOG: base.replace(b"| t2 | Accepted |", b"| t2 | Superseded |")}, "peer status")
    assert land.main(["--tests", "none"]) == 1
    assert no_merge_left(wt)


def test_modify_delete_is_manual(repos):
    main, wt = repos
    commit(main, {"docs/logs.md": "a\n"}, "base log")
    git(wt, "merge", "-q", "main")
    git(wt, "rm", "-q", "docs/logs.md")
    git(wt, "commit", "-q", "-m", "branch deletes log")
    commit(main, {"docs/logs.md": "a\nb\n"}, "peer appends")
    assert land.main(["--tests", "none"]) == 1
    assert no_merge_left(wt)


def test_failure_while_resolving_aborts_the_merge(repos, monkeypatch):
    main, wt = repos
    base = (main / LOG).read_bytes()
    commit(wt, {LOG: base + b"| D-4 | branch | Proposed |\r\n"}, "branch row")
    commit(main, {LOG: base + b"| D-3 | peer | Proposed |\r\n"}, "peer row")
    real = land.git

    def git_failing_commit(cwd, *args, check=True):
        if args[:1] == ("commit",):
            raise land.Stop("simulated commit hook failure")
        return real(cwd, *args, check=check)

    monkeypatch.setattr(land, "git", git_failing_commit)
    assert land.main(["--tests", "none"]) == 1
    assert no_merge_left(wt)


def test_commit_on_branch_during_checks_is_not_landed(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    real = land.run_tests

    def run_tests(wt_, *rest):
        result = real(wt_, *rest)
        commit(wt, {"pkg/b.py": "late = 1\n"}, "untested late commit")
        return result

    monkeypatch.setattr(land, "run_tests", run_tests)
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto"]) == 1
    assert git(main, "rev-parse", "HEAD") == before


def test_main_checkout_must_have_main(repos, tmp_path):
    main, wt = repos
    other = tmp_path / "other"
    git(main, "worktree", "add", "-q", str(other), "-b", "feat/other", "main")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    assert land.main(["--tests", "none", "--main-checkout", str(other)]) == 1
    assert git(other, "rev-parse", "HEAD") == git(main, "rev-parse", "HEAD")


def test_ff_refused_by_peer_dirty_file_leaves_it(repos, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    (main / "pkg/a.py").write_bytes(b"peer's uncommitted edit\n")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 1
    assert "would be overwritten" in capsys.readouterr().err
    assert (main / "pkg/a.py").read_bytes() == b"peer's uncommitted edit\n"
    assert git(main, "rev-parse", "HEAD") == before


FULL = ('{"mode": "full", "escalations": ["tools/x: harness"], "invocations": [],'
        ' "local_invocations": [["pkg/test"]]}')


@pytest.mark.parametrize("affected, code", [
    ("sys.exit(3)", 1),                    # harness present but selector broken: stop, no guessing
    (f"print({FULL!r})", 0),               # FULL: land on the local subset, owe the rest to CI
])
def test_harness_selector(repos, capsys, affected, code):
    main, wt = repos
    stub = f"import sys\nif sys.argv[1] == 'affected':\n    {affected}\n"
    commit(wt, {"tools/harness/affected_tests.py": "", "tools/harness/rosy_harness.py": stub,
                "pkg/a.py": "x = 2\n"}, "branch with harness")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto"]) == code
    captured = capsys.readouterr()
    if code:
        assert "affected selector failed" in captured.err
        assert git(main, "rev-parse", "HEAD") == before
    else:
        assert "FULL tier is still owed to CI" in captured.out.split("== landed")[1]


GUARD = ("from pathlib import Path\n\n\n"
         "def test_docs_follow_rules():\n"
         "    for doc in [*Path('docs').glob('*.md'), *Path('docs/adr').glob('*.md')]:\n"
         "        assert doc.read_text().startswith('# '), doc\n")


@pytest.mark.parametrize("peer_path, second_round", [
    ("docs/readme.md", [["pkg/test", "test/test_guard.py"]]),  # a doc a guard reads: full rerun
    ("docs/adr/D-9.md", [["test/test_guard.py"]]),             # records only: root guard still reruns
])
def test_peer_doc_edit_that_breaks_a_root_guard_is_not_landed(repos, monkeypatch, peer_path, second_round):
    main, wt = repos
    commit(main, {"test/test_guard.py": GUARD, "docs/readme.md": "# ok\n"}, "guard")
    git(wt, "merge", "-q", "main")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    real, calls = land.run_tests, []

    def run_tests(wt_, args, invocations, logdir, round_no):
        calls.append(invocations)
        if round_no == 1:  # the peer's doc breaks the guard while our tests run
            commit(main, {peer_path: "no heading\n"}, "peer doc")
        return real(wt_, args, invocations, logdir, round_no)

    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "pkg/test test/test_guard.py"]) == 1
    assert calls == [[["pkg/test", "test/test_guard.py"]], second_round]
    assert git(main, "log", "-1", "--format=%s") == "peer doc"  # only the peer's commit on main


def test_unusable_selector_json_stops(repos, capsys):
    main, wt = repos
    stub = "import sys\nif sys.argv[1] == 'affected':\n    print('{\"mode\": \"affected\"}')\n"
    commit(wt, {"tools/harness/affected_tests.py": "", "tools/harness/rosy_harness.py": stub}, "harness")
    assert land.main(["--tests", "auto"]) == 1
    assert "unusable JSON" in capsys.readouterr().err


def test_logs_md_ours_end_append_with_their_mid_insert():
    first, last = ENTRY.format(who="first"), ENTRY.format(who="last")
    base = "# docs logs\n" + first + last
    theirs = "# docs logs\n" + first + ENTRY.format(who="peer") + last  # peer entry before the last one
    ours = base + ENTRY.format(who="branch")
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()) == (
        theirs + ENTRY.format(who="branch")).encode()


def test_logs_md_their_mid_insert_lands_end_to_end(repos):
    # git's own merge may or may not conflict on this shape (it did in the D-510
    # landing); either way the landed log is theirs verbatim plus our entry.
    main, wt = repos
    first, last = ENTRY.format(who="first"), ENTRY.format(who="last")
    base = "# docs logs\n" + first + last
    theirs = "# docs logs\n" + first + ENTRY.format(who="peer") + last
    commit(main, {"docs/logs.md": base}, "base log")
    git(wt, "merge", "-q", "main")
    commit(wt, {"docs/logs.md": base + ENTRY.format(who="branch")}, "branch entry")
    commit(main, {"docs/logs.md": theirs}, "peer entry mid-file")
    assert land.main(["--tests", "none"]) == 0
    assert (main / "docs/logs.md").read_text(encoding="utf-8") == theirs + ENTRY.format(who="branch")


@pytest.mark.parametrize("theirs, ours", [
    ("a\nc\n", "a\nb\nc\nd\n"),          # theirs deleted a base line
    ("a\nP\nb\nc\n", "a\nb\nX\nc\n"),     # ours is not an end-append
])
def test_logs_md_mid_insert_needs_a_human_otherwise(theirs, ours):
    assert land.append_blocks(b"a\nb\nc\n", ours.encode(), theirs.encode()) is None


def test_logs_md_their_deletion_next_to_append_is_manual(repos):
    main, wt = repos
    commit(main, {"docs/logs.md": "a\nb\n"}, "base log")
    git(wt, "merge", "-q", "main")
    commit(wt, {"docs/logs.md": "a\nb\nc\n"}, "branch append")
    commit(main, {"docs/logs.md": "a\n"}, "peer deletes b")
    assert land.main(["--tests", "none"]) == 1
    assert no_merge_left(wt)
