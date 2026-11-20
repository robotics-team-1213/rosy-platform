"""Single-plane RGB capture with Linux V4L2 start-of-exposure provenance."""

import argparse
import ctypes as c
import mmap
import os
from pathlib import Path
import platform
import select
import signal
import sys
import time


WIDTH, HEIGHT = 640, 480
CAPTURE, MMAP = 1, 1
TIMESTAMP_MASK, TIMESTAMP_MONOTONIC = 0xE000, 0x2000
SOURCE_MASK, SOURCE_EXPOSURE = 0x70000, 0x10000
BUFFER_ERROR = 0x40
U32 = c.c_uint32


class PixelFormat(c.Structure):
    _fields_ = [(name, U32) for name in (
        "width", "height", "pixelformat", "field", "bytesperline", "sizeimage",
        "colorspace", "priv", "flags", "ycbcr_enc", "quantization", "xfer_func",
    )]


class FormatData(c.Union):
    # v4l2_format's union includes pointer-bearing structs as well as this pixel format.
    _fields_ = [("pix", PixelFormat), ("raw", c.c_ubyte * 200), ("alignment", c.c_void_p)]


class Format(c.Structure):
    _fields_ = [("type", U32), ("data", FormatData)]


class RequestBuffers(c.Structure):
    _fields_ = [("count", U32), ("type", U32), ("memory", U32), ("capabilities", U32),
                ("flags", c.c_uint8), ("reserved", c.c_uint8 * 3)]


class Timeval(c.Structure):
    _fields_ = [("sec", c.c_long), ("usec", c.c_long)]


class BufferAddress(c.Union):
    _fields_ = [("offset", U32), ("userptr", c.c_ulong), ("planes", c.c_void_p)]


class Buffer(c.Structure):
    _fields_ = [(name, U32) for name in ("index", "type", "bytesused", "flags", "field")] + [
        ("timestamp", Timeval), ("timecode", U32 * 4), ("sequence", U32), ("memory", U32),
        ("address", BufferAddress), ("length", U32), ("reserved2", U32), ("request_fd", c.c_int32),
    ]


def _request(direction, number, data):
    return (direction << 30) | (c.sizeof(data) << 16) | (ord("V") << 8) | number


S_FMT = _request(3, 5, Format)
REQBUFS = _request(3, 8, RequestBuffers)
QUERYBUF = _request(3, 9, Buffer)
QBUF = _request(3, 15, Buffer)
DQBUF = _request(3, 17, Buffer)
STREAMON = _request(1, 18, c.c_int)
STREAMOFF = _request(1, 19, c.c_int)


