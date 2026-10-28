"""The scanner's flat-file callers retain the same guards after policy separation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_copied_scanner_and_syntax_policy_import_without_repository_path(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'deploy/robot/pinky_pro/release'
    for name in ('secret_scan.py', 'secret_scan_syntax.py'):
        shutil.copyfile(source / name, tmp_path / name)
    program = (
        "from pathlib import Path; import secret_scan as scanner; "
        "assert Path(scanner.__file__).parent == Path.cwd(); "
        "sample = 'pass' + 'word = ' + repr('not-a-real-' + 'fixture-value'); "
        "assert any(item.kind == 'credential' for item in scanner.scan_text('sample.env', sample)); "
        "assert not scanner.scan_text('sample.env', 'pass' + 'word = ${OPERATOR_INPUT}'); "
        "print('SCANNER_RULES_OK')"
    )
    result = subprocess.run([sys.executable, '-c', program], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=''), capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout.strip() == b'SCANNER_RULES_OK'
