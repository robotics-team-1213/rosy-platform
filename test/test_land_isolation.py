"""tools/land_isolation.py: per-file checks catch imports a sibling module hides in a shared pytest process.

The fixture set: test_a_inserts.py puts helpers/ on sys.path at import; test_b_needs.py imports a module that
lives only there at import; test_c_fixture.py imports it inside a fixture (the 2026-10-26 shape). A folder run is
green (a is collected first). Collected alone b is red and c green; run alone both are red.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_guards  # noqa: E402
import land_isolation  # noqa: E402
from test_land import GREEN, _runner, commit, repos  # noqa: E402,F401  (land.py's fixture repos)

PAIR = {
    "helpers/hidden_mod.py": "VALUE = 1\n",
    "test_a_inserts.py": "import sys\nfrom pathlib import Path\n\n"
                         "sys.path.insert(0, str(Path(__file__).parent / 'helpers'))\n\n\ndef test_a():\n    pass\n",
    "test_b_needs.py": "import hidden_mod\n\n\ndef test_b():\n    assert hidden_mod.VALUE == 1\n",
    "test_c_fixture.py": "import pytest\n\n\n@pytest.fixture\ndef mod():\n    import hidden_mod\n    return hidden_mod\n\n\n"
                         "def test_c(mod):\n    assert mod.VALUE == 1\n",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def pair(tmp_path):
    for name, text in PAIR.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", ".")
    return tmp_path


def pytest_run(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **(env or {})}, timeout=300)


def runner(pair: Path, **words: str) -> str:
    """tools/collect_alone.py as land runs it, over the fixture tree; its output."""
    done = pytest_run(ROOT, "-rfE", "--rootdir=.", land_isolation.GATE, env={"ROSY_COLLECT_ROOT": str(pair), **words})
    return f"exit {done.returncode}\n{done.stdout}{done.stderr}"


def test_folder_run_is_green_and_the_collection_gate_is_red(pair):
    folder = pytest_run(pair, ".")
    assert folder.returncode == 0, folder.stdout + folder.stderr
    text = runner(pair, ROSY_COLLECT_PATHS=".")
    assert text.startswith("exit 1") and "FAILED tools/collect_alone.py::test_collects_alone[test_b_needs.py]" in text
    assert "test_collects_alone[test_c_fixture.py]" not in text, "collect-only cannot see a fixture-time import"


def test_alone_runs_catch_the_fixture_time_import_and_report_completion(pair):
    text = runner(pair, ROSY_ALONE_FILES="test_c_fixture.py,test_a_inserts.py")
    assert text.startswith("exit 1") and "FAILED tools/collect_alone.py::test_runs_alone[test_c_fixture.py]" in text
    assert "[isolation] complete: 2" in text, text


def test_alone_runs_past_the_budget_are_reported_not_dropped(pair):
    text = runner(pair, ROSY_ALONE_FILES="test_c_fixture.py,test_a_inserts.py", ROSY_COLLECT_BUDGET_S="-1")
    assert text.startswith("exit 0") and "[isolation] incomplete: test_c_fixture.py,test_a_inserts.py" in text, text


@pytest.mark.parametrize("xdist", [[], ["-n", "2"]], ids=["serial", "xdist"])
def test_root_conftest_names_the_inserter_and_never_fails(pair, xdist):
    if xdist and not importlib.util.find_spec("xdist"):
        pytest.skip("pytest-xdist not installed (CI)")
    (pair / "conftest.py").write_bytes((ROOT / "conftest.py").read_bytes())
    run = pytest_run(pair, ".", *xdist)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text
    assert "sys.path added by 1 test module(s)" in text and "test_a_inserts.py: helpers" in text, text


def test_each_alone_reports_only_the_masked_file(pair):
    files = land_isolation.tracked_tests(pair, ["."])
    assert files == ["test_a_inserts.py", "test_b_needs.py", "test_c_fixture.py"]
    found = land_isolation.each_alone(pair, files, land_isolation.COLLECT)
    assert found["test_a_inserts.py"][0] == 0 and found["test_c_fixture.py"][0] == 0
    assert found["test_b_needs.py"][0] not in (0, 5) and "hidden_mod" in found["test_b_needs.py"][1]
    assert land_isolation.each_alone(pair, files, land_isolation.COLLECT, budget_s=-1) == {}


def test_alone_job_workers_equal_the_cores_its_job_word_reserves(pair):
    """remote_job.JOB writes ROSY_JOB_CORES to the job's lock; the pool must use exactly that many."""
    for words in ({"ROSY_ALONE_FILES": "test_a_inserts.py"}, {"ROSY_COLLECT_PATHS": "."}):
        assert "[isolation] workers 3 (ROSY_JOB_CORES 3)" in runner(pair, ROSY_JOB_CORES="3", **words)
    for inv in land_isolation.job(["a"]) + land_isolation.gate(ROOT, [["test"]]):
        assert inv[0] == f"ROSY_JOB_CORES={land_isolation.GATE_CORES}"


