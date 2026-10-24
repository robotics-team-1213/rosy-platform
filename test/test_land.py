"""tools/land.py (+ land_checks.py, land_queue.py, land_full.py, land_merge.py) on throwaway repos: main and a worktree."""

from __future__ import annotations

import re
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

    def fake_run(invocations, logs, sha="HEAD", repo=None, label=None, **kw):
        # Fixture repos are throwaway and cannot be shipped to a test host; this test itself
        # already runs on one (D-584), so the inner pytest runs in the fixture worktree.
        return [land.remote_pytest.capture([sys.executable, "-m", "pytest", *inv, *land.remote_pytest.PYTEST_TAIL],
                                           log, cwd=repo) for inv, log in zip(invocations, logs)]

    monkeypatch.setattr(land.remote_pytest, "run", fake_run)
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


def test_local_size_check_failure_stops_before_any_test_host(repos, monkeypatch):
    main, wt = repos
    commit(wt, {land.SIZE_RANGE: "import sys\nprint('ratchet row too high', file=sys.stderr)\nsys.exit(1)\n"}, "size")
    monkeypatch.setattr(land.remote_pytest, "run", lambda *a, **k: pytest.fail("test host reached"))
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


def test_web_change_adds_its_browser_tests_opted_in_and_other_changes_do_not(repos):
    _, wt = repos
    commit(wt, {"operations/apps/games/x.py": "y = 1\n"}, "games page")
    browser = [[land.remote_pytest.BROWSER_ENV, "test/test_games_board_browser.py"]]  # test/browser_scope.py GAMES
    assert land.browser_tier(wt, "main") == browser
    assert land.select(wt, "main", sys.executable) == ([["test"], *browser], None)  # fallback: nearest test/
    commit(wt, {"pkg/a.py": "x = 3\n"}, "not web")
    assert land.browser_tier(wt, "HEAD~1") == []


def test_browser_files_split_into_size_balanced_chunks_for_both_hosts(tmp_path):
    sizes = {"a_browser.py": 900, "b_browser.py": 500, "c_browser.py": 400, "d_browser.py": 300,
             "e_browser.py": 200, "f_browser.py": 100}
    for name, size in sizes.items():
        (tmp_path / name).write_text("x" * size)
    chunks = land.balanced(tmp_path, sorted(sizes), land.BROWSER_CHUNKS)
    assert sorted(p for c in chunks for p in c) == sorted(sizes) and len(chunks) == 4
    totals = sorted(sum(sizes[p] for p in c) for c in chunks)
    assert totals == [500, 500, 500, 900]  # LPT: no chunk waits behind more than the largest file
    assert land.balanced(tmp_path, ["a_browser.py"], 4) == [["a_browser.py"]]  # never an empty invocation


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


@pytest.mark.parametrize("signaled", [False, True])
def test_remote_exit_one_without_failed_lines_stops_before_ff(repos, monkeypatch, capsys, signaled):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before = git(main, "rev-parse", "HEAD")

    def interrupted_run(invocations, logs, *args, **kwargs):
        for log in logs:
            log.write_text("..... [ 42%]\n" + (
                "[tailscale-ssh: process died: signal: terminated]\n" if signaled else ""),
                           encoding="utf-8")
        return [1] * len(invocations)  # The remote wrapper normalizes a signal to exit 1.

    monkeypatch.setattr(land.remote_pytest, "run", interrupted_run)
    assert land.main(["--tests", "pkg/test"]) == 1
    assert "not landing" in capsys.readouterr().err
    assert git(main, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("signaled", [False, True])
def test_remote_exit_one_with_known_failures_lands_only_when_not_signaled(repos, monkeypatch, capsys, signaled):
    main, wt = repos
    nodeid = "pkg/test/test_a.py::test_a"
    commit(wt, {"pkg/test/test_a.py": "def test_a():\n    assert False\n",
                "test/known_failures.txt": nodeid + "  # pre-existing fixture failure\n"}, "known failure")
    candidate = git(wt, "rev-parse", "HEAD")
    before = git(main, "rev-parse", "HEAD")

    def known_failure_run(invocations, logs, *args, **kwargs):
        for log in logs:
            log.write_text("F [100%]\nFAILED " + nodeid + " - AssertionError\n"
                           + ("[tailscale-ssh: process died: signal: terminated]\n" if signaled
                              else "1 failed in 0.01s\n"), encoding="utf-8")
        return [1] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, "run", known_failure_run)
    assert land.main(["--tests", "pkg/test"]) == int(signaled)
    assert git(main, "rev-parse", "HEAD") == (before if signaled else candidate)
    if signaled:
        assert "not landing" in capsys.readouterr().err


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


