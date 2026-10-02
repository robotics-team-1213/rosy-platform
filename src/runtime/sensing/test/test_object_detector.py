"""D-423 §2: the object detector core behind object_detector_node -- rate cap, seq, status, ranges."""
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from control.object_detector import TOPIC, STATUS_TOPIC, BoxRanger, ObjectDetectorCore
from control.sensing.body import LIDAR_X
from control.sensing.lidar import NOSE_YAW
from control.sensing.perception.camera_ground import nominal_ground_plane
from control.sensing.perception.learned.detector import DetectResult

PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "products" / "pinky_pro" / "profile"
                          / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
FRAME = np.zeros((240, 320, 3), np.uint8)
CONE = dict(label='cone', x=140 / 320, y=20 / 240, w=40 / 320, h=55 / 240, confidence=0.9,
            bbox_xyxy=[140, 20, 180, 75])


class FakeModel:
    model_revision = 'object-det-r1'

    def __init__(self, detections=(CONE,), fail=False):
        self.detections, self.fail, self.calls = list(detections), fail, 0

    def infer(self, bgr):
        self.calls += 1
        if self.fail:
            raise RuntimeError('session died')
        return DetectResult(self.detections, 12.0, self.model_revision)


class FakeSlot:
    def __init__(self, model=None, error=None):
        self.current, self.last_error = model, error

    def poll(self):
        return self.current


def core(model=FakeModel(), **kw):
    return ObjectDetectorCore(FakeSlot(model), max_rate_hz=kw.pop('max_rate_hz', 2.0),
                              camera_fps=8.0, **kw)


def test_topics_are_advisory_names_core_does_not_read():
    """D-137: CORE reads detection_evidence; vision/detections is display and training only."""
    assert TOPIC == 'vision/detections'
    assert STATUS_TOPIC == 'perception/learned/object_det/status'
    gateway = Path(__file__).resolve().parents[3] / 'runtime'
    readers = [p for p in gateway.rglob('*.py') if '/test' not in p.as_posix()
               and 'vision/detections' in p.read_text(encoding='utf-8', errors='ignore')
               and 'sensing' not in p.relative_to(gateway).parts[0]]
    assert readers == []


def test_packet_per_inferred_frame_with_contiguous_seq():
    c = core()
    first = c.on_frame(FRAME, stamp=10.0, now=100.0)
    assert first['seq'] == 0 and first['model_revision'] == 'object-det-r1'
    assert first['detections'][0]['label'] == 'cone' and 'ranges' not in first
    assert c.on_frame(FRAME, stamp=10.1, now=100.1) is None           # under the 2 Hz cap
    second = c.on_frame(FRAME, stamp=10.6, now=100.6)
    assert second['seq'] == 1                                         # a skip is not a loss
    status = c.status_payload()
    assert status['model_revision'] == 'object-det-r1'
    assert status['frames_inferred'] == 2 and status['frames_rate_limited'] == 1


def test_no_model_publishes_nothing_and_says_so():
    c = ObjectDetectorCore(FakeSlot(None, error='pointer: missing'), max_rate_hz=2.0, camera_fps=8.0)
    assert c.on_frame(FRAME, stamp=1.0, now=1.0) is None
    status = c.status_payload()
    assert status['model_revision'] is None and status['last_error'] == 'pointer: missing'


def test_inference_failure_is_reported_not_raised():
    c = core(FakeModel(fail=True))
    assert c.on_frame(FRAME, stamp=1.0, now=1.0) is None
    assert 'session died' in c.status_payload()['last_error']


def plane():
    return nominal_ground_plane(source='NOMINAL', allowed=True, width_px=320, height_px=240,
                                profile=PROFILE)


def ranger():
    return BoxRanger(plane(), frame_size=(320, 240), camera_x_m=PROFILE['x_offset_m'], nose_rad=NOSE_YAW, lidar_x_m=LIDAR_X,
                     max_age_s=0.3, tolerance_m=0.05, tolerance_ratio=0.2)


def scan(ranger_, stamp, ahead_m):
    ranges = [math.inf] * 720
    ranges[360] = ahead_m
    ranger_.set_scan(ranges, 0.0, 2 * math.pi / 720, 0.05, 12.0, stamp=stamp)


