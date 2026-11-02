"""Account starts independently of the Fleet distribution or its import bootstrap."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_account_import_does_not_require_fleet():
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(str(ROOT / p) for p in (
        'operations/account', 'contracts/foundation'))}
    result = subprocess.run([sys.executable, '-c',
        'import sys; import rosy_account.app; '
        'assert not any(m == "fleet" or m.startswith("fleet.") for m in sys.modules)'],
        cwd=ROOT / 'operations/account', env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