FULL = ('{"mode": "full", "escalations": ["a -> b/a: folder move"], "invocations": [],'
        ' "local_invocations": [["pkg/test/test_a.py"]], "full_invocations": [["pkg/test"]]}')


@pytest.mark.parametrize("affected, red, code", [
    ("sys.exit(3)", False, 1),             # harness present but selector broken: stop, no guessing
    (f"print({FULL!r})", False, 0),        # FULL: the whole tier on the lab PCs, then land
    (f"print({FULL!r})", True, 1),         # FULL with a NEW failure in the full tier: not landed
])
def test_harness_selector(repos, monkeypatch, capsys, affected, red, code):
    main, wt = repos
    stub = f"import sys\nif sys.argv[1] == 'affected':\n    {affected}\n"
    files = {"tools/harness/rosy_harness.py": stub, "tools/harness/affected_tests.py": "", "pkg/a.py": "x = 2\n"}
    if red:
        files["pkg/test/test_bad.py"] = "def test_bad():\n    assert False\n"
    commit(wt, files, "branch with harness")
    before = git(main, "rev-parse", "HEAD")
    real, calls = land.remote_pytest.run, []
    monkeypatch.setattr(land.remote_pytest, "run", lambda inv, *a, **k: calls.append(inv) or real(inv, *a, **k))
    assert land.main(["--tests", "auto"]) == code
    captured = capsys.readouterr()
    if code:
        assert ("affected selector failed" if affected.startswith("sys") else "NEW failure") in captured.err
        assert git(main, "rev-parse", "HEAD") == before
    else:
        assert calls == [[["pkg/test"]]], "a FULL landing runs full_invocations, not the guards alone"
        assert "FULL tier took" in captured.out.split("== landed")[1]


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


SAFETY = "tools/harness/safety_review.py"


def install_safety_rule(main: Path) -> None:
    """The real safety_review.py (and its data files) with the fixture's init commit as BASELINE."""
    rule = re.sub(r'BASELINE = "[0-9a-f]{40}"', f'BASELINE = "{git(main, "rev-parse", "HEAD")}"',
                  (ROOT / SAFETY).read_text(encoding="utf-8"), count=1)
    files = {SAFETY: rule, "tools/harness/platform_parts.yaml": "roots:\n  - path: safe\n    concern: safety\n",
             "safe/stop.py": "LIMIT = 1\n"}
    for data in sorted((ROOT / "tools/harness").glob("safety_review_*")):
        files[f"tools/harness/{data.name}"] = data.read_bytes()
    commit(main, files, "rule")


@pytest.mark.parametrize("trailer, code", [("", 1), ("\n\nSafety-Review: test-reviewer unit evidence", 0)])
def test_safety_tagged_change_needs_its_trailer_before_landing(repos, capsys, trailer, code):
    """D-762 stage 0: CI's own D-430 5 rule (safety_review.py) runs on the commits the landing adds."""
    main, wt = repos
    install_safety_rule(main)
    git(wt, "merge", "-q", "main")
    commit(wt, {"safe/stop.py": "LIMIT = 2\n"}, "loosen the stop" + trailer)
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == code
    err = capsys.readouterr().err
    if code:
        assert "touches safe/stop.py" in err and "not landing" in err
        assert git(main, "rev-parse", "HEAD") == before
    else:
        assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


def test_ordinary_landing_reports_distance_from_origin(repos, capsys):
    main, wt = repos
    git(main, "update-ref", "refs/remotes/origin/main", "HEAD")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    assert land.main(["--tests", "none"]) == 0
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")
    assert "local main is 1 commits / 0.0 hours ahead of origin/main" in capsys.readouterr().out


def test_untrailered_safety_commit_already_on_main_does_not_block_a_landing(repos):
    """Only the commits the landing adds are checked; main's own history is pre-push's and CI's."""
    main, wt = repos
    install_safety_rule(main)
    commit(main, {"safe/stop.py": "LIMIT = 3\n"}, "untrailered safety edit already on main")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "ordinary branch change")
    assert land.main(["--tests", "none"]) == 0
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


FULL_THEN_DELTA = """import json, sys
if sys.argv[1] == 'affected':
    if '--head' in sys.argv:
        print(json.dumps({"mode": "affected", "escalations": [], "invocations": [["pkg/test/test_a.py"]]}))
    else:
        print(json.dumps({"mode": "full", "escalations": ["a -> b/a: folder move"], "invocations": [],
                          "local_invocations": [], "full_invocations": [["pkg/test"]]}))
"""


