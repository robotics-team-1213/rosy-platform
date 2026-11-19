"""The GPU env scripts are syntactically valid, non-destructive, and the pins match what native_cycle needs."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ENV = Path(__file__).resolve().parents[1]
SCRIPTS = ('provision_policy_gpu.sh', 'bootstrap_model_pc.sh')


@pytest.mark.parametrize('name', SCRIPTS)
def test_script_passes_bash_syntax_check(name):
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('no bash on this host')
    result = subprocess.run([bash, '-n'], input=(ENV / name).read_bytes().replace(b'\r\n', b'\n'),
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


@pytest.mark.parametrize('name', SCRIPTS)
def test_script_never_deletes(name):
    text = (ENV / name).read_text(encoding='utf-8')
    assert not re.search(r'(^|[\s;&|(])(rm|rmdir|shred|mkfs)\s', text, re.M), 'env scripts must not delete'
    assert '--clear' not in text and 'rm -rf' not in text


def test_requirements_pin_the_smolvla_and_act_stack():
    lines = (ENV / 'requirements-policy-gpu.txt').read_text(encoding='utf-8').splitlines()
    pins = dict(line.split('==', 1) for line in lines if '==' in line and not line.startswith('#'))
    assert pins['lerobot'] == '0.4.4'  # native_cycle.training_environment requires it for SmolVLA
    assert pins['torch'].endswith('+cu128') and pins['torchvision'].endswith('+cu128')
    assert {'transformers', 'safetensors', 'accelerate', 'num2words', 'av', 'datasets', 'tokenizers'} <= set(pins)
    assert any(line.startswith('--extra-index-url') and line.endswith('/whl/cu128') for line in lines)
