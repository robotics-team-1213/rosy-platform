"""Local preview images; host receive stamps and no calibration grant no arm authority."""
import argparse
import os
from pathlib import Path
import socket
import signal
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


def open_capture(cv, device):
    capture = cv.VideoCapture(device, cv.CAP_V4L2)
    try:
        if not capture.isOpened():
            raise OSError('camera open failed')
        mjpeg = cv.VideoWriter_fourcc(*'MJPG')
        for key, value in ((cv.CAP_PROP_FOURCC, mjpeg), (cv.CAP_PROP_FRAME_WIDTH, 640),
                           (cv.CAP_PROP_FRAME_HEIGHT, 480), (cv.CAP_PROP_BUFFERSIZE, 1)):
            capture.set(key, value)
        if (int(capture.get(cv.CAP_PROP_FOURCC)) != mjpeg
                or capture.get(cv.CAP_PROP_FRAME_WIDTH) != 640
                or capture.get(cv.CAP_PROP_FRAME_HEIGHT) != 480):
            raise OSError('camera capture format differs from MJPEG 640x480')
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
    import cv2
    from core_common.observation_snapshot import SnapshotChannel, interrupt_on_termination
    from camera_quality import frame_quality

    channel, capture = SnapshotChannel(args.topic), None
    previous = signal.signal(signal.SIGTERM, interrupt_on_termination)
    try:
        while True:
            started = time.monotonic()
            notify_watchdog()
            try:
                if capture is None:
                    capture = open_capture(cv2, selected_device(args.device))
                    print('native MJPEG 640x480 preview; calibration=unverified', flush=True)
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
