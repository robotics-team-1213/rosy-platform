"""Teacher sampling preserves source stamps and still rejects missing evidence."""
import json
import time
from types import SimpleNamespace as NS

import pytest

from omx_adapter.pilot_sim.capture import PilotSimCapture
from omx_adapter.ros_goal_contract import RosGoalEvent
from test_pilot_sim_capture import create_capture, state


def capture_at(tmp_path, fps):
    original = create_capture(tmp_path)
    capture = PilotSimCapture(original.runtime, tmp_path, original.source,
                             sim_time_ns=original.sim_time_ns, recording_fps=fps)
    capture.camera = original.camera
    episode = capture.start('sample the teacher')
    capture.prepare(NS(command_id='command', positions={'joint1': .02, 'gripper_joint_1': -.1}, duration_s=.8))
    capture.on_goal_event(RosGoalEvent(kind='GOAL_ACCEPTED', command_id='command', phase_id=None,
        goal_id='11111111-1111-4111-8111-111111111111',
        observed_at_monotonic_s=time.monotonic(), sequence=1))
    return capture, episode


def frame(capture, stamp, sequence):
    capture.observe_joint_state(state(stamp-2_000_000, .01))
    _, image, info = capture.camera.latest_frame
    metadata = NS(capture_time_ns=stamp, received_at=time.monotonic(), sequence=sequence,
                  camera_identity='gazebo:front', width=8, height=6)
    capture.camera.latest_frame = (metadata, image, info)
    capture.observe_frame(capture.camera.latest_frame)
    capture.tick()


@pytest.mark.parametrize('fps,stride', [(5, 2), (10, 1)])
def test_recording_rate_preserves_original_source_times_and_targets(tmp_path, fps, stride):
    capture, episode = capture_at(tmp_path, fps)
    stamps = [1_100_000_000+i*100_000_000 for i in range(5)]
    for sequence, stamp in enumerate(stamps, 2):
        frame(capture, stamp, sequence)
    result = capture.stop(episode['episode_id'], 'success')
    assert result['status'] == 'complete' and result['provenance']['fps'] == fps
    rows = [json.loads(line) for line in (tmp_path/episode['episode_id']/'samples.jsonl').read_text().splitlines()]
    assert [row['capture_time_ns'] for row in rows] == stamps[::stride]
    assert all(row['state_time_ns'] == row['capture_time_ns']-2_000_000 for row in rows)
    assert all(row['command_id'] == 'command' and row['action'] == [.02, -.1] for row in rows)


@pytest.mark.parametrize('stamp,issue', [(1_500_000_000, 'frame_gap'), (1_050_000_000, 'clock_not_advancing')])
def test_slower_capture_does_not_hide_a_missing_frame_or_clock_reversal(tmp_path, stamp, issue):
    capture, episode = capture_at(tmp_path, 5)
    frame(capture, 1_100_000_000, 2)
    frame(capture, stamp, 3)
    result = capture.stop(episode['episode_id'], 'success')
    assert result['status'] == 'incomplete' and issue in result['issues']


def test_failure_on_an_unsampled_frame_still_interrupts_capture(tmp_path):
    capture, _ = capture_at(tmp_path, 5)
    frame(capture, 1_100_000_000, 2)
    capture.on_goal_event(RosGoalEvent(kind='GOAL_REJECTED', command_id='command', phase_id=None,
        goal_id=None, observed_at_monotonic_s=time.monotonic(), sequence=2))
    frame(capture, 1_200_000_000, 3)
    assert 'goal_acceptance_or_result_unknown' in capture.status()['issues']


@pytest.mark.parametrize('fps', [0, True, 20])
def test_sampling_must_divide_the_fixed_ten_hz_camera(tmp_path, fps):
    with pytest.raises(ValueError, match='recording fps'):
        capture_at(tmp_path, fps)
