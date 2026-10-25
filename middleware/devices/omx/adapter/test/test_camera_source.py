"""USB bandwidth and disconnect regressions without opening a camera or ROS."""
from types import SimpleNamespace

import pytest

from omx_adapter.camera_source import main, open_capture, read_frame, selected_device


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


def test_driver_cannot_keep_a_hidden_frame_backlog(camera):
    cv, cap = camera
    cap.get = lambda key: 4 if key == cv.CAP_PROP_BUFFERSIZE else cap.values[key]
    with pytest.raises(OSError, match="one-frame"):
        open_capture(cv, "/dev/v4l/by-id/selected-camera")
    assert cap.released


@pytest.mark.parametrize("frame", [None, SimpleNamespace(shape=(720, 1280, 3))])
def test_disconnected_or_changed_frame_closes_device_for_reopen(camera, frame):
    _, cap = camera
    cap.frame = frame
    with pytest.raises(OSError, match="frame unavailable"):
        read_frame(cap)
    assert cap.released


@pytest.mark.parametrize("device", [
    "/dev/video2", "0", "dev/v4l/by-path/camera", "/tmp/camera",
    "/dev/v4l/by-path/../camera", "/dev/v4l/by-path/nested/camera",
])
def test_untrusted_device_selection_is_refused_before_open(device):
    with pytest.raises(ValueError, match="persistent"):
        selected_device(device)


@pytest.mark.parametrize("directory", ["by-id", "by-path"])
def test_persistent_camera_symlink_to_character_device_is_accepted(monkeypatch, directory):
    monkeypatch.setattr("omx_adapter.camera_source.Path.exists", lambda path: True)
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_symlink", lambda path: True)
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_char_device", lambda path: True)
    device = f"/dev/v4l/{directory}/selected-camera"
    assert selected_device(device) == device


@pytest.mark.parametrize("directory", ["by-id", "by-path"])
@pytest.mark.parametrize("symlink,character,error", [(False, True, ValueError), (True, False, OSError)])
def test_persistent_selector_requires_symlink_and_character_device(monkeypatch, directory, symlink, character, error):
    monkeypatch.setattr("omx_adapter.camera_source.Path.exists", lambda path: True)
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_symlink", lambda path: symlink)
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_char_device", lambda path: character)
    with pytest.raises(error):
        selected_device(f"/dev/v4l/{directory}/selected-camera")


@pytest.mark.parametrize("directory", ["by-id", "by-path"])
def test_unplugged_persistent_device_is_retryable(monkeypatch, directory):
    monkeypatch.setattr("omx_adapter.camera_source.Path.is_symlink", lambda path: False)
    monkeypatch.setattr("omx_adapter.camera_source.Path.exists", lambda path: False)
    with pytest.raises(OSError, match="unavailable"):
        selected_device(f"/dev/v4l/{directory}/unplugged-camera")


@pytest.mark.parametrize("fps", ["0", "-1", "31"])
def test_frame_rate_cap_is_bounded_before_ros_starts(monkeypatch, fps):
    from omx_adapter import camera_source
    monkeypatch.setattr("sys.argv", ["camera_source", "--device", "/dev/v4l/by-id/cam",
                                     "--topic", "/omx/top", "--frame-id", "top", "--max-fps", fps])
    with pytest.raises(SystemExit):
        camera_source.main()


def test_cli_accepts_persistent_by_path_before_optional_ros_imports(monkeypatch):
    import builtins
    original_import = builtins.__import__

    def stop_at_camera_import(name, *args, **kwargs):
        if name == "cv2":
            raise RuntimeError("camera arguments accepted")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("sys.argv", ["camera_source", "--device", "/dev/v4l/by-path/selected-camera",
                                     "--topic", "/arm_a_wrist_camera/image_raw", "--frame-id", "arm_a_wrist"])
    monkeypatch.setattr(builtins, "__import__", stop_at_camera_import)
    with pytest.raises(RuntimeError, match="camera arguments accepted"):
        main()