def test_main_moving_during_a_full_round_reruns_only_the_delta_tier(repos, monkeypatch, capsys):
    """D-762 stage 0: round 2 selects main's delta since the FULL-tested main, not the whole tier."""
    main, wt = repos
    commit(wt, {"tools/harness/rosy_harness.py": FULL_THEN_DELTA, "tools/harness/affected_tests.py": "",
                "pkg/a.py": "x = 2\n"}, "branch with harness")
    real, calls = land.run_tests, []

    def run_tests(wt_, args, invocations, logdir, round_no):
        calls.append(invocations)
        if round_no == 1:  # a peer lands while the full tier runs
            commit(main, {"lib/util.py": "peer = 1\n"}, "peer")
        return real(wt_, args, invocations, logdir, round_no)

    monkeypatch.setattr(land, "run_tests", run_tests)
    first_main = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto"]) == 0
    assert calls == [[["pkg/test"]], [["pkg/test/test_a.py"]]]
    assert f"FULL tier passed over main {first_main[:10]}" in capsys.readouterr().out
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


def test_peer_edit_to_a_path_the_branch_moved_reruns_full(repos, monkeypatch, capsys):
    """A delta path gone from the candidate (renamed here, edited there) is not narrowed to the delta tier."""
    main, wt = repos
    big = "".join(f"line_{i} = {i}\n" for i in range(30))
    commit(main, {"pkg/big.py": big}, "big module")
    git(wt, "merge", "-q", "main")
    commit(wt, {"tools/harness/rosy_harness.py": FULL_THEN_DELTA, "tools/harness/affected_tests.py": ""}, "harness")
    (wt / "moved").mkdir()
    git(wt, "mv", "pkg/big.py", "moved/big.py")
    git(wt, "commit", "-q", "-m", "move big")
    real, calls = land.run_tests, []

    def run_tests(wt_, args, invocations, logdir, round_no):
        calls.append(invocations)
        if round_no == 1:  # a peer edits the file at its old path while the full tier runs
            commit(main, {"pkg/big.py": big.replace("line_0 = 0", "line_0 = -1")}, "peer edit")
        return real(wt_, args, invocations, logdir, round_no)

    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "auto"]) == 0
    assert calls == [[["pkg/test"]], [["pkg/test"]]]
    assert "gone here (pkg/big.py): FULL again" in capsys.readouterr().out
    assert "line_0 = -1" in (main / "moved/big.py").read_text()


def dated(day: str, who: str) -> str:
    return ENTRY.replace("2026-10-07", day).format(who=who)


def test_logs_md_appends_merge_in_date_order_and_pass_lint():
    sys.path.insert(0, str(ROOT / "tools/harness"))
    import rosy_harness

    base = "# docs logs\n" + dated("2026-10-13", "base")
    theirs = base + dated("2026-10-15", "peer")             # main landed the newer entry first
    ours = base + dated("2026-10-14", "branch") + dated("2026-10-15", "branch2")
    merged = land.append_blocks(base.encode(), ours.encode(), theirs.encode()).decode()
    assert merged == base + dated("2026-10-14", "branch") + dated("2026-10-15", "peer") + dated("2026-10-15", "branch2")
    assert rosy_harness.validate_log(merged) == []


def test_logs_md_moved_own_entry_then_new_main_entry_lands(repos):
    """The 2026-10-15 stop: an earlier landing merged main after our older entry; we moved it by hand."""
    main, wt = repos
    base = "# docs logs\n" + dated("2026-10-13", "base")
    commit(main, {"docs/logs.md": base}, "base log")
    git(wt, "merge", "-q", "main")
    commit(wt, {"docs/logs.md": base + dated("2026-10-14", "branch")}, "branch entry")
    commit(main, {"docs/logs.md": base + dated("2026-10-15", "peer")}, "peer entry")
    subprocess.run(["git", "-C", str(wt), "merge", "-q", "main"], capture_output=True)  # may conflict
    # The stopped landing's merge commit: main's entry first, ours after it, out of date order.
    commit(wt, {"docs/logs.md": base + dated("2026-10-15", "peer") + dated("2026-10-14", "branch")}, "merge")
    commit(wt, {"docs/logs.md": base + dated("2026-10-14", "branch") + dated("2026-10-15", "peer")}, "move entry")
    commit(main, {"docs/logs.md": base + dated("2026-10-15", "peer") + dated("2026-10-16", "peer2")}, "peer 2")
    assert land.main(["--tests", "none"]) == 0
    assert (main / "docs/logs.md").read_text(encoding="utf-8") == (
        base + dated("2026-10-14", "branch") + dated("2026-10-15", "peer") + dated("2026-10-16", "peer2"))


def test_logs_md_edit_of_an_existing_entry_still_refuses():
    base = "# docs logs\n" + dated("2026-10-13", "base")
    ours = base + dated("2026-10-14", "branch")
    theirs = base.replace("- 증거: 없음", "- 증거: 있음") + dated("2026-10-15", "peer")
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()) is None


