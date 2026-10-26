"""Execute the client build stage and prove offline dependency closure in a fresh target."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_omx_client_workflow_build_and_offline_install(tmp_path):
    workflow = yaml.safe_load((ROOT/'.github/workflows/build-omx-client.yml').read_text())
    build = next(step['run'] for step in workflow['jobs']['build']['steps']
                 if step.get('name') == 'Build client wheels')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    python_bin = tmp_path/'python-bin'
    python_bin.mkdir()
    python_launcher = python_bin/'python'
    python_launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding='utf-8')
    python_launcher.chmod(0o755)
    result = subprocess.run(['bash', '-c', build], cwd=ROOT, capture_output=True, text=True,
                            env={**os.environ, 'RUNNER_TEMP': str(tmp_path), 'GITHUB_SHA': revision,
                                 'PATH': str(python_bin) + os.pathsep + os.environ.get('PATH', '')},
                            timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    stage = tmp_path/'omx-client'
    assert (stage/'source-sha.txt').read_text().strip() == revision
    checked = subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=stage, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    installed = tmp_path/'installed'
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--find-links', str(stage),
                             '--target', str(installed), 'rosy-integration-robot-omx==0.1.0'],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from importlib.metadata import distribution
from rosy.integrations.robots.omx.core_arm_client import CoreArmClient
from rosy.integrations.robots.omx.deployment import main
entries = {item.name: item.value for item in distribution('rosy-integration-robot-omx').entry_points}
assert entries['rosy-omx-preflight'] == 'rosy.integrations.robots.omx.deployment:main'
assert entries['rosy-omx-record'] == 'lerobot_robot_rosy_omx:record'
assert 'rclpy' not in sys.modules and 'torch' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', script, str(installed)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
