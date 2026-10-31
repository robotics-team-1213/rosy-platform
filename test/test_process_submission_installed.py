"""Process-owned submissions survive delivery without adding execution dependencies."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _run(args, cwd):
    result = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("delivery", ["wheel", "sdist"])
def test_installed_submission_preserves_process_validation_and_execution_independence(tmp_path, delivery):
    sources = []
    for relative in ("contracts/skill", "operations/site_execution", "operations/processes/palletizing",
                     "applications/fleet/gateway"):
        target = tmp_path / "source" / relative
        shutil.copytree(ROOT / relative, target,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "build", "dist"))
        if delivery == "sdist":
            archives = tmp_path / "archives" / target.name
            archives.mkdir(parents=True)
            _run(["-c", "from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])",
                  str(archives)], target)
            sources.append(next(archives.glob("*.tar.gz")))
        else:
            sources.append(target)
    wheels, installed = tmp_path / "wheels", tmp_path / "installed"
    _run(["-m", "pip", "wheel", "--no-deps", "--no-index", "--no-build-isolation", "--wheel-dir",
          str(wheels), *map(str, sources)], tmp_path)
    _run(["-m", "pip", "install", "--no-deps", "--no-index", "--target", str(installed),
          *map(str, wheels.glob("*.whl"))], tmp_path)
    examples = ROOT / "operations/processes/cell/examples/omx_sim"
    documents = tmp_path / "documents.json"
    documents.write_text(json.dumps([yaml.safe_load((examples / name).read_text(encoding="utf-8"))
                                    for name in ("recipe.yaml", "cell.yaml")]), encoding="utf-8")
    probe = r'''
import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
class RefuseOwners(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fleet', 'omx_adapter', 'rclpy'}:
            raise AssertionError('submission imported execution owner ' + fullname)
        if fullname.startswith('rosy.processes'):
            raise AssertionError('common execution imported process ' + fullname)
guard = RefuseOwners()
sys.meta_path.insert(0, guard)
from rosy.execution.api import PlanBundle
from rosy.execution.site.goal_evidence import GoalPredicate
from rosy.execution.site.workflow import mission_step_state
assert mission_step_state('ACTION_SUCCEEDED') == 'AWAITING_GOAL_EVIDENCE'
assert importlib.util.find_spec('rosy.execution.site.cell_submission') is None
sys.meta_path.remove(guard)
for name in sys.argv[3].split(','):
    module = importlib.import_module('rosy.processes.palletizing.' + name)
    assert Path(module.__file__).is_relative_to(Path(sys.argv[1]))
from rosy_gateway.cell_compiler import PalletizingCellCompiler
recipe, cell = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
compiler = PalletizingCellCompiler(process_artifact_digest='a'*64, tol_m=.001)
compiled = compiler.compile(recipe, cell)
assert isinstance(compiled.plan_bundle, PlanBundle)
candidate = dict(kind='cell_job', recipe=recipe, cell=cell, job=compiled.job,
                 recipe_sha256=compiled.plan_bundle.recipe_digest, cell_sha256=compiled.plan_bundle.cell_digest)
document = compiler.compile_submission(candidate, workcell_id='cell-1', instance_id='arm-1')
assert document['resources'] == [['workcell', 'cell-1'], ['pallet', 'A'], ['pallet', 'B']]
assert len(document['steps']) == 18
assert document['ledger_markers'] == [{'after_step_ordinal': 9, 'pallet_id': 'A'},
                                     {'after_step_ordinal': 18, 'pallet_id': 'B'}]
candidate['job']['steps'][1]['target']['x'] += .001
try:
    compiler.compile_submission(candidate, workcell_id='cell-1', instance_id='arm-1')
except ValueError as exc:
    assert 'differs from the recompiled Job' in str(exc)
else:
    raise AssertionError('installed compiler accepted tampered Job')
recipe['schema'] = 'rosy_cell.recipe/2'
recipe['slip_sheet'] = {'handling': 'operator', 'thickness': .002}
del cell['stations']['sheets']
manual = compiler.compile(recipe, cell)
assert len(manual.operator_checkpoints) == 2
candidate = dict(kind='cell_job', recipe=recipe, cell=cell, job=manual.job,
                 recipe_sha256=manual.plan_bundle.recipe_digest, cell_sha256=manual.plan_bundle.cell_digest)
document = compiler.compile_submission(candidate, workcell_id='cell-1', instance_id='arm-1')
assert document['operator_checkpoints'] == list(manual.operator_checkpoints)
assert len(document['steps']) == 16
'''
    for order in ("plan_bundle,submission", "submission,plan_bundle"):
        _run(["-I", "-c", probe, str(installed), str(documents), order], tmp_path)
