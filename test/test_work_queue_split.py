"""Long invocations split by measured run time and ordered by it (2026-11-01: FULL rounds of 45-60 min ran at
0.4-0.7x parallelism, tails of 30 min combined invocations)."""

from __future__ import annotations

import json
import math
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
    unpacked = wq.split(tmp_path, [multi], seen)
    # min(ceil(600 / 90), 5 files) = 5 groups; a small path count still ends one file per job, and the empty
    # other/test folder contributes no test file, so no invocation carries it.
    assert len(unpacked) == 5 and all(g[0] == "ROSY_JOB_CORES=6" for g in unpacked)
    assert sorted(w for g in unpacked for w in g if w != "ROSY_JOB_CORES=6") == [
        f"pkg/test/test_{n}.py" for n in "abcde"]
    assert not any("other/test" in w for g in unpacked for w in g)
    assert wq.split(tmp_path, [["short/test"]], seen) == [["short/test"]], "under SPLIT_S stays whole"
    assert wq.split(tmp_path, [["never/ran"]], seen) == [["never/ran"]], "a missing path has zero estimated cost"
    groups = wq.split(tmp_path, [["pkg/test"]], seen)
    assert len(groups) == 5  # min(ceil(600 / 90), 5 files)
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
    # exactly SPLIT_S is one group of both files (the invocation unchanged); past it, two single-file groups,
    # heaviest first
    expected = [packet] if offset <= 0 else [[*packet[:2], "test_b.py"], [*packet[:2], "test_a.py"]]
    assert wq.split(tmp_path, [packet, packet], {}) == expected
    assert wq.split(tmp_path, [packet], {tuple(packet): 0}) == [packet], "measured history wins over byte cost"


