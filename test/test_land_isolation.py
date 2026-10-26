"""tools/land_isolation.py: the collection gate catches an import a sibling module hides in a shared process.

The fixture pair: test_a_inserts.py puts helpers/ on sys.path at import, test_b_needs.py imports a module that
lives only there. A folder run is green (a is collected first); under the gate b is red.
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
}


@pytest.fixture
def pair(tmp_path):
    for name, text in PAIR.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    for args in (["init", "-q"], ["add", "."]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def pytest_run(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **(env or {})}, timeout=300)


def test_folder_run_is_green_and_the_gate_runner_is_red(pair):
    folder = pytest_run(pair, ".")
    assert folder.returncode == 0, folder.stdout + folder.stderr
    gate = pytest_run(ROOT, "-rfE", "--rootdir=.", land_isolation.GATE,
                      env={"ROSY_COLLECT_ROOT": str(pair), "ROSY_COLLECT_PATHS": "."})
    text = gate.stdout + gate.stderr
    assert gate.returncode == 1, text
    assert "FAILED tools/collect_alone.py::test_collects_alone[test_b_needs.py]" in text, text
    assert "hidden_mod" in text and "1 passed" in text, text


@pytest.mark.parametrize("xdist", [[], ["-n", "2"]], ids=["serial", "xdist"])
def test_root_conftest_names_the_inserter_and_never_fails(pair, xdist):
    if xdist and not importlib.util.find_spec("xdist"):
        pytest.skip("pytest-xdist not installed (CI)")
    (pair / "conftest.py").write_bytes((ROOT / "conftest.py").read_bytes())
    run = pytest_run(pair, ".", *xdist)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text
    assert "sys.path added by 1 test module(s)" in text and "test_a_inserts.py: helpers" in text, text


def test_collect_alone_reports_only_the_masked_file(pair):
    files = land_isolation.tracked_tests(pair, ["."])
    assert files == ["test_a_inserts.py", "test_b_needs.py"]
    found = land_isolation.collect_alone(pair, files)
    assert found["test_a_inserts.py"][0] == 0
    assert found["test_b_needs.py"][0] not in (0, 5) and "hidden_mod" in found["test_b_needs.py"][1]
    assert land_isolation.collect_alone(pair, files, budget_s=-1) == {}  # past the budget: nothing started


def test_guard_round_carries_the_gate_and_the_safety_tests_alone(monkeypatch):
    """Wiring: land_guards.first sends the gate with the guards; safety tests and reference tests go alone."""
    monkeypatch.setattr(land_isolation, "alone", lambda wt, inv: [["middleware/drive/safety/test/test_x.py"]])
    batches = []
    selection = [["pkg/test", "test/test_y.py"]]
    land_guards.first(ROOT, argparse.Namespace(tests="auto", node=True), selection, Path("."), 1,
                      lambda wt, args, inv, logdir, round_no: batches.append(inv) or [])
    assert batches == [[list(land_guards.GUARDS), ["ROSY_COLLECT_PATHS=pkg/test,test/test_y.py", land_isolation.GATE],
                        ["middleware/drive/safety/test/test_x.py"]]]


def test_alone_caps_reference_tests_and_keeps_safety_tests(monkeypatch, tmp_path):
    """Above CAP reference tests only spec_from_file_location loaders stay; safety tests always run alone."""
    import affected_narrow
    import affected_tests
    import safety_review

    (tmp_path / land_isolation.GATE).parent.mkdir(parents=True)
    (tmp_path / land_isolation.GATE).write_text("", encoding="utf-8")
    refs = [f"m/test/test_{n:02}.py" for n in range(land_isolation.CAP + 2)]
    selected = [*refs, "safe/test/test_s.py", "m/test/test_other.py"]

    class Repo:
        safety_roots, safety_modules = [{"path": "safe", "concern": "safety"}], set()

        @staticmethod
        def referencing_tests(path):
            return refs

        @staticmethod
        def text(path):
            return "spec_from_file_location" if path == refs[3] else ""

    monkeypatch.setattr(land_isolation, "tracked_tests", lambda root, paths: selected)
    monkeypatch.setattr(affected_tests.Repo, "load", classmethod(lambda cls, root: Repo))
    monkeypatch.setattr(affected_tests, "changed_files", lambda *a: ["m/a.py"])
    monkeypatch.setattr(affected_narrow, "registry_readers", lambda repo, path: [])
    assert safety_review.is_safety("safe/test/test_s.py", Repo.safety_roots, set())
    assert land_isolation.alone(tmp_path, [["m/test", "safe/test"]]) == [[refs[3]], ["safe/test/test_s.py"]]
    refs[:] = refs[:2]  # at or under CAP: every reference test alone
    assert land_isolation.alone(tmp_path, [["m/test", "safe/test"]]) == [[refs[0]], [refs[1]], ["safe/test/test_s.py"]]
