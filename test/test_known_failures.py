"""test/known_failures.py tells a listed pre-existing failure from a new one."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import known_failures  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
KNOWN = {
    "src/a/test/test_x.py::test_old": "reason",
    "test/test_y.py::test_param[B]": "reason",
}


def test_a_listed_failure_is_known_and_an_unlisted_one_is_new():
    report = "\n".join([
        "FAILED src/a/test/test_x.py::test_old - AssertionError: boom",
        "FAILED test/test_y.py::test_param[C] - nope",
        "7 failed, 3 passed in 1.00s",
    ])
    new, seen, quiet = known_failures.compare(report, KNOWN)
    assert new == ["test/test_y.py::test_param[C]"]
    assert seen == ["src/a/test/test_x.py::test_old"]
    assert quiet == ["test/test_y.py::test_param[B]"]


def test_a_run_from_inside_a_module_matches_on_a_path_boundary():
    new, seen, _quiet = known_failures.compare("FAILED test/test_x.py::test_old", KNOWN)
    assert (new, seen) == ([], ["src/a/test/test_x.py::test_old"])
    new, _seen, _quiet = known_failures.compare("FAILED t_x.py::test_old", KNOWN)
    assert new == ["t_x.py::test_old"]


def test_windows_separators_and_errors_are_read():
    new, seen, _quiet = known_failures.compare(r"ERROR src\a\test\test_x.py::test_old", KNOWN)
    assert (new, seen) == ([], ["src/a/test/test_x.py::test_old"])


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_main_exits_nonzero_only_for_a_new_failure(tmp_path, capsys, monkeypatch, encoding):
    # 2026-10-02 — 장부가 비어도(전 녹색이 목표 상태) 이 시험은 합성 항목으로 돈다.
    synthetic = tmp_path / "known.txt"
    synthetic.write_text("test/test_synthetic.py::test_old  # synthetic\n", encoding="utf-8")
    monkeypatch.setattr(known_failures, "LIST", synthetic)
    listed = next(iter(known_failures.load_known(synthetic.read_text(encoding="utf-8"))))
    report = tmp_path / "run.txt"
    report.write_text(f"FAILED {listed} - x\n", encoding=encoding)
    assert known_failures.main([str(report)]) == 0
    report.write_text("FAILED test/test_nobody.py::test_new - x\n", encoding=encoding)
    assert known_failures.main([str(report)]) == 1
    assert "NEW       test/test_nobody.py::test_new" in capsys.readouterr().out


FLAKY_ID = "test/test_q.py::test_flaky[a]"


@pytest.mark.parametrize("listed,rerun,verdict", [
    (True, f"PASSED {FLAKY_ID}\n1 passed", "FLAKY"),      # listed, passes once more
    (True, f"FAILED {FLAKY_ID} - again\n1 failed", "NEW"),  # listed, fails twice
    (False, "", "NEW"),                                     # unlisted: never rerun
])
def test_quarantined_failure_that_passes_its_one_rerun_is_flaky(tmp_path, monkeypatch, capsys, listed, rerun, verdict):
    quarantine = tmp_path / "flaky.txt"
    quarantine.write_text(f"{FLAKY_ID}  # synthetic; remove when fixed; 2026-10-14; test\n" if listed else "",
                          encoding="utf-8")
    monkeypatch.setattr(known_failures, "LIST", tmp_path / "known.txt")
    (tmp_path / "known.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(known_failures, "QUARANTINE", quarantine)
    first = f"FAILED {FLAKY_ID} - boom\n1 failed\n"
    q = known_failures.load_known(quarantine.read_text(encoding="utf-8"))
    assert known_failures.rerun_ids(first, q) == ([FLAKY_ID] if listed else [])
    report = tmp_path / "run.txt"
    report.write_text(first + (f"\n{known_failures.RERUN_MARKER}\n{rerun}\n" if rerun else ""), encoding="utf-8")
    assert known_failures.main([str(report)]) == (0 if verdict == "FLAKY" else 1)
    assert f"{verdict:<10}{FLAKY_ID}" in capsys.readouterr().out


def test_a_rerun_does_not_excuse_an_unlisted_failure_beside_a_flaky_one():
    q = {FLAKY_ID: "synthetic"}
    report = "\n".join([f"FAILED {FLAKY_ID} - x", "FAILED test/test_q.py::test_real - x",
                        known_failures.RERUN_MARKER, f"PASSED {FLAKY_ID}", "PASSED test/test_q.py::test_real"])
    assert known_failures.rerun_ids(report, q) == [FLAKY_ID]
    assert known_failures.flaky(report, q) == [FLAKY_ID]
    new, _seen, _quiet = known_failures.compare(report, {})
    assert "test/test_q.py::test_real" in new


def test_every_quarantined_id_names_a_real_test_with_a_removal_condition():
    quarantine = known_failures.load_known(known_failures.QUARANTINE.read_text(encoding="utf-8"))
    for nodeid, reason in quarantine.items():
        path, _, name = nodeid.partition("::")
        assert (ROOT / path).is_file(), nodeid
        assert f"def {name.split('[', 1)[0]}(" in (ROOT / path).read_text(encoding="utf-8"), nodeid
        assert "remove when" in reason and "2026-" in reason, nodeid


def test_every_listed_id_names_a_real_test_with_a_reason():
    known = known_failures.load_known(known_failures.LIST.read_text(encoding="utf-8"))
    # 2026-10-02 — 빈 장부는 합법이다(전 녹성). 항목이 있을 때만 형식을 검사한다.
    for nodeid, reason in known.items():
        path, _, name = nodeid.partition("::")
        assert (ROOT / path).is_file(), nodeid
        function = name.split("[", 1)[0]
        assert f"def {function}(" in (ROOT / path).read_text(encoding="utf-8"), nodeid
        assert reason, nodeid


def test_a_teardown_error_on_the_rerun_is_not_flaky(tmp_path, monkeypatch, capsys):
    quarantine = tmp_path / "flaky.txt"
    quarantine.write_text(f"{FLAKY_ID}  # synthetic; remove when fixed; 2026-10-14; test\n", encoding="utf-8")
    monkeypatch.setattr(known_failures, "QUARANTINE", quarantine)
    monkeypatch.setattr(known_failures, "LIST", tmp_path / "known.txt")
    (tmp_path / "known.txt").write_text("", encoding="utf-8")
    report = tmp_path / "run.txt"
    report.write_text(f"FAILED {FLAKY_ID} - boom\n{known_failures.RERUN_MARKER}\n"
                      f"PASSED {FLAKY_ID}\nERROR {FLAKY_ID} - teardown\n", encoding="utf-8")
    assert known_failures.main([str(report)]) == 1
    assert f"NEW       {FLAKY_ID}" in capsys.readouterr().out


CLEAN = f"PASSED {FLAKY_ID}\n1 passed"


@pytest.mark.parametrize("code,report,rerun_code,section,green", [
    (1, f"FAILED {FLAKY_ID} - x", 0, CLEAN, True),
    (1, f"FAILED {FLAKY_ID} - x\nFAILED test/test_q.py::test_real - x", 0, CLEAN, False),  # mixed
    *((c, f"FAILED {FLAKY_ID} - x", 0, CLEAN, False) for c in (2, 3, 4, 5)),           # not a test failure
    (1, f"FAILED {FLAKY_ID} - x\nERROR test/test_q.py - ImportError", 0, CLEAN, False),  # collection error
    (1, "1 failed in 0.1s", 0, CLEAN, False),                                         # no summary lines
    (1, f"FAILED {FLAKY_ID} - x", 0, f"PASSED {FLAKY_ID}\nERROR {FLAKY_ID} - teardown", False),
    (1, f"FAILED {FLAKY_ID} - x", 1, CLEAN, False),                                   # rerun exit 1
    (1, f"FAILED {FLAKY_ID} - x", 0, "", False),                                      # rerun ran nothing
])
def test_the_rerun_decision_shared_by_ci_and_the_lab_runner(code, report, rerun_code, section, green):
    quarantine = {FLAKY_ID: "synthetic"}
    failed = known_failures.failed_ids(report)
    ids = known_failures.rerun_ids(report, quarantine)
    due = known_failures.should_rerun(code, failed, ids)
    assert due == (code == 1 and set(failed) == {FLAKY_ID})
    assert known_failures.rerun_passed(code, failed, ids, rerun_code, section) is green

def test_the_quarantine_is_safety_tagged_and_never_holds_a_safety_test():
    """D-762 stage 1: adding an id needs a Safety-Review trailer; a safety-path test is never retried."""
    import yaml

    sys.path.insert(0, str(ROOT / "tools" / "harness"))
    import safety_review

    manifest = yaml.safe_load((ROOT / safety_review.MANIFEST).read_text(encoding="utf-8"))
    roots, modules = manifest["roots"], set(manifest.get("safety_modules") or ())
    assert safety_review.is_safety("test/flaky_quarantine.txt", roots, modules)
    quarantine = known_failures.load_known(known_failures.QUARANTINE.read_text(encoding="utf-8"))
    under_safety = [n for n in quarantine if safety_review.is_safety(n.partition("::")[0], roots, modules)]
    assert not under_safety, under_safety