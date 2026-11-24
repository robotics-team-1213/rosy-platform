"""Tests for 2-slot POSIX mmap front camera transport and DDS fallback."""
from __future__ import annotations

import errno
import os
import sys
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from control.camera_shm import (  # noqa: E402
    CameraFrontSource,
    CameraShmReader,
    CameraShmWriter,
    ShmImageFrame,
    default_camera_shm_path,
)


def _fake_node(params=None):
    params = dict(params or {})
    timers = []
    subs = []
    destroyed = []

    class _FakeNode:
        def has_parameter(self, name):
            return name in params

        def declare_parameter(self, name, value):
            params.setdefault(name, value)
            return SimpleNamespace(value=params[name])

        def get_parameter(self, name):
            return SimpleNamespace(value=params[name])

        def create_timer(self, period, cb):
            t = SimpleNamespace(period=period, cb=cb)
            timers.append(t)
            return t

        def create_subscription(self, *args):
            sub = SimpleNamespace(args=args)
            subs.append(sub)
            return sub

        def destroy_subscription(self, sub):
            destroyed.append(sub)

    return _FakeNode(), timers, subs, destroyed


def test_shm_writer_and_reader_roundtrip_and_seq_monotonicity(tmp_path):
    shm = tmp_path / "front.bgr"
    writer = CameraShmWriter(str(shm), slot_bytes=4096)
    reader = CameraShmReader(str(shm))
    try:
        frame1 = np.arange(2 * 3 * 3, dtype=np.uint8).reshape((2, 3, 3))
        seq1 = writer.write(frame1, 100.25, frame_id="cam_front")
        out1 = reader.read_latest(0)
        assert out1 is not None
        rseq1, w, h, c, stamp_ns, fid, raw1 = out1
        assert (rseq1, w, h, c, fid) == (seq1, 3, 2, 3, "cam_front")
        assert stamp_ns == 100_250_000_000
        assert raw1 == frame1.tobytes()
        assert reader.read_latest(rseq1) is None

        frame2 = (frame1 + 7).astype(np.uint8)
        seq2 = writer.write(frame2, 100.375, frame_id="cam_front")
        assert seq2 > seq1
        out2 = reader.read_latest(rseq1)
        assert out2 is not None and out2[0] == seq2 and out2[6] == frame2.tobytes()
    finally:
        reader.close()
        writer.close()


def test_shm_writer_and_reader_reject_symlinks(tmp_path):
    target = tmp_path / "real.bgr"
    target.write_bytes(b"\x00" * 256)
    link = tmp_path / "front.bgr"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(OSError) as excinfo:
        CameraShmWriter(str(link), slot_bytes=4096)
    assert excinfo.value.errno in (errno.ELOOP, errno.EEXIST, errno.EPERM, errno.EINVAL)
    # Init failure must release .owner fd/flock so a clean path replacement can immediately acquire ownership.
    link.unlink()
    clean = CameraShmWriter(str(link), slot_bytes=4096)
    clean.close()
    reader = CameraShmReader(str(link))
    assert reader.read_latest(0) is None
    reader.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX unlink-while-open semantics")
def test_shm_reader_detects_writer_restart_via_inode_change(tmp_path):
    shm = tmp_path / "front.bgr"
    w1 = CameraShmWriter(str(shm), slot_bytes=4096)
    reader = CameraShmReader(str(shm))
    try:
        f1 = np.full((2, 2, 3), 11, dtype=np.uint8)
        s1 = w1.write(f1, 1.0)
        assert reader.read_latest(0)[6] == f1.tobytes()
        w1.close()
        shm.unlink()
        w2 = CameraShmWriter(str(shm), slot_bytes=4096)
        try:
            f2 = np.full((2, 2, 3), 22, dtype=np.uint8)
            w2.write(f2, 2.0)
            out = reader.read_latest(s1)
            assert out is not None and out[6] == f2.tobytes()
        finally:
            w2.close()
    finally:
        reader.close()


