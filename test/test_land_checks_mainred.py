"""land_checks.main_red reruns alone-class NEW ids on main per file, not as node ids (2026-11-13)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land_checks  # noqa: E402
from test_land import repos  # noqa: E402,F401  (land.py's fixture repos)

RUNS = "tools/collect_alone.py::test_runs_alone[pkg/test/test_a.py]"
COLLECTS = "tools/collect_alone.py::test_collects_alone[pkg/test/test_b.py]"
PLAIN = "pkg/test/test_a.py::test_a"


@pytest.mark.parametrize("main_fails", [True, False])
def test_alone_ids_rerun_per_file_with_env_and_plain_ids_as_before(repos, tmp_path, capsys, main_fails):
    _, wt = repos
    seen = []

    def run(invocations, logs, sha="HEAD", **kw):
        seen.extend(invocations)
        for inv, log in zip(invocations, logs):
            log.write_text(f"FAILED {inv[-1]}\n1 failed\n" if main_fails else "1 passed\n", encoding="utf-8")
        return [1 if main_fails else 0] * len(invocations)

    verdict = "".join(f"NEW {i}\n" for i in (PLAIN, RUNS, COLLECTS))
    out = land_checks.main_red(wt, ["ROSY_X=1", "pkg/test"], verdict, tmp_path, "t", sys.executable, run)
    assert seen == [["ROSY_X=1", PLAIN],
                    ["ROSY_X=1", "ROSY_ALONE_FILES=pkg/test/test_a.py", "tools/collect_alone.py", "-rA"],
                    ["ROSY_X=1", "ROSY_COLLECT_PATHS=pkg/test/test_b.py", "tools/collect_alone.py", "-rA"]]
    if main_fails:
        assert out.startswith("MAIN-RED: 3 of 3") and "MAIN-RED " + PLAIN in capsys.readouterr().out
    else:
        assert "pass on main" in out
