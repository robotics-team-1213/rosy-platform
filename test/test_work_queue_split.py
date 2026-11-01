"""Long invocations split by measured run time and ordered by it (2026-11-01: FULL rounds of 45-60 min ran at
0.4-0.7x parallelism, tails of 30 min combined invocations)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import work_queue as wq  # noqa: E402


def _tree(tmp_path, monkeypatch, serial=""):
    (tmp_path / "pkg" / "test").mkdir(parents=True)
    for n, size in (("a", 900), ("b", 700), ("c", 500), ("d", 300), ("e", 100)):
        (tmp_path / "pkg" / "test" / f"test_{n}.py").write_text("x" * size)
    (tmp_path / "pkg" / "test" / "helper.py").write_text("y")
    (tmp_path / "other" / "test").mkdir(parents=True)
    serial_file = tmp_path / "serial_suites.txt"
    serial_file.write_text(serial)
    monkeypatch.setattr(wq, "SERIAL_FILE", serial_file)


def test_only_measured_long_invocations_split_and_every_test_file_runs_once(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    multi = ["ROSY_JOB_CORES=6", "pkg/test", "other/test"]
    seen = {tuple(multi): 600.0, ("pkg/test",): 600.0, ("short/test",): 30.0}
    assert wq.split(tmp_path, [multi], seen) == [["ROSY_JOB_CORES=6", "pkg/test"], ["ROSY_JOB_CORES=6", "other/test"]]
    assert wq.split(tmp_path, [["short/test"]], seen) == [["short/test"]], "under SPLIT_S stays whole"
    assert wq.split(tmp_path, [["never/ran"]], seen) == [["never/ran"]], "no history stays whole"
    groups = wq.split(tmp_path, [["pkg/test"]], seen)
    assert len(groups) == 3  # ceil(600 / 240)
    files = sorted(f for g in groups for f in g)
    assert files == [f"pkg/test/test_{n}.py" for n in "abcde"], "each test file exactly once, helpers not run"


def test_browser_alone_node_ids_flags_and_serial_paths_stay_whole(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch, serial="pkg/test  # shared ports\n")
    keep = [["ROSY_RUN_BROWSER_TESTS=1", "a/test_x_browser.py", "b/test_y_browser.py"],
            ["ROSY_ALONE_FILES=x", "tools/collect_alone.py"],
            ["pkg/test/test_a.py::test_one", "other/test"],
            ["-k", "fast", "other/test", "pkg/test"],
            ["pkg/test"]]
    seen = {tuple(inv): 900.0 for inv in keep}
    assert wq.split(tmp_path, keep, seen) == keep


def test_history_is_the_median_run_of_each_argv_from_the_events_log(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    rows = [{"event": "tests", "argv": ["pkg/test"], "run_s": s} for s in (100, 300, 200)]
    rows.append({"event": "tests", "argv": ["x"], "verdict": "cancelled"})
    (tmp_path / ".git" / "rosy-land-events.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
    seen = wq.history(tmp_path)
    assert seen == {("pkg/test",): 200}
    assert wq.cost(tmp_path, ["pkg/test"], seen) == 200


def test_a_run_may_ask_six_main_workers_of_a_full_host():
    room = {"cores": 24.0, "mem": 30.0, "site": False, "light": False}
    assert wq.MAX_MAIN == 6 and wq.main_workers(room, 20) == 6
