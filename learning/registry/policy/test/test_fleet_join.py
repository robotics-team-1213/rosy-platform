import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'),
               str(ROOT / 'src/contracts/foundation'), str(ROOT / 'test')]
from fleet_join import join, export
from rosy.contracts.learning import seal
from test_learning_artifact_contracts import episode


def receipt():
    return dict(mission_id='mission-1', step_id='step-1', action_id='action-1',
                attempt_id='attempt-1', workcell_id='cell-1', instance_id='sim-arm',
                request_digest='b' * 64, authority_epoch=3, dispatch_generation=7,
                state='SUCCEEDED', journal_event_id=5, observed_at='2026-10-04T00:00:00Z',
                driver_goal_id='goal-1')


def correlated():
    doc = episode()
    doc['correlations'] = dict(action_ids=['action-1'], attempt_ids=['attempt-1'])
    return seal(doc)


def test_join_preserves_unknown_task_and_policy():
    result = join(correlated(), receipt())
    assert result['status'] == 'matched'
    assert result['binding']['mission_id'] == 'mission-1'
    assert result['binding']['dispatch_generation'] == 7
    assert result['episode_outcome']['task'] == 'unknown'
    assert result['policy_revision'] is None
    assert result['receipt']['state'] == 'SUCCEEDED'


@pytest.mark.parametrize('field,value', [('action_id', 'other-action'),
                                       ('attempt_id', 'other-attempt'), ('instance_id', 'other-arm')])
def test_unrelated_receipt_never_creates_binding(field, value):
    wire = receipt()
    wire[field] = value
    result = join(correlated(), wire)
    assert result['status'] == 'unmatched' and result['binding'] is None


def test_separate_multi_id_lists_do_not_prove_pair():
    doc = correlated()
    doc['correlations']['action_ids'].append('action-2')
    assert join(seal(doc), receipt())['reason'] == 'ambiguous_episode_correlations'


def test_missing_keys_are_not_backfilled():
    assert join(episode(), receipt())['reason'] == 'missing_episode_correlations'


def test_conflicting_terminal_action_not_joined():
    wire = receipt()
    wire['state'] = 'FAILED'
    result = join(correlated(), wire)
    assert result['reason'] == 'action_outcome_conflict' and result['binding'] is None


@pytest.mark.parametrize('field,value', [('dispatch_generation', True), ('observed_at', '2026-10-04'),
                                       ('state', 'INVENTED')])
def test_existing_wire_validator_rejects_invalid_receipt(field, value):
    wire = receipt()
    wire[field] = value
    with pytest.raises(ValueError):
        join(correlated(), wire)


def test_episode_revision_tampering_rejected():
    doc = correlated()
    doc['device'] = 'other'
    with pytest.raises(ValueError, match='revision'):
        join(doc, receipt())


def test_export_verifies_original_files_and_does_not_overwrite(tmp_path):
    sys.path[:0] = [str(ROOT / 'src/products/omx/adapter'),
                   str(ROOT / 'src/products/omx/adapter/test'), str(ROOT / 'learning/curation/omx')]
    from test_demonstration import complete_episode
    from common_episode import convert
    original = tmp_path / 'recordings'
    recorded = complete_episode(original)
    source = tmp_path / 'episode'
    doc = convert(original / recorded['episode_id'], source)
    manifest = source / 'manifest.json'
    manifest.write_text(json.dumps(doc), encoding='utf-8')
    wire = tmp_path / 'receipt.json'
    wire.write_text(json.dumps(receipt()), encoding='utf-8')
    output = tmp_path / 'binding.json'
    result = export(manifest, wire, output)
    assert json.loads(output.read_text()) == result
    assert result['inputs']['receipt_sha256'] == hashlib.sha256(wire.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        export(manifest, wire, output)
    (source / 'source/samples.jsonl').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='hash/size'):
        export(manifest, wire, tmp_path / 'new.json')
