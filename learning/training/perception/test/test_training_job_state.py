"""Crash/retry and output integrity, without GPU or device actions."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from job_state import Job, JobError, Rejected, receipt  # noqa: E402


def test_failed_step_retries_without_repeating_valid_completed_step(tmp_path):
    calls = []
    job = Job(tmp_path / "job", {"dataset": "sha"})

    def prepare(attempt):
        calls.append("prepare")
        path = tmp_path / "input"
        path.write_text("immutable")
        return receipt({"value": 1}, [path])

    def broken(attempt):
        calls.append("broken")
        raise RuntimeError("interrupted")

    with job:
        job.step("prepare", prepare)
        with pytest.raises(RuntimeError):
            job.step("train", broken)
    resumed = Job(tmp_path / "job", {"dataset": "sha"})
    with resumed:
        assert resumed.step("prepare", prepare)["value"] == 1
        assert resumed.step("train", lambda attempt: receipt({"attempt": attempt}))["attempt"] == 2
    assert calls == ["prepare", "broken"]


def test_completed_output_tamper_and_changed_inputs_refused(tmp_path):
    path = tmp_path / "model"
    path.write_text("weights")
    with Job(tmp_path / "job", {"dataset": "a"}) as job:
        job.step("export", lambda attempt: receipt({}, [path]))
    with pytest.raises(JobError, match="inputs"):
        Job(tmp_path / "job", {"dataset": "b"})
    path.write_text("changed")
    with Job(tmp_path / "job", {"dataset": "a"}) as job:
        with pytest.raises(JobError, match="output"):
            job.step("export", lambda attempt: pytest.fail("must not overwrite"))


def test_rejection_is_terminal_and_never_runs_ready(tmp_path):
    def reject(attempt):
        raise Rejected("quality floor")
    with Job(tmp_path / "job", {}) as job:
        with pytest.raises(Rejected):
            job.step("intake", reject)
        with pytest.raises(Rejected):
            job.step("ready", lambda attempt: pytest.fail("READY forbidden"))
    with Job(tmp_path / "job", {}) as job:
        with pytest.raises(Rejected):
            job.step("intake", lambda attempt: pytest.fail("rejected is terminal"))


def test_live_job_lock_refuses_second_writer(tmp_path):
    first = Job(tmp_path / "job", {})
    with first:
        with pytest.raises(JobError, match="running"):
            with Job(tmp_path / "job", {}):
                pass