def fake_round(logs: dict[str, dict[str, str]], calls: list):
    """run_tests that records each batch and writes the logs given for its round label."""
    def run_tests(wt, args, batch, logdir, round_no):
        calls.append((round_no, batch))
        for name, text in logs.get(round_no, {}).items():
            (logdir / name).write_text(text, encoding="utf-8")
        return []
    return run_tests


@pytest.fixture
def prepared(pair, monkeypatch, tmp_path):
    """A committed fixture tree with the gate present; alone_files picks a.py and b.py, b.py of a safety source."""
    git(pair, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    (pair / "tools").mkdir()
    (pair / land_isolation.GATE).write_text("", encoding="utf-8")
    monkeypatch.setattr(land_isolation, "gate", lambda wt, sel: [])
    monkeypatch.setattr(land_isolation, "_cache_entries", lambda wt: [])
    monkeypatch.setattr(land_isolation, "alone_files", lambda wt, sel: (["m/test/test_a.py", "m/test/test_b.py"], set()))
    (logdir := tmp_path / "logs").mkdir()
    args = argparse.Namespace(tests="auto", node=False, no_cache=False, no_queue=False)
    return pair, logdir, args


FILES = ["m/test/test_a.py", "m/test/test_b.py"]


@pytest.mark.parametrize("log, cut", [("[isolation] incomplete: m/test/test_b.py\n", ["m/test/test_b.py"]),
                                      ("[isolation] complete: 2\n", [])])
def test_prepare_records_alone_files_the_budget_cut(prepared, log, cut):
    pair, logdir, args = prepared
    calls = []
    lines = land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "pre",
                               fake_round({"gpre": {"run-gpre-1.txt": log}}, calls), [], prepare=True)
    assert calls == [("gpre", land_isolation.job(FILES))]
    assert lines == ([f"isolation incomplete: {', '.join(cut)}"] if cut else [])
    rec = land_isolation.last(pair, "fix/x")
    assert rec["alone"] == FILES and rec["incomplete"] == cut
    calls.clear()  # the turn's summary carries the cut again; nothing reruns while main has not moved
    turn = land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "1", fake_round({}, calls), [], prepare=False)
    assert calls == [] and turn == lines


def test_a_job_without_its_report_is_retried_once_then_stops(prepared):
    pair, logdir, args = prepared
    calls = []
    retried = fake_round({"gpre": {"run-gpre-1.txt": "killed\n"}, "gprer": {"run-gprer-1.txt": "[isolation] complete: 2\n"}},
                         calls)
    assert land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "pre", retried, [], prepare=True) == []
    assert [c[0] for c in calls] == ["gpre", "gprer"]
    calls.clear()
    (fresh := logdir.parent / "logs2").mkdir()
    with pytest.raises(land_isolation.IsolationStop, match="without its \\[isolation\\] report"):
        land_isolation.run(pair, "fix/x", [["m/test"]], args, fresh, "pre", fake_round({}, calls), [], prepare=True)
    assert [c[0] for c in calls] == ["gpre", "gprer"]
    rec = land_isolation.rows(pair)[-1]
    assert rec["incomplete"] == FILES and rec["error"], "the files are recorded as not run alone"


def test_safety_test_unreached_at_the_cap_stops_the_landing(prepared, monkeypatch):
    pair, logdir, args = prepared
    monkeypatch.setattr(land_isolation, "alone_files", lambda wt, sel: (FILES, {"m/test/test_b.py"}))
    cut = fake_round({"gpre": {"run-gpre-1.txt": "[isolation] incomplete: m/test/test_b.py\n"}}, [])
    with pytest.raises(land_isolation.IsolationStop, match="safety never lands as isolation incomplete"):
        land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "pre", cut, [], prepare=True)
    assert land_isolation.rows(pair)[-1]["incomplete"] == ["m/test/test_b.py"]
    other = fake_round({"gpre": {"run-gpre-1.txt": "[isolation] incomplete: m/test/test_a.py\n"}}, [])
    assert land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "pre", other, [], prepare=True) == [
        "isolation incomplete: m/test/test_a.py"]  # a non-safety cut is recorded, not a stop


