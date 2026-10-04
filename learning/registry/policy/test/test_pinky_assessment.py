import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/registry/policy'))
from registry import pinky_assessment


def report():
    return {'schema': 'rosy.pinky-offline-eval/1', 'model': 'tiny_cnn', 'target': 'recorded_core_final_velocity',
            'expert_status': 'unverified', 'verdict': 'reject', 'eval_frames': 222,
            'reloaded_prediction_verified': True, 'prediction_limit_violations': 0,
            'mae_m_s': .0055, 'mae_rad_s': .0184,
            'zero_mae_m_s': .0054, 'zero_mae_rad_s': .0117,
            'constant_mae_m_s': .0054, 'constant_mae_rad_s': .0119}


def test_recorded_command_and_failed_metrics_remain_rejected():
    result = pinky_assessment(report())
    assert result['verdict'] == 'reject'
    assert 'does_not_beat_velocity_baseline_m_s' in result['reasons']
    assert 'recorded_velocity_expert_intent_unverified' in result['reasons']


@pytest.mark.parametrize('change', [{'mae_m_s': float('nan')}, {'eval_frames': True},
                                  {'prediction_limit_violations': -1}, {'verdict': 'pass'},
                                  {'expert_status': 'verified'}, {'model': 'unknown'}])
def test_invalid_or_forged_claim_rejected(change):
    doc = copy.deepcopy(report()); doc.update(change)
    with pytest.raises(ValueError):
        pinky_assessment(doc)