@pytest.mark.parametrize("files, calls_expected, code", [
    # A NEW guard failure stops before the long round (pkg/test never runs).
    ({"test/architecture/test_rule.py": "def test_rule():\n    assert False\n", "pkg/a.py": "x = 2\n"},
     [[["test/architecture"]], [["test/architecture/test_rule.py::test_rule"]],  # D-790: rerun alone once
      [["test/architecture/test_rule.py::test_rule"]]], 1),  # then once on main (MAIN-RED check)
    # Green guards, then the round as selected.
    ({"test/architecture/test_rule.py": "def test_rule():\n    assert True\n", "pkg/a.py": "x = 2\n"},
     [[["test/architecture"]], [["pkg/test", "test/architecture/test_rule.py"]]], 0),
    # The selection already is guards only: no extra round.
    ({"test/architecture/test_rule.py": "def test_rule():\n    assert True\n"},
     [[["test/architecture/test_rule.py"]]], 0),
])
def test_guard_round_runs_first_and_stops_on_new(repos, monkeypatch, files, calls_expected, code):
    main, wt = repos
    commit(wt, files, "branch")
    real, calls = land.remote_pytest.run, []
    monkeypatch.setattr(land.remote_pytest, "run", lambda inv, *a, **k: calls.append(inv) or real(inv, *a, **k))
    assert land.main(["--tests", "auto"]) == code
    assert calls == calls_expected


def test_logs_md_side_reordering_base_entries_refuses():
    a, b = dated("2026-10-13", "a"), dated("2026-10-14", "b")
    base = "# docs logs\n" + a + b
    ours = base + dated("2026-10-15", "branch")
    theirs = "# docs logs\n" + b + a  # main's entries swapped: not ours to move
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()) is None


def test_logs_md_same_new_entry_on_both_sides_is_written_once():
    base = "# docs logs\n" + dated("2026-10-13", "base")
    picked = dated("2026-10-14", "picked")
    ours = base + picked + dated("2026-10-15", "branch")
    theirs = base + picked
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()).decode() == ours


def test_logs_md_both_sides_inserting_mid_file_refuses():
    a, b = dated("2026-10-13", "a"), dated("2026-10-15", "b")
    base = "# docs logs\n" + a + b
    ours = "# docs logs\n" + a + dated("2026-10-14", "x") + b
    theirs = "# docs logs\n" + a + dated("2026-10-14", "y") + b
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()) is None


def test_logs_md_entry_older_than_the_last_base_entry_stays_below_it():
    base = "# docs logs\n" + dated("2026-10-13", "a") + dated("2026-10-15", "b")
    theirs = base + dated("2026-10-16", "peer")
    ours = base + dated("2026-10-14", "late")
    assert land.append_blocks(base.encode(), ours.encode(), theirs.encode()).decode() == (
        base + dated("2026-10-14", "late") + dated("2026-10-16", "peer"))


def test_main_moving_during_the_guard_round_skips_to_the_next_round(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"test/architecture/test_rule.py": "def test_rule():\n    assert True\n", "pkg/a.py": "x = 2\n"}, "b")
    real, calls = land.remote_pytest.run, []

    def run(inv, *a, **k):
        calls.append(inv)
        if len(calls) == 1:  # a peer lands while the guards run
            commit(main, {"lib/util.py": "peer = 1\n"}, "peer")
        return real(inv, *a, **k)

    monkeypatch.setattr(land.remote_pytest, "run", run)
    assert land.main(["--tests", "auto"]) == 0
    long_round = [["pkg/test", "test/architecture/test_rule.py"]]
    assert calls == [[["test/architecture"]], [["test/architecture"]], long_round]


# --- D-790: load-flaky rerun, stale history, size advice ----------------------------

def _red_once(repos, monkeypatch, alone_codes, ids=("pkg/test/test_a.py::test_a",)):
    """The landing run fails ``ids``; the rerun alone returns ``alone_codes``. Returns the calls made."""
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    calls = []

    def run(invocations, logs, *args, **kwargs):
        calls.append([list(inv) for inv in invocations])
        if len(calls) > 1:
            return list(alone_codes)
        for log in logs:
            log.write_text("F [100%]\n" + "".join(f"FAILED {i} - TimeoutError\n" for i in ids) + "1 failed\n",
                           encoding="utf-8")
        return [1] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, "run", run)
    return calls


