"""Real CDR/MCAP and video round-trip; independent of ROS and physical hardware."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'learning/curation/pinky'))
from test_pinky_episode import recording
from pinky_episode import convert
from verify_raw import verify
from prepare_behavior import prepare
from rosy.contracts.learning import seal

IMAGE = '''std_msgs/Header header
uint32 height
uint32 width
string encoding
uint8 is_bigendian
uint32 step
uint8[] data
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
'''
TWIST = '''geometry_msgs/Vector3 linear
geometry_msgs/Vector3 angular
================================================================================
MSG: geometry_msgs/Vector3
float64 x
float64 y
float64 z
'''


def native_recording(tmp_path, *, raw_linear=.02, mixed_namespace=False,
                     command_schema='geometry_msgs/msg/Twist'):
    pytest.importorskip('mcap_ros2'); cv2 = pytest.importorskip('cv2'); np = pytest.importorskip('numpy')
    from mcap_ros2.writer import Writer
    raw, metadata = recording(tmp_path)
    with (raw / 'bag/bag_0.mcap').open('wb') as stream:
        writer = Writer(stream); image = writer.register_msgdef('sensor_msgs/msg/Image', IMAGE)
        twist = writer.register_msgdef(command_schema, TWIST)
        for index in range(2):
            stamp = 1_000_000_000 + index * 100_000_000
            namespace = '/another' if mixed_namespace and index else '/fixture'
            writer.write_message(namespace + '/cmd_vel', twist, {
                'linear': {'x': raw_linear, 'y': 0., 'z': 0.}, 'angular': {'x': 0., 'y': 0., 'z': -.1}},
                log_time=stamp, publish_time=stamp)
            writer.write_message('/fixture/camera/front', image, {
                'header': {'stamp': {'sec': 1, 'nanosec': index * 100_000_000}, 'frame_id': 'front'},
                'height': 6, 'width': 8, 'encoding': 'rgb8', 'is_bigendian': 0,
                'step': 24, 'data': bytes([12, 34, 56] * 48)},
                log_time=stamp + 10_000_000, publish_time=stamp)
        writer.finish()
    video = metadata.parent / 'capture.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (8, 6))
    assert writer.isOpened()
    for _ in range(2):
        writer.write(np.full((6, 8, 3), [56, 34, 12], np.uint8))
    writer.release()
    doc = json.loads(metadata.read_text())
    doc['source'].update(bag_bytes=(raw / 'bag/bag_0.mcap').stat().st_size,
                         topics={'camera/front': 2, 'cmd_vel': 2}, skipped_frames=0)
    doc['video']['bytes'] = video.stat().st_size
    metadata.write_text(json.dumps(doc))
    return raw, metadata


def test_real_ros2_mcap_and_video_verify(tmp_path):
    raw, meta = native_recording(tmp_path)
    convert(raw, meta, tmp_path / 'common', environment='sim', clock_domain='gazebo_sim')
    result = verify(tmp_path / 'common')
    assert result['verdict'] == 'pass' and result['frames'] == result['decoded_video_frames'] == 2
    assert result['matched_side_frames'] == {'cmd_vel': 2}
    assert result['pixel_provenance'] == 'unverified'


def test_hash_consistent_sidecar_still_rejects_different_raw_command(tmp_path):
    raw, meta = native_recording(tmp_path, raw_linear=.03)
    convert(raw, meta, tmp_path / 'common', environment='sim', clock_domain='gazebo_sim')
    with pytest.raises(ValueError, match='raw cmd_vel'):
        verify(tmp_path / 'common')


def test_mixed_robot_namespace_rejected(tmp_path):
    raw, meta = native_recording(tmp_path, mixed_namespace=True)
    convert(raw, meta, tmp_path / 'common', environment='sim', clock_domain='gazebo_sim')
    with pytest.raises(ValueError, match='namespaces'):
        verify(tmp_path / 'common')


def test_native_preparation_keeps_research_holds(tmp_path):
    raw, meta = native_recording(tmp_path)
    episode = convert(raw, meta, tmp_path / 'common', environment='sim', clock_domain='gazebo_sim')
    result = prepare(tmp_path / 'common', tmp_path / 'inputs')
    assert result['episode_revision'] == episode['revision'] and result['split'] == 'unassigned'
    assert result['eligibility'] == 'research_input_only' and 'camera_profile' in result['holds']
    assert result['action']['semantics'] == 'recorded_core_final_velocity'
    assert (tmp_path / 'inputs/raw-verification.json').is_file()


def test_same_fields_with_wrong_ros_message_type_rejected(tmp_path):
    raw, meta = native_recording(tmp_path, command_schema='geometry_msgs/msg/TwistStamped')
    convert(raw, meta, tmp_path / 'common', environment='sim', clock_domain='gazebo_sim')
    with pytest.raises(ValueError, match='schema/encoding'):
        prepare(tmp_path / 'common', tmp_path / 'inputs')
    assert not (tmp_path / 'inputs').exists()


def test_omitted_source_files_rejected_even_with_resealed_manifest(tmp_path):
    raw, meta = native_recording(tmp_path)
    root = tmp_path / 'common'
    convert(raw, meta, root, environment='sim', clock_domain='gazebo_sim')
    path = root / 'dataset-manifest.json'
    manifest = json.loads(path.read_text())
    manifest['files'] = [item for item in manifest['files'] if item['path'] == 'episode.json']
    path.write_text(json.dumps(seal(manifest)))
    with pytest.raises(ValueError, match='dataset closure'):
        prepare(root, tmp_path / 'inputs')
    assert not (tmp_path / 'inputs').exists()