def test_camera_front_source_shm_primary_and_dds_fallback_teardown(tmp_path):
    shm = tmp_path / "front.bgr"
    node, timers, subs, destroyed = _fake_node({"camera_shm_path": str(shm)})
    now = [0.0]
    received = []
    source = CameraFrontSource(
        node,
        received.append,
        lambda: node.create_subscription("dds"),
        shm_path=None,
        fallback_after_s=1.0,
        stale_after_s=1.5,
        clock=lambda: now[0],
    )
    try:
        assert not source.dds_active and len(timers) == 1
        now[0] = 1.2
        timers[0].cb()
        assert source.dds_active and len(subs) == 1

        writer = CameraShmWriter(str(shm), slot_bytes=4096)
        try:
            frame = np.full((2, 3, 3), 42, dtype=np.uint8)
            writer.write(frame, 50.5, frame_id="front")
            now[0] = 1.3
            timers[0].cb()
            assert len(received) == 1
            assert isinstance(received[0], ShmImageFrame)
            assert received[0].data == frame.tobytes()
            assert source.dds_active  # waits for 2nd contiguous SHM hit before tearing down DDS
            writer.write(frame, 50.625, frame_id="front")
            now[0] = 1.4
            timers[0].cb()
            assert not source.dds_active and len(destroyed) == 1
        finally:
            writer.close()
    finally:
        source.close()


def test_default_camera_shm_path_rollback_env(monkeypatch):
    monkeypatch.delenv("ROSY_CAMERA_SHM_PATH", raising=False)
    assert default_camera_shm_path() == "/run/rosy-media/front.bgr"
    for off in ("", "0", "off", "false", "none"):
        monkeypatch.setenv("ROSY_CAMERA_SHM_PATH", off)
        assert default_camera_shm_path() == ""
    monkeypatch.setenv("ROSY_CAMERA_SHM_PATH", "/tmp/custom.bgr")
    assert default_camera_shm_path() == "/tmp/custom.bgr"

def test_camera_front_source_env_off_uses_pure_dds(monkeypatch):
    monkeypatch.setenv("ROSY_CAMERA_SHM_PATH", "off")
    node, timers, subs, _ = _fake_node()
    source = CameraFrontSource(node, lambda _m: None, lambda: node.create_subscription("dds"))
    try:
        assert source.dds_active and len(subs) == 1 and len(timers) == 0
    finally:
        source.close()


def test_camera_detect_node_skips_dds_when_no_subscribers_and_keeps_jpeg_header(tmp_path):
    from pathlib import Path
    import numpy as np
    from control.camera_shm import open_camera_shm_writer, publish_camera_front_frame

    class FakeImage:
        def __init__(self):
            self.header = SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0), frame_id="")
            self.height = 0
            self.width = 0
            self.encoding = ""
            self.is_bigendian = 0
            self.step = 0
            self.data = b""

    class FakeCompressedImage:
        def __init__(self):
            self.header = SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=0), frame_id="")
            self.format = ""
            self.data = b""

    detect_src = (Path(__file__).resolve().parents[1] / "sensor_nodes" / "camera_detect_node.py").read_text(encoding="utf-8")
    assert "publish_camera_front_frame(" in detect_src and "open_camera_shm_writer(" in detect_src

    shm = tmp_path / "front.bgr"
    params = {"camera_shm_path": str(shm), "camera_frame": "cam_link"}
    raw_published = []
    jpeg_published = []
    sub_count = [0]
    fake_node = SimpleNamespace(
        has_parameter=lambda n: n in params,
        get_parameter=lambda n: SimpleNamespace(value=params[n]),
        get_logger=lambda: SimpleNamespace(warn=lambda *a, **k: None),
        img_pub=SimpleNamespace(get_subscription_count=lambda: sub_count[0], publish=raw_published.append),
        jpeg_pub=SimpleNamespace(publish=jpeg_published.append),
        _jpeg_quality=80,
    )
    fake_node._shm_writer = open_camera_shm_writer(fake_node)
    reader = CameraShmReader(str(shm))
    try:
        frame = np.full((2, 3, 3), 99, dtype=np.uint8)
        publish_camera_front_frame(
            fake_node, frame, 42.5,
            image_cls=FakeImage, compressed_cls=FakeCompressedImage,
            encode_jpeg_fn=lambda _bgr, _q: (b"\xff\xd8jpg", "jpeg"),
        )
        assert raw_published == []
        assert len(jpeg_published) == 1
        assert (jpeg_published[0].header.stamp.sec, jpeg_published[0].header.stamp.nanosec) == (42, 500_000_000)
        assert jpeg_published[0].header.frame_id == "cam_link"
        out = reader.read_latest(0)
        assert out is not None and out[6] == frame.tobytes()

        sub_count[0] = 1
        publish_camera_front_frame(
            fake_node, frame, 43.25,
            image_cls=FakeImage, compressed_cls=FakeCompressedImage,
            encode_jpeg_fn=lambda _bgr, _q: (b"\xff\xd8jpg", "jpeg"),
        )
        assert len(raw_published) == 1
    finally:
        reader.close()
        fake_node._shm_writer.close()
