"""USB bandwidth and disconnect regressions without opening a camera or ROS."""
from types import SimpleNamespace

import pytest

from omx_adapter.camera_source import open_capture, read_frame, selected_device


class Capture:
    def __init__(self):
        self.values = {}
        self.released = False
        self.frame = SimpleNamespace(shape=(480, 640, 3))

    def isOpened(self):
        return True

    def set(self, key, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key, 0)

    def read(self):
        return self.frame is not None, self.frame

    def release(self):
        self.released = True


@pytest.fixture
def camera():
    cap = Capture()
    cv = SimpleNamespace(CAP_V4L2=200, CAP_PROP_FOURCC=6, CAP_PROP_FRAME_WIDTH=3,
                         CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_BUFFERSIZE=38,
                         VideoWriter_fourcc=lambda *chars: 1196444237,
                         VideoCapture=lambda device, backend: cap)
    return cv, cap


def test_usb_capture_uses_mjpeg_and_one_buffer(camera):
    cv, cap = camera
    assert open_capture(cv, "/dev/v4l/by-id/selected-camera") is cap
    assert cap.values == {6: 1196444237, 3: 640, 4: 480, 38: 1}
    assert read_frame(cap) is cap.frame


def test_driver_cannot_silently_fall_back_to_raw_usb_bandwidth(camera):
    cv, cap = camera
    cap.get = lambda key: 0 if key == cv.CAP_PROP_FOURCC else cap.values[key]
    with pytest.raises(OSError, match="capture format"):
        open_capture(cv, "/dev/v4l/by-id/selected-camera")
    assert cap.released


@pytest.mark.parametrize("frame", [None, SimpleNamespace(shape=(720, 1280, 3))])
def test_disconnected_or_changed_frame_closes_device_for_reopen(camera, frame):
    _, cap = camera
    cap.frame = frame
    with pytest.raises(OSError, match="frame unavailable"):
        read_frame(cap)
    assert cap.released


def test_numeric_device_selection_is_refused_before_open():
    with pytest.raises(ValueError, match="persistent"):
        selected_device("/dev/video2")


def test_unplugged_persistent_device_is_retryable(monkeypatch):
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_symlink", lambda path: False)
    monkeypatch.setattr("omx_adapter.camera_source.Path.exists", lambda path: False)
    with pytest.raises(OSError, match="unavailable"):
        selected_device("/dev/v4l/by-id/unplugged-camera")
