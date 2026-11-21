"""Merge queue retest (D-1059): the guard set alone when the queue's tree is the one the PR's green run passed, else everything."""
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))
import affected_queue  # noqa: E402
import affected_tests as affected  # noqa: E402

MEDIA = "middleware/media/src/rosy_media_edge/camera_tap.py"
WORLD = "applications/fleet/dev/connected.py"


@functools.lru_cache(maxsize=None)
def _repo():
    return affected.Repo.load(ROOT)


@functools.lru_cache(maxsize=None)
def _pr():
    sel = affected.select(_repo(), [MEDIA])
    assert sel.mode == "affected" and any(p.startswith("middleware/media/test") for p in sel.reasons)
    return sel


def _paths(sel):
    return sorted(p for inv in sel.invocations for p in inv if not p.startswith("-"))


def test_without_the_queue_environment_the_selection_is_untouched(monkeypatch):
    monkeypatch.delenv(affected_queue.ENV, raising=False)
    assert affected_queue.narrowed(_repo(), _pr()) is _pr()


def test_the_same_tree_repeats_the_guard_set_alone():
    before = (dict(_pr().reasons), _paths(_pr()))
    out, why = affected_queue.narrow(_repo(), _pr(), "")
    assert why.startswith("same tree") and set(out.reasons) == {g for g in affected.GUARD_SET if g in _pr().reasons}
    assert set(_paths(out)) < set(before[1]) and out.changed == _pr().changed  # build-smoke still reads the PR's files
    assert (dict(_pr().reasons), _paths(_pr())) == before, "the pull request's own selection is not changed in place"


def test_any_difference_keeps_the_whole_selection():
    # 2026-11-21 review: each of these looked safe to narrow on and is not. A test runs another module's script,
    # reads an ADR by glob, or imports a fixture from another test file, and the selector sees none of it.
    for status in (f"M\t{WORLD}", "M\tdocs/logs.md", "M\tmiddleware/media/test/test_camera_tap.py",
                   "M\tcontracts/foundation/core_common/domain/command_mapping.py", "D\tx.py", f"M\t{MEDIA}"):
        out, why = affected_queue.narrow(_repo(), _pr(), status)
        assert out is _pr() and why.startswith("whole selection"), status
    full = affected.Selection("full", [], escalations=["x: forced"])
    assert affected_queue.narrow(_repo(), full, "")[0] is full


def test_an_unknown_tested_commit_keeps_the_whole_selection():
    assert affected_queue.narrowed(_repo(), _pr(), "0" * 40) is _pr()


def test_ci_matrix_reads_the_queue_environment(monkeypatch):
    monkeypatch.setenv(affected_queue.ENV, "HEAD")  # nothing changed since: the guards alone
    queue = affected.ci_matrix(_repo(), _pr())["include"]
    monkeypatch.delenv(affected_queue.ENV)
    whole = affected.ci_matrix(_repo(), _pr())["include"]
    files = lambda matrix: {p for e in matrix for inv in e["invocations"] for p in inv if not p.startswith("-")}  # noqa: E731
    assert files(queue) < files(whole) and not any("middleware/media/test" in p for p in files(queue))
    assert [e["name"] for e in queue if e["kind"] == "smoke"] == [e["name"] for e in whole if e["kind"] == "smoke"]


def test_tested_commit_comes_from_a_green_ci_result_notice_only():
    sha, base = "a" * 40, "https://api.example/repos/o/r"
    pages = {
        f"{base}/commits/HEAD1/check-runs?check_name=ci-result&per_page=100": {"check_runs": [
            {"id": 1, "conclusion": "failure", "completed_at": "2026-11-21T03:00:00Z", "app": {"slug": "github-actions"}},
            {"id": 2, "conclusion": "success", "completed_at": "2026-11-21T02:00:00Z", "app": {"slug": "github-actions"}},
            {"id": 3, "conclusion": "success", "completed_at": "2026-11-21T04:00:00Z", "app": {"slug": "someone-else"}}]},
        f"{base}/check-runs/1/annotations": [{"title": affected_queue.NOTICE, "message": "b" * 40}],
        f"{base}/check-runs/2/annotations": [{"title": "", "message": "Node.js 20 is deprecated"},
                                             {"title": affected_queue.NOTICE, "message": sha + "\n"}],
        f"{base}/check-runs/3/annotations": [{"title": affected_queue.NOTICE, "message": "c" * 40}],
        f"{base}/commits/HEAD2/check-runs?check_name=ci-result&per_page=100": {"check_runs": [
            {"id": 4, "conclusion": "success", "completed_at": "2026-11-21T02:00:00Z", "app": {"slug": "github-actions"}}]},
        f"{base}/check-runs/4/annotations": [{"title": affected_queue.NOTICE, "message": "not-a-sha"}],
    }
    assert affected_queue.tested_commit("https://api.example", "o/r", "HEAD1", "t", pages.__getitem__) == sha
    assert affected_queue.tested_commit("https://api.example", "o/r", "HEAD2", "t", pages.__getitem__) == ""


