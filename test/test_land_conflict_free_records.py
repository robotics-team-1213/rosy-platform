"""Tests for conflict-free record shards, ci_runnable, and fast-clone bootstrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import ci_runnable  # noqa: E402
import new_record  # noqa: E402
import rosy_harness as harness  # noqa: E402
import setup_fast_clone  # noqa: E402


def _make_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tools" / "harness").mkdir(parents=True)
    (repo / "tools" / "hooks").mkdir(parents=True)
    (repo / "tools" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    (repo / "tools" / "harness" / "harness.yaml").write_text(
        "adr_log: docs/reference/ROSY ADR Log.md\nstatus: STATUS.md\n"
        "modules:\n  - {name: fleet, path: operations/fleet}\n",
        encoding="utf-8",
    )
    (repo / "docs" / "reference").mkdir(parents=True)
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "reference" / "ROSY ADR Log.md").write_text(
        "| ID | 제목 | Status |\n|---|---|---|\n| D-1 | one | Accepted |\n\n---\n\n## D-1 one\n**Status:** Accepted\n",
        encoding="utf-8",
    )
    (repo / "operations" / "fleet").mkdir(parents=True)
    (repo / "operations" / "fleet" / "progress.md").write_text(
        "---\nmodule: fleet\nlogical_modules: [M01]\nowner: FLEET\n"
        "last_verified: { commit: \"abc1234\", date: 2026-11-19 }\n"
        "gates: { SOURCE: { state: GO, evidence: 'ok', cmd: 'pytest' }, LOCAL: { state: N/A }, "
        "ROS-SIM: { state: N/A }, ARTIFACT: { state: N/A }, DEVICE: { state: N/A }, FIELD: { state: N/A } }\n"
        "adrs: [D-1]\nplans: []\n---\n",
        encoding="utf-8",
    )
    (repo / "operations" / "fleet" / "logs.md").write_text(
        "# fleet logs\n\n## 2026-11-18 · abc1234 · init\n- 변경: init\n- 증거: ok\n- gate 변화: 없음\n",
        encoding="utf-8",
    )
    harness.generate(repo)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    return repo


def test_new_record_shards_lint_and_consolidate(tmp_path):
    repo = _make_sample_repo(tmp_path)
    shard = new_record.write_log_shard(repo, "fleet", "add conflict-free log", change="shard", evidence="pytest ok", date="2026-11-19")
    assert shard.relative_to(repo).as_posix().startswith("operations/fleet/logs/2026/11/19-")
    frag = new_record.write_api_fragment(repo, "berth-status", surface="fleet", title="add berth_status field",
                                         date="2026-11-19")
    assert frag.relative_to(repo).as_posix() == "docs/reference/api-changes/berth-status.md"
    frag.unlink()  # numbering needs the API reference; test_records_fragments.py covers it

    errors, _ = harness.lint(repo)
    assert errors == []

    # Invalid shard missing gate/change fields must be flagged by lint().
    bad = repo / "operations" / "fleet" / "logs" / "2026" / "11" / "19-bad.md"
    bad.write_text("## 2026-11-19 · abc · oops\n- 변경: only\n", encoding="utf-8")
    errors, _ = harness.lint(repo)
    assert any("fleet/logs/2026/11/19-bad.md" in e for e in errors)
    bad.unlink()

    res = new_record.consolidate(repo)
    assert shard.relative_to(repo).as_posix() in res["folded"]
    assert not shard.exists()
    assert "add conflict-free log" in (repo / "operations" / "fleet" / "logs.md").read_text(encoding="utf-8")


def test_ci_runnable_separates_gha_from_h5_lab_invocations():
    assert ci_runnable.ci_runnable(["operations/fleet/test"]) is True
    assert ci_runnable.ci_runnable(["test/test_harness_contracts.py"]) is True
    assert ci_runnable.ci_runnable(["test/learning/perception/test_learning_workflow_pipeline_browser.py"]) is False
    assert ci_runnable.ci_runnable(["test"]) is True and ci_runnable.ci_runnable(["test/learning"]) is True
    assert ci_runnable.ci_runnable(["middleware/devices/omx/adapter/test"]) is False
    assert ci_runnable.ci_runnable(["integrations/simulation/gazebo/test"]) is False
    assert ci_runnable.ci_runnable(["ROSY_RUN_BROWSER_TESTS=1", "test/test_x.py"]) is False
    assert ci_runnable.ci_runnable(["ROSY_JOB_ALONE=1", "test/test_platform_g1_timing.py"]) is False


def test_setup_fast_clone_configures_repo_and_removes_graphify_hooks(tmp_path):
    repo = _make_sample_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "post-merge"
    hook.write_text("#!/bin/sh\ngraphify update .\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(repo), "config", "rosy.publishOnly", "true"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "merge.graphify.driver", "true"], check=True)

    setup_fast_clone.configure_clone(repo)
    assert not hook.exists()
    assert (repo / ".git" / "hooks" / "pre-push").is_file()
    cfg = subprocess.run(["git", "-C", str(repo), "config", "--list"], capture_output=True, text=True, check=True).stdout
    assert "rosy.staticprepush=true" in cfg.lower()
    assert "rosy.publishonly" not in cfg.lower()
    assert "merge.graphify" not in cfg.lower()


def test_refresh_generated_docs_workflow_contract():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "refresh-generated-docs.yml").read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))
    assert {"cron": "0 3,15 * * *"} in triggers["schedule"]
    assert triggers["push"] == {"branches": ["main"]}  # D-1061: the bot numbers fragments after each merge
    assert wf["concurrency"] == {"group": "rosy-refresh-generated-docs", "cancel-in-progress": False}
    assert "ci-result" not in wf["jobs"]
    # D-1061: GITHUB_TOKEN PRs start no pull_request CI, so PRs come only from the RECORDS_BOT_TOKEN secret
    job = wf["jobs"]["consolidate"]
    assert wf["permissions"] == {"contents": "read"}
    assert job["env"]["RECORDS_BOT_TOKEN"] == "${{ secrets.RECORDS_BOT_TOKEN }}"
    steps = {s.get("name"): s for s in job["steps"]}
    pr_step = steps["Open or update consolidation PR"]
    assert pr_step["if"] == "env.RECORDS_BOT_TOKEN != ''"
    assert pr_step["env"]["GH_TOKEN"] == "${{ env.RECORDS_BOT_TOKEN }}"
    app = steps["Mint records bot App token"]
    assert app["if"] == "vars.RECORDS_BOT_CLIENT_ID != ''" and app["uses"].startswith("actions/create-github-app-token@")
    assert app["with"] == {"client-id": "${{ vars.RECORDS_BOT_CLIENT_ID }}", "private-key": "${{ secrets.RECORDS_BOT_PRIVATE_KEY }}"}
    assert "repositories" not in app["with"]  # the token defaults to this repository only
    assert steps["Use the App token"]["if"] == "steps.app.outputs.token != ''"
    script = pr_step["run"]
    assert 'gh pr merge "$pr" --auto --merge --match-head-commit "$head"' in script  # pr_land.py's queue call
    assert script.count("gh pr create") == 1 and "gh pr list --head bot/records-refresh --state open" in script
    assert "gh workflow run" not in script and "github.token" not in str(pr_step)
    assert pr_step["env"]["EVENT_NAME"] == "${{ github.event_name }}"
    assert "gh api graphql" in script and "isInMergeQueue" in script and "ci.yml/runs" in script
    assert script.index("isInMergeQueue") < script.index("git push -f")
    report = steps["Report pending records (no RECORDS_BOT_TOKEN)"]
    assert report["if"] == "env.RECORDS_BOT_TOKEN == ''"
    assert "GITHUB_STEP_SUMMARY" in report["run"] and "git push" not in report["run"]
