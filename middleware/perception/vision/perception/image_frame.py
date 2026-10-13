"""Subject: sensor_msgs/Image to a numpy frame, without importing ROS.

Shared by the camera observers. mono8 gives HxW, bgr8 gives HxWx3 BGR, rgb8 is
reversed to BGR. Anything else, or a payload that does not match the declared
dimensions, raises ValueError."""

import numpy as np


def image_msg_to_frame(msg) -> np.ndarray:
    channels = 1 if msg.encoding == 'mono8' else 3
    if msg.encoding not in ('mono8', 'bgr8', 'rgb8'):
        raise ValueError(f'unsupported camera encoding {msg.encoding!r}')
    expected = int(msg.height) * int(msg.width) * channels
    pixels = np.frombuffer(msg.data, dtype=np.uint8)
    if pixels.size != expected:
        raise ValueError('camera payload size does not match dimensions')
    frame = pixels.reshape((int(msg.height), int(msg.width), channels))
    if channels == 1:
        frame = frame[:, :, 0]
    elif msg.encoding == 'rgb8':
        frame = frame[:, :, ::-1]
    return frame