class RgbExposureCapture:
    """Copy payload and time from the same dequeued buffer before requeue."""

    def __init__(self, device, fourcc):
        if (sys.platform != "linux" or platform.machine() not in ("x86_64", "aarch64")
                or c.sizeof(c.c_long) != 8 or sys.byteorder != "little"):
            raise OSError("native exposure capture requires x86-64 or ARM64 Linux")
        if fourcc not in ("MJPG", "YUYV"):
            raise ValueError("exposure capture supports MJPG or YUYV")
        from fcntl import ioctl

        self._boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not self._boot_id:
            raise OSError("local boot identity unavailable")
        self._buffers, self._limits = [], []
        self._streaming = False
        self._last_sequence = self._last_stamp = None
        self._clock = time.monotonic
        self._fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        self._ioctl = lambda command, payload: ioctl(self._fd, command, payload, True)
        self._ready = lambda: bool(select.select([self._fd], [], [], 1.0)[0])
        try:
            self._configure(fourcc)
        except BaseException:
            self.release()
            raise

    def _configure(self, fourcc):
        code = int.from_bytes(fourcc.encode("ascii"), "little")
        fmt = Format(type=CAPTURE)
        fmt.data.pix = PixelFormat(width=WIDTH, height=HEIGHT, pixelformat=code, field=1)
        self._ioctl(S_FMT, fmt)
        pix = fmt.data.pix
        if ((pix.width, pix.height, pix.pixelformat, pix.field) != (WIDTH, HEIGHT, code, 1)
                or (fourcc == "YUYV" and pix.bytesperline != WIDTH * 2)):
            raise OSError("camera did not accept the requested RGB buffer layout")
        buffers = RequestBuffers(count=2, type=CAPTURE, memory=MMAP)
        self._ioctl(REQBUFS, buffers)
        if not 0 < buffers.count <= 32:
            raise OSError("driver did not allocate valid camera buffers")
        for index in range(buffers.count):
            buffer = Buffer(type=CAPTURE, memory=MMAP, index=index)
            self._ioctl(QUERYBUF, buffer)
            if not 0 < buffer.length <= 4 * 1024 * 1024:
                raise OSError("invalid camera buffer length")
            self._buffers.append(mmap.mmap(self._fd, buffer.length, flags=mmap.MAP_SHARED,
                                           prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                           offset=buffer.address.offset))
            self._limits.append(buffer.length)
            self._queue(index)
        self._ioctl(STREAMON, c.c_int(CAPTURE))
        self._streaming = True

    def _queue(self, index):
        self._ioctl(QBUF, Buffer(type=CAPTURE, memory=MMAP, index=index))

    def read(self):
        if not self._ready():
            raise OSError("RGB exposure buffer timed out")
        buffer = Buffer(type=CAPTURE, memory=MMAP)
        self._ioctl(DQBUF, buffer)
        if buffer.index >= len(self._buffers):
            raise OSError("unknown RGB capture buffer")
        try:
            stamp = buffer.timestamp.sec + buffer.timestamp.usec / 1e6
            valid = (buffer.flags & TIMESTAMP_MASK == TIMESTAMP_MONOTONIC
                     and buffer.flags & SOURCE_MASK == SOURCE_EXPOSURE
                     and not buffer.flags & BUFFER_ERROR
                     and 0 <= buffer.timestamp.usec < 1_000_000 and 0 < stamp <= self._clock()
                     and (self._last_sequence is None or buffer.sequence > self._last_sequence)
                     and (self._last_stamp is None or stamp > self._last_stamp))
            if not valid or not 0 < buffer.bytesused <= self._limits[buffer.index]:
                raise OSError("camera did not supply a fresh, valid start-of-exposure buffer")
            data = self._buffers[buffer.index][:buffer.bytesused]
            self._last_sequence, self._last_stamp = buffer.sequence, stamp
            return data, {"clock_semantics": "v4l2_monotonic_start_of_exposure",
                          "exposure_monotonic_s": stamp, "source_seq": buffer.sequence,
                          "boot_id": self._boot_id}
        finally:
            self._queue(buffer.index)

    def release(self):
        if self._fd is None:
            return
        try:
            if self._streaming:
                try:
                    self._ioctl(STREAMOFF, c.c_int(CAPTURE))
                except OSError:
                    pass
            for mapped in self._buffers:
                mapped.close()
        finally:
            os.close(self._fd)
            self._fd = None


def read_exposure_frame(cv, np, capture, fourcc):
    raw, exposure = capture.read()
    pixels = np.frombuffer(raw, dtype=np.uint8)
    if fourcc == "YUYV":
        if pixels.size != WIDTH * HEIGHT * 2:
            raise OSError("wrong YUYV exposure payload size")
        frame = cv.cvtColor(pixels.reshape(HEIGHT, WIDTH, 2), cv.COLOR_YUV2BGR_YUY2)
    else:
        frame = cv.imdecode(pixels, cv.IMREAD_COLOR)
    if frame is None or frame.shape != (HEIGHT, WIDTH, 3):
        raise OSError("RGB exposure frame could not be decoded at the requested size")
    return frame, exposure


def main():
    from camera_source import FORMATS, notify_watchdog, selected_device

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--max-fps", type=float, default=15.0)
    args = parser.parse_args()
    fourcc = os.environ.get("ROSY_CAMERA_FOURCC", "MJPG")
    if not 0 < args.max_fps <= 30 or fourcc not in FORMATS:
        parser.error("valid RGB format and capture rate in (0, 30] required")
    if (not args.topic.startswith("/") or not args.frame_id
            or any(c.isspace() for c in args.topic + args.frame_id)):
        parser.error("explicit image topic and frame id are required")

    import cv2
    import numpy as np
    from core_common.observation_snapshot import SnapshotChannel, interrupt_on_termination
    from core_common.camera_quality import frame_quality

    channel, camera = SnapshotChannel(args.topic), None
    previous = signal.signal(signal.SIGTERM, interrupt_on_termination)
    try:
        while True:
            started = time.monotonic()
            notify_watchdog()
            try:
                if camera is None:
                    camera = RgbExposureCapture(selected_device(args.device), fourcc)
                frame, exposure = read_exposure_frame(cv2, np, camera, fourcc)
                captured_at = time.time() - (time.monotonic() - exposure["exposure_monotonic_s"])
                quality = dict(frame_quality(frame), **exposure)
                ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise OSError("camera JPEG encoding failed")
                channel.write("jpeg", encoded.tobytes(), captured_at=captured_at, quality=quality)
            except (OSError, cv2.error) as error:
                if camera is not None:
                    camera.release()
                camera = None
                print(str(error), flush=True)
                time.sleep(1)
            time.sleep(max(0, 1 / args.max_fps - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        if camera is not None:
            camera.release()


if __name__ == "__main__":
    main()
