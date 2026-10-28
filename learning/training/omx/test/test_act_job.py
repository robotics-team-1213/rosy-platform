"""ACT chunk boundaries and research evaluation refusal for constant demonstrations."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from act_job import chunk_indices, offline_report, compatible_sources, run


def test_bounded_sampling_checks_the_whole_chunk_without_changing_labels():
    import copy
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    rows=[dict(command_id='a',ros_goal_id='ga',
               **{'observation.state':[state]+[0.]*5,'action':[action]+[0.]*5})
          for state,action in [(0.,.02),(.01,.02),(.02,.04),(.03,.04),(.04,.04)]]
    original=copy.deepcopy(rows)
    assert act_job.training_sample_indices(rows,names,sampling='command_entry_and_exit',
        max_delta_rad=.035)==[1,4]
    assert rows==original


@pytest.mark.parametrize('sampling',['all_frames','command_entry','command_entry_and_exit'])
def test_bounded_sampling_refuses_an_unrepresentable_gripper_command(sampling):
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    rows=[dict(command_id='a',ros_goal_id='ga',
               **{'observation.state':[0.]*6,'action':[0.]*5+[.039]})]
    with pytest.raises(ValueError,match='bound|every command'):
        act_job.training_sample_indices(rows,names,sampling=sampling,max_delta_rad=.035)


def test_bounded_state_noise_preserves_all_absolute_chunk_targets():
    import act_job
    origin=np.array([0.,0.])
    targets=np.array([[.02,-.01],[.03,.01]])
    original=targets.copy()
    noisy=act_job.augment_training_origin(origin,targets,np.array([-.1,.1]),max_delta_rad=.035)
    np.testing.assert_allclose(noisy,[-.005,.025])
    assert np.max(np.abs(targets-noisy))<=.035+1e-12
    np.testing.assert_array_equal(targets,original)
    np.testing.assert_array_equal(origin,[0.,0.])


def test_state_noise_without_a_bounded_head_remains_gaussian_input_only():
    import act_job
    np.testing.assert_allclose(act_job.augment_training_origin(
        np.array([.1]),np.array([[.9]]),np.array([.02])),[.12])


def test_bounded_state_noise_refuses_original_targets_outside_the_head_support():
    import act_job
    with pytest.raises(ValueError,match='bound'):
        act_job.augment_training_origin(np.array([0.]),np.array([[.04]]),
            np.array([0.]),max_delta_rad=.035)


def test_command_entry_sampling_keeps_every_command_and_original_labels():
    import copy
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    rows=[dict(command_id=command,ros_goal_id=goal,
               **{'observation.state':[0.]*6,'action':[arm,0.,0.,0.,0.,gripper]})
          for command,goal,arm,gripper in [('a','ga',.041,.0399),('a','ga',.034,.0399),
              ('a','ga',.001,.0399),('b','gb',.03,.0399),('b','gb',.001,.0399)]]
    original=copy.deepcopy(rows)
    assert act_job.training_sample_indices(rows,names,sampling='command_entry')==[1,3]
    assert rows==original
    assert chunk_indices(len(rows),1,4)==[1,2,3,4]  # Chunk still follows original frames.
    assert act_job.training_sample_indices(rows,names,sampling='all_frames')==list(range(5))


def test_command_entry_and_exit_keeps_last_eligible_original_frame_and_order():
    import copy
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    rows=[dict(command_id=command,ros_goal_id=goal,
               **{'observation.state':[0.]*6,'action':[arm,0.,0.,0.,0.,gripper]})
          for command,goal,arm,gripper in [('a','ga',.041,.0399),('a','ga',.034,.0399),
              ('a','ga',.001,.0399),('a','ga',.001,.0401),('b','gb',.03,.0399),
              ('b','gb',.001,.0401),('c','gc',.02,.0399),('c','gc',.001,.0399)]]
    original=copy.deepcopy(rows)
    assert act_job.training_sample_indices(rows,names,sampling='command_entry_and_exit')==[1,2,4,6,7]
    assert act_job.training_sample_indices(rows,names,sampling='command_entry')==[1,4,6]
    assert rows==original
    assert chunk_indices(len(rows),2,4)==[2,3,4,5]


def test_place_open_sampling_adds_only_eligible_original_interiors_until_arm_moves(tmp_path):
    import copy
    import json
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    commands=[dict(command_id=key,sim_time=stamp,
                   target=dict(zip(names,[arm,0.,0.,0.,0.,grip])))
              for key,stamp,arm,grip in [('a',1.,.1,.4),('b',2.,.2,.4),
                  ('c',3.,.2,.3),('d',4.,.3,.3),('e',5.,.2,.2)]]
    phases=[dict(phase_id='transfer',started_sim_s=.5,ended_sim_s=2.5)]
    proof=tmp_path/'truth.json'
    for name,value in [('phases',phases),('commands',commands)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value))
    proof.write_text(json.dumps(dict(files={key:dict(path=key+'.json')
                                           for key in ('phases','commands')})))
    rows=[]
    for command in commands:
        action=list(command['target'].values())
        for _ in range(4):
            rows.append(dict(command_id=command['command_id'],ros_goal_id='g'+command['command_id'],
                             **{'action':action[:],'observation.state':action[:]}))
    rows[5]['observation.state'][0]-=.0351
    original=copy.deepcopy(rows)
    endpoints=[0,3,4,7,8,11,12,15,16,19]
    assert act_job.training_sample_indices(rows,names,sampling='command_entry_and_exit')==endpoints
    assert act_job.training_sample_indices(rows,names,sampling='command_entry_exit_and_place_open',
        sim_truth=proof)==sorted(endpoints+[6,9,10])
    assert rows==original
    assert chunk_indices(len(rows),6,4)==[6,7,8,9]


def test_place_open_sampling_requires_original_sim_truth_metadata():
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    with pytest.raises(ValueError,match='SIM truth'):
        act_job.training_sample_indices([],names,sampling='command_entry_exit_and_place_open')


@pytest.mark.parametrize('sampling',['command_entry','command_entry_and_exit'])
def test_command_entry_sampling_refuses_to_drop_unrepresented_commands(sampling):
    import act_job
    names=[f'joint{i}' for i in range(1,6)]+['gripper_joint_1']
    rows=[dict(command_id='a',ros_goal_id='ga',
               **{'observation.state':[0.]*6,'action':[0.,0.,0.,0.,0.,.0401]})]
    with pytest.raises(ValueError,match='every command'):
        act_job.training_sample_indices(rows,names,sampling=sampling)


def test_invalid_training_sampling_fails_before_source_or_model_access(tmp_path):
    with pytest.raises(ValueError,match='sampling'):
        run([],tmp_path/'absent',tmp_path/'out',sampling='unknown')
    assert not (tmp_path/'out').exists()


def test_unknown_action_representation_fails_before_source_or_model_access(tmp_path):
    with pytest.raises(ValueError,match='action representation'):
        run([],tmp_path/'absent',tmp_path/'out',action_representation='unknown')
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('std',[True,-.01,float('inf'),float('nan')])
def test_invalid_state_noise_fails_before_source_or_model_access(tmp_path,std):
    with pytest.raises(ValueError,match='state noise'):
        run([],tmp_path/'absent',tmp_path/'out',state_noise_std_rad=std,
            action_representation='joint_delta_from_chunk_source_v1')
    assert not (tmp_path/'out').exists()


def test_state_noise_requires_source_relative_targets(tmp_path):
    with pytest.raises(ValueError,match='relative'):
        run([],tmp_path/'absent',tmp_path/'out',state_noise_std_rad=.02)
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('mode,parent',[('absolute_tanh_from_chunk_source_v1',None),
    ('absolute','unused-parent'),('joint_delta_tanh_from_chunk_source_v1','unused-parent')])
def test_parent_initialization_is_explicit_and_only_for_bounded_absolute(tmp_path,mode,parent):
    with pytest.raises(ValueError,match='initial policy'):
        run([],tmp_path/'absent',tmp_path/'out',action_representation=mode,initial_policy=parent)
    assert not (tmp_path/'out').exists()


def test_multiple_validation_episodes_cannot_overlap_training(tmp_path, monkeypatch):
    monkeypatch.setattr('act_job.importlib.metadata.version', lambda *_: '0.4.4')
    with pytest.raises(ValueError, match='disjoint'):
        run([tmp_path/'train-a', tmp_path/'train-b'],
            [tmp_path/'val-a', tmp_path/'train-b'],tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_chunk_padding_never_crosses_episode_boundary():
    assert chunk_indices(3, 1, 4) == [1, 2, None, None]
    with pytest.raises(ValueError):
        chunk_indices(3, 3, 4)


def test_constant_goal_is_rejected_even_with_perfect_predictions():
    actions = np.full((10, 2), .02)
    report = offline_report(actions, actions.copy(), actions[0], actions, [[-1, 1]]*2)
    assert report["mae_rad"] == 0
    assert report["verdict"] == "reject"
    assert "insufficient_target_diversity" in report["reasons"]


def test_unsafe_or_nonfinite_prediction_is_not_clamped_to_pass():
    actions = np.array([[.01, .02], [-.1, -.2], [.2, .3]])
    predictions = actions.copy()
    predictions[0, 0] = 10
    report = offline_report(actions, predictions, np.zeros(2), actions, [[-1, 1]]*2)
    assert report["limit_violations"] == 1 and report["verdict"] == "reject"
    predictions[0, 0] = np.nan
    assert offline_report(actions, predictions, np.zeros(2), actions, [[-1, 1]]*2)["verdict"] == "reject"


def test_rig_joint_order_and_limits_mismatch_refused():
    source = {"joint_names": ["j1", "j2"], "position_limits_rad": {"j1": [-1, 1], "j2": [-1, 1]},
              "camera": {"identity": "sim-camera"}, "fps": 10,
              "calibration_revision": "sim-calib", "world_sha256": "a"*64}
    compatible_sources([source, source.copy()])
    with pytest.raises(ValueError):
        compatible_sources([source, {**source, "joint_names": ["j2", "j1"]}])


@pytest.mark.parametrize('steps',[True,0,5,1.5])
def test_invalid_action_queue_length_fails_before_source_or_model_access(tmp_path,steps):
    with pytest.raises(ValueError,match='n_action_steps'):
        run([],tmp_path/'absent',tmp_path/'output',n_action_steps=steps)
    assert not (tmp_path/'output').exists()


def test_consumed_reader_frame_is_bound_to_original_png(tmp_path):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    rgb = np.full((32, 32, 3), [255, 0, 0], dtype=np.uint8)
    Image.fromarray(rgb).save(original)
    matching = rgb.transpose(2, 0, 1).astype(np.float32) / 255
    assert verify_reader_image(matching, original, sha256(original.read_bytes()).hexdigest()) == 0
    # Preserve the existing exporter's lossy encoding allowance.
    assert verify_reader_image(matching * .99, original, sha256(original.read_bytes()).hexdigest()) < 8
    substituted = np.full((3, 32, 32), 0., dtype=np.float32)
    substituted[2] = 1
    with pytest.raises(ValueError, match="source image differs"):
        verify_reader_image(substituted, original, sha256(original.read_bytes()).hexdigest())


@pytest.mark.parametrize('pixels', [
    np.full((3, 32, 32), np.nan), np.zeros((3, 31, 32)),
    np.full((3, 32, 32), 1.1), np.zeros((3, 32, 32), dtype=np.uint8),
])
def test_consumed_reader_frame_shape_range_and_finiteness_are_checked(tmp_path, pixels):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    Image.fromarray(np.zeros((32, 32, 3), dtype=np.uint8)).save(original)
    with pytest.raises(ValueError, match="source image dimensions/range"):
        verify_reader_image(pixels, original, sha256(original.read_bytes()).hexdigest())


def test_source_png_changed_after_validation_is_refused_even_if_reader_matches(tmp_path):
    from hashlib import sha256
    from PIL import Image
    from act_job import verify_reader_image
    original = tmp_path / "original.png"
    Image.fromarray(np.full((32, 32, 3), [255, 0, 0], dtype=np.uint8)).save(original)
    validated_hash = sha256(original.read_bytes()).hexdigest()
    changed = np.full((32, 32, 3), [0, 0, 255], dtype=np.uint8)
    Image.fromarray(changed).save(original)
    with pytest.raises(ValueError, match="PNG hash differs"):
        verify_reader_image(changed.transpose(2, 0, 1).astype(np.float32) / 255,
                            original, validated_hash)
