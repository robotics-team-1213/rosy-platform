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
from known_failures import NO_ROS_LAUNCH_PLUGINS

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
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *NO_ROS_LAUNCH_PLUGINS,
                           "-p", "no:cacheprovider", *args],
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


def test_ros_environment_does_not_skip_path_reporting(pair, monkeypatch):
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(pair / "ros"))
    try:
        test_root_conftest_names_the_inserter_and_never_fails(pair, [])
    except pytest.skip.Exception as error:
        pytest.fail(f"ROS environment must retain the path-report assertions: {error}")


@pytest.mark.parametrize("plugin_name", ["launch_testing", "launch_ros"])
def test_nested_pytest_reports_paths_when_ros_plugins_preimport_modules(pair, plugin_name):
    (pair / "conftest.py").write_bytes((ROOT / "conftest.py").read_bytes())
    plugins = pair / "ros_plugins"
    metadata = plugins / "fake_ros_launch-0.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: fake-ros-launch\nVersion: 0.0\n")
    (metadata / "entry_points.txt").write_text(f"[pytest11]\n{plugin_name} = early_collect\n")
    # ROS launch collection can import a module before the report hook observes its sys.path change.
    (plugins / "early_collect.py").write_text(
        f"import runpy\nrunpy.run_path({str(pair / 'test_a_inserts.py')!r})\n")
    run = pytest_run(pair, ".", env={"PYTHONPATH": str(plugins), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": ""})
    text = run.stdout + run.stderr
    assert run.returncode == 0, text
    assert "sys.path added by 1 test module(s)" in text and "test_a_inserts.py: helpers" in text, text


def test_tracked_tests_takes_more_paths_than_a_windows_command_line(pair):
    # 40,000+ characters of pathspecs: argv would hit WinError 206 on Windows.
    filler = [f"missing/{'x' * 200}/{n}" for n in range(200)]
    assert land_isolation.tracked_tests(pair, [*filler, "test_b_needs.py"]) == ["test_b_needs.py"]


def test_each_alone_reports_only_the_masked_file(pair):
    files = land_isolation.tracked_tests(pair, ["."])
    assert files == ["test_a_inserts.py", "test_b_needs.py", "test_c_fixture.py"]
    found = land_isolation.each_alone(pair, files, land_isolation.COLLECT)
    assert found["test_a_inserts.py"][0] == 0 and found["test_c_fixture.py"][0] == 0
    assert found["test_b_needs.py"][0] not in (0, 5) and "hidden_mod" in found["test_b_needs.py"][1]
    assert land_isolation.each_alone(pair, files, land_isolation.COLLECT, budget_s=-1) == {}


def test_a_serial_prefix_file_runs_with_nothing_else_on_the_host(monkeypatch, tmp_path):
    """2026-10-27: test_platform_g1_timing failed beside five other alone processes."""
    import threading
    import time
    live, seen, lock = [0], {}, threading.Lock()

    def run(argv, **kw):
        with lock:
            live[0] += 1
            seen[argv[-1]] = max(seen.get(argv[-1], 0), live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(land_isolation.subprocess, "run", run)
    files = ["pkg/test_a.py", "test/test_timing.py", "pkg/test_b.py", "pkg/test_c.py"]
    done = land_isolation.each_alone(tmp_path, files, [], workers=4, serial=("test",))
    assert set(done) == set(files) and seen["test/test_timing.py"] == 1, seen


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


def test_closed_record_stops_ancestry_scan_but_later_incomplete_record_stays_open(pair, monkeypatch):
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(pair, *ident, "commit", "-q", "-m", "init")
    land_isolation.record(pair, "fix/old", "skipped", ["m/test/test_b.py"], ["m/test/test_b.py"])
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "closed")
    land_isolation.record(pair, "fix/closed", "done", ["m/test/test_b.py"], [])
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "incomplete again")
    land_isolation.record(pair, "fix/new", "prepare", ["m/test/test_b.py"], ["m/test/test_b.py"])
    old, closed, latest = land_isolation.rows(pair)
    ancestor = land_isolation._ancestor
    calls = []

    def checked(a_pair, a, b):
        calls.append((a, b))
        return ancestor(a_pair, a, b)

    monkeypatch.setattr(land_isolation, "_ancestor", checked)
    now = latest["t"] + land_isolation.OPEN_AFTER_S + 1
    assert land_isolation.open_entries(pair, now) == [(latest, ["m/test/test_b.py"])]
    assert calls == [(old["candidate"], "main"), (old["candidate"], closed["candidate"]),
                     (latest["candidate"], "main")]


def test_open_entries_skips_unrelated_rows_and_memoizes_ancestry(pair, monkeypatch):
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(pair, *ident, "commit", "-q", "-m", "init")
    land_isolation.record(pair, "fix/old", "prepare", ["m/test/test_a.py"], ["m/test/test_a.py"])
    land_isolation.record(pair, "fix/dup", "prepare", ["m/test/test_a.py"], ["m/test/test_a.py"])
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "other")
    land_isolation.record(pair, "fix/unrelated", "done", ["m/test/test_other.py"], [])
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "close")
    land_isolation.record(pair, "fix/close", "done", ["m/test/test_a.py"], [])
    old, dup, unrelated, closer = land_isolation.rows(pair)
    assert old["candidate"] == dup["candidate"]
    calls = []

    def fake_ancestor(a_pair, a, b):
        calls.append((a, b))
        return True

    monkeypatch.setattr(land_isolation, "_ancestor", fake_ancestor)
    now = closer["t"] + land_isolation.OPEN_AFTER_S + 1
    assert land_isolation.open_entries(pair, now) == []
    assert (old["candidate"], unrelated["candidate"]) not in calls
    assert calls.count((old["candidate"], closer["candidate"])) == 1
    assert calls.count((old["candidate"], "main")) == 1