def test_new_failure_that_passes_alone_lands_as_load_flaky(repos, monkeypatch, capsys):
    main, wt = repos
    calls = _red_once(repos, monkeypatch, [0])
    assert land.main(["--tests", "pkg/test"]) == 0
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")
    assert calls == [[["pkg/test"]], [["pkg/test/test_a.py::test_a"]]]  # one more invocation, the id alone
    out = capsys.readouterr().out
    assert "LOAD-FLAKY pkg/test/test_a.py::test_a" in out
    candidates = (main / ".git" / land.land_checks.CANDIDATES).read_text(encoding="utf-8")
    assert candidates.startswith("pkg/test/test_a.py::test_a  # LOAD-FLAKY ") and "flaky_quarantine" in candidates


def test_head_move_during_remote_checks_cannot_create_flaky_receipt(repos, monkeypatch, capsys):
    main, wt = repos
    calls = _red_once(repos, monkeypatch, [0])
    original = land.remote_pytest.run

    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(calls) == 1:
            commit(wt, {"pkg/a.py": "x = 3\n"}, "fix while original tests run")
        return result

    monkeypatch.setattr(land.remote_pytest, "run", run)
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "pkg/test"]) == 1
    assert len(calls) == 1
    assert not (main / ".git" / land.land_checks.CANDIDATES).exists()
    assert git(main, "rev-parse", "HEAD") == before
    assert "HEAD changed" in capsys.readouterr().err


def test_isolated_rerun_keeps_original_revision_even_when_head_moves(repos, tmp_path):
    main, wt = repos
    tested = git(wt, "rev-parse", "HEAD")
    commit(wt, {"pkg/a.py": "x = 3\n"}, "later fix")
    received = []

    def run(invocations, logs, sha, **kwargs):
        received.append(sha)
        return [0 if sha == tested else 1] * len(invocations)

    ids, why = land.land_checks.load_flaky(
        wt, ["pkg/test"], tmp_path / "original.txt", "NEW pkg/test/test_a.py::test_a\n",
        tmp_path, "pinned", sys.executable, run, tested_sha=tested)
    assert ids == ["pkg/test/test_a.py::test_a"] and not why
    assert received == [tested]
    text = (main / ".git" / land.land_checks.CANDIDATES).read_text(encoding="utf-8")
    assert "on " + tested[:10] in text


@pytest.mark.parametrize("waiting", [False, True])
def test_head_move_cannot_publish_full_record(repos, monkeypatch, waiting):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], "FULL"))

    def run_tests(*args, **kwargs):
        commit(wt, {"pkg/a.py": "x = 3\n"}, "late branch commit")
        return []

    monkeypatch.setattr(land, "run_tests", run_tests)
    monkeypatch.setattr(land.land_full, "save", lambda *a: pytest.fail("published an obsolete FULL record"))
    if waiting:
        with pytest.raises(land.Stop, match="HEAD changed"):
            land.pretest(wt, "feat/x", land.argparse.Namespace(), sys.executable)
    else:
        before = git(main, "rev-parse", "HEAD")
        assert land.main(["--tests", "auto"]) == 1
        assert git(main, "rev-parse", "HEAD") == before


def test_incomplete_remote_results_cannot_land(repos, monkeypatch, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before = git(main, "rev-parse", "HEAD")
    monkeypatch.setattr(land.remote_pytest, "run", lambda *a, **k: [])
    assert land.main(["--tests", "pkg/test"]) == 1
    assert git(main, "rev-parse", "HEAD") == before
    assert "incomplete remote results" in capsys.readouterr().err


def test_incomplete_isolated_results_cannot_create_flaky_receipt(repos, tmp_path):
    main, wt = repos
    ids, why = land.land_checks._rerun_alone(
        wt, ["pkg/test"], tmp_path / "original.txt", "NEW pkg/test/test_a.py::test_a\n",
        tmp_path, "incomplete", sys.executable, lambda *a, **k: [],
        tested_sha=git(wt, "rev-parse", "HEAD"))
    assert not ids and "incomplete" in why
    assert not (main / ".git" / land.land_checks.CANDIDATES).exists()
    assert "pkg/test/test_a.py" not in (wt / "test" / "known_failures.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("alone_codes, ids, why", [
    ([1], ("pkg/test/test_a.py::test_a",), "failed again when run alone"),
    ([0] * 6, tuple(f"pkg/test/test_a.py::test_{n}" for n in range(6)), "a rerun alone is tried only for 1 to 5"),
])
def test_new_failure_that_fails_again_or_too_many_still_stops(repos, monkeypatch, capsys, alone_codes, ids, why):
    main, wt = repos
    before = git(main, "rev-parse", "HEAD")
    calls = _red_once(repos, monkeypatch, alone_codes, ids)
    assert land.main(["--tests", "pkg/test"]) == 1
    assert why in capsys.readouterr().err and git(main, "rev-parse", "HEAD") == before
    assert len(calls) == (3 if len(ids) == 1 else 2)  # + the MAIN-RED check on main
    assert not (main / ".git" / land.land_checks.CANDIDATES).exists()


