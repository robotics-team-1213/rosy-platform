"""Merge queue retest narrowing (D-1059): only tests the changes since the PR's green run can reach, else everything."""
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))
import affected_queue  # noqa: E402
import affected_tests as affected  # noqa: E402

MEDIA = "middleware/media/src/rosy_media_edge/camera_tap.py"
WORLD = "operations/world/src/rosy/world/api/observation.py"


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


def test_changes_that_cannot_reach_a_selected_test_leave_it_out_and_keep_the_guards():
    for status in ("", f"M\t{WORLD}", "M\tdocs/logs.md"):
        out, why = affected_queue.narrow(_repo(), _pr(), status)
        assert not any(p.startswith("middleware/media/test") for p in out.reasons), why
        assert set(out.reasons) < set(_pr().reasons)
        assert {g for g in affected.GUARD_SET if g in _pr().reasons} <= set(out.reasons), "guards always run"
        assert _paths(out) == sorted(out.reasons) and out.changed == _pr().changed  # build-smoke still reads the PR's files
    assert _paths(_pr()) == sorted(_pr().reasons), "the pull request's own selection is not changed in place"


def test_a_change_under_the_same_tests_keeps_them():
    out, _ = affected_queue.narrow(_repo(), _pr(), f"M\t{MEDIA}")
    assert set(out.reasons) == set(_pr().reasons)
    # A test file changed on the base side alone is not in the PR's selection: the queue never ran it before either.
    out, _ = affected_queue.narrow(_repo(), _pr(), "M\tmiddleware/media/test/test_camera_tap.py")
    assert "middleware/media/test/test_camera_tap.py" in out.reasons or "middleware/media/test" in out.reasons


def test_anything_unproven_keeps_the_whole_selection():
    for status in ("D\tmiddleware/media/src/rosy_media_edge/gone.py",   # a removed file
                   "M\ttools/harness/harness.yaml",                      # the registry itself
                   "M\ttools/land.py",                                   # a narrowed tier names known readers only
                   f"M\t{WORLD}\nM\ttools/land.py"):
        out, why = affected_queue.narrow(_repo(), _pr(), status)
        assert out is _pr() and why.startswith("whole selection"), status
    full = affected.Selection("full", [], escalations=["x: forced"])
    assert affected_queue.narrow(_repo(), full, f"M\t{WORLD}")[0] is full


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