def test_open_entries_uses_single_topo_dag_for_branches_and_missing_shas(pair, monkeypatch):
    import json

    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(pair, *ident, "commit", "-q", "-m", "c1")
    c1 = git(pair, "rev-parse", "HEAD")
    git(pair, "checkout", "-q", "-b", "side")
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "side")
    side_c = git(pair, "rev-parse", "HEAD")
    git(pair, "checkout", "-q", "main")
    git(pair, *ident, "commit", "-q", "--allow-empty", "-m", "c2")
    c2 = git(pair, "rev-parse", "HEAD")

    old_c1 = {"t": 1000, "branch": "fix/c1", "kind": "prepare", "candidate": c1, "main": c1,
              "alone": ["m/test/test_a.py"], "incomplete": ["m/test/test_a.py"]}
    old_c2 = {"t": 1000, "branch": "fix/c2", "kind": "prepare", "candidate": c2, "main": c2,
              "alone": ["m/test/test_b.py"], "incomplete": ["m/test/test_b.py"]}
    unlanded_side = {"t": 1000, "branch": "fix/side", "kind": "prepare", "candidate": side_c, "main": c1,
                     "alone": ["m/test/test_c.py"], "incomplete": ["m/test/test_c.py"]}
    missing_sha = {"t": 1000, "branch": "fix/missing", "kind": "prepare", "candidate": "0" * 40, "main": c1,
                   "alone": ["m/test/test_d.py"], "incomplete": ["m/test/test_d.py"]}
    side_done = {"t": 1001, "branch": "side", "kind": "done", "candidate": side_c, "main": c2,
                 "alone": ["m/test/test_b.py"], "incomplete": []}
    c2_done = {"t": 1002, "branch": "main", "kind": "done", "candidate": c2, "main": c2,
               "alone": ["m/test/test_a.py"], "incomplete": []}
    rec_path = land_isolation._common(pair) / land_isolation.RECORD
    rec_path.write_text("\n".join(json.dumps(r) for r in (old_c1, old_c2, unlanded_side, missing_sha, side_done, c2_done))
                        + "\n", encoding="utf-8")

    cmds: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(cmd, *a, **kw):
        cmds.append(list(cmd))
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(land_isolation.subprocess, "run", spy_run)
    now = 1000 + land_isolation.OPEN_AFTER_S + 10
    assert land_isolation.open_entries(pair, now) == [(old_c2, ["m/test/test_b.py"])]
    assert not any("merge-base" in cmd for cmd in cmds)


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
    seen.clear()
    land_guards.first(ROOT, argparse.Namespace(tests=mode, node=True),
                      [["pkg/test", "test/test_harness_contracts.py"]], Path("."), "pre", None, isolated=True)
    assert seen[0][2] == [[g for g in land_guards.GUARDS if g != "test/test_harness_contracts.py"]]
    seen.clear()
    land_guards.first(ROOT, argparse.Namespace(tests=mode, node=True),
                      [["pkg/test", "test/test_harness_contracts.py"]], Path("."), 1, None, isolated=False)
    assert seen[0][2] == [list(land_guards.GUARDS)]


