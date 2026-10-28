"""D-789 T3: the camera owner feeds an independent 640x480 media branch, never an upscale."""

import importlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT / 'src'))
NODE = REPO / 'middleware/perception/nodes/camera_detect_node.py'


def module():
    assert (ROOT / 'src/rosy_media_edge/camera_tap.py').is_file(), 'D-789 camera media branch missing'
    return importlib.import_module('rosy_media_edge.camera_tap')


class Writer:
    def __init__(self, path, result=True):
        self.path, self.frames, self.result = path, [], result

    def offer(self, rgb, **identity):
        if isinstance(self.result, Exception):
            raise self.result
        self.frames.append((rgb, identity))
        return self.result

    def close(self):
        pass


class Request:
    def __init__(self, arrays):
        self.arrays, self.released = arrays, False

    def make_array(self, name):
        return self.arrays[name]

    def release(self):
        self.released = True


class Cam:
    def __init__(self, arrays=None):
        self.requests, self.arrays, self.configs, self.stopped = [], arrays, [], False

    def capture_request(self):
        self.requests.append(Request(self.arrays))
        return self.requests[-1]

    def capture_array(self, name='main'):
        return ('direct', name)

    def create_preview_configuration(self, **config):
        self.configs.append(config)
        return config

    def stop(self):
        self.stopped = True


def frames():
    main = np.zeros((480, 640, 3), np.uint8)
    main[0, 0] = (1, 2, 3)          # BGR top-left
    main[479, 639] = (7, 8, 9)      # BGR bottom-right
    return {'main': main, 'lores': np.full((240, 320, 3), 5, np.uint8)}


def tap(rotate=180, writer=None):
    holder = []
    made = module().CameraMediaTap('/run/rosy-media/front.rgb', rotate_deg=rotate, clock=lambda: 1000.5,
        writer_factory=lambda path: holder.append(writer or Writer(path)) or holder[-1])
    return made, holder[0]


def test_one_request_feeds_perception_lores_and_media_main():
    media, writer = tap()
    cam = Cam(frames())
    wrapped = module().TapCamera(cam, media)
    perception = wrapped.capture_array('main')
    assert perception.shape == (240, 320, 3)
    assert len(cam.requests) == 1 and cam.requests[0].released
    rgb, identity = writer.frames[0]
    assert len(rgb) == 640 * 480 * 3
    assert identity == {'epoch': 1000, 'sequence': 1, 'captured_ms': 1000500}
    # 180 degrees: the old bottom-right is now top-left, and BGR became RGB.
    assert tuple(rgb[:3]) == (9, 8, 7)
    assert tuple(rgb[-3:]) == (3, 2, 1)
    wrapped.stop()
    assert cam.stopped                               # everything else reaches the real camera


def test_upright_camera_only_swaps_channels():
    media, writer = tap(rotate=0)
    media.offer(frames()['main'])
    assert tuple(writer.frames[0][0][:3]) == (3, 2, 1)


@pytest.mark.parametrize('shape', [(240, 320, 3), (480, 640), (960, 1280, 3)])
def test_non_native_640x480_frames_are_refused_not_scaled(shape):
    media, writer = tap()
    assert media.offer(np.zeros(shape, np.uint8)) is False
    assert writer.frames == []


@pytest.mark.parametrize('failure', [False, OSError('busy'), ValueError('bad')])
def test_media_consumer_trouble_never_breaks_the_capture_tick(failure):
    media, _ = tap(writer=Writer('x', failure))
    assert module().TapCamera(Cam(frames()), media).capture_array('main').shape == (240, 320, 3)


def test_configuration_keeps_perception_size_and_rate():
    cam = Cam()
    wrapped = module().TapCamera(cam, None)
    config = wrapped.create_preview_configuration(main={'size': (320, 240), 'format': 'RGB888'},
                                                  controls={'FrameRate': 8.0})
    assert config == {'main': {'size': (640, 480), 'format': 'RGB888'},
                      'lores': {'size': (320, 240), 'format': 'RGB888'}, 'controls': {'FrameRate': 8.0}}
    with pytest.raises(ValueError):
        wrapped.create_preview_configuration(main={'size': (800, 600), 'format': 'RGB888'})


class Node:
    def __init__(self, rotate=180):
        self.logs, self.rotate = [], rotate

    def get_parameter(self, name):
        assert name == 'rotate_deg'
        return type('P', (), {'value': self.rotate})()

    def get_logger(self):
        return type('L', (), {'warn': lambda _, line: self.logs.append(line)})()


def test_unconfigured_robot_keeps_the_plain_camera(tmp_path):
    node, cam = Node(), Cam()
    assert module().media_camera(cam, node, config=tmp_path / 'absent.json') is cam
    assert node.logs == []


def test_bad_media_config_logs_and_keeps_the_plain_camera(tmp_path):
    config = tmp_path / 'rosy-media.json'
    config.write_text(json.dumps({'mailbox': str(tmp_path / 'front.rgb')}))
    node, cam = Node(rotate=90), Cam()
    assert module().media_camera(cam, node, config=config) is cam
    assert node.logs and node.logs[0].startswith('media branch off')


def test_configured_robot_opens_one_mailbox_across_camera_restarts(tmp_path):
    pytest.importorskip('fcntl')
    from rosy_media_edge.source import FrameReader
    config = tmp_path / 'rosy-media.json'
    config.write_text(json.dumps({'mailbox': str(tmp_path / 'front.rgb')}))
    node = Node()
    first = module().media_camera(Cam(frames()), node, config=config)
    second = module().media_camera(Cam(frames()), node, config=config)   # restart: same writer
    try:
        assert first._tap is second._tap
        assert first.capture_array('main').shape == (240, 320, 3)
        with FrameReader(tmp_path / 'front.rgb') as reader:
            frame = reader.latest()
        assert frame.sequence == 1 and bytes(frame.rgb[:3]) == bytes((9, 8, 7))
    finally:
        node._media_tap.close()


def test_camera_owner_opens_the_device_once_and_media_never_opens_a_camera():
    node = NODE.read_text(encoding='utf-8')
    assert node.count('Picamera2()') == 2      # one construction, written for both branches
    assert 'media_camera(Picamera2(), self) if media_camera else Picamera2()' in node
    source = (ROOT / 'src/rosy_media_edge/camera_tap.py').read_text(encoding='utf-8')
    for forbidden in ('Picamera2(', 'VideoCapture', 'resize', 'rclpy'):
        assert forbidden not in source
