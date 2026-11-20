"""Prove the camera never attaches one buffer's timestamp to another buffer."""

import ctypes
import shutil
import subprocess
import sys

import pytest

from pathlib import Path
from types import SimpleNamespace

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
ADAPTER = OMX.parents[2] / "middleware/devices/omx/adapter/omx_adapter"
sys.path[:0] = [str(OMX), str(ADAPTER)]
from camera_exposure import Buffer, Format, RgbExposureCapture, DQBUF, QBUF, S_FMT


def test_exposure_entrypoint_publishes_the_matching_snapshot(monkeypatch, tmp_path):
    import camera_exposure as app
    import camera_source
    from core_common.observation_snapshot import SnapshotChannel

    events, frame = [], object()
    metadata = {"boot_id": "native-boot", "clock_semantics": "v4l2_monotonic_start_of_exposure",
                "exposure_monotonic_s": app.time.monotonic() - 0.05, "source_seq": 3}
    monkeypatch.setenv("ROSY_OBSERVATION_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["camera_exposure", "--device", "/dev/v4l/by-id/cam",
                                    "--topic", "/top", "--frame-id", "top"])
    monkeypatch.setattr(camera_source, "selected_device", lambda name: name)
    monkeypatch.setattr(camera_source, "notify_watchdog", lambda: events.append("watchdog"))
    monkeypatch.setattr(app, "RgbExposureCapture",
                        lambda *_: SimpleNamespace(release=lambda: events.append("release")))
    monkeypatch.setattr(app, "read_exposure_frame", lambda *_: (frame, metadata))
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(
        imencode=lambda *_: (True, SimpleNamespace(tobytes=lambda: b"jpeg")),
        IMWRITE_JPEG_QUALITY=1, error=RuntimeError))
    monkeypatch.setitem(sys.modules, "core_common.camera_quality",
                        SimpleNamespace(frame_quality=lambda _: {"source": "original"}))

    def stop(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(app.time, "sleep", stop)
    app.main()
    sample = SnapshotChannel("/top").read()
    assert sample["payload"] == b"jpeg"
    assert sample["quality"] == dict(metadata, source="original")
    assert events == ["watchdog", "release"]


def camera(flags, *, recorded=23):
    capture = RgbExposureCapture.__new__(RgbExposureCapture)
    capture._buffers = [b"discard", b"matching"]
    capture._limits = [7, 8]
    capture._last_sequence = None
    capture._last_stamp = None
    capture._ready = lambda: True
    capture._clock = lambda: 24.0
    capture._boot_id = "same-boot"
    calls = []

    def ioctl(op, buffer):
        calls.append(op)
        if op == DQBUF:
            buffer.index, buffer.bytesused, buffer.sequence, buffer.flags = 1, 8, 42, flags
            buffer.timestamp.sec = recorded
            buffer.timestamp.usec = 250_000
        elif op == QBUF:
            assert buffer.index == 1 and buffer.flags == buffer.reserved2 == buffer.request_fd == 0

    capture._ioctl = ioctl
    return capture, calls


def test_exact_bytes_and_monotonic_exposure_share_the_driver_buffer():
    capture, calls = camera(0x12000)
    raw, metadata = capture.read()
    assert raw == b"matching" and calls == [DQBUF, QBUF]
    assert metadata == {"boot_id": "same-boot", "source_seq": 42, "exposure_monotonic_s": 23.25,
                        "clock_semantics": "v4l2_monotonic_start_of_exposure"}


def test_camera_initialization_maps_driver_buffers_with_v4l2_protections(monkeypatch):
    import camera_exposure as app

    mappings = []
    for key, value in {"MAP_SHARED": 1, "PROT_READ": 2, "PROT_WRITE": 4}.items():
        monkeypatch.setattr(app.mmap, key, value, raising=False)

    def map_buffer(fd, size, **options):
        mappings.append((fd, size, options))
        return b""

    def ioctl(op, arg):
        if op == app.REQBUFS:
            arg.count = 1
        elif op == app.QUERYBUF:
            arg.length = 4096
            arg.address.offset = 8192

    monkeypatch.setattr(app.mmap, "mmap", map_buffer)
    capture = RgbExposureCapture.__new__(RgbExposureCapture)
    capture._fd, capture._buffers, capture._limits, capture._ioctl = 5, [], [], ioctl
    capture._configure("MJPG")
    assert mappings == [(5, 4096, {"flags": 1, "prot": 6, "offset": 8192})]


@pytest.mark.parametrize("flags", [0, 0x2000, 0x10000, 0x14000, 0x12040])
def test_refuse_non_exposure_or_corrupted_buffers_but_return_them(flags):
    capture, calls = camera(flags)
    with pytest.raises(OSError, match="exposure"):
        capture.read()
    assert calls == [DQBUF, QBUF]


def test_refuse_future_and_repeated_driver_samples():
    capture, _ = camera(0x12000, recorded=24)
    with pytest.raises(OSError, match="exposure"):
        capture.read()
    capture, _ = camera(0x12000)
    capture.read()
    with pytest.raises(OSError, match="exposure"):
        capture.read()


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("cc"), reason="native Linux ABI check needs cc")
def test_ioctl_layout_matches_the_installed_kernel_headers(tmp_path):
    code = tmp_path / "layout.c"
    binary = tmp_path / "layout"
    code.write_text(r"""
        #include <linux/videodev2.h>
        #include <stddef.h>
        #include <stdio.h>
        int main(void) {
            printf("%zu %zu %zu %zu %lu %lu %lu\n", sizeof(struct v4l2_format),
                   sizeof(struct v4l2_buffer), offsetof(struct v4l2_buffer, timestamp),
                   offsetof(struct v4l2_buffer, m), (unsigned long)VIDIOC_S_FMT,
                   (unsigned long)VIDIOC_DQBUF, (unsigned long)VIDIOC_QBUF);
        }
    """)
    subprocess.run(["cc", str(code), "-o", str(binary)], check=True, timeout=20)
    expected = tuple(map(int, subprocess.check_output([str(binary)], text=True, timeout=5).split()))
    assert expected == (ctypes.sizeof(Format), ctypes.sizeof(Buffer), Buffer.timestamp.offset,
                        Buffer.address.offset, S_FMT, DQBUF, QBUF)


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("systemd-analyze"),
                    reason="native camera unit syntax needs systemd-analyze")
def test_camera_unit_passes_systemd_verification():
    subprocess.run(["systemd-analyze", "verify", str(OMX / "rosy-omx-camera@.service")],
                   check=True, timeout=20)