def test_no_queue_records_skipped_once_and_doctor_fails_it_after_a_night(prepared):
    import doctor

    pair, logdir, args = prepared
    args.no_queue = True
    for _ in range(2):  # two rounds of one landing: one record
        lines = land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "1", fake_round({}, []), [], prepare=False)
        assert lines == ["isolation gate skipped (--no-queue)"]
    assert [r["kind"] for r in land_isolation.rows(pair)] == ["skipped"]
    now = land_isolation.rows(pair)[0]["t"]
    assert doctor.check_isolation(pair, now)[0][0] == "OK", "not yet a night old"
    (level, text, fix), = doctor.check_isolation(pair, now + land_isolation.OPEN_AFTER_S + 1)
    assert level == "FAIL" and "skipped fix/x" in text and "close m/test/test_a.py m/test/test_b.py --reason" in fix


def test_doctor_open_records_close_by_a_later_alone_run_on_a_descendant(prepared):
    import doctor

    pair, logdir, args = prepared
    cut = fake_round({"gpre": {"run-gpre-1.txt": "[isolation] incomplete: m/test/test_b.py\n"}}, [])
    land_isolation.run(pair, "fix/x", [["m/test"]], args, logdir, "pre", cut, [], prepare=True)
    later = land_isolation.rows(pair)[0]["t"] + land_isolation.OPEN_AFTER_S + 1
    assert doctor.check_isolation(pair, later)[0][0] == "FAIL"
    git(pair, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "next")
    land_isolation.record(pair, "fix/y", "done", ["m/test/test_b.py"], [])
    assert doctor.check_isolation(pair, later)[0][0] == "OK"
    out = []
    assert doctor.run(pair, now=later, out=out.append) in (0, 1) and any("isolation:" in o for o in out)


def test_turn_reruns_alone_only_tests_whose_referenced_file_main_changed(pair, monkeypatch):
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(pair, *ident, "commit", "-q", "-m", "init")
    prepared_main = git(pair, "rev-parse", "HEAD")
    refs = {"src/used.py": ["m/test/test_used.py"], "src/other.py": ["m/test/test_other.py"]}
    monkeypatch.setattr(land_isolation, "_selector", lambda wt: (None, None, lambda p: refs.get(p, []), None))
    rec = {"main": prepared_main, "alone": ["m/test/test_used.py", "m/test/test_spare.py"]}
    for path, expected in (("src/unrelated.py", []), ("src/used.py", ["m/test/test_used.py"])):
        (pair / path).parent.mkdir(exist_ok=True)
        (pair / path).write_text("x = 1\n", encoding="utf-8")
        git(pair, "add", path)
        git(pair, *ident, "commit", "-q", "-m", path)
        assert land_isolation.stale(pair, rec) == expected
    assert land_isolation.stale(pair, {**rec, "main": git(pair, "rev-parse", "HEAD")}) == []  # main did not move


def test_turn_stale_reruns_ride_the_turns_round_its_cap_and_overtime_path(repos, monkeypatch):
    """The stale reruns join land.py's turn invocations, so TURN_CAP_S cancels them as Overtime and
    land_prepare.again tests them outside the lock, as for the delta selection."""
    import land

    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n", land_isolation.GATE: ""}, "branch")
    monkeypatch.setattr(land_isolation, "last", lambda wt_, branch: {"main": "0" * 40, "alone": ["pkg/test/test_a.py"]})
    stale = iter([["pkg/test/test_a.py"]])
    monkeypatch.setattr(land_isolation, "stale", lambda wt_, rec: next(stale, []))
    monkeypatch.setattr(land_isolation, "alone_files", lambda wt_, sel: ([], set()))
    monkeypatch.setattr(land_isolation, "gate", lambda wt_, sel: [])
    monkeypatch.setattr(land, "TURN_CAP_S", -1)
    real, calls, again = _runner({"pkg/test": GREEN, "pkg/test/test_a.py": GREEN}), [], []
    monkeypatch.setattr(land.remote_pytest, "run", lambda inv, *a, **k: calls.append([list(i) for i in inv]) or real(inv, *a, **k))
    real_again = land.land_prepare.again
    monkeypatch.setattr(land.land_prepare, "again", lambda *a: again.append(a[-2]) or real_again(*a))
    assert land.main(["--tests", "auto"]) == 0
    assert calls[0][0][0] == "pkg/test" and calls[0][1:] == [["pkg/test/test_a.py"]], "in the turn's own round"
    assert again and ["pkg/test/test_a.py"] in again[0], "past the cap it went outside the lock"


