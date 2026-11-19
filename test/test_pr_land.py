"""Contract tests for tools/pr_land.py (D-1052)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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

    def fake_run(cmd, cwd, env=None, check=True):
        calls.append(cmd)
        if cmd[:3] == ["git", "config", "--bool"]:
            return ""
        if cmd[:2] == ["git", "rev-parse"]:
            return "feat/topic" if "--abbrev-ref" in cmd else "a" * 40
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:2] == ["git", "log"]:
            return "feat: sample"
        raise AssertionError(cmd)

    monkeypatch.setattr(pr_land, "_run", fake_run)
    monkeypatch.setattr(pr_land, "required_lab_invocations", lambda cwd, base, head: [])
    assert pr_land.main(["--dry-run", "--self-review", "solo"], repo=tmp_path) == 0
    assert "dry-run branch=feat/topic" in capsys.readouterr().out
    assert not any(c[0] == "gh" or (c[0] == "git" and c[1] == "push") for c in calls)


def test_refuses_publish_only_clone_per_d868(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pr_land,
        "_run",
        lambda cmd, cwd, env=None, check=True: "true" if cmd[:3] == ["git", "config", "--bool"] else "",
    )
    with pytest.raises(SystemExit, match="rosy.publishOnly=true"):
        pr_land.check_coexistence(tmp_path, "a" * 40)


def test_ci_runnable_excludes_lab_only_omx_browser_alone_and_sim():
    assert pr_land.ci_runnable(["operations/world/test"])
    assert not pr_land.ci_runnable(["middleware/devices/omx/adapter/test"])
    assert not pr_land.ci_runnable(["ROSY_RUN_BROWSER_TESTS=1", "operations/fleet/test"])
    assert not pr_land.ci_runnable(["ROSY_JOB_ALONE=1", "test/test_platform_g1_timing.py"])
    assert not pr_land.ci_runnable(["integrations/simulation/gazebo/test"])
    assert not pr_land.ci_runnable(["test/learning/perception/test_learning_workflow_pipeline_browser.py"])


def test_lab_only_requires_intact_lab_cache_and_ci_covers_lab_ids(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "f.py")
    git("commit", "-qm", "base")
    head = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    inv = ["middleware/devices/omx/adapter/test"]

    monkeypatch.setattr(pr_land.land_cache, "env_id", lambda cwd, sha: "env1")
    with pytest.raises(SystemExit, match="requires remote_pytest lab evidence"):
        pr_land.verify_lab_evidence(tmp_path, head, [inv])

    log = tmp_path / "lab.txt"
    log.write_text("PASSED middleware/devices/omx/adapter/test/test_a.py::test_one\n1 passed in 0.2s\n", encoding="utf-8")
    digest = hashlib.sha256(log.read_bytes()).hexdigest()
    git_dir = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir"))
    (git_dir / "rosy-land-cache.jsonl").write_text(
        json.dumps({"tree": tree, "commit": head, "env": "env1", "argv": inv, "log": str(log), "log_sha256": digest}) + "\n",
        encoding="utf-8",
    )
    pr_land.verify_lab_evidence(tmp_path, head, [inv])
    assert pr_land.covers_lab_baseline(tmp_path, head, inv, "PASSED middleware/devices/omx/adapter/test/test_a.py::test_one\n")
    assert not pr_land.covers_lab_baseline(tmp_path, head, inv, "1 skipped\n")
