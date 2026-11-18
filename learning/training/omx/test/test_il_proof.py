"""il_proof.py end to end on CPU with tiny steps (ACT only); synthetic, so wiring only."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'il_proof.py'
EXPECTED = ['env', 'synthetic_sessions', 'prepare', 'synthetic_decisions', 'train_act',
            'independent_eval_act', 'register_dry_run', 'hub_prepare']


def test_il_proof_cpu_act_chain_writes_a_passing_synthetic_receipt(tmp_path):
    for name in ('lerobot', 'torch'):
        if importlib.util.find_spec(name) is None:
            pytest.skip(f'{name} is not installed in this python; run in the learning env (learning/training/env)')
    out = tmp_path / 'proof'
    result = subprocess.run([sys.executable, str(SCRIPT), '--out', str(out), '--device', 'cpu',
                             '--steps', '2', '--timeout', '600'],
                            capture_output=True, text=True, timeout=900)
    receipt = json.loads((out / 'proof-receipt.json').read_text(encoding='utf-8'))
    detail = result.stdout[-2000:] + result.stderr[-2000:] + json.dumps(receipt['stages'], indent=1)[-4000:]
    assert result.returncode == 0 and receipt['ok'], detail
    assert receipt['synthetic'] is True and receipt['evidence_of'] == 'environment and wiring only'
    assert receipt['uploaded'] is False and receipt['promotion'] is False
    assert [s['name'] for s in receipt['stages']] == EXPECTED
    assert all(s['status'] == 'passed' for s in receipt['stages']), detail
    stages = {s['name']: s for s in receipt['stages']}
    assert stages['synthetic_decisions']['human_evidence'] is False
    assert stages['train_act']['split'] == dict(train=[0], eval=[1], test=[2])
    assert stages['independent_eval_act']['max_mae_gap'] <= 1e-3
    assert stages['hub_prepare']['uploaded'] is False and not (out / 'hub-bundle/receipt.json').exists()
    decisions = json.loads((out / 'synthetic-decisions.json').read_text(encoding='utf-8'))
    assert {row['reviewer'] for row in decisions} == {'synthetic-proof'}


def test_il_proof_refuses_an_existing_output_directory(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--out', str(tmp_path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and 'FileExistsError' in result.stderr
