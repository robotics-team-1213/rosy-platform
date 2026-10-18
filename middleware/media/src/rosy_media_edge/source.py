"""Latest-only local packed RGB mailbox, with nonblocking producer/consumer locks.

Only the existing capture owner creates a writer. A separate ownership lock
prevents competing writers without holding the data lock against readers.
An incomplete producer write leaves an invalid commit marker.
"""

from dataclasses import dataclass, field
import fcntl
import mmap
import os
from pathlib import Path
import stat
import struct


WIDTH, HEIGHT = 640, 480
RGB_SIZE = WIDTH * HEIGHT * 3
HEADER = struct.Struct('!4sIIQII')
MAGIC = b'RMF1'
FILE_SIZE = HEADER.size + RGB_SIZE


@dataclass(frozen=True)
class MediaFrame:
    epoch: int
    sequence: int
    captured_ms: int
    rgb: bytes = field(repr=False)


def _open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('camera mailbox must be a regular file')
    return fd


class FrameWriter:
    def __init__(self, path):
        path = Path(path)
        self._owner, self.fd, self._memory = None, None, None
        try:
            self._owner = _open(path.with_name(path.name + '.owner'), os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('camera mailbox already has a producer') from None
            self.fd = _open(path, os.O_RDWR | os.O_CREAT)
            os.ftruncate(self.fd, FILE_SIZE)
            self._memory = mmap.mmap(self.fd, FILE_SIZE, access=mmap.ACCESS_WRITE)
            self._memory[:4] = bytes(4)
        except Exception:
            self.close()
            raise

    def offer(self, rgb, *, epoch, sequence, captured_ms):
        if len(rgb) != RGB_SIZE or any(type(value) is not int or not 0 <= value < upper
                for value, upper in ((epoch, 2**32), (sequence, 2**32), (captured_ms, 2**64))):
            raise ValueError('invalid packed camera frame or identity')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        try:
            self._memory[:4] = bytes(4)
            self._memory[HEADER.size:] = rgb
            self._memory[4:HEADER.size] = HEADER.pack(MAGIC, epoch, sequence, captured_ms, WIDTH, HEIGHT)[4:]
            self._memory[:4] = MAGIC
            return True
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def close(self):
        if self._memory is not None:
            self._memory.close()
            self._memory = None
        for name in ('fd', '_owner'):
            value = getattr(self, name)
            if value is not None:
                os.close(value)
                setattr(self, name, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FrameReader:
    def __init__(self, path):
        self.fd = _open(path, os.O_RDONLY)
        try:
            if os.fstat(self.fd).st_size != FILE_SIZE:
                raise ValueError('camera mailbox has wrong dimensions')
            self._memory = mmap.mmap(self.fd, FILE_SIZE, access=mmap.ACCESS_READ)
        except Exception:
            os.close(self.fd)
            raise
        self._last = None

    def latest(self):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        try:
            magic, epoch, sequence, captured_ms, width, height = HEADER.unpack(self._memory[:HEADER.size])
            if magic != MAGIC or (width, height) != (WIDTH, HEIGHT):
                return None
            if self._last is not None and epoch == self._last[0] and sequence <= self._last[1]:
                return None
            frame = MediaFrame(epoch, sequence, captured_ms, self._memory[HEADER.size:])
            self._last = (epoch, sequence)
            return frame
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def close(self):
        self._memory.close()
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
