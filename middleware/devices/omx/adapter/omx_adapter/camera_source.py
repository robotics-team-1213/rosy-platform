"""Local preview images; host receive stamps and no calibration grant no arm authority."""
import argparse
import os
from pathlib import Path
import socket
import signal
import subprocess
import time


PERSISTENT_CAMERA_DIRECTORIES = (Path('/dev/v4l/by-id'), Path('/dev/v4l/by-path'))
PERSISTENT_CAMERA_ERROR = 'a persistent /dev/v4l/by-id or /dev/v4l/by-path camera is required'


def selected_device(value):
    path = Path(value)
    if path.parent not in PERSISTENT_CAMERA_DIRECTORIES:
        raise ValueError(PERSISTENT_CAMERA_ERROR)
    if not path.exists():
        raise OSError('selected camera is unavailable')
    if not path.is_symlink():
        raise ValueError(PERSISTENT_CAMERA_ERROR)
    if not path.is_char_device():
        raise OSError('selected camera is unavailable')
    return str(path)


FORMATS = ('MJPG', 'YUYV')  # YUYV only when a camera's role names it: a RealSense D435 colour node has no MJPEG
# A depth role names its raw format; its frames are read through v4l2-ctl, as OpenCV 4.10 opened no Z16 node
# (2026-10-31, RealSense D435). Bytes per pixel, little-endian.
DEPTH_FORMATS = {'Z16': 2}