def test_ci_wires_the_notice_and_the_queue_switch():
    import yaml
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    notice = next(s for s in jobs["ci-result"]["steps"] if s["name"] == "Tested commit notice (D-1059)")
    for needle in ("github.event_name == 'pull_request'", "needs.scope.result == 'success'", "needs.test.result == 'success'"):
        assert needle in notice["if"], "only a green pull_request run names what it tested"
    assert f"title={affected_queue.NOTICE}::" in notice["run"] and "github.sha" in notice["run"]
    scope = next(s for s in jobs["scope"]["steps"] if s["name"] == "Test scope (D-436)")
    assert scope["env"]["QUEUE_DELTA"] == "${{ vars.ROSY_QUEUE_DELTA }}"
    call = scope["run"].split("tools/harness/affected_queue.py")[0].rsplit("if [", 1)[1]
    assert "= merge_group ]" in call and '"$QUEUE_DELTA" = 1' in call and f"{affected_queue.ENV}=" in call


def test_queue_passed_needs_a_green_merge_group_run_of_ci_on_that_commit():
    sha, parent = "a" * 40, "f" * 40
    url = "https://api.example/repos/o/r/actions/runs?head_sha={}&event=merge_group&per_page=50"
    ci, ref = ".github/workflows/ci.yml", f"gh-readonly-queue/main/pr-7-{parent}"
    pages = {
        url.format(sha): {"workflow_runs": [
            {"head_sha": sha, "conclusion": "success", "path": ".github/workflows/review-gate.yml", "head_branch": ref},
            {"head_sha": sha, "conclusion": "success", "path": ci, "head_branch": ref}]},
        url.format("b" * 40): {"workflow_runs": [
            {"head_sha": "b" * 40, "conclusion": "failure", "path": ci, "head_branch": ref},
            {"head_sha": "c" * 40, "conclusion": "success", "path": ci, "head_branch": ref}]},
        url.format("d" * 40): {"workflow_runs": []},
        # green on this commit, but the queue built and selected it against another base
        url.format("e" * 40): {"workflow_runs": [
            {"head_sha": "e" * 40, "conclusion": "success", "path": ci, "head_branch": "gh-readonly-queue/main/pr-7-" + "9" * 40}]},
    }
    passed = lambda commit: affected_queue.queue_passed("https://api.example", "o/r", commit, parent, "t", pages.__getitem__)  # noqa: E731
    assert passed(sha)
    assert not passed("b" * 40) and not passed("d" * 40) and not passed("e" * 40)


def test_a_push_narrows_only_when_it_is_the_one_entry_the_queue_run_tested():
    import pytest
    affected_queue.pushed("p" * 40, "p" * 40, lambda: True)  # one entry, its queue run passed: no error
    for parent, before, passed in (("p" * 40, "q" * 40, True),   # several entries merged in one push
                                   ("p" * 40, "", True),          # unknown previous tip
                                   ("p" * 40, "p" * 40, False)):  # a direct push, or the queue run did not pass
        with pytest.raises(affected.SelectionError):
            affected_queue.pushed(parent, before, lambda: passed)


def test_ci_wires_the_push_switch():
    import yaml
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    scope = next(s for s in jobs["scope"]["steps"] if s["name"] == "Test scope (D-436)")
    assert scope["env"]["PUSH_SAME"] == "${{ vars.ROSY_PUSH_SAME }}"
    push = scope["run"].split("push)", 1)[1].split(";;", 1)[0]
    call = push.split("tools/harness/affected_queue.py --pushed")[0].rsplit("if [", 1)[1]
    assert '"$PUSH_SAME" = 1' in call and f"{affected_queue.ENV}=" in call
    assert push.index("escalating to --full") < push.index("--pushed"), "an unknown push base stays the full tier"
