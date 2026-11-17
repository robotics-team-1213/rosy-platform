"""Real LeRobot 0.4.4 round trip of the two-arm export and its weighted mix, in the pinned learner venv (skips where there is none)."""
from pathlib import Path
import subprocess

import pytest

HOST_CAPABILITIES = ('learner_venv',)  # remote_pytest places this file only on hosts with the pinned learner venv
PYTHON = Path.home() / '.local/share/rosy-learning-center/venv-cpu/bin/python'


def test_export_readback_and_weighted_aggregation_in_the_learner_venv(tmp_path):
    if not PYTHON.is_file():
        pytest.skip('no pinned learner venv on this host')
    done = subprocess.run([str(PYTHON), '-I', '-B', str(Path(__file__).with_name('two_arm_lerobot_check.py')), str(tmp_path)],
                          capture_output=True, text=True, timeout=900)
    assert done.returncode == 0 and done.stdout.strip().endswith('OK'), done.stdout[-2000:] + done.stderr[-4000:]
