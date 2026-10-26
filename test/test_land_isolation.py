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


def fake_round(logs: dict[str, str], calls: list):
    def run_tests(wt, args, batch, logdir, round_no):
        calls.append((round_no, batch))
        for name, text in logs.items():
            (logdir / name).write_text(text, encoding="utf-8")
        return []
    return run_tests


@pytest.mark.parametrize("log, cut", [
    ("[isolation] incomplete: m/test/test_b.py\n", ["m/test/test_b.py"]),
    ("[isolation] complete: 2\n", []),
    ("job died before its report\n", ["m/test/test_a.py", "m/test/test_b.py"]),  # no evidence: none counts as run
])
def test_prepare_records_alone_files_the_budget_cut(pair, monkeypatch, tmp_path, log, cut):
    monkeypatch.setattr(land_isolation, "alone_files", lambda wt, sel: ["m/test/test_a.py", "m/test/test_b.py"])
    monkeypatch.setattr(land_isolation, "gate", lambda wt, sel: [])
    monkeypatch.setattr(land_isolation, "_cache_entries", lambda wt: [])
    git(pair, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    (pair / "tools").mkdir()
    (pair / land_isolation.GATE).write_text("", encoding="utf-8")
    logdir, calls = tmp_path / "logs", []
    logdir.mkdir()
    lines = land_isolation.run(pair, "fix/x", [["m/test"]], None, logdir, "pre", fake_round({"run-gpre-1.txt": log}, calls),
                               [], prepare=True)
    assert calls == [("gpre", land_isolation.job(["m/test/test_a.py", "m/test/test_b.py"]))]
    assert lines == ([f"isolation incomplete: {', '.join(cut)}"] if cut else [])
    rec = land_isolation.last(pair, "fix/x")
    assert rec["alone"] == ["m/test/test_a.py", "m/test/test_b.py"] and rec["incomplete"] == cut
    # The turn's summary carries the cut again; nothing reruns while main has not moved.
    calls.clear()
    turn = land_isolation.run(pair, "fix/x", [["m/test"]], None, logdir, "1", fake_round({}, calls), [], prepare=False)
    assert calls == [] and turn == ([f"isolation incomplete: {', '.join(cut)}"] if cut else [])


def test_turn_reruns_alone_only_tests_whose_referenced_file_main_changed(pair, monkeypatch, tmp_path):
    ident = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(pair, *ident, "commit", "-q", "-m", "init")
    prepared = git(pair, "rev-parse", "HEAD")
    refs = {"src/used.py": ["m/test/test_used.py"], "src/other.py": ["m/test/test_other.py"]}
    monkeypatch.setattr(land_isolation, "_selector", lambda wt: (None, None, lambda p: refs.get(p, []), None))
    rec = {"main": prepared, "alone": ["m/test/test_used.py", "m/test/test_spare.py"]}
    for path, expected in (("src/unrelated.py", []), ("src/used.py", ["m/test/test_used.py"])):
        (pair / path).parent.mkdir(exist_ok=True)
        (pair / path).write_text("x = 1\n", encoding="utf-8")
        git(pair, "add", path)
        git(pair, *ident, "commit", "-q", "-m", path)
        assert land_isolation.stale(pair, rec) == expected
    assert land_isolation.stale(pair, {**rec, "main": git(pair, "rev-parse", "HEAD")}) == []  # main did not move
    (pair / "tools").mkdir()
    (pair / land_isolation.GATE).write_text("", encoding="utf-8")
    monkeypatch.setattr(land_isolation, "last", lambda wt, branch: rec)
    monkeypatch.setattr(land_isolation, "_cache_entries", lambda wt: [])
    logdir, calls = tmp_path / "logs", []
    logdir.mkdir()
    land_isolation.run(pair, "fix/x", [["m/test"]], None, logdir, "2",
                       fake_round({"run-g2-1.txt": "[isolation] complete: 1\n"}, calls), [["test/architecture"]], False)
    assert calls == [("g2", [["test/architecture"], *land_isolation.job(["m/test/test_used.py"])])]  # no gate in the turn


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
    picked = land_isolation.alone_files(tmp_path, [["m/test", "s/test"]])
    assert picked == ["s/test/test_brake.py", many[7], *[t for t in many if t != many[7]]]


def test_guard_round_wiring(monkeypatch):
    seen = []
    monkeypatch.setattr(land_isolation, "run", lambda wt, branch, sel, args, logdir, rnd, rt, guards, prep:
                        seen.append((sel, rnd, guards, prep)) or ["x"])
    out = land_guards.first(ROOT, argparse.Namespace(tests="auto", node=True), [["pkg/test"]], Path("."), "pre",
                            None, isolated=True)
    assert seen == [([["pkg/test"]], "pre", [list(land_guards.GUARDS)], True)] and out == ["round pre: guard round first: x"]


def test_selector_edge_on_this_repo_selects_the_incident_test():
    """The 2026-10-26 change to native_cycle.py: its test is on the references edge and loads it by path."""
    repo, _, refs, _ = land_isolation._selector(ROOT)
    found = refs("learning/training/omx/native_cycle.py")
    assert "learning/training/omx/test/test_native_cycle.py" in found
    assert "spec_from_file_location" in repo.text("learning/training/omx/test/test_native_cycle.py")
