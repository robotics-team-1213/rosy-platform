"""D-782 checker: stop verdicts only, abstention leaves gates unchanged, approved digest only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
from rosy.contracts.learning.prediction import ARTIFACT_SCHEMA, PredictionRequest, StateRef, artifact_digest


def _load(name, relative):
    sys.path.insert(0, str(HERE.parent))
    spec = importlib.util.spec_from_file_location(name, ROOT/relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


checker_module = _load('checker', 'operations/prediction/world_model/checker.py')
shadow_module = _load('shadow', 'operations/prediction/world_model/shadow.py')
NOW = 5_000_000_000


def artifact(spread=0.0):
    """Exact one-step lag model next = state + 0.5*(action - state); members differ by `spread`."""
    weights = [[0.0]*6 for _ in range(12)]
    for i in range(6):
        weights[i][i], weights[6+i][i] = -0.5, 0.5
    members = [dict(bias=[sign*spread]*6, weights=weights) for sign in (1, -1)]
    document = dict(schema=ARTIFACT_SCHEMA, kind='m1_linear_ensemble', horizon=1, step_s=0.1,
                    rig_revision='rig-1', calibration_revision='cal-1', dataset_manifest_sha256='b'*64,
                    feature_mean=[0.0]*12, feature_std=[1.0]*12, state_min=[-60.0]*5+[0.0],
                    state_max=[60.0]*5+[100.0], action_min=[-60.0]*5+[0.0], action_max=[60.0]*5+[100.0],
                    members=members)
    document['digest'] = artifact_digest(document)
    return document


def make(tmp_path, spread=0.0, **config):
    document = artifact(spread)
    path = tmp_path/f'artifact-{spread}.json'
    path.write_text(json.dumps(document))
    return checker_module.WorldModelChecker(path, document['digest'], checker_module.CheckerConfig(**config))


def request(state=(0.,)*5+(50.,), action=((10.,)*5+(50.,),), age_ns=0, **ref):
    fields = dict(sample_id='s/c/0', observed_at_ns=NOW-age_ns, rig_revision='rig-1', calibration_revision='cal-1')
    fields.update(ref)
    return PredictionRequest(state_ref=StateRef(**fields), state=state, action=action, step_s=0.1,
                             action_source='teacher:'+'c'*64)


def test_no_objection_is_a_prediction_not_a_permission(tmp_path):
    result = make(tmp_path).check(request(), NOW)
    assert result.verdict == 'NO_OBJECTION' and result.blocks is False
    assert result.predicted_states[0][0] == pytest.approx(5.0) and 'not a permission' in result.reason
    assert result.is_current(NOW) and not result.is_current(result.expires_at_ns)


def test_predicted_limit_violation_rejects(tmp_path):
    checker = make(tmp_path, limits_low=(-100.,)*5+(0.,), limits_high=(4.,)*5+(100.,))
    result = checker.check(request(), NOW)
    assert result.verdict == 'REJECT' and result.blocks and 'joint 0' in result.reason


def test_disagreeing_members_hold(tmp_path):
    result = make(tmp_path, spread=3.0, hold_sigma=1.0).check(request(), NOW)
    assert result.verdict == 'HOLD' and result.blocks and max(result.uncertainty[0]) == pytest.approx(3.0)


@pytest.mark.parametrize('case,expected', [
    (dict(age_ns=2_000_000_000), 'stale'),
    (dict(calibration_revision='cal-2'), 'revision'),
    (dict(action=((10.,)*5+(50.,),)*2), 'horizon'),
    (dict(state=(90.,)*5+(50.,)), 'training range'),
])
def test_abstention_carries_nothing_and_blocks_nothing(tmp_path, case, expected):
    result = make(tmp_path).check(request(**case), NOW)
    assert result.verdict == 'ABSTAIN' and expected in result.reason
    assert result.blocks is False and result.predicted_states == () and result.object_result is None


def test_only_the_approved_unaltered_artifact_loads(tmp_path):
    document = artifact()
    path = tmp_path/'artifact.json'
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='approved'):
        checker_module.WorldModelChecker(path, 'f'*64)
    with pytest.raises(ValueError, match='approved artifact digest is required'):
        checker_module.WorldModelChecker(path, '')
    document['members'][0]['bias'][0] = 1.0
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='digest differs'):
        checker_module.WorldModelChecker(path, document['digest'])


def test_world_arm_state_fact_becomes_a_checked_request(tmp_path):
    sys.path.insert(0, str(ROOT/'operations/world/src'))
    from rosy.world.state.projections.arm_state import ArmStateTracker
    tracker = ArmStateTracker('rig-1', 'cal-1')
    tracker.observe('owner/41', NOW - 1_000_000, (0.,)*5+(50.,))
    state = tracker.current(NOW, .5)
    req = checker_module.request_from_arm_state(state, ((10.,)*5+(50.,),), step_s=.1, action_source='policy:r1')
    result = make(tmp_path).check(req, NOW)
    assert result.verdict == 'NO_OBJECTION' and req.state_ref.sample_id == 'owner/41'


def test_limits_may_only_narrow_the_normalized_range():
    with pytest.raises(ValueError, match='narrow'):
        checker_module.CheckerConfig(limits_high=(120.,)*6)


def test_shadow_log_records_verdicts_without_returning_them(tmp_path):
    checker, log = make(tmp_path), shadow_module.ShadowLog(tmp_path/'shadow.jsonl')
    req = request()
    assert log.record(req, checker.check(req, NOW)) is None
    row = json.loads((tmp_path/'shadow.jsonl').read_text().splitlines()[0])
    assert row['shadow_only'] is True and row['result']['verdict'] == 'NO_OBJECTION'
    assert row['result']['request_digest'] == req.digest()


def test_replay_compares_stop_verdicts_with_human_labels(tmp_path):
    windows = [dict(attempt=0, frame_index=0, state=[0.]*5+[50.], action=[[10.]*5+[50.]], next_states=[[5.]*5+[50.]]),
               dict(attempt=1, frame_index=0, state=[0.]*5+[50.], action=[[10.]*5+[50.]], next_states=[[5.]*5+[50.]])]
    attempts = [dict(session_id='s', cycle_id='ok', outcome='success', object_result='moved_as_intended'),
                dict(session_id='s', cycle_id='bad', outcome='unknown', object_result='dropped')]
    dataset = dict(schema='rosy.world-model-dataset.v1', horizon=1, step_s=0.1, rig_revision='rig-1',
                   calibration_revision='cal-1', attempts=attempts, windows=dict(train=[], eval=windows, test=[]))
    root = tmp_path/'dataset'
    root.mkdir()
    raw = json.dumps(dataset).encode()
    (root/'dataset.json').write_bytes(raw)
    (root/'receipt.json').write_text(json.dumps(dict(dataset_sha256=hashlib.sha256(raw).hexdigest())))
    report = shadow_module.replay(root, make(tmp_path), tmp_path/'replay')
    assert report['attempts_by_label'] == {'success/not_blocked': 1, 'failure/not_blocked': 1}
    assert report['shadow_only'] is True and report['live_veto'] is False
