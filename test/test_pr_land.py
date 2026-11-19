"""Contract tests for tools/pr_land.py (D-1052)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pr_land", ROOT / "tools" / "pr_land.py")
pr_land = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pr_land
SPEC.loader.exec_module(pr_land)


def test_build_body_appends_self_overlap_review():
    assert "Overlap-Review: self (coordinated)" in pr_land.build_body("summary", "coordinated")
    assert "Overlap-Review:" not in pr_land.build_body("summary", "")


def test_dry_run_skips_push_and_gh(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(cmd, cwd, env=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return "feat/topic"
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:2] == ["git", "log"]:
            return "feat: sample"
        raise AssertionError(cmd)

    monkeypatch.setattr(pr_land, "_run", fake_run)
    assert pr_land.main(["--dry-run", "--self-review", "solo"], repo=tmp_path) == 0
    assert "dry-run branch=feat/topic" in capsys.readouterr().out
    assert not any(c[0] == "gh" or (c[0] == "git" and c[1] == "push") for c in calls)
