"""The shared image lock reader keeps literal scalar bytes and section boundaries."""

from pathlib import Path
import subprocess

import pytest

LIB = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/image/lib/lock.sh'


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_lock_reader_preserves_scalar_and_stops_at_next_section(tmp_path, newline):
    assert LIB.is_file()
    lock = tmp_path / 'inputs.yaml'
    lock.write_bytes(newline.join(['runtime:', "  key: 'two words'", 'other:', '  key: ignored', '']).encode())
    result = subprocess.run(['bash', '-c', 'LOCK="$1"; source "$2"; lock_value runtime key',
                             'lock-test', str(lock), str(LIB)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "'two words'\n"
