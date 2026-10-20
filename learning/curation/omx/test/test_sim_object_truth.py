"""Automatic SIM truth requires exact execution bytes and measured object success."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'contracts/learning/src'), str(ROOT/'deploy/robot/omx'),
               str(ROOT/'learning/curation/omx')]


def measured_samples():
    samples = []
    for index in range(41):
        clock = 1+index/10
        xyz = (.2, 0., .015) if index == 0 else (.2, 0., .115) if index < 10 else (.2075, .0725, .025)
        samples.append({'model_id': 'infeed_block', 'clock': clock,
            'model_pose_base': dict(zip(('x_m','y_m','z_m'), xyz)),
            'gripper_position': .42 if index < 10 else 1.})
    return samples


def test_measured_judge_is_shared_with_the_native_object_task():
    from rosy.contracts.learning.sim_object_truth import judge_episode
    from sim_pick_place_task import judge_episode as native_judge
    assert native_judge is judge_episode
    result = judge_episode(measured_samples(), model='infeed_block', initial_z=.015,
                           goal=(.2075,.0725,.025), released_at=2., released=True)
    assert result['success'] is True
    assert result['lift_m'] == pytest.approx(.1)


@pytest.mark.parametrize('change', ['unknown_object','no_lift','closed','reset','not_released'])
def test_automatic_truth_never_accepts_contradictory_measurements(change):
    from rosy.contracts.learning.sim_object_truth import judge_episode
    samples = measured_samples()
    if change == 'unknown_object':
        samples[-1]['model_id'] = 'another-object'
    elif change == 'no_lift':
        for row in samples:
            row['model_pose_base']['z_m'] = .025
    elif change == 'closed':
        for row in samples:
            row['gripper_position'] = .42
    elif change == 'reset':
        samples[-1]['clock'] = 0.
    result = judge_episode(samples, model='infeed_block', initial_z=.015,
        goal=(.2075,.0725,.025), released_at=2., released=change != 'not_released')
    assert result['success'] is False


def test_explicit_companion_is_required_and_missing_bytes_fail_before_conversion(tmp_path):
    from common_episode import convert
    from test_common_episode import recorded
    source = recorded(tmp_path)
    output = tmp_path/'converted'
    with pytest.raises((ValueError, FileNotFoundError)):
        convert(source, output, sim_ground_truth=tmp_path/'missing-proof.json')
    assert not output.exists()


def test_ground_truth_roundtrip_keeps_original_bytes_and_all_proof_dependencies(tmp_path):
    from sim_object_truth_fixture import fixture
    from sim_object_truth import build
    from common_episode import convert
    from rosy.contracts.learning.omx import validate_profile
    run, native, source = fixture(tmp_path)
    proof = build(run,native,tmp_path/'proof')
    assert proof['metrics']['success'] is True
    output = tmp_path/'common'
    episode = convert(source,output,sim_ground_truth=proof['truth'])
    assert episode['outcome']['judge'] == 'sim_ground_truth'
    assert episode['correlations'] == {'action_ids':[],'attempt_ids':[]}
    assert (output/'source/manifest.json').read_bytes() == (source/'manifest.json').read_bytes()
    validate_profile(episode,root=output)
    (output/'sim-truth/files/phases.json').write_text('[]')
    with pytest.raises(ValueError,match='hash|size'):
        validate_profile(episode,root=output)


@pytest.mark.parametrize('change', ['missing_receipt','stale','future','generation','native_asset','goal_uuid','terminal'])
def test_resealed_but_unbound_execution_cannot_become_sim_truth(tmp_path, change):
    from sim_object_truth_fixture import fixture, write
    from sim_object_truth import build
    run, native, source = fixture(tmp_path)
    if change in ('missing_receipt','stale','future','generation'):
        phases = json.loads((run/'teacher-phases.json').read_text())
        phase = phases[1] if change != 'generation' else phases[-1]
        prefix = 'hold' if change != 'generation' else 'release'
        evidence = phase[prefix+'_evidence']
        if change == 'missing_receipt':
            phase[prefix+'_receipt'] = {'instance_id':'omx_cell_sim_01','object_id':'box'}
            evidence['receipt'] = phase[prefix+'_receipt']
        elif change in ('stale','future'):
            value = evidence['checked_owner_s']+(-.6 if change == 'stale' else .1)
            evidence['observation']['received_at'] = evidence['receipt']['received_at'] = value
        else:
            evidence['observation']['owner_generation'] = evidence['receipt']['owner_generation'] = 2
        write(run/'teacher-phases.json',phases)
    elif change == 'native_asset':
        document = json.loads(native.read_text())
        document['source_hashes']['deploy/robot/omx/sim/cell_profile.yaml'] = 'f'*64
        write(native,document)
        # Rebind the declared inventory hash too; the task input itself must still be checked.
        digest = hashlib.sha256(json.dumps(document['source_hashes'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        manifest = json.loads((source/'manifest.json').read_text())
        manifest['provenance']['source_tree_sha256'] = digest
        write(source/'manifest.json',manifest)
        result = json.loads((run/'teacher-result.json').read_text())
        result['source']['source_tree_sha256'] = digest
        result['capture'] = manifest
        write(run/'teacher-result.json',result)
    else:
        events = [json.loads(line) for line in (source/'events.jsonl').read_text().splitlines()]
        if change == 'goal_uuid': events[0]['goal_id'] = '99999999-9999-4999-8999-999999999999'
        else: events[1]['status'] = 6
        payload = ''.join(json.dumps(row)+'\n' for row in events).encode()
        (source/'events.jsonl').write_bytes(payload)
        manifest = json.loads((source/'manifest.json').read_text())
        manifest['events_sha256'] = hashlib.sha256(payload).hexdigest()
        write(source/'manifest.json',manifest)
        result = json.loads((run/'teacher-result.json').read_text())
        result['capture'] = manifest
        write(run/'teacher-result.json',result)
    with pytest.raises(ValueError):
        build(run,native,tmp_path/'proof')