def test_unknown_large_directory_uses_existing_balancing_and_cap_and_preserves_measured_history(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    extra = [f"{i:02d}" for i in range(14)]
    for n in extra:
        (tmp_path / "pkg/test" / f"test_{n}.py").write_bytes(b"x" * (wq.SPLIT_S * wq.BYTES_PER_S))
    packet = ["ROSY_JOB_CORES=2", "pkg/test"]
    groups = wq.split(tmp_path, [packet], {})
    assert len(groups) == wq.MAX_SPLIT
    assert all(g[0] == packet[0] for g in groups)
    expected = sorted(f"pkg/test/test_{n}.py" for n in [* "abcde", *extra])
    assert sorted(p for g in groups for p in g[1:]) == expected
    assert len(wq.split(tmp_path, [packet], {tuple(packet): 600})) == 7
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


def test_a_run_may_ask_three_main_workers_of_a_full_host():
    room = {"cores": 24.0, "mem": 30.0, "site": False, "light": False}
    assert wq.MAX_MAIN == 3 and wq.main_workers(room, 20) == 3


def test_an_ignore_word_splits_too_and_the_ignored_file_never_runs(tmp_path, monkeypatch):
    """2026-11-09: `test --ignore=<g1 timing>` was the FULL long pole (11 min median, 71 min worst) and stayed whole."""
    _tree(tmp_path, monkeypatch)
    inv = ["pkg/test", "--ignore=pkg/test/test_a.py"]
    groups = wq.split(tmp_path, [inv], {tuple(inv): 600.0})
    assert len(groups) == 4 and all(g[-1] == "--ignore=pkg/test/test_a.py" for g in groups)
    files = sorted(w for g in groups for w in g if not w.startswith("-"))
    assert files == [f"pkg/test/test_{n}.py" for n in "bcde"], "every other test file exactly once"
    other = ["pkg/test", "-k", "x"]
    assert wq.split(tmp_path, [other], {tuple(other): 600.0}) == [other], "any other option keeps it whole"
    bare = ["--ignore=pkg/test/test_a.py"]
    assert wq.split(tmp_path, [bare], {tuple(bare): 600.0}) == [bare], "no path: nothing to split"


def test_fleet_weights_and_unpacked_serial_paths_are_preserved(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch, serial="serial/test\n")
    (tmp_path / "serial/test").mkdir(parents=True)
    (tmp_path / "serial/test/test_s.py").write_text("x\n")
    (tmp_path / "operations/fleet/test").mkdir(parents=True)
    for n in "abc":
        (tmp_path / "operations/fleet/test" / f"test_{n}.py").write_text("x\n")
    (tmp_path / "tools/harness").mkdir(parents=True)
    (tmp_path / wq.FLEET_SECONDS).write_text(json.dumps({"test_a.py": 180.0, "test_b.py": 20.0, "test_c.py": 20.0}))
    assert wq._fleet_weights(tmp_path) == {"test_a.py": 180.0, "test_b.py": 20.0, "test_c.py": 20.0}
    assert wq._file_weight(tmp_path, tmp_path / "operations/fleet/test/test_a.py", {"test_a.py": 180.0}) == 180.0
    fleet_groups = wq.split(tmp_path, [["operations/fleet/test"]], {("operations/fleet/test",): 400.0})
    assert ["operations/fleet/test/test_a.py"] in fleet_groups and len(fleet_groups) == 3
    assert wq.split(tmp_path, [["pkg/test", "serial/test"]], {("pkg/test", "serial/test"): 600.0}) == [
        ["pkg/test", "serial/test"]]


def _deep_tree(tmp_path, monkeypatch):
    _tree(tmp_path, monkeypatch)
    (tmp_path / "pkg/a").mkdir(parents=True)
    (tmp_path / "pkg/b").mkdir(parents=True)


def test_multi_path_repack_balances_into_ceil_groups_and_keeps_every_file_once(tmp_path, monkeypatch):
    """The 2026-11-18 fix: a >= SPLIT_S multi-path invocation becomes ceil(seconds/SPLIT_S) balanced groups,
    not one job per file (8,111 single-file jobs a day, 39 % of run time, ~9-11 s fixed cost each)."""
    _deep_tree(tmp_path, monkeypatch)
    unit = wq.SPLIT_S * wq.BYTES_PER_S // 4  # 22.5 s a file: 20 of them plus the _tree files
    for n in range(20):
        (tmp_path / "pkg/test" / f"test_{n:02d}.py").write_bytes(b"x" * unit)
    inv = ["ROSY_JOB_CORES=4", "pkg/test", "pkg/test/test_a.py", "other/test"]  # test_a named twice: once deduped
    files = sorted([*[f"pkg/test/test_{n}.py" for n in "abcde"], *[f"pkg/test/test_{n:02d}.py" for n in range(20)]])
    seconds = sum((tmp_path / f).stat().st_size for f in files) / wq.BYTES_PER_S
    seen = {tuple(inv): seconds}
    groups = wq.split(tmp_path, [inv], seen)
    assert len(groups) == math.ceil(seconds / wq.SPLIT_S) == 6, "the tail bound the 11-01 fix wanted"
    assert sorted(p for g in groups for p in g[1:]) == files, "every test file exactly once, none duplicated"
    assert all(g[0] == "ROSY_JOB_CORES=4" for g in groups)
    for g in groups:  # balanced by the cold estimate: no group over SPLIT_S
        assert sum((tmp_path / p).stat().st_size for p in g[1:]) / wq.BYTES_PER_S <= wq.SPLIT_S
    again = wq.split(tmp_path, [inv], {tuple(inv): seconds, ("an/unrelated/argv",): 999.0})
    assert again == groups == wq.split(tmp_path, [inv], seen), "same tree, same argv: land_cache reuse fires"


def test_repack_separates_clashing_names_and_keeps_the_exclusive_file_alone(tmp_path, monkeypatch):
    _deep_tree(tmp_path, monkeypatch)
    (tmp_path / "pkg/a/test_twin.py").write_bytes(b"x" * 900)   # same basename as pkg/b's: pytest module clash
    (tmp_path / "pkg/b/test_twin.py").write_bytes(b"x" * 900)
    (tmp_path / "pkg/a/test_one.py").write_text("import shared_test\n")
    (tmp_path / "pkg/a/shared_test.py").write_text("x = 1\n")   # a *_test.py sibling: same name, other source
    (tmp_path / "pkg/b/test_two.py").write_text("import shared_test\n")
    (tmp_path / "pkg/b/shared_test.py").write_text("x = 2\n")
    (tmp_path / wq.EXCLUSIVE_FILE).parent.mkdir(parents=True)
    (tmp_path / wq.EXCLUSIVE_FILE).write_text("def test_g1(): pass\n")
    inv = ["pkg/a", "pkg/b", "pkg/test", wq.EXCLUSIVE_FILE]
    groups = wq.split(tmp_path, [inv], {tuple(inv): 4 * wq.SPLIT_S})
    expected = sorted(["pkg/a/test_twin.py", "pkg/b/test_twin.py", "pkg/a/test_one.py", "pkg/a/shared_test.py",
                       "pkg/b/test_two.py", "pkg/b/shared_test.py", wq.EXCLUSIVE_FILE,
                       *[f"pkg/test/test_{n}.py" for n in "abcde"]])
    assert sorted(p for g in groups for p in g) == expected
    joins = [set(g) for g in groups]
    assert not any({"pkg/a/test_twin.py", "pkg/b/test_twin.py"} <= g for g in joins), "basename clash"
    assert not any({"pkg/a/test_one.py", "pkg/b/test_two.py"} <= g for g in joins), "import-name clash"
    assert not any({"pkg/a/shared_test.py", "pkg/b/shared_test.py"} <= g for g in joins), "clash via the siblings"
    assert next(g for g in groups if wq.EXCLUSIVE_FILE in g) == [wq.EXCLUSIVE_FILE], "G1 timing runs whole-file"
    assert all(sum(len(p) + 1 for p in g) <= wq.MAX_INVOCATION_CHARS for g in groups)


def test_repack_yields_the_count_bound_to_the_command_budget(tmp_path, monkeypatch):
    _deep_tree(tmp_path, monkeypatch)
    for n in range(100):  # 64-char paths, 1.6 s each: 2 balanced groups would need 3250 chars apiece
        (tmp_path / f"pkg/deep/{n:03d}/" / ("d" * 35)).mkdir(parents=True)
        (tmp_path / f"pkg/deep/{n:03d}/" / ("d" * 35) / f"test_x_{n:03d}.py").write_bytes(b"x" * 3200)
    inv = ["pkg/deep", "other/test"]
    seconds = 100 * 3200 / wq.BYTES_PER_S
    groups = wq.split(tmp_path, [inv], {tuple(inv): seconds})
    assert math.ceil(seconds / wq.SPLIT_S) == 2 < len(groups) == 3, "a broken constraint is worse than one more job"
    assert all(sum(len(p) + 1 for p in g) <= wq.MAX_INVOCATION_CHARS for g in groups)
    assert sorted(p for g in groups for p in g) == sorted(
        f"pkg/deep/{n:03d}/" + "d" * 35 + f"/test_x_{n:03d}.py" for n in range(100))


def test_a_group_may_exceed_split_s_only_when_one_file_does(tmp_path, monkeypatch):
    _deep_tree(tmp_path, monkeypatch)
    (tmp_path / "pkg/test/test_huge.py").write_bytes(b"x" * (2 * wq.SPLIT_S * wq.BYTES_PER_S))
    inv = ["pkg/test", "pkg/test/test_huge.py", "other/test"]
    groups = wq.split(tmp_path, [inv], {tuple(inv): 185.0})
    estimates = [sum((tmp_path / p).stat().st_size for p in g) / wq.BYTES_PER_S for g in groups]
    assert [e > wq.SPLIT_S for e in estimates] == [True, False, False]
    assert len(groups[0]) == 1 and groups[0] == ["pkg/test/test_huge.py"]


def test_a_multi_path_ignore_word_is_kept_and_the_ignored_file_never_runs(tmp_path, monkeypatch):
    _deep_tree(tmp_path, monkeypatch)
    inv = ["pkg/test", "other/test", "--ignore=pkg/test/test_a.py"]
    groups = wq.split(tmp_path, [inv], {tuple(inv): 600.0})
    assert all(g[-1] == "--ignore=pkg/test/test_a.py" for g in groups)
    assert sorted(p for g in groups for p in g[:-1]) == [f"pkg/test/test_{n}.py" for n in "bcde"]
