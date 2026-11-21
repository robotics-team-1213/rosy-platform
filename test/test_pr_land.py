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


@pytest.fixture(autouse=True)
def _normal_cutover(monkeypatch):
    monkeypatch.setattr(pr_land.land_freeze, "load", lambda cwd: {"phase": "normal", "allow": []})
    monkeypatch.setattr(pr_land.land_freeze, "path", lambda cwd: Path("rosy-cutover.json"))
    monkeypatch.setattr(pr_land, "preflight", lambda cwd, base: None)  # its own test below


@pytest.mark.parametrize("phase,refused", [("drain", True), ("open", False), ("normal", False)])
def test_cutover_phase_gates_submission(monkeypatch, tmp_path, phase, refused):
    state = {"phase": phase, "allow": [], "owner": "coordinator"}
    monkeypatch.setattr(pr_land.land_freeze, "load", lambda cwd: state)
    msg = pr_land.cutover_refusal(tmp_path)
    assert (msg is not None) == refused
    if refused:
        assert "drain" in msg and "coordinator" in msg and "rosy-cutover.json" in msg


def test_drain_refuses_real_run_but_dry_run_prints_reason(monkeypatch, tmp_path, capsys):
    def fake_run(cmd, cwd, env=None, check=True):
        if cmd[:2] == ["git", "rev-parse"]:
            return "feat/topic" if "--abbrev-ref" in cmd else "a" * 40
        if cmd[:2] == ["git", "status"]:
            return ""
        if cmd[:2] == ["git", "log"]:
            return "feat: sample"
        if cmd[:3] == ["git", "config", "--bool"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(pr_land, "_run", fake_run)
    monkeypatch.setattr(pr_land, "check_coexistence", lambda *a, **kw: "origin/main")
    monkeypatch.setattr(pr_land, "required_lab_invocations", lambda *a: [])
    monkeypatch.setattr(pr_land.land_freeze, "load", lambda cwd: {"phase": "drain", "allow": [], "owner": "coordinator"})
    with pytest.raises(SystemExit, match="drain"):
        pr_land.main(["--title", "T"], repo=tmp_path)
    assert pr_land.main(["--dry-run"], repo=tmp_path) == 0
    out = capsys.readouterr().out
    assert "phase drain" in out and "gh pr merge --auto" in out


def test_build_body_appends_self_overlap_review():
    assert "Overlap-Review: self (coordinated)" in pr_land.build_body("summary", "coordinated")
    assert "Overlap-Review:" not in pr_land.build_body("summary", "")


def test_build_body_appends_session_line(monkeypatch):
    for env, name in (("ROSY_SESSION_NAME", "opencode-1"), ("CLAUDE_SESSION_NAME", "claude-x")):
        monkeypatch.delenv("ROSY_SESSION_NAME", raising=False)
        monkeypatch.delenv("CLAUDE_SESSION_NAME", raising=False)
        monkeypatch.setenv(env, name)
        assert pr_land.build_body("s", "r").rstrip().endswith(f"Session: {name}")
    monkeypatch.delenv("ROSY_SESSION_NAME", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_NAME", raising=False)
    assert pr_land.build_body("s", "").rstrip().endswith("Session: unknown")


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
    out = capsys.readouterr().out
    assert "dry-run branch=feat/topic" in out
    assert "gh pr merge --auto --merge --match-head-commit " + "a" * 40 in out
    assert not any(c[0] == "gh" or (c[0] == "git" and c[1] == "push") for c in calls)


def test_enqueues_only_the_verified_head(monkeypatch, tmp_path):
    head = "a" * 40
    calls = []

    def fake_run(cmd, cwd, env=None, check=True):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return "fix/topic" if "--abbrev-ref" in cmd else head
        if cmd[:2] in (["git", "status"], ["git", "push"], ["git", "config"]):
            return ""
        if cmd[:3] == ["gh", "pr", "list"]:
            return '[{"number": 42}]'
        if cmd[:4] == ["gh", "pr", "merge", "42"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(pr_land, "_run", fake_run)
    monkeypatch.setattr(pr_land, "check_coexistence", lambda *a, **kw: "origin/main")
    monkeypatch.setattr(pr_land, "required_lab_invocations", lambda *a: [])

    assert pr_land.main(["--title", "Test"], repo=tmp_path) == 0
    assert ["gh", "pr", "merge", "42", "--auto", "--merge", "--match-head-commit", head] in calls


def test_refuses_publish_only_clone_per_d868(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pr_land,
        "_run",
        lambda cmd, cwd, env=None, check=True: "true" if cmd[:4] == ["git", "config", "--bool", "rosy.publishOnly"] else "",
    )
    with pytest.raises(SystemExit, match="rosy.publishOnly=true"):
        pr_land.check_coexistence(tmp_path, "a" * 40)


def test_publish_only_clone_allowed_once_activated(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pr_land,
        "_run",
        lambda cmd, cwd, env=None, check=True: "true" if cmd[:3] == ["git", "config", "--bool"] else "origin-main-sha",
    )
    assert pr_land.activated(tmp_path)
    assert pr_land.check_coexistence(tmp_path, "a" * 40) == "origin-main-sha"


def test_activated_by_accepted_adr_only(monkeypatch, tmp_path):
    monkeypatch.setattr(pr_land, "_run", lambda cmd, cwd, env=None, check=True: "")
    adr = tmp_path / "docs/adr"
    adr.mkdir(parents=True)
    (adr / "D-1055-x.md").write_text("**Status:** Proposed (x)\n", encoding="utf-8")
    assert not pr_land.activated(tmp_path)
    (adr / "D-1055-x.md").write_text("**Status:** Accepted (x)\n", encoding="utf-8")
    assert pr_land.activated(tmp_path)


def test_refuses_missing_base_instead_of_head_caret(monkeypatch, tmp_path):
    monkeypatch.setattr(pr_land, "_run", lambda cmd, cwd, env=None, check=True: "")
    with pytest.raises(SystemExit, match="neither origin/main nor main"):
        pr_land.check_coexistence(tmp_path, "a" * 40)


def test_ci_runnable_excludes_lab_only_omx_browser_alone_and_sim():
    assert pr_land.ci_runnable(["operations/world/test"])
    assert not pr_land.ci_runnable(["middleware/devices/omx/adapter/test"])
    assert not pr_land.ci_runnable(["ROSY_RUN_BROWSER_TESTS=1", "operations/fleet/test"])
    assert not pr_land.ci_runnable(["ROSY_JOB_ALONE=1", "test/test_platform_g1_timing.py"])
    assert not pr_land.ci_runnable(["integrations/simulation/gazebo/test"])
    assert not pr_land.ci_runnable(["test/learning/perception/test_learning_workflow_pipeline_browser.py"])
    # 2026-11-21: a folder above the lab-only file is CI's root-test. Counted as lab evidence, the whole root suite
    # (18,847 tests, 37 min) ran on a lab PC for every selection that fell back to `test`. Placement still refuses it.
    for folder in ("test", "test/learning", "test/learning/perception"):
        assert pr_land.ci_runnable([folder]) and pr_land.ci_runnable(["--ignore=test/test_platform_g1_timing.py", folder])
        assert pr_land.work_queue.lab_only([folder]) and not pr_land.work_queue.lab_only([folder], above=False)
        assert not pr_land.ci_runnable(["ROSY_RUN_BROWSER_TESTS=1", folder])


def _required(monkeypatch, invs, changed=()):
    monkeypatch.setattr(pr_land, "_run", lambda cmd, cwd, **k: json.dumps({"mode": "x", "invocations": invs}) if "affected" in cmd else "\n".join(changed))
    return pr_land.required_lab_invocations(Path("."), "b", "h")


def test_mixed_ci_entries_need_no_lab_but_omx_and_browser_parts_stay(monkeypatch):
    mixed = ["middleware/core/gateway/test", "operations/overhead/test", "test/architecture"]
    assert _required(monkeypatch, [mixed]) == []
    omx = ["middleware/devices/omx/adapter/test"]
    assert _required(monkeypatch, [mixed + omx]) == [omx]
    brow = "test/learning/perception/test_learning_workflow_pipeline_browser.py"
    assert _required(monkeypatch, [mixed + [brow]]) == [[brow]]
    assert _required(monkeypatch, [["ROSY_RUN_BROWSER_TESTS=1"] + mixed]) != []


def test_what_this_prs_own_ci_run_executes_is_not_lab_evidence(monkeypatch):
    """2026-11-21: one UI PR spent 2 to 2.5 h per lab run, mostly on tests its pull_request run executes anyway."""
    media = ["middleware/media/test"]  # a selector suite no full-matrix entry names
    assert pr_land.ci_entry(media) is None and not pr_land.ci_runnable(media) and pr_land.ci_runnable(media, selected=True)
    assert _required(monkeypatch, [media]) == []
    assert not pr_land.ci_runnable(["middleware/perception/test"], selected=True), "a non-gating root stays lab evidence"
    monkeypatch.setattr(pr_land, "_run", lambda cmd, cwd, **k: json.dumps({"mode": "full", "local_invocations": [media]})
                        if "affected" in cmd else "")
    assert pr_land.required_lab_invocations(Path("."), "b", "h") == [media], "a FULL selection is not run per invocation"

    browser, alone = "ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1"
    fleet, other = "operations/fleet/test/test_fleet_header_browser.py", "shared/web/test/test_x_browser.py"
    assert pr_land.lab_browser_chunk([browser, fleet, other], ["operations/fleet/test"]) == [browser, other]
    assert pr_land.lab_browser_chunk([browser, fleet], [fleet]) == []
    assert pr_land.lab_browser_chunk([browser, fleet], ["operations/world/test"]) == [browser, fleet], "not in this PR's CI run"
    site_map = "operations/fleet/test/test_site_map_browser.py"
    assert pr_land.lab_browser_chunk([browser, alone, site_map], ["operations/fleet/test"]) == [browser, alone, site_map]
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'p.startswith(("%s", "%s"))' % pr_land.CI_BROWSER_ROOTS in workflow, "ci.yml opts these roots in to Chromium itself"


def test_preflight_runs_the_trailer_and_size_checks_and_stops_on_either(monkeypatch):
    seen = []
    monkeypatch.undo()  # the autouse fixture stubs preflight for the other tests
    monkeypatch.setattr(pr_land, "_run", lambda cmd, cwd, **k: seen.append(cmd[1:]))
    pr_land.preflight(Path("."), "origin/main")
    assert seen == [["tools/harness/safety_review.py", "origin/main", "HEAD"], ["tools/harness/size_range.py", "origin/main", "HEAD"]]

    def refuse(cmd, cwd, **k):
        raise SystemExit("no Safety-Review trailer")
    monkeypatch.setattr(pr_land, "_run", refuse)
    with pytest.raises(SystemExit):
        pr_land.preflight(Path("."), "origin/main")


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


def test_lab_evidence_accepts_all_skipped_log_only(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "f.py")
    git("commit", "-qm", "base")
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    inv = ["middleware/robot_execution/local/test/test_policy_runtime_ros.py"]
    monkeypatch.setattr(pr_land.land_cache, "env_id", lambda cwd, sha: "env1")
    cache = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "rosy-land-cache.jsonl"

    def row(text):
        log = tmp_path / "lab.txt"
        log.write_text(text, encoding="utf-8")
        cache.write_text(json.dumps({"tree": tree, "commit": head, "env": "env1", "argv": inv, "log": str(log),
                                     "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}) + "\n", encoding="utf-8")

    row("SKIPPED [1] x.py:3: no rclpy\n== 1 skipped in 0.10s ==\n")
    pr_land.verify_lab_evidence(tmp_path, head, [inv])
    row("no tests ran in 0.01s\n")
    with pytest.raises(SystemExit, match="requires remote_pytest lab evidence"):
        pr_land.verify_lab_evidence(tmp_path, head, [inv])


def _push_fake(monkeypatch, tmp_path, *, publish_only, active, lab=()):
    head = "a" * 40
    calls = []

    def fake_run(cmd, cwd, env=None, check=True):
        calls.append((cmd, env))
        if cmd[:2] == ["git", "rev-parse"]:
            return "fix/topic" if "--abbrev-ref" in cmd else head
        if cmd[:3] == ["git", "config", "--bool"]:
            return "true" if cmd[3] == "rosy.publishOnly" and publish_only else ""
        if cmd[:2] in (["git", "status"], ["git", "push"], ["git", "log"]):
            return ""
        if cmd[:3] == ["gh", "pr", "list"]:
            return '[{"number": 7}]'
        if cmd[:3] == ["gh", "pr", "merge"]:
            return ""
        raise AssertionError(cmd)

    monkeypatch.setattr(pr_land, "_run", fake_run)
    monkeypatch.setattr(pr_land, "activated", lambda cwd: active)
    monkeypatch.setattr(pr_land, "check_coexistence", lambda *a, **kw: "origin/main")
    monkeypatch.setattr(pr_land, "required_lab_invocations", lambda *a: [list(i) for i in lab])
    monkeypatch.setattr(pr_land, "verify_lab_evidence", lambda *a: calls.append((["verify"], None)))
    return calls


@pytest.mark.parametrize("publish_only,active,expect", [(True, True, True), (True, False, False), (False, True, False)])
def test_push_env_carries_reason_only_when_publish_only_and_activated(monkeypatch, tmp_path, publish_only, active, expect):
    monkeypatch.setenv("ROSY_SESSION_NAME", "sess1")
    monkeypatch.delenv("ROSY_PUSH_REASON", raising=False)
    calls = _push_fake(monkeypatch, tmp_path, publish_only=publish_only, active=active)
    assert pr_land.main([], repo=tmp_path) == 0
    push_env = next(env for cmd, env in calls if cmd[:2] == ["git", "push"])
    assert push_env.get("ROSY_PUSH_REASON") == ("pr_land D-1055 sess1" if expect else None)
    assert "ROSY_PUSH_REASON" not in pr_land.os.environ


def test_evidence_flag_runs_pr_evidence_before_verify(monkeypatch, tmp_path):
    inv = ["middleware/devices/omx/adapter/test"]
    calls = _push_fake(monkeypatch, tmp_path, publish_only=False, active=False, lab=[inv])
    monkeypatch.setattr(pr_land, "preflight", lambda cwd, base: calls.append((["preflight", base], None)))
    fake = type(sys)("pr_evidence")
    fake.main = lambda argv, repo=None: calls.append((["evidence", *argv], None)) or 0
    monkeypatch.setitem(sys.modules, "pr_evidence", fake)
    assert pr_land.main(["--evidence", "--dry-run"], repo=tmp_path) == 0
    order = [c[0][0] for c in calls if c[0][0] in ("evidence", "verify")]
    assert order == ["evidence", "verify"]
    # 2026-11-21: the trailer and size checks stop a doomed push before the lab run, not after it
    names = [c[0][0] for c in calls]
    assert names.index("preflight") < names.index("evidence")
    calls.clear()
    assert pr_land.main(["--dry-run"], repo=tmp_path) == 0
    assert [c[0][0] for c in calls if c[0][0] == "evidence"] == []


def test_local_main_only_behind_origin_is_not_a_backlog(tmp_path):
    """robot-17 11-20: local main behind origin/main (nothing unpublished) is an ancestor of HEAD but no backlog."""
    import subprocess as sp

    def git(*a):
        return sp.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "a")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("commit", "-q", "--allow-empty", "-m", "b")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("reset", "-q", "--hard", "HEAD~1")  # local main behind origin/main
    git("checkout", "-q", "-b", "topic", "origin/main")
    git("commit", "-q", "--allow-empty", "-m", "c")
    head = git("rev-parse", "HEAD")
    assert pr_land.check_coexistence(tmp_path, head) == git("rev-parse", "origin/main")
    git("checkout", "-q", "main")
    git("commit", "-q", "--allow-empty", "-m", "unpublished")  # now local main has a commit origin lacks
    git("checkout", "-q", "-b", "topic2")
    with pytest.raises(SystemExit):
        pr_land.check_coexistence(tmp_path, git("rev-parse", "HEAD"))
