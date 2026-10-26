"""tools/land_isolation.py's jobs, as one pytest invocation on a test host (remote_pytest.py).

Job words: ``ROSY_COLLECT_PATHS`` (comma-separated selection paths: ``pytest --collect-only`` for each tracked test
file under them) or ``ROSY_ALONE_FILES`` (comma-separated test files, in priority order: each runs whole), optional
``ROSY_COLLECT_BUDGET_S`` (wall cap, default land_isolation.BUDGET_S) and ``ROSY_COLLECT_ROOT`` (the tree, default
this checkout). Each file gets its own process, ``ROSY_JOB_CORES`` at a time (else 2); files under one
``serial_suites.txt`` prefix never overlap. A file that fails alone (beyond test/known_failures.txt for a whole run)
fails its own id; one the budget did not reach skips, and the alone job prints ``[isolation] incomplete: <files>``
(else ``[isolation] complete: <n>``) for land_isolation.unreached.
Not a test_*.py file: pytest collects it only when named, so no folder run picks it up.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / "remote")]
import land_isolation  # noqa: E402
import xdist_plan  # noqa: E402

ROOT = Path(os.environ.get("ROSY_COLLECT_ROOT") or HERE.parent)
FILES = land_isolation.tracked_tests(ROOT, [p for p in os.environ.get("ROSY_COLLECT_PATHS", "").split(",") if p])
ALONE = [p for p in os.environ.get("ROSY_ALONE_FILES", "").split(",") if p]
WORKERS = int(os.environ.get("ROSY_JOB_CORES") or 2)
BUDGET = float(os.environ.get("ROSY_COLLECT_BUDGET_S") or land_isolation.BUDGET_S)
SERIAL = tuple(xdist_plan.load_serial(xdist_plan.SERIAL_FILE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def collected():
    return land_isolation.each_alone(ROOT, FILES, land_isolation.COLLECT, WORKERS, BUDGET)


@pytest.fixture(scope="module")
def ran(request):
    done = land_isolation.each_alone(ROOT, ALONE, land_isolation.TAIL, WORKERS, BUDGET, SERIAL)
    line = land_isolation.report_line(ALONE, done)

    class Report:
        @staticmethod
        def pytest_terminal_summary(terminalreporter):
            terminalreporter.write_line(line)

    request.config.pluginmanager.register(Report(), "rosy-isolation-report")
    return done


@pytest.mark.parametrize("path", FILES)
def test_collects_alone(path, collected):
    code, text = collected.get(path, (None, "not reached within the budget"))
    if code is None:
        pytest.skip(text)
    assert code in (0, 5), f"{path} does not collect in its own pytest process (exit {code}):\n{text}"


@pytest.mark.parametrize("path", ALONE)
def test_runs_alone(path, ran):
    code, text = ran.get(path, (None, "not reached within the budget"))
    if code is None:
        pytest.skip(text)
    new = [] if code in (0, 5) else land_isolation.new_failures(text) or [f"exit {code}"]
    assert not new, f"{path} fails in its own pytest process: {new}\n{text}"
