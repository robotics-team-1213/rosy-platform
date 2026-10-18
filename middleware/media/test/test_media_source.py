"""The capture owner never waits for its media consumer."""

import importlib
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media_edge/source.py').is_file(), 'D-789 bounded camera IPC is missing'
    return importlib.import_module('rosy_media_edge.source')


def test_capture_mailbox_contains_only_latest_frame(tmp_path):
    module = implementation()
    path = tmp_path / 'front.rgb'
    with module.FrameWriter(path) as writer, module.FrameReader(path) as reader:
        for sequence in range(1, 101):
            assert writer.offer(bytes([sequence]) * (640 * 480 * 3), epoch=2,
                                sequence=sequence, captured_ms=1000 + sequence)
        frame = reader.latest()
        assert (frame.epoch, frame.sequence, frame.captured_ms) == (2, 100, 1100)
        assert frame.rgb == bytes([100]) * (640 * 480 * 3)
        assert reader.latest() is None


def test_mailbox_producer_drops_instead_of_blocking_held_reader(tmp_path):
    import fcntl
    module = implementation()
    path = tmp_path / 'front.rgb'
    with module.FrameWriter(path) as writer, module.FrameReader(path) as reader:
        fcntl.flock(reader.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        try:
            assert writer.offer(bytes(640 * 480 * 3), epoch=2, sequence=1, captured_ms=1001) is False
        finally:
            fcntl.flock(reader.fd, fcntl.LOCK_UN)
        assert writer.offer(bytes(640 * 480 * 3), epoch=2, sequence=2, captured_ms=1002)
        assert reader.latest().sequence == 2


def test_mailbox_epoch_reset_is_new_frame_and_second_writer_is_refused(tmp_path):
    module = implementation()
    path = tmp_path / 'front.rgb'
    with module.FrameWriter(path) as writer, module.FrameReader(path) as reader:
        writer.offer(bytes(640 * 480 * 3), epoch=1, sequence=80, captured_ms=1000)
        assert reader.latest().sequence == 80
        with pytest.raises(ValueError):
            module.FrameWriter(path)
        writer.offer(bytes(640 * 480 * 3), epoch=2, sequence=1, captured_ms=1001)
        assert reader.latest().epoch == 2


def test_mailbox_rejects_malformed_frames_and_symlink_paths(tmp_path):
    module = implementation()
    with module.FrameWriter(tmp_path / 'front.rgb') as writer:
        with pytest.raises(ValueError):
            writer.offer(bytes(10), epoch=1, sequence=1, captured_ms=1000)
    (tmp_path / 'alias.rgb').symlink_to(tmp_path / 'front.rgb')
    with pytest.raises((ValueError, OSError)):
        module.FrameReader(tmp_path / 'alias.rgb')
