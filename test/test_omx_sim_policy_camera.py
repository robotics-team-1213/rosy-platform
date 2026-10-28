"""Original camera bytes/clock boundary, without ROS or Gazebo execution."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('middleware/robot_execution/local/test','deploy/robot/omx',
                                  'learning/training/omx')]
from test_omx_policy_session import setup_session
from sim_policy_camera import SimPolicyCamera, packet_from_message


def image():
    return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=10,nanosec=0),
                                                 frame_id='workcell_camera_optical'),
        encoding='rgb8',height=240,width=320,step=960,data=bytearray(320*240*3))


def test_receipt_clock_and_source_stamp_remain_distinct_and_bytes_are_frozen():
    message=image()
    packet=packet_from_message(message,sim_now_ns=10_030_000_000,owner_received_ns=99_000_000_000)
    message.data[0]=255
    assert packet.rgb[0]==0
    assert packet.source_stamp_ns==10_000_000_000
    assert packet.metadata.received_at_ns==99_000_000_000
    assert packet.metadata.source_shape==(3,240,320)


@pytest.mark.parametrize('change',[dict(encoding='bgr8'),dict(width=319),dict(step=961),
                                  dict(data=b'bad')])
def test_wrong_camera_layout_cannot_be_silently_converted(change):
    message=image()
    for key,value in change.items():setattr(message,key,value)
    with pytest.raises(ValueError):
        packet_from_message(message,sim_now_ns=10_030_000_000,owner_received_ns=99_000_000_000)


@pytest.mark.parametrize('now',[9_999_999_999,10_500_000_001])
def test_future_or_stale_source_frame_is_refused(now):
    with pytest.raises(ValueError):
        packet_from_message(image(),sim_now_ns=now,owner_received_ns=99_000_000_000)


def camera_without_ros():
    camera=object.__new__(SimPolicyCamera)
    camera._lock=threading.RLock()
    camera._latest=packet_from_message(image(),sim_now_ns=10_030_000_000,
                                      owner_received_ns=99_000_000_000)
    camera.error=None
    camera.captures=[]
    return camera


def test_fresh_selection_retries_preserve_original_packet_and_every_audit_record():
    camera=camera_without_ros()
    original=camera._latest
    for _ in range(1001):
        with camera.capture() as packet:
            assert packet is original
    assert len(camera.captures)==1001
    assert all(record==dict(frame_sha256=original.metadata.frame_sha256,
        received_owner_ns=99_000_000_000,source_sim_ns=10_000_000_000)
        for record in camera.captures)


def test_capture_audit_limit_refuses_without_dropping_or_appending_records():
    from sim_policy_camera import MAX_CAPTURE_RECORDS
    camera=camera_without_ros()
    camera.captures=[dict(existing=True)]*MAX_CAPTURE_RECORDS
    with pytest.raises(RuntimeError,match='bounded policy capture limit'):
        with camera.capture():
            pytest.fail('capture beyond the declared bound was yielded')
    assert len(camera.captures)==MAX_CAPTURE_RECORDS
    assert all(record==dict(existing=True) for record in camera.captures)
