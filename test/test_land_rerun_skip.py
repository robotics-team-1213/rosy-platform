"""A landing's rerun alone that only skipped says nothing about the failure (2026-11-07)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import git, repos  # noqa: E402,F401  (land.py's fixture repos)


@pytest.mark.parametrize("summary, flaky", [("1 skipped in 0.09s", False), ("1 passed in 0.09s", True)])
def test_a_rerun_that_only_skipped_is_no_verdict_not_load_flaky(repos, tmp_path, summary, flaky):
    """A test needing the LeRobot venv failed on the AI PC, skipped on the site PC and read as flaky."""
    main, wt = repos

    def run(invs, logs, *a, **k):
        logs[0].write_text(f"s [100%]\n{summary}\n", encoding="utf-8")
        return [0]

    (tmp_path / "original.txt").write_text("FAILED pkg/test/test_a.py::test_a\n", encoding="utf-8")
    ids, said = land.land_checks._rerun_alone(
        wt, ["pkg/test"], tmp_path / "original.txt", "NEW pkg/test/test_a.py::test_a\n", tmp_path, "skip",
        sys.executable, run, tested_sha=git(wt, "rev-parse", "HEAD"))
    assert bool(ids) is flaky
    assert flaky or "gave no verdict" in said