def test_safety_root_test_is_never_rerun(repos, monkeypatch, capsys):
    main, wt = repos
    monkeypatch.setattr(land.land_checks, "_safety", lambda wt_, python, ids: list(ids))
    calls = _red_once(repos, monkeypatch, [0])
    assert land.main(["--tests", "pkg/test"]) == 1
    assert "never retried (D-762)" in capsys.readouterr().err and len(calls) == 2  # + the MAIN-RED check


def test_new_failure_that_also_fails_on_main_is_named_main_red(repos, monkeypatch, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before, shas = git(main, "rev-parse", "HEAD"), []

    def run(invocations, logs, sha="HEAD", *args, **kwargs):  # red everywhere, main included
        shas.append(sha)
        for log in logs:
            log.write_text("F [100%]\nFAILED pkg/test/test_a.py::test_a - AssertionError\n1 failed\n", encoding="utf-8")
        return [1] * len(invocations)

    monkeypatch.setattr(land.remote_pytest, "run", run)
    assert land.main(["--tests", "pkg/test"]) == 1
    captured = capsys.readouterr()
    assert shas[-1] == before and "MAIN-RED pkg/test/test_a.py::test_a" in captured.out
    assert "Main is broken, not this branch" in captured.err and git(main, "rev-parse", "HEAD") == before


def test_branch_on_the_pre_rewrite_history_is_refused(repos, monkeypatch, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    monkeypatch.setattr(land.worktree_rules, "STALE_COMMITS", 0)
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 1
    assert "more than 0 commits not in main" in capsys.readouterr().err
    assert git(main, "rev-parse", "HEAD") == before


def test_size_failure_says_how_to_fix_it(repos, monkeypatch, capsys):
    main, wt = repos
    commit(wt, {land.SIZE_RANGE: "import sys\nprint('tools/x.py 612 > 600', file=sys.stderr)\nsys.exit(1)\n"}, "size")
    monkeypatch.setattr(land.remote_pytest, "run", lambda *a, **k: pytest.fail("test host reached"))
    assert land.main(["--tests", "auto"]) == 1
    err = capsys.readouterr().err
    assert "tools/x.py 612 > 600" in err and "never raise a row" in err and f"python {land.SIZE_RANGE} main HEAD" in err


# --- land_cache: passed invocations reused across land.py runs ---------------------------------

@pytest.fixture
def cached(repos, monkeypatch, tmp_path):
    """run_tests with a known test-environment hash; returns (wt, run(invocations, **args), remote calls)."""
    main, wt = repos
    monkeypatch.setattr(land.land_cache, "env_id", lambda wt_, sha: "env1")
    real, calls = land.remote_pytest.run, []
    monkeypatch.setattr(land.remote_pytest, "run", lambda inv, *a, **k: calls.append(inv) or real(inv, *a, **k))

    def run(invocations, **kw):
        args = land.argparse.Namespace(**{"tests": "auto", "node": False, "no_cache": False, **kw})
        return land.run_tests(wt, args, invocations, tmp_path / "logs", len(calls) + 1)
    return wt, run, calls


def test_cache_reuses_a_pass_on_the_identical_tree_only(cached, capsys):
    wt, run, calls = cached
    assert run([["pkg/test"]]) == ["pytest pkg/test ok (run-1-1.txt)"]
    tree = git(wt, "rev-parse", "HEAD^{tree}")
    git(wt, "commit", "-q", "--allow-empty", "-m", "same tree, new commit")  # a retry's re-merge
    done = run([["pkg/test"]])
    assert calls == [[["pkg/test"]], []] and done == [f"pytest pkg/test reused: passed on this tree {tree[:10]} (env env1)"]
    assert "[cache] pytest pkg/test reused" in capsys.readouterr().out
    commit(wt, {"pkg/a.py": "x = 2\n"}, "changed tree")
    run([["pkg/test"]])
    assert calls[-1] == [["pkg/test"]], "another tree reruns (no selector here for a narrow reuse)"
    assert run([["pkg/test"]], tests="pkg/test") and calls[-1] == []  # explicit --tests reuse too


def test_cache_never_keeps_a_failure_or_a_partial_run(cached, monkeypatch):
    wt, run, calls = cached
    commit(wt, {"pkg/test/test_bad.py": "def test_bad():\n    assert False\n"}, "red")
    for _ in range(2):
        with pytest.raises(land.Stop, match="NEW failure"):
            run([["pkg/test"]])
    assert calls.count([["pkg/test"]]) == 2 and land.land_cache.entries(wt) == []  # plus D-790 reruns alone
    git(wt, "rm", "-q", "pkg/test/test_bad.py")
    git(wt, "commit", "-q", "-m", "green")
    real = land.remote_pytest.capture
    lost = lambda inv, logs, *a, **k: [real([sys.executable, "-m", "pytest", "pkg/test"], logs[0], cwd=wt), 255]
    monkeypatch.setattr(land.remote_pytest, "run", lost)  # the second invocation's host was lost
    with pytest.raises(land.Stop, match="exited 255"):
        run([["pkg/test"], ["pkg/test/test_a.py"]])
    assert land.land_cache.entries(wt) == [], "the first invocation passed, but the run was partial"


def test_cache_ignores_corrupt_lines_and_no_cache_reruns(cached, capsys):
    wt, run, calls = cached
    assert land.main(["--no-cache", "--dry-run"]) == 0  # the flag parses (before pytest leaves __pycache__)
    run([["pkg/test"]])
    path = land.land_cache.path(wt)
    good = path.read_text(encoding="utf-8")
    path.write_text("not json\n{\"tree\": 1}\n[]\n" + good + "{\"truncated", encoding="utf-8")
    assert len(land.land_cache.entries(wt)) == 1
    run([["pkg/test"]])
    assert calls[-1] == []
    run([["pkg/test"]], no_cache=True)
    assert calls[-1] == [["pkg/test"]] and "[cache] off (--no-cache)" in capsys.readouterr().out


def test_cache_file_is_trimmed_to_its_newest_lines(cached, monkeypatch):
    wt, run, _ = cached
    monkeypatch.setattr(land.land_cache, "MAX_LINES", 3)
    monkeypatch.setattr(land.land_cache, "KEEP", 2)
    for n in range(4):
        land.land_cache.record(wt, "a" * 40, "b" * 40, "env1", [f"t{n}"], Path("log"))
    assert [e["argv"] for e in land.land_cache.entries(wt)] == [["t2"], ["t3"]]


@pytest.mark.parametrize("change, picked, full, reused", [
    ({"pkg/b.py": "y = 1\n"}, [["other/test"]], False, True),     # the delta selects other tests only
    ({"pkg/b.py": "y = 1\n"}, [["pkg/test/test_a.py"]], False, False),  # it selects this invocation's tests
    ({"pkg/b.py": "y = 1\n"}, [["other/test"]], True, False),      # a FULL-class delta
    ({"test/known_failures.txt": "x\n"}, [["other/test"]], False, False),  # the known-failure list moved
    (None, [["other/test"]], False, False),                         # the delta deletes a file
])
def test_cache_narrow_reuse_across_trees_only_where_the_selector_vouches(cached, change, picked, full, reused):
    wt, run, calls = cached
    commit(wt, {"tools/harness/affected_tests.py": "", "pkg/gone.py": ""}, "harness")
    land.land_cache.record(wt, git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}"), "env1",
                           ["pkg/test"], Path("log"))
    if change:
        commit(wt, change, "delta")
    else:
        git(wt, "rm", "-q", "pkg/gone.py")
        git(wt, "commit", "-q", "-m", "delete")
    select = lambda wt_, base, python, head=None: (picked, "FULL" if full else None)
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    done, todo, _ = land.land_cache.split(wt, args, [["pkg/test"]], git(wt, "rev-parse", "HEAD"), sys.executable,
                                          select)
    assert (todo, bool(done)) == (([], True) if reused else ([["pkg/test"]], False))
    assert all(land.land_cache.NARROW in line for line in done)

def queued(main: Path) -> list[str]:
    return sorted(p.name for p in (main / ".git" / land.land_queue.QUEUE).glob("*"))


def test_a_live_ticket_ahead_holds_the_landing_until_the_queue_timeout(repos, monkeypatch, capsys):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    peer = land.land_queue.take(main / ".git" / land.land_queue.QUEUE, "feat/peer")  # this test process: alive
    monkeypatch.setattr(land.remote_pytest, "run", lambda *a, **k: pytest.fail("test host reached"))
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto", "--queue-timeout", "0"]) == 1
    captured = capsys.readouterr()
    assert "position 2; ahead: feat/peer" in captured.out and "--no-queue" in captured.err
    assert git(main, "rev-parse", "HEAD") == before and git(wt, "rev-list", "--merges", "main..HEAD") == ""
    assert queued(main) == [peer.name], "the waiting run removed its own ticket, not the peer's"


def test_a_full_tier_runs_while_waiting_and_counts_as_the_turns_full_tier(repos, monkeypatch, capsys):
    """2026-10-19: five landers ahead, each with its FULL tier inside the queue, held a landing 100+ min."""
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    land.land_queue.take(main / ".git" / land.land_queue.QUEUE, "feat/peer")      # a live lander ahead
    real_select, rounds = land.select, []
    monkeypatch.setattr(land, "select", lambda *a, **k: (real_select(*a, **k)[0], "FULL tier (test)"))
    monkeypatch.setattr(land, "run_tests", lambda wt_, args, inv, logdir, round_no: rounds.append(round_no) or [])
    assert land.main(["--tests", "auto", "--queue-timeout", "0"]) == 1                # the peer never leaves
    assert rounds == ["pre"] and "FULL tier while waiting" in capsys.readouterr().out
    assert land.land_full.restore(wt, git(wt, "rev-parse", "--abbrev-ref", "HEAD")) == git(wt, "rev-parse", "main")


def test_no_pretest_without_anyone_ahead(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    rounds = []
    monkeypatch.setattr(land, "run_tests", lambda wt_, args, inv, logdir, round_no: rounds.append(round_no) or [])
    assert land.main(["--tests", "auto"]) == 0
    assert "pre" not in rounds


def test_the_ticket_is_released_after_a_stop_and_after_ctrl_c(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    seen = []

    def run_tests(wt_, args, invocations, logdir, round_no):
        seen.append(queued(main))
        raise land.Stop("simulated NEW failure")

    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "auto"]) == 1
    assert len(seen[0]) == 1 and queued(main) == []

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(land, "run_tests", interrupted)
    with pytest.raises(KeyboardInterrupt):
        land.main(["--tests", "auto"])
    assert queued(main) == []


def test_no_queue_lands_without_a_ticket(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    land.land_queue.take(main / ".git" / land.land_queue.QUEUE, "feat/peer")  # would block a queued run
    assert land.main(["--tests", "none", "--no-queue"]) == 0
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


def full_pass_then_host_lost(main: Path, wt: Path, monkeypatch) -> list:
    """Run 1: the FULL tier passes while a peer lands, then the delta round loses its test host."""
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    calls = []

    def select(wt_, base, python, head=None):
        calls.append(head)
        return [["pkg/test"]], (None if head else "selector escalated to FULL")

    def run_tests(wt_, args, invocations, logdir, round_no):
        if round_no == 2:
            raise land.Stop("no test host reachable")
        commit(main, {"lib/util.py": "peer = 1\n"}, "peer")
        return ["pytest ok"]

    monkeypatch.setattr(land, "select", select)
    monkeypatch.setattr(land, "run_tests", run_tests)
    assert land.main(["--tests", "auto"]) == 1
    assert calls == [None, git(main, "rev-parse", "HEAD")]
    calls.clear()
    monkeypatch.setattr(land, "run_tests", lambda *a: ["pytest ok"])
    return calls


def test_a_later_run_reruns_only_main_delta_over_an_earlier_full_pass(repos, monkeypatch):
    main, wt = repos
    calls = full_pass_then_host_lost(main, wt, monkeypatch)
    peer_main = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "auto"]) == 0
    assert calls == [peer_main], "delta selection only, no FULL tier"
    assert not list((main / ".git" / land.land_full.RECORDS).glob("*")), "the record goes once landed"