class DepthCapture:
    """Raw 640x480 frames of a depth node, one fixed-size frame per read, through `v4l2-ctl --stream-to=-`."""

    def __init__(self, device, fourcc, popen=subprocess.Popen):
        self.size = 640 * 480 * DEPTH_FORMATS[fourcc]
        self.process = popen(['v4l2-ctl', '-d', device,
                              f'--set-fmt-video=width=640,height=480,pixelformat={fourcc.ljust(4)}',
                              '--stream-mmap', '--stream-to=-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, np):
        data = self.process.stdout.read(self.size)
        if len(data) != self.size:
            self.release()
            raise OSError('depth frame unavailable')
        return np.frombuffer(data, '<u2').reshape(480, 640)

    def release(self):
        self.process.kill()
        self.process.wait(timeout=5)


def depth_outputs(depth, cv, np, unit_m, range_mm):
    """(colour-mapped JPEG preview for people, lossless 16-bit PNG and its facts for learning and the cell)."""
    lo, hi = range_mm
    scaled = np.clip((depth.astype(np.float32) * unit_m * 1000 - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    preview = cv.applyColorMap(255 - scaled, cv.COLORMAP_TURBO)  # near is warm
    preview[depth == 0] = 0  # no depth reading
    ok_jpeg, jpeg = cv.imencode('.jpg', preview, [cv.IMWRITE_JPEG_QUALITY, 80])
    ok_png, png = cv.imencode('.png', depth)
    if not (ok_jpeg and ok_png):
        raise OSError('depth encoding failed')
    return jpeg.tobytes(), png.tobytes(), {'unit_m': unit_m, 'valid_fraction': round(float((depth > 0).mean()), 3)}


def open_capture(cv, device, fourcc='MJPG'):
    capture = cv.VideoCapture(device, cv.CAP_V4L2)
    try:
        if not capture.isOpened():
            raise OSError('camera open failed')
        code = cv.VideoWriter_fourcc(*fourcc)
        for key, value in ((cv.CAP_PROP_FOURCC, code), (cv.CAP_PROP_FRAME_WIDTH, 640),
                           (cv.CAP_PROP_FRAME_HEIGHT, 480), (cv.CAP_PROP_BUFFERSIZE, 1)):
            capture.set(key, value)
        if (int(capture.get(cv.CAP_PROP_FOURCC)) != code
                or capture.get(cv.CAP_PROP_FRAME_WIDTH) != 640
                or capture.get(cv.CAP_PROP_FRAME_HEIGHT) != 480):
            raise OSError(f'camera capture format differs from {fourcc} 640x480')
        if capture.get(cv.CAP_PROP_BUFFERSIZE) != 1:
            raise OSError('camera driver did not accept a one-frame buffer')
        return capture
    except Exception:
        capture.release()
        raise


def read_frame(capture):
    ok, frame = capture.read()
    if not ok or frame is None or frame.shape != (480, 640, 3):
        capture.release()
        raise OSError('camera frame unavailable or format changed')
    return frame


def notify_watchdog():
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(b'WATCHDOG=1', '\0'+address[1:] if address.startswith('@') else address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--topic', required=True)
    parser.add_argument('--frame-id', required=True)
    # The registered topic-shaped key addresses local IPC, never DDS.
    parser.add_argument('--max-fps', type=float, default=10.0)
    args = parser.parse_args()
    if not 0 < args.max_fps <= 30:
        parser.error('--max-fps must be in (0, 30]')
    if (not args.topic.startswith('/') or any(c.isspace() for c in args.topic)
            or not args.frame_id or any(c.isspace() for c in args.frame_id)):
        parser.error('explicit image topic and frame id are required')
    # Missing USB devices are retried, but numeric or unstable selectors never start.
    if Path(args.device).parent not in PERSISTENT_CAMERA_DIRECTORIES:
        parser.error(PERSISTENT_CAMERA_ERROR)
    fourcc = os.environ.get('ROSY_CAMERA_FOURCC', 'MJPG')  # raw USB bandwidth is an explicit per-camera choice
    if fourcc not in FORMATS + tuple(DEPTH_FORMATS):
        parser.error(f'ROSY_CAMERA_FOURCC must be one of {FORMATS + tuple(DEPTH_FORMATS)}')
    depth = fourcc in DEPTH_FORMATS
    try:
        unit_m = float(os.environ.get('ROSY_DEPTH_UNIT_M', '0.001'))
        range_mm = tuple(float(v) for v in os.environ.get('ROSY_DEPTH_RANGE_MM', '300,1200').split(','))
    except ValueError:
        parser.error('ROSY_DEPTH_UNIT_M is metres per count and ROSY_DEPTH_RANGE_MM is near,far')
    if depth and not (0 < unit_m < 1 and len(range_mm) == 2 and 0 <= range_mm[0] < range_mm[1]):
        parser.error('ROSY_DEPTH_UNIT_M is metres per count and ROSY_DEPTH_RANGE_MM is near,far')
    import cv2
    import numpy as np
    from core_common.observation_snapshot import SnapshotChannel, interrupt_on_termination
    from camera_quality import frame_quality

    # a depth role keeps its preview on the topic (viewer, bridge, Fleet unchanged) and the raw depth beside it
    channel, capture = SnapshotChannel(args.topic), None
    raw = SnapshotChannel(args.topic + ':depth16') if depth else None
    previous = signal.signal(signal.SIGTERM, interrupt_on_termination)
    try:
        while True:
            started = time.monotonic()
            notify_watchdog()
            try:
                if capture is None:
                    device = selected_device(args.device)
                    capture = DepthCapture(device, fourcc) if depth else open_capture(cv2, device, fourcc)
                    print(f'native {fourcc} 640x480 preview; calibration=unverified', flush=True)
                if depth:
                    preview, png, facts = depth_outputs(capture.read(np), cv2, np, unit_m, range_mm)
                    captured_at = time.time()
                    raw.write('depth16', png, captured_at=captured_at, quality=facts)
                    channel.write('jpeg', preview, captured_at=captured_at)
                    time.sleep(max(0, 1/args.max_fps-(time.monotonic()-started)))
                    continue
                frame = read_frame(capture)
                captured_at = time.time()
                # shortcut: receipt time only; use exposure timestamps before calibrated control or recording.
                quality = frame_quality(frame)
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise OSError('camera JPEG encoding failed')
                channel.write('jpeg', encoded.tobytes(), captured_at=captured_at, quality=quality)
            except (OSError, cv2.error) as error:
                if capture is not None:
                    capture.release()
                capture = None
                print(str(error), flush=True)
                time.sleep(1)
            time.sleep(max(0, 1/args.max_fps-(time.monotonic()-started)))
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        if capture is not None:
            capture.release()


if __name__ == '__main__':
    main()
