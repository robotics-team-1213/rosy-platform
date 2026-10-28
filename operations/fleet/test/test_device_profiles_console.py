"""Device metadata editing stays on the existing Fleet installation surface."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / 'applications/fleet/web'


def test_device_profile_web_behavior():
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed')
    script = Path(__file__).parent / 'web/device-profiles.test.mjs'
    result = subprocess.run([node, '--test', str(script)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_device_profiles_are_mounted_in_installation():
    html = (WEB / 'installation/install.html').read_text(encoding='utf-8')
    script = (WEB / 'installation/install.js').read_text(encoding='utf-8')
    assert 'id="device-profiles"' in html
    assert '장치 정보' in html
    assert 'createDeviceProfiles' in script
    assert 'device-profiles.js' in script
    manifest = json.loads((WEB / 'assets.json').read_text(encoding='utf-8'))
    assert 'devices/device-profiles.js' in json.dumps(manifest)
