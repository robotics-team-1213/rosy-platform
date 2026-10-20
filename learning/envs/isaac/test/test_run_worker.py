"""Real child execution is bounded independently of SDK availability."""
import importlib
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    assert (ROOT / 'run_worker.py').is_file(), 'Bounded SDK worker is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_worker')


def run(tmp_path, code, **kwargs):
    return module().supervise([sys.executable, '-c', code], cwd=tmp_path, env=None,
        descriptors=(), output=tmp_path, stop_requested=lambda: False, **kwargs)


def test_process_exit_does_not_claim_import_success(tmp_path):
    row = run(tmp_path, "print('finished')", timeout=2)
    assert row['exit_code'] == 0
    assert 'import_verified' not in row
    assert (tmp_path / 'sdk.log').read_text().strip() == 'finished'


def test_timeout_and_stop_reap_the_owned_child(tmp_path):
    start = time.monotonic()
    row = run(tmp_path, 'import time; time.sleep(20)', timeout=0.1)
    assert row['reason'] == 'runtime_limit'
    assert row['exit_code'] != 0
    assert time.monotonic() - start < 4
    other = tmp_path / 'stop'
    other.mkdir()
    row = module().supervise([sys.executable, '-c', 'import time;time.sleep(20)'], cwd=other,
        env=None, descriptors=(), output=other, timeout=5, stop_requested=lambda: True)
    assert row['reason'] == 'stop_requested'


def test_output_limit_and_linked_outputs_refuse_success(tmp_path):
    row = run(tmp_path, "print('x'*100000)", timeout=2, log_limit=1024)
    assert row['reason'] == 'output_limit'
    assert (tmp_path / 'sdk.log').stat().st_size <= 1024
    bad = tmp_path / 'linked'
    bad.mkdir()
    row = run(bad, "from pathlib import Path;Path('leak').symlink_to('/etc/passwd')", timeout=2)
    assert row['reason'] == 'unsafe_output'
