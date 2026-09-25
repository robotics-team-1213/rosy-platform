"""test/known_failures.py tells a listed pre-existing failure from a new one."""

from __future__ import annotations

from pathlib import Path
import sys

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


def test_main_exits_nonzero_only_for_a_new_failure(tmp_path, capsys):
    listed = next(iter(known_failures.load_known(known_failures.LIST.read_text(encoding="utf-8"))))
    report = tmp_path / "run.txt"
    report.write_text(f"FAILED {listed} - x\n", encoding="utf-8")
    assert known_failures.main([str(report)]) == 0
    report.write_text("FAILED test/test_nobody.py::test_new - x\n", encoding="utf-8")
    assert known_failures.main([str(report)]) == 1
    assert "NEW       test/test_nobody.py::test_new" in capsys.readouterr().out


def test_every_listed_id_names_a_real_test_with_a_reason():
    known = known_failures.load_known(known_failures.LIST.read_text(encoding="utf-8"))
    assert known
    for nodeid, reason in known.items():
        path, _, name = nodeid.partition("::")
        assert (ROOT / path).is_file(), nodeid
        function = name.split("[", 1)[0]
        assert f"def {function}(" in (ROOT / path).read_text(encoding="utf-8"), nodeid
        assert reason, nodeid
