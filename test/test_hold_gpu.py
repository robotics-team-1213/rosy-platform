"""D-866 §4: hold_gpu.sh leaves a `gpu` lock that host_probe counts while the job runs and drops after."""
import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/remote/hold_gpu.sh"


def test_the_lock_names_the_job_itself(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    seen = subprocess.run(["bash", str(SCRIPT), "4", "12", "bash", "-c", 'echo $$; cat ~/rosy-jobs/*.lock'],
                          env=env, capture_output=True, text=True, check=True).stdout.split("\n")
    assert re.fullmatch(r"\d+ gpu 4 12", seen[1])
    assert seen[1].split()[0] == seen[0]  # exec: the lock's pid is the job's, so it dies with the job


def test_it_refuses_a_budget_that_is_not_whole_numbers(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(["bash", str(SCRIPT), "4", "$(reboot)", "true"], env=env, capture_output=True, text=True)
    assert result.returncode == 2 and not (tmp_path / "rosy-jobs").exists()
