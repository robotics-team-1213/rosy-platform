"""Exercise the Fleet Docker payload without checkout or installed ROSY fallbacks."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_fleet_image_contains_its_process_and_model_contracts(tmp_path):
    dockerfile = (ROOT / 'deploy/site/Dockerfile.fleet').read_text()
    image = tmp_path / 'image'
    for line in dockerfile.splitlines():
        if not line.startswith('COPY '):
            continue
        *sources, destination = shlex.split(line)[1:]
        target = image / destination.lstrip('/')
        for source in sources:
            origin = ROOT / source
            if origin.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(origin, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
            else:
                file_target = target / origin.name if destination.endswith('/') else target
                file_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, file_target)
    roots = re.search(r'PYTHONPATH=(\S+)', dockerfile).group(1).split(':')
    probe = '''
import inspect
from pathlib import Path
import sys
sys.path[:0] = sys.argv[2:]
from fleet.server.cell_compiler import PalletizingCellJobCompiler
from fleet.server.mission_progress import MissionProgressService
from fleet.server.model_feedback_dispatch import MissionFeedbackToolDispatcher
from rosy.contracts.learning.inference import InferenceResult
from rosy.contracts.skill import SkillInvocation
from rosy.processes.palletizing import submission
for item in (PalletizingCellJobCompiler, MissionProgressService, MissionFeedbackToolDispatcher,
             InferenceResult, SkillInvocation, submission):
    assert Path(inspect.getfile(item)).is_relative_to(Path(sys.argv[1])), item
assert callable(PalletizingCellJobCompiler.compile_submission)
assert callable(MissionProgressService.model_context_from_snapshot)
'''
    result = subprocess.run(
        [sys.executable, '-I', '-c', probe, str(image),
         *(str(image / root.lstrip('/')) for root in roots)],
        cwd=tmp_path, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