def test_guards_cover_every_existing_root_guard_set_file():
    import affected_tests
    from pathlib import PurePosixPath

    assert land_guards.GUARDS[:3] == (
        "test/architecture",
        "test/test_harness_contracts.py",
        "test/test_behavior_test_ownership.py",
    )
    expected_root = {
        path for path in affected_tests.GUARD_SET
        if len(PurePosixPath(path).parts) == 2 and PurePosixPath(path).parts[0] == "test" and (ROOT / path).is_file()
    }
    assert expected_root <= set(land_guards.GUARDS)
    assert all((ROOT / path).exists() for path in land_guards.GUARDS)


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


def test_a_quarantined_timing_flake_is_not_an_isolation_failure():
    """The alone runs judge import isolation; flaky_quarantine.txt entries are rerun-as-FLAKY elsewhere."""
    quarantined = "test/test_platform_g1_timing.py::test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds"
    other = "test/test_other.py::test_new"
    report = f"FAILED {quarantined} - AssertionError\nFAILED {other} - AssertionError\n2 failed in 1.00s\n"
    assert land_isolation.new_failures(report) == [other]


def test_gate_shards_large_selection_and_runs_alone_jobs_first(pair, monkeypatch, tmp_path):
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    for i in range(9):
        p = pair / f"p{i}" / "test_x.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def test_ok(): pass\n", encoding="utf-8")
    git(pair, "add", ".")
    git(pair, *ident, "commit", "-q", "-m", "pkgs")
    (pair / "tools").mkdir(exist_ok=True)
    (pair / land_isolation.GATE).write_text("", encoding="utf-8")
    sel = [[f"p{i}" for i in range(9)]]
    sharded = land_isolation.gate(pair, sel)
    assert len(sharded) == land_isolation.GATE_SHARDS
    seen_paths = [p for inv in sharded for p in inv[1].removeprefix("ROSY_COLLECT_PATHS=").split(",")]
    assert sorted(seen_paths) == [f"p{i}" for i in range(9)]
    monkeypatch.setattr(land_isolation, "alone_files", lambda wt, s: (["p0/test_x.py"], set()))
    calls = []
    logdir = tmp_path / "logs"
    logdir.mkdir()
    args = argparse.Namespace(tests="auto", node=False, no_cache=False, no_queue=False)
    land_isolation.run(pair, "fix/s", sel, args, logdir, "pre",
                       fake_round({"gpre": {"run-gpre-1.txt": "[isolation] complete: 1\n"}}, calls),
                       [["guard"]], prepare=True)
    batch = calls[0][1]
    assert batch[0] == ["guard"] and batch[1] == land_isolation.job(["p0/test_x.py"])[0]
    assert len(batch) == 2 + land_isolation.GATE_SHARDS
