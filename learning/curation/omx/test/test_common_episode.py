"""Common Episode wrapper retains validated OMX bytes and separate clocks."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT / "contracts/learning/src", ROOT / "middleware/apps/device/omx/adapter",
             ROOT / "contracts/foundation", ROOT / "middleware/apps/device/omx/adapter/test",
             ROOT / "learning/curation/omx"):
    sys.path.insert(0, str(path))

from test_demonstration import complete_episode, DemonstrationRecorder, provenance, sample
from common_episode import convert
from rosy.contracts.learning import validate_episode
from rosy.contracts.learning import seal
from rosy.contracts.learning.omx import validate_profile


def test_common_episode_roundtrip_keeps_source_clock_action_and_unknowns(tmp_path):
    original = tmp_path / "recordings"
    manifest = complete_episode(original)
    source = original / manifest["episode_id"]
    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    output = tmp_path / "common"
    doc = convert(source, output)
    assert validate_episode(doc, root=output)["revision"] == doc["revision"]
    assert doc["outcome"]["task"] == "success" and doc["outcome"]["judge"] == "operator"
    assert doc["outcome"]["action"] == "unknown"
    assert doc["revisions"]["policy"] is None
    samples = [json.loads(row) for row in (output/'source/samples.jsonl').read_text().splitlines()]
    assert samples[0]["capture_time_ns"] == 1_000_000_000
    assert samples[0]["received_at_ns"] == 1_000_000_010
    assert samples[0]["action"] == [.02, -.1]
    assert all((source / p).read_bytes() == value == (output / 'source' / p).read_bytes()
               for p, value in before.items())
    with pytest.raises(ValueError, match="new directory"):
        convert(source, output)


def test_tampered_omx_source_refused_before_common_output(tmp_path):
    original = tmp_path / "recordings"
    manifest = complete_episode(original)
    source = original / manifest["episode_id"]
    (source / 'samples.jsonl').write_text('{}\n')
    output = tmp_path / "common"
    with pytest.raises(ValueError, match="hash"):
        convert(source, output)
    assert not output.exists()


def owner_receipt(source, **changes):
    row = json.loads((source / 'samples.jsonl').read_text().splitlines()[0])
    manifest = json.loads((source / 'manifest.json').read_text())
    value = dict(mission_id='mission-1', step_id='step-1', action_id='action-1',
                 attempt_id='attempt-1', instance_id=manifest['provenance']['instance_id'],
                 workcell_id='cell-1', request_digest='a' * 64, authority_epoch=2,
                 dispatch_generation=4, state='SUCCEEDED', journal_event_id=3,
                 journal_id='owner-journal-1', observed_at='2026-10-04T00:00:00Z',
                 driver_goal_id=row['ros_goal_id'])
    value.update(changes)
    return value


def recorded(tmp_path):
    folder = tmp_path / 'recordings'
    doc = complete_episode(folder)
    return folder / doc['episode_id']


def test_profile_rejects_unproven_episode_correlations(tmp_path):
    source = recorded(tmp_path)
    output = tmp_path / 'common'
    doc = convert(source, output)
    doc['correlations'] = dict(action_ids=['action-1'], attempt_ids=['attempt-1'])
    with pytest.raises(ValueError, match='correlation'):
        validate_profile(seal(doc), root=output)


def test_receipt_bytes_goal_identity_and_correlations_preserved(tmp_path):
    source = recorded(tmp_path)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(owner_receipt(source)), encoding='utf-8')
    output = tmp_path / 'common'
    doc = convert(source, output, owner_receipts=[receipt])
    assert doc['correlations'] == dict(action_ids=['action-1'], attempt_ids=['attempt-1'])
    assert doc['revisions']['policy'] is None and doc['outcome']['action'] == 'unknown'
    assert (output / 'owner-receipts/000000.json').read_bytes() == receipt.read_bytes()
    validate_profile(doc, root=output)
    (output / 'owner-receipts/000000.json').write_text('{}')
    with pytest.raises(ValueError, match='hash/size'):
        validate_profile(doc, root=output)


@pytest.mark.parametrize('change', [dict(instance_id='other'), dict(driver_goal_id='other-goal'),
                                   dict(dispatch_generation=True), dict(journal_id=None)])
def test_bad_receipt_refused_before_output(tmp_path, change):
    source = recorded(tmp_path)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(owner_receipt(source, **change)), encoding='utf-8')
    output = tmp_path / 'common'
    with pytest.raises(ValueError):
        convert(source, output, owner_receipts=[receipt])
    assert not output.exists()


def test_owner_receipt_correlations_reach_fleet_export(tmp_path):
    source = recorded(tmp_path)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(owner_receipt(source)), encoding='utf-8')
    output = tmp_path / 'common'
    doc = convert(source, output, owner_receipts=[receipt])
    sys.path.insert(0, str(ROOT / 'learning/registry/policy'))
    from fleet_join import export
    result = export(output / 'manifest.json', receipt, tmp_path / 'fleet.json')
    assert result['status'] == 'matched' and result['episode_revision'] == doc['revision']
    assert result['episode_outcome']['task'] == 'success'
    assert result['episode_outcome']['judge'] == 'operator'
    assert result['policy_revision'] is None


@pytest.mark.parametrize('change', [None, 'partial', 'attempt', 'generation', 'journal'])
def test_multiple_goal_coverage_requires_one_execution_identity(tmp_path, change):
    recorder = DemonstrationRecorder(tmp_path / 'recordings', provenance())
    recorder.start('two goals')
    sample(recorder)
    second_goal = '22222222-2222-4222-8222-222222222222'
    sample(recorder, 1_100_000_000, ros_goal_id=second_goal)
    manifest = recorder.stop('success')
    source = tmp_path / 'recordings' / manifest['episode_id']
    values = [owner_receipt(source), owner_receipt(source, driver_goal_id=second_goal, journal_event_id=4)]
    if change == 'partial':
        values.pop()
    elif change is not None:
        key = {'attempt': 'attempt_id', 'generation': 'dispatch_generation', 'journal': 'journal_id'}[change]
        values[1][key] = 5 if change == 'generation' else 'other'
    files = []
    for i, value in enumerate(values):
        file = tmp_path / f'receipt-{i}.json'
        file.write_text(json.dumps(value), encoding='utf-8')
        files.append(file)
    output = tmp_path / 'common'
    if change is None:
        doc = convert(source, output, owner_receipts=files)
        validate_profile(doc, root=output)
        assert doc['correlations']['attempt_ids'] == ['attempt-1']
    else:
        with pytest.raises(ValueError):
            convert(source, output, owner_receipts=files)
        assert not output.exists()


@pytest.mark.parametrize('field,value', [('mission_id', 'other'), ('workcell_id', 'other'),
                                       ('request_digest', 'b'*64), ('dispatch_generation', 999),
                                       ('authority_epoch', 999), ('journal_id', 'other'),
                                       ('driver_goal_id', 'other')])
def test_fleet_export_rechecks_preserved_owner_identity(tmp_path, field, value):
    source = recorded(tmp_path)
    receipt = tmp_path / 'receipt.json'
    wire = owner_receipt(source)
    receipt.write_text(json.dumps(wire), encoding='utf-8')
    output = tmp_path / 'common'
    convert(source, output, owner_receipts=[receipt])
    wire[field] = value
    receipt.write_text(json.dumps(wire), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'learning/registry/policy'))
    from fleet_join import export
    result = export(output / 'manifest.json', receipt, tmp_path / 'fleet.json')
    assert result['status'] == 'unmatched' and result['binding'] is None


@pytest.mark.parametrize('profile', ['pinky_recording_session_v1', 'pilot_recording_v1'])
def test_profile_change_cannot_bypass_fleet_provenance(tmp_path, profile):
    source = recorded(tmp_path)
    output = tmp_path / 'common'
    doc = convert(source, output)
    doc['profile'] = profile
    doc['correlations'] = dict(action_ids=['action-1'], attempt_ids=['attempt-1'])
    (output / 'manifest.json').write_text(json.dumps(seal(doc)), encoding='utf-8')
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(owner_receipt(source)), encoding='utf-8')
    sys.path.insert(0, str(ROOT / 'learning/registry/policy'))
    from fleet_join import export
    with pytest.raises(ValueError):
        export(output / 'manifest.json', receipt, tmp_path / 'fleet.json')