def test_a_branch_commit_after_the_full_pass_means_full_again(repos, monkeypatch):
    main, wt = repos
    calls = full_pass_then_host_lost(main, wt, monkeypatch)
    commit(wt, {"pkg/a.py": "x = 3\n"}, "fix after the FULL tier")
    assert land.main(["--tests", "auto"]) == 0
    assert calls[0] is None


def test_a_merge_that_changed_more_than_main_voids_the_full_pass(repos, monkeypatch):
    main, wt = repos
    full_pass_then_host_lost(main, wt, monkeypatch)
    commit(main, {"lib/other.py": "peer = 2\n"}, "peer 2")
    subprocess.run(["git", "-C", str(wt), "merge", "--no-commit", "--no-ff", "main"], check=True, capture_output=True)
    commit(wt, {"pkg/a.py": "x = 4\n"}, "merge main, with an edit of its own")
    assert land.land_full.restore(wt, "feat/x") is None


def test_a_gap_line_whose_adr_landed_on_main_is_dropped_after_the_merge(repos, capsys):
    main, wt = repos
    gaps = "tools/harness/adr_gaps.txt"
    commit(wt, {gaps: "D-3 reserved in another worktree\nD-4 reserved in another worktree\n"}, "declare peers' gaps")
    commit(main, {"docs/adr/D-3-peer.md": "## D-3 peer\n"}, "peer lands D-3")
    assert land.main(["--tests", "none"]) == 0
    assert (main / gaps).read_text() == "D-4 reserved in another worktree\n"
    assert "drop adr_gaps lines of landed D-3" in git(main, "log", "-1", "--format=%s")
    assert "dropped ['D-3']" in capsys.readouterr().out