def test_alone_files_put_safety_references_first_with_no_count_cap(monkeypatch, tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / land_isolation.GATE).write_text("", encoding="utf-8")
    many = [f"m/test/test_{n:02}.py" for n in range(15)]
    refs = {"safe/brake.py": ["s/test/test_brake.py"], "m/a.py": many}

    class Repo:
        @staticmethod
        def text(path):
            return "spec_from_file_location" if path == many[7] else ""

    class At:
        @staticmethod
        def changed_files(*a):
            return ["m/a.py", "safe/brake.py"]

    monkeypatch.setattr(land_isolation, "tracked_tests", lambda root, paths: [*many, "s/test/test_brake.py"])
    monkeypatch.setattr(land_isolation, "_selector",
                        lambda wt: (Repo, At, lambda p: refs.get(p, []), lambda p: p.startswith("safe/")))
    picked, safety = land_isolation.alone_files(tmp_path, [["m/test", "s/test"]])
    assert picked == ["s/test/test_brake.py", many[7], *[t for t in many if t != many[7]]]
    assert safety == {"s/test/test_brake.py"}


@pytest.mark.parametrize("mode", ["auto", "full"])
def test_guard_round_wiring(monkeypatch, mode):
    seen = []
    monkeypatch.setattr(land_isolation, "run", lambda wt, branch, sel, args, logdir, rnd, rt, guards, prep:
                        seen.append((sel, rnd, guards, prep)) or ["x"])
    out = land_guards.first(ROOT, argparse.Namespace(tests=mode, node=True), [["pkg/test"]], Path("."), "pre",
                            None, isolated=True)
    assert seen == [([["pkg/test"]], "pre", [list(land_guards.GUARDS)], True)] and out == ["round pre: guard round first: x"]


def test_selector_edge_on_this_repo_selects_the_incident_test():
    """The 2026-10-26 change to native_cycle.py: its test is on the references edge and loads it by path."""
    repo, _, refs, _ = land_isolation._selector(ROOT)
    found = refs("learning/training/omx/native_cycle.py")
    assert "learning/training/omx/test/test_native_cycle.py" in found
    assert "spec_from_file_location" in repo.text("learning/training/omx/test/test_native_cycle.py")


def test_close_needs_a_reason_and_records_who_and_when(prepared, monkeypatch, capsys):
    import remote_pytest

    pair, _, _ = prepared
    monkeypatch.chdir(pair)
    git(pair, "config", "user.email", "closer@example.invalid")
    for argv in (["close", "m/test/test_b.py"], ["close", "m/test/test_b.py", "--reason", "  "]):
        with pytest.raises(SystemExit):
            land_isolation.main(argv)
    assert land_isolation.rows(pair) == [], "refused: nothing recorded, nothing run"

    def ran(invs, logs, sha, **kw):
        logs[0].write_text("[isolation] complete: 1\n", encoding="utf-8")
        return [0]
    monkeypatch.setattr(remote_pytest, "run", ran)
    assert land_isolation.main(["close", "m/test/test_b.py", "--reason", "nightly not built yet"]) == 0
    rec, = land_isolation.rows(pair)
    assert (rec["kind"], rec["reason"], rec["by"], rec["alone"]) == ("done", "nightly not built yet",
                                                                  "closer@example.invalid", ["m/test/test_b.py"])
    assert rec["at"] and rec["t"]


@pytest.mark.parametrize("mode", ["auto", "full"])
@pytest.mark.parametrize("fresh", [False, True])
def test_full_current_report_cannot_fall_back_to_historical_cache_complete(prepared, monkeypatch, tmp_path, mode, fresh):
    import land_cache
    pair, logdir, args = prepared
    args.tests = mode
    candidate = git(pair, "rev-parse", "HEAD")
    old = tmp_path / "historical-complete.txt"
    old.write_text("[isolation] complete: 2\n", encoding="utf-8")
    land_cache.record(pair, candidate, git(pair, "rev-parse", "HEAD^{tree}"), "fixture-env",
                      land_isolation.job(FILES)[0], old)
    calls = []
    report = "[isolation] complete: 2\n" if fresh else "1 passed\n"
    run = fake_round({"gpre": {"run-gpre-1.txt": report}, "gprer": {"run-gprer-1.txt": report}}, calls)
    if mode == "full" and not fresh:
        with pytest.raises(RuntimeError, match=r"without its \[isolation\] report"):
            land_isolation.run(pair, "feat/x", [["m/test"]], args, logdir, "pre", run, [], True)
        assert [name for name, _ in calls] == ["gpre", "gprer"]
        assert land_isolation.rows(pair)[-1]["error"] == "no [isolation] report twice"
    else:
        land_isolation.run(pair, "feat/x", [["m/test"]], args, logdir, "pre", run, [], True)
        assert [name for name, _ in calls] == ["gpre"]
        assert land_isolation.rows(pair)[-1]["incomplete"] == []
