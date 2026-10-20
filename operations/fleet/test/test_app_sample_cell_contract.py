"""The backend-free app replays an actual compiler result, not a second planner."""
import base64
import json
from pathlib import Path

import yaml

from fleet.server.cell_compiler import PalletizingCellJobCompiler

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / 'applications/fleet/dev/sample/fixtures/cell-preview.json'


def test_sample_cell_preview_matches_the_existing_compiler():
    folder = ROOT / 'operations/processes/cell/examples/omx_sim'
    recipe, cell = [yaml.safe_load((folder / f'{kind}.yaml').read_text(encoding='utf-8')) for kind in ('recipe', 'cell')]
    compiled = PalletizingCellJobCompiler(tol_m=0.001).compile(recipe, cell)
    bundle = compiled.plan_bundle
    expected = {'candidate': {'kind': 'cell_job', 'recipe': recipe, 'cell': cell,
                              'recipe_sha256': bundle.recipe_digest, 'cell_sha256': bundle.cell_digest,
                              'job': dict(compiled.job)},
                'process_artifact_digest': bundle.process_artifact_digest,
                'summary': {'transfer_count': len(bundle.steps), 'pallet_markers': list(compiled.ledger_markers)}}
    if not FIXTURE.is_file():
        print('CELL_FIXTURE=' + base64.b64encode(json.dumps(expected).encode()).decode())
    assert FIXTURE.is_file(), 'recorded sample compiler fixture is missing'
    assert json.loads(FIXTURE.read_text(encoding='utf-8')) == expected
