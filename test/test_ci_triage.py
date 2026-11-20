"""tools/harness/ci_triage.py: replay of PR #247 (run 44516702259) logs, 2026-11-19.

Attempts 1-2: 25 shards died in 'apt-get' at Install colcon & tools (infra). Attempt 3: the omx_cell assertion and a
segfault in the Test step (real). Fixture: test/fixtures/ci_triage/pr247_run44516702259.json (trimmed real excerpts).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "harness"))

import ci_triage as ct  # noqa: E402

FX = json.loads((ROOT / "test" / "fixtures" / "ci_triage" / "pr247_run44516702259.json").read_text(encoding="utf-8"))
SHA = FX["head_sha"]
RUN = 44516702259


class FakeGh:
    """The few GitHub endpoints ci_triage reads; calls are recorded, run state can be changed per test."""

    def __init__(self, jobs: list[tuple[dict, str]], *, attempt: int = 1, sha: str = SHA, newest: int = RUN):
        self.jobs = jobs
        self.logs = {j["id"]: log for j, log in jobs}
        self.run = {"id": RUN, "run_attempt": attempt, "head_sha": sha, "status": "completed",
                    "conclusion": "failure", "event": "pull_request",
                    "repository": {"full_name": "robotics-team-1213/rosy-platform"}}
        self.newest = newest
        self.calls: list[tuple] = []
        self.rerun_error = False

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("repo", "view"):
            return "o/r\n"
        if args[:2] == ("run", "rerun"):
            if self.rerun_error:
                raise RuntimeError("HTTP 403: Resource not accessible")
            return ""
        path = args[-1]
        if path.endswith(f"/actions/runs/{RUN}"):
            return json.dumps(self.run)
        if "/attempts/" in path and path.endswith("/jobs?per_page=100"):
            return json.dumps({"jobs": [j for j, _ in self.jobs] + [FX["ci_result"]]})
        if "/actions/jobs/" in path and path.endswith("/logs"):
            return self.logs[int(path.split("/")[-2])]
        if "/workflows/ci.yml/runs?head_sha=" in path:
            return json.dumps({"workflow_runs": [{"id": self.newest, "head_sha": self.run["head_sha"]},
                                                 {"id": RUN - 5, "head_sha": self.run["head_sha"]}]})
        raise AssertionError(f"unexpected gh call {args}")

    def reruns(self) -> list[tuple]:
        return [c for c in self.calls if c[:2] == ("run", "rerun")]


def _shards(sample: str, count: int, first: int = 1000) -> list[tuple[dict, str]]:
    out = []
    for n in range(count):
        job = copy.deepcopy(FX[sample]["job"])
        job["id"], job["name"] = first + n, f"test (affected-{n + 1})"
        out.append((job, FX[sample]["log"]))
    return out


def _handle(gh: FakeGh, tmp_path: Path, **kw):
    return ct.handle(gh, "o/r", RUN, ledger=tmp_path / ct.LEDGER, expected_sha=kw.pop("expected_sha", SHA), now=1000, **kw)


def test_25_shards_failing_in_apt_at_install_are_infra_and_rerun_once(tmp_path):
    gh = FakeGh(_shards("apt_install", 25))
    result = _handle(gh, tmp_path)
    assert result["category"] == "infra" and result["action"] == "rerun"
    assert gh.reruns() == [("run", "rerun", str(RUN), "--failed", "--repo", "o/r")]
    rows = ct.read_ledger(tmp_path / ct.LEDGER)
    assert len(rows) == 25 and {r["category"] for r in rows} == {"infra"} and {r["action"] for r in rows} == {"rerun"}
    assert rows[0]["step"] == "Install colcon & tools" and "Failed to fetch" in rows[0]["signature"]
    assert {"t", "repo", "workflow", "event", "head_sha", "run_id", "attempt", "job", "step", "category",
            "signature", "action"} <= rows[0].keys()
    assert "ci-result" not in {r["job"] for r in rows}
    # the same attempt asked again (the 15 minute merge task) neither rereads logs nor reruns
    again = _handle(gh, tmp_path)
    assert again["action"] == "seen" and len(gh.reruns()) == 1


def test_the_rerun_that_fails_the_same_way_is_not_rerun_again(tmp_path):
    shards = _shards("apt_install", 3)
    assert _handle(FakeGh(shards), tmp_path)["action"] == "rerun"
    second = FakeGh(shards, attempt=2)
    result = _handle(second, tmp_path)
    assert result["action"] == "none" and "already had its 1 rerun" in result["reason"] and second.reruns() == []


def test_the_omx_cell_assertion_and_the_segfault_in_the_test_step_are_real_failures(tmp_path):
    gh = FakeGh([(FX["assertion_test"]["job"], FX["assertion_test"]["log"]), (FX["segfault_test"]["job"], FX["segfault_test"]["log"])],
                attempt=3)
    result = _handle(gh, tmp_path)
    assert result["category"] == "real_failure" and result["action"] == "none" and gh.reruns() == []
    sigs = {r["job"]: r["signature"] for r in result["rows"]}
    assert "test_omx_cell_frame" in sigs["test (affected-25)"] and "Segmentation fault" in sigs["test (affected-23)"]
    assert "[FAILED] PASSED" not in "".join(sigs.values())  # a parametrised test id is not a failure


def test_one_test_failure_among_infra_failures_blocks_the_rerun(tmp_path):
    gh = FakeGh(_shards("apt_install", 3) + _shards("assertion_test", 1, first=2000))
    result = _handle(gh, tmp_path)
    assert result["category"] == "real_failure" and result["action"] == "none" and gh.reruns() == []
    assert "not every causing job" in result["reason"]


def test_a_stale_sha_or_a_newer_run_is_never_rerun(tmp_path):
    moved = FakeGh(_shards("apt_install", 2))
    assert "stale" in _handle(moved, tmp_path, expected_sha="f" * 40)["reason"] and moved.reruns() == []
    newer = FakeGh(_shards("apt_install", 2), newest=RUN + 9)
    assert "newer run" in _handle(newer, tmp_path / "b")["reason"] and newer.reruns() == []


def test_two_reruns_per_sha_and_workflow_is_the_cap(tmp_path):
    ledger = tmp_path / ct.LEDGER
    for other in (RUN - 1, RUN - 2):  # earlier runs of the same sha and workflow, each already rerun once
        ct.append_ledger(ledger, [{"run_id": other, "attempt": 1, "job": "x", "head_sha": SHA, "workflow": "ci.yml",
                                   "category": "infra", "action": "rerun"}])
    gh = FakeGh(_shards("apt_install", 2))
    result = _handle(gh, tmp_path)
    assert result["action"] == "none" and "2 reruns already" in result["reason"] and gh.reruns() == []


def test_a_refused_rerun_stays_red_and_is_recorded(tmp_path):
    gh = FakeGh(_shards("apt_install", 1))
    gh.rerun_error = True
    result = _handle(gh, tmp_path)
    assert result["action"] == "none" and result["reason"].startswith("rerun refused")
    assert ct.read_ledger(tmp_path / ct.LEDGER)[0]["action"].startswith("blocked: rerun refused")


def test_classification_follows_the_failing_step_and_the_signature():
    install = {"name": "j", "steps": [{"name": "Install colcon & tools", "conclusion": "failure"}]}
    assert ct.classify(install, "x\n##[group]Run pip\nTemporary failure resolving 'pypi.org'\n##[error]exit 1")["category"] == "infra"
    assert ct.classify(install, "##[group]Run pip\nERROR: HTTP error 503 while getting x\n##[error]x")["category"] == "infra"
    assert ct.classify(install, "##[group]Run pip\nResolutionImpossible: conflict\nConnection timed out\n##[error]x")["category"] == "env_drift"
    assert ct.classify(install, "##[group]Run pip\nsomething else broke\n##[error]x")["category"] == "real_failure"
    assert ct.classify(install, None)["category"] == "real_failure"
    # a retried-and-fine warning in an earlier step does not turn a later failure into infra
    assert ct.classify(install, "W: Failed to fetch x\n##[group]Run other\nboom\n##[error]x")["category"] == "real_failure"
    setup = {"name": "j", "steps": [{"name": "Set up job", "conclusion": "failure"}]}
    assert ct.classify(setup, "The runner has lost communication with the server")["category"] == "infra"
    test = {"name": "j", "steps": [{"name": "Test (matrix suite, D-436)", "conclusion": "failure"}]}
    for log in ("Failed to fetch http://x Connection timed out", "collected 0 items", "ERROR collecting x", ""):
        assert ct.classify(test, log)["category"] == "real_failure"
    assert ct.classify({"name": "j", "steps": []}, "Failed to fetch")["category"] == "real_failure"


def test_backlog_lines_name_red_runs_for_a_person_and_stay_empty_otherwise(tmp_path):
    ledger = tmp_path / ct.LEDGER
    assert ct.backlog_lines(ledger, 2000) == []
    gh = FakeGh([(FX["assertion_test"]["job"], FX["assertion_test"]["log"])], attempt=3)
    ct.handle(gh, "o/r", RUN, ledger=ledger, expected_sha=SHA, now=1000)
    lines = ct.backlog_lines(ledger, 2000)
    assert "(ALERT)" in lines[0] and f"run {RUN}#3 real_failure" in lines[1]
    assert ct.backlog_lines(ledger, 1000 + 25 * 3600) == []
    assert any("real_failure" in line for line in ct.describe(ct.handle(gh, "o/r", RUN, ledger=ledger, expected_sha=SHA), RUN))
