"""The browser must reject raw/legacy/stale-session responses as measured images."""
from pathlib import Path
import subprocess


def test_measured_frame_header_contract_in_node():
    script = Path(__file__).parent/'web/measured-calibration-view.test.mjs'
    result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
