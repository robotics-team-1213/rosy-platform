"""tools/land_isolation.py's collection gate, as one pytest job on a test host (remote_pytest.py).

Job words: ``ROSY_COLLECT_PATHS`` (comma-separated selection paths), optional ``ROSY_COLLECT_BUDGET_S`` (wall cap,
default 600) and ``ROSY_COLLECT_ROOT`` (the tree, default this checkout). Each tracked test file under the paths
gets ``pytest --collect-only`` in its own process, as many at once as the job's ``ROSY_JOB_CORES`` (else 2).
A file that does not collect alone fails its own id; one not reached within the budget skips.
Not a test_*.py file: pytest collects it only when named, so no folder run picks it up.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_isolation  # noqa: E402

ROOT = Path(os.environ.get("ROSY_COLLECT_ROOT") or Path(__file__).resolve().parents[1])
PATHS = [p for p in os.environ.get("ROSY_COLLECT_PATHS", "").split(",") if p]
FILES = land_isolation.tracked_tests(ROOT, PATHS)


@pytest.fixture(scope="module")
def collected():
    workers = int(os.environ.get("ROSY_JOB_CORES") or 2)
    return land_isolation.collect_alone(ROOT, FILES, workers, float(os.environ.get("ROSY_COLLECT_BUDGET_S") or 600))


@pytest.mark.parametrize("path", FILES)
def test_collects_alone(path, collected):
    if path not in collected:
        pytest.skip("not reached within ROSY_COLLECT_BUDGET_S")
    code, text = collected[path]
    if code is None:
        pytest.skip(text)
    assert code in (0, 5), f"{path} does not collect in its own pytest process (exit {code}):\n{text}"