def test_ranges_follow_the_detections_from_a_fresh_scan():
    r = ranger()
    scan(r, 10.0, 0.6)
    packet = core(ranger=r).on_frame(FRAME, stamp=10.1, now=1.0)
    assert packet['ranges'] == [{'m': pytest.approx(round(0.6 + LIDAR_X - PROFILE['x_offset_m'], 3)),
                                 's': 'L'}]


def test_a_stale_scan_leaves_only_the_floor_answer():
    r = ranger()
    scan(r, 10.0, 0.6)
    packet = core(ranger=r).on_frame(FRAME, stamp=11.0, now=1.0)
    assert packet['ranges'] == [None]          # the cone sits above the horizon: no floor answer


def test_a_frame_of_another_size_is_not_ranged_with_this_plane():
    r = ranger()
    scan(r, 10.0, 0.6)
    packet = core(ranger=r).on_frame(np.zeros((480, 640, 3), np.uint8), stamp=10.1, now=1.0)
    assert packet['ranges'] == [None]


@pytest.fixture
def node_module(monkeypatch, tmp_path):
    """object_detector_node imported against rclpy stubs (only when ROS is absent)."""
    import importlib
    import sys
    import types
    if 'rclpy' not in sys.modules:
        stubs = {
            'rclpy': types.ModuleType('rclpy'),
            'rclpy.node': types.SimpleNamespace(Node=object),
            'rclpy.qos': types.SimpleNamespace(DurabilityPolicy=None, QoSProfile=None,
                                               ReliabilityPolicy=None, qos_profile_sensor_data=None),
            'sensor_msgs': types.ModuleType('sensor_msgs'),
            'sensor_msgs.msg': types.SimpleNamespace(Image=None, LaserScan=None),
            'std_msgs': types.ModuleType('std_msgs'),
            'std_msgs.msg': types.SimpleNamespace(String=None),
        }
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv('ROSY_CALIBRATION_ROOT', str(tmp_path / 'store'))
    loaded = ('control.object_detector_node', 'control.executor_choice')
    saved = {name: sys.modules.pop(name) for name in loaded if name in sys.modules}
    yield importlib.import_module('control.object_detector_node')
    for name in loaded:
        sys.modules.pop(name, None)
    sys.modules.update(saved)


def fake_node(subscriptions):
    import types
    logger = types.SimpleNamespace(info=lambda *a, **k: None, warn=lambda *a, **k: None)
    return types.SimpleNamespace(get_logger=lambda: logger, _on_scan=None,
                                 create_subscription=lambda *a: subscriptions.append(a))


@pytest.mark.parametrize('params,expect_ranger,expect_scan', [
    ({}, False, False),                                                     # no profile: unranged
    ({'allow_nominal_ground': False}, False, False),                        # second opt-in missing
    ({'allow_nominal_ground': True}, True, False),                          # floor only
    ({'allow_nominal_ground': True, 'region_lidar_range': True}, True, True),
])
def test_node_ranger_needs_the_same_two_opt_ins_as_camera_detect(node_module, tmp_path, params,
                                                                 expect_ranger, expect_scan):
    profile = tmp_path / 'camera_nominal.yaml'
    profile.write_text(yaml.safe_dump(PROFILE), encoding='utf-8')
    values = dict(params)
    if params:
        values['nominal_camera_profile_path'] = str(profile)
    subscriptions = []
    ranger_ = node_module.ObjectDetectorNode._ranger(fake_node(subscriptions),
                                                     lambda name, default: values.get(name, default))
    assert (ranger_ is not None) is expect_ranger
    assert [s[1] for s in subscriptions] == (['scan'] if expect_scan else [])


def test_node_opens_models_through_the_signature_check():
    """D-423 §3.4: unsigned object_det bundles are refused unless allow_unsigned_models (dev)."""
    source = (Path(__file__).resolve().parents[1] / 'control' / 'object_detector_node.py').read_text(
        encoding='utf-8')
    assert "checked_opener(" in source
    assert "p('allow_unsigned_models', False)" in source
    assert "p('trusted_keys_dir', TRUSTED_KEYS)" in source
