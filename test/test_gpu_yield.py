"""A long GPU job gives its hold_gpu lock back while an alone test waits, and a round's training resumes from its checkpoint."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/remote"))
sys.path.insert(0, str(ROOT / "tools/sim"))
import gpu_yield  # noqa: E402

pytest.importorskip("fcntl")


def dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_only_live_alone_waiters_and_alone_locks_count(tmp_path):
    (tmp_path / "1.alone-wait").write_text(f"{dead_pid()}\n")
    (tmp_path / "x.7.lock").write_text(f"{os.getpid()} pytest 2 6\n")
    assert not gpu_yield.alone_waiting(tmp_path) and not gpu_yield.alone_running(tmp_path)
    (tmp_path / "2.alone-wait").write_text(f"{os.getpid()}\n")
    (tmp_path / "y.1.lock").write_text(f"{os.getpid()} alone 2 6\n")
    assert gpu_yield.alone_waiting(tmp_path) and gpu_yield.alone_running(tmp_path)


def test_the_lock_goes_aside_until_no_alone_job_waits_or_runs(tmp_path):
    lock = tmp_path / "train-42.lock"
    lock.write_text("42 gpu 8 16\n")
    assert gpu_yield.yield_turn(tmp_path, pid=42, sleep=lambda s: None) == 0  # nobody waits: keep going
    waiter = tmp_path / "9.alone-wait"
    waiter.write_text(f"{os.getpid()}\n")
    seen = []

    def sleep(_):
        seen.append(lock.exists())
        if len(seen) == 1:  # the alone job is admitted: its wait marker becomes a lock
            waiter.unlink()
            (tmp_path / "a.1.lock").write_text(f"{os.getpid()} alone 2 6\n")
        elif len(seen) == 2:
            (tmp_path / "a.1.lock").unlink()
    gpu_yield.yield_turn(tmp_path, pid=42, sleep=sleep, say=lambda *a, **k: None)
    assert seen == [False, False] and lock.read_text() == "42 gpu 8 16\n"


def test_a_round_trainer_stops_at_a_checkpoint_for_a_waiting_test_and_resumes(tmp_path, monkeypatch):
    import omx_two_arm_policy as policy
    jobs, out = tmp_path / "jobs", tmp_path / "train"
    jobs.mkdir()
    (jobs / "9.alone-wait").write_text(f"{os.getpid()}\n")
    monkeypatch.setattr(gpu_yield, "JOBS", jobs)
    monkeypatch.setattr(policy, "TRAIN_POLL_S", 0.1)
    fake = tmp_path / "lerobot-train"
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f"""
        import os, sys, time
        out = {str(out)!r}
        if "--resume=true" in sys.argv:
            open(out + "/resumed", "w").write(" ".join(sys.argv[1:]))
            sys.exit(0)
        os.makedirs(out + "/checkpoints/000010/pretrained_model")
        os.makedirs(out + "/checkpoints/000020/pretrained_model")
        os.symlink("000020", out + "/checkpoints/last")
        time.sleep(60)
        """))
    fake.chmod(0o755)
    with open(tmp_path / "round.log", "w") as log:
        policy.train([str(fake)], out, str(fake), log, dict(os.environ))
    assert "config_path=" + str(out / "checkpoints/last/pretrained_model/train_config.json") in (out / "resumed").read_text()
    assert sorted(p.name for p in (out / "checkpoints").iterdir()) == ["000020", "last"]  # the older checkpoint went


def test_a_failed_trainer_still_fails_the_round(tmp_path, monkeypatch):
    import omx_two_arm_policy as policy
    monkeypatch.setattr(gpu_yield, "JOBS", tmp_path)
    monkeypatch.setattr(policy, "TRAIN_POLL_S", 0.1)
    with open(tmp_path / "round.log", "w") as log, pytest.raises(subprocess.CalledProcessError):
        policy.train([sys.executable, "-c", "raise SystemExit(3)"], tmp_path / "train", "unused", log, dict(os.environ))
