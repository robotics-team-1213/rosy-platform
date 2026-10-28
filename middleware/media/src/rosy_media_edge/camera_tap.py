"""D-789 T3: an independent 640x480 media branch inside the single camera owner.

camera_detect_node wraps its one Picamera2 with ``media_camera``. When the robot media
service is configured (/etc/rosy/media/rosy-media.json names the mailbox), Picamera2 is
configured once with a 640x480 ``main`` stream for media and the node's own perception
size as ``lores`` (both scaled by the ISP from one sensor mode); each capture is one
request. Perception keeps its size and cadence. Without the config the camera is returned
unwrapped and nothing changes. A frame that is not native 640x480 is refused, never upscaled.
"""

import json
from pathlib import Path
import time

CONFIG = Path('/etc/rosy/media/rosy-media.json')
MEDIA_SIZE = (640, 480)


class CameraMediaTap:
    def __init__(self, path, *, rotate_deg, writer_factory=None, clock=time.time):
        if rotate_deg not in (0, 180):
            raise ValueError('media branch supports 0 or 180 degree rotation only')
        if writer_factory is None:
            from .source import FrameWriter as writer_factory
        self._writer = writer_factory(path)
        self._flip, self._clock = rotate_deg == 180, clock
        self._epoch, self._sequence = int(clock()) & 0xFFFFFFFF, 0

    def offer(self, bgr):
        import numpy as np
        if getattr(bgr, 'shape', None) != (MEDIA_SIZE[1], MEDIA_SIZE[0], 3):
            return False  # never scale up a smaller frame into the 640x480 profile
        # libcamera RGB888 is BGR in memory; reversing both image axes is the 180 degree turn.
        rgb = bgr[::-1, ::-1, ::-1] if self._flip else bgr[:, :, ::-1]
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        try:
            # Nonblocking: a busy or dead consumer drops this frame, never the capture tick.
            return self._writer.offer(np.ascontiguousarray(rgb).tobytes(), epoch=self._epoch,
                                      sequence=self._sequence, captured_ms=int(self._clock() * 1000))
        except (OSError, ValueError):
            return False

    def close(self):
        self._writer.close()


class TapCamera:
    """Picamera2 stand-in: the owner's calls are unchanged, ``main`` means perception."""

    def __init__(self, cam, tap):
        self._cam, self._tap = cam, tap

    def __getattr__(self, name):
        return getattr(self._cam, name)

    def create_preview_configuration(self, *, main, **kwargs):
        width, height = main['size']
        if width > MEDIA_SIZE[0] or height > MEDIA_SIZE[1]:
            raise ValueError('perception stream must not exceed the 640x480 media stream')
        return self._cam.create_preview_configuration(
            main={'size': MEDIA_SIZE, 'format': 'RGB888'},
            lores={'size': (width, height), 'format': main.get('format', 'RGB888')}, **kwargs)

    def capture_array(self, name='main'):
        if name != 'main':
            return self._cam.capture_array(name)
        request = self._cam.capture_request()
        try:
            perception = request.make_array('lores')
            media = request.make_array('main')
        finally:
            request.release()
        self._tap.offer(media)
        return perception


def media_camera(cam, node, *, config=CONFIG):
    """Return ``cam`` wrapped for media when this robot has site media configured, else ``cam``."""
    tap = getattr(node, '_media_tap', None)
    if tap is None:  # one mailbox writer for the node's life, across camera restarts
        tap = False
        try:
            if config.is_file():
                mailbox = json.loads(config.read_text(encoding='utf-8'))['mailbox']
                tap = CameraMediaTap(mailbox, rotate_deg=int(node.get_parameter('rotate_deg').value))
        except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
            node.get_logger().warn(f'media branch off: {type(exc).__name__}: {exc}')
        node._media_tap = tap
    return TapCamera(cam, tap) if tap else cam
