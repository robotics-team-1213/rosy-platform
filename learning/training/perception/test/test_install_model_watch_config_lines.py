"""Native dry-run must include store/drop-in for LF and CRLF quoted configs."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT/'deploy/site/install-model-watch.sh'
pytestmark = pytest.mark.skipif(os.name != 'posix' or not shutil.which('bash'),
                                reason='native POSIX Bash installer behavior')


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
@pytest.mark.parametrize('style', ['plain', 'quoted', 'comment'])
def test_config_line_endings_create_store_and_writable_dropin(tmp_path, newline, style):
    config = tmp_path/'model-watch.yaml'
    store = tmp_path/'store'
    backend = 'inbox' if style == 'plain' else '"inbox"'
    target = str(store) if style == 'plain' else f'"{store}"'
    suffix = ' # configured value' if style == 'comment' else ''
    config.write_bytes(newline.join([
        'backend: '+backend+suffix,
        'store: '+target+suffix,
        'robots:', '  fixture: "<robot-ip>"', '']).encode())
    # Isolate reads from any real /etc config; dry-run itself must make no writes.
    script = tmp_path/'install-model-watch.sh'
    script.write_bytes(SCRIPT.read_bytes().replace(
        b'CONFIG=/etc/rosy/model-watch.yaml', ('CONFIG='+str(config)).encode()))
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    run=subprocess.run(['bash',str(script),'--dry-run','--src',str(tmp_path/'source'),
                        '--venv',str(tmp_path/'missing-venv')],capture_output=True,text=True)
    assert run.returncode==0, run.stderr
    assert f'+ install -d -o rosy-model-watch -g rosy-model-watch -m 2770 {store}' in run.stdout
    assert 'store.conf: [Service] ReadWritePaths='+str(store) in run.stdout
    assert 'timer NOT enabled' in run.stdout
    assert not store.exists()
    assert before=={p.name:p.read_bytes() for p in tmp_path.iterdir()}
