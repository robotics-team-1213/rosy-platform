"""Long invocations split by measured run time and ordered by it (2026-11-01: FULL rounds of 45-60 min ran at
0.4-0.7x parallelism, tails of 30 min combined invocations)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_measured_long_invocations_split_and_every_test_file_runs_once(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    multi = ["ROSY_JOB_CORES=6", "pkg/test", "other/test"]
    seen = {tuple(multi): 600.0, ("pkg/test",): 600.0, ("short/test",): 30.0}
    assert wq.split(tmp_path, [multi], seen) == [["ROSY_JOB_CORES=6", "pkg/test"], ["ROSY_JOB_CORES=6", "other/test"]]
    assert wq.split(tmp_path, [["short/test"]], seen) == [["short/test"]], "under SPLIT_S stays whole"
    assert wq.split(tmp_path, [["never/ran"]], seen) == [["never/ran"]], "a missing path has zero estimated cost"
    groups = wq.split(tmp_path, [["pkg/test"]], seen)
    assert len(groups) == 3  # ceil(600 / 240)
    files = sorted(f for g in groups for f in g)
    assert files == [f"pkg/test/test_{n}.py" for n in "abcde"], "each test file exactly once, helpers not run"


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_unknown_safe_packets_use_the_existing_byte_cost_at_the_same_threshold(tmp_path, monkeypatch, offset):
    _tree(tmp_path, monkeypatch)
    total = wq.SPLIT_S * wq.BYTES_PER_S + offset
    paths = ["test_a.py", "test_b.py"]
    for i, path in enumerate(paths):
        (tmp_path / path).write_bytes(b"x" * (total // 2 + (total % 2 if i else 0)))
    packet = ["ROSY_JOB_CORES=6", "ROSY_CUSTOM=1", *paths]
    expected = [[*packet[:2], path] for path in paths] if offset >= 0 else [packet]
    assert wq.split(tmp_path, [packet, packet], {}) == expected
    assert wq.split(tmp_path, [packet], {tuple(packet): 0}) == [packet], "measured history wins over byte cost"


def test_unknown_large_directory_uses_existing_balancing_and_cap_and_preserves_measured_history(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    for n in "abcdefg":
        (tmp_path / "pkg/test" / f"test_{n}.py").write_bytes(b"x" * (wq.SPLIT_S * wq.BYTES_PER_S))
    packet = ["ROSY_JOB_CORES=2", "pkg/test"]
    groups = wq.split(tmp_path, [packet], {})
    assert len(groups) == wq.MAX_SPLIT
    assert all(g[0] == packet[0] for g in groups)
    assert sorted(p for g in groups for p in g[1:]) == [f"pkg/test/test_{n}.py" for n in "abcdefg"]
    assert len(wq.split(tmp_path, [packet], {tuple(packet): 600})) == 3
    assert wq.split(tmp_path, [packet], {tuple(packet): 30}) == [packet]


def test_unknown_long_packets_keep_every_existing_scope_and_serial_exclusion(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    (tmp_path / "pkg/test/test_a.py").write_bytes(b"x" * (wq.SPLIT_S * wq.BYTES_PER_S + 1))
    paths = ["pkg/test", "other/test"]
    keep = [[flag, *paths] for flag in ("ROSY_RUN_BROWSER_TESTS=1", "ROSY_ALONE_FILES=x", "ROSY_JOB_ALONE=1", "ROSY_COLLECT=1")]
    keep += [["pkg/test/test_a.py::test_one", "other/test"], [*paths, "-k", "fast"], [*paths, "-n", "2"],
             ["tools/collect_alone.py", *paths]]
    assert wq.split(tmp_path, keep, {}) == keep
    wq.SERIAL_FILE.write_text("pkg/test\n")
    assert wq.split(tmp_path, [paths], {}) == [paths]


def test_browser_alone_node_ids_flags_and_serial_paths_stay_whole(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch, serial="pkg/test  # shared ports\n")
    keep = [["ROSY_RUN_BROWSER_TESTS=1", "a/test_x_browser.py", "b/test_y_browser.py"],
            ["ROSY_ALONE_FILES=x", "tools/collect_alone.py"],
            ["pkg/test/test_a.py::test_one", "other/test"],
            ["-k", "fast", "other/test", "pkg/test"],
            ["pkg/test"]]
    seen = {tuple(inv): 900.0 for inv in keep}
    assert wq.split(tmp_path, keep, seen) == keep


def test_observed_stale_singletons_are_deduplicated_after_splitting(tmp_path, monkeypatch):
    """Metric round 2 queued these five paths both through a packed selection and stale-isolation extras."""
    _tree(tmp_path, monkeypatch)
    paths = ["test/architecture/test_document_placement.py", "test/architecture/test_platform_parts.py",
             "test/test_affected_tests.py", "test/test_harness_contracts.py", "test/test_land.py"]
    broad = [*paths, "test/test_browser_scope.py"]
    singletons = [[p] for p in paths]
    planned = [broad, paths, *singletons]
    assert wq.split(tmp_path, planned, {tuple(paths): 600.0}) == [broad, *singletons]
    assert planned == [broad, paths, *singletons], "do not mutate the producer's selection"


def test_dedup_preserves_full_environment_options_and_node_scope(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    path = "pkg/test/test_a.py"
    distinct = [[path], ["ROSY_JOB_CORES=2", path], ["ROSY_JOB_CORES=4", path],
                [path, "-k", "fast"], [path + "::test_one"], [path + "::test_two"],
                ["ROSY_ALONE_FILES=x", "tools/collect_alone.py"]]
    assert wq.split(tmp_path, [*distinct, *distinct], {}) == distinct


def test_dedup_does_not_share_state_between_batch_calls(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    invocations = [["pkg/test/test_a.py"]]
    assert wq.split(tmp_path, invocations, {}) == invocations
    assert wq.split(tmp_path, invocations, {}) == invocations


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


def test_an_ignore_word_splits_too_and_the_ignored_file_never_runs(tmp_path, monkeypatch):
    """2026-11-09: `test --ignore=<g1 timing>` was the FULL long pole (11 min median, 71 min worst) and stayed whole."""
    _tree(tmp_path, monkeypatch)
    inv = ["pkg/test", "--ignore=pkg/test/test_a.py"]
    groups = wq.split(tmp_path, [inv], {tuple(inv): 600.0})
    assert len(groups) == 3 and all(g[-1] == "--ignore=pkg/test/test_a.py" for g in groups)
    files = sorted(w for g in groups for w in g if not w.startswith("-"))
    assert files == [f"pkg/test/test_{n}.py" for n in "bcde"], "every other test file exactly once"
    other = ["pkg/test", "-k", "x"]
    assert wq.split(tmp_path, [other], {tuple(other): 600.0}) == [other], "any other option keeps it whole"
