"""Read exact native RGB views from one row bound to a preparation revision."""
import base64
import io
import math

import numpy as np
from PIL import Image

from experiment_native import native

MAX_CAMERAS = 8
MAX_PIXELS = 16_000_000
MAX_JPEG_BYTES = 8 * 1024 * 1024


def _read(reviews, prepared, revision, episode, local_frame, cameras):
    if any(type(value) is not int or value < 0 for value in (episode, local_frame)):
        raise ValueError('nonnegative episode, frame and camera indices required')
    if (not isinstance(cameras, list) or not 1 <= len(cameras) <= MAX_CAMERAS
            or any(type(value) is not int or value < 0 for value in cameras)
            or len(set(cameras)) != len(cameras)):
        raise ValueError('one to eight distinct nonnegative camera indices required')
    source = reviews.source(prepared)
    if source['source_revision'] != revision:
        raise ValueError('source changed; reload the review before viewing frames')
    report = source['inspection']
    declared = next((row for row in report['episodes'] if row['episode_index'] == episode), None)
    if (declared is None or local_frame >= declared['frames']
            or any(camera >= len(report['camera_keys']) for camera in cameras)):
        raise ValueError('frame or camera outside the inspected episode')
    # The pinned reader stays offline and decodes this row; no nearest-frame fallback is supplied.
    reader = native.load_dataset(source['root'], report['repo_id'])
    meta = [row for row in reader.meta.episodes if row['episode_index'] == episode]
    if len(meta) != 1 or len(reader) != report['frame_count']:
        raise ValueError('reader episode metadata differs from inspected source')
    start, end = meta[0]['dataset_from_index'], meta[0]['dataset_to_index']
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(reader)
            or end - start != declared['frames']):
        raise ValueError('reader episode boundaries differ from inspected source')
    index = start + local_frame
    row = reader[index]
    for key, expected in [('episode_index', episode), ('frame_index', local_frame), ('index', index)]:
        if native._integer(row.get(key), key) != expected:
            raise ValueError('reader row identity differs from requested episode frame')
    return source, reader, row, index


def _encode(row, key, remaining_pixels=None):
    pixels = np.asarray(row.get(key))
    if (pixels.ndim != 3 or pixels.shape[0] != 3 or min(pixels.shape[1:]) < 1
            or max(pixels.shape[1:]) > 4096 or not np.issubdtype(pixels.dtype, np.floating)
            or not np.isfinite(pixels).all() or pixels.min() < 0 or pixels.max() > 1):
        raise ValueError('reader preview must be bounded normalized CHW RGB')
    height, width = pixels.shape[1:]
    if remaining_pixels is not None and height * width > remaining_pixels:
        raise ValueError('frame set exceeds 16 million pixels; select fewer cameras')
    image = np.rint(pixels.transpose(1, 2, 0) * 255).astype(np.uint8)
    output = io.BytesIO()
    Image.fromarray(image).save(output, format='JPEG', quality=90)
    return output.getvalue(), width, height


def _check_source(reviews, prepared, revision):
    if reviews.source(prepared)['source_revision'] != revision:
        raise ValueError('source changed while reading review frame')


def frame(reviews, prepared, revision, episode, local_frame, camera):
    source, reader, row, index = _read(reviews, prepared, revision, episode, local_frame, [camera])
    result, _, _ = _encode(row, source['inspection']['camera_keys'][camera])
    _check_source(reviews, prepared, revision)
    return result


def frame_set(reviews, prepared, revision, episode, local_frame, cameras):
    source, reader, row, index = _read(reviews, prepared, revision, episode, local_frame, cameras)
    fps = reader.meta.info.get('fps')
    timestamp = np.asarray(row.get('timestamp'))
    if (type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0
            or timestamp.size != 1 or timestamp.dtype.kind not in 'fiu'):
        raise ValueError('frame set requires a finite positive fps and recorded row timestamp')
    stamp = float(timestamp.item())
    if not math.isfinite(stamp) or abs(stamp - local_frame / fps) > 1e-3:
        raise ValueError('recorded row timestamp differs from episode frame time')
    images, pixels, jpeg_bytes = [], 0, 0
    for camera in cameras:
        key = source['inspection']['camera_keys'][camera]
        encoded, width, height = _encode(row, key, MAX_PIXELS - pixels)
        pixels += width * height
        jpeg_bytes += len(encoded)
        if jpeg_bytes > MAX_JPEG_BYTES:
            raise ValueError('frame set exceeds 8 MiB JPEG; select fewer cameras')
        images.append(dict(camera_index=camera, camera_key=key, width=width, height=height,
                           jpeg_base64=base64.b64encode(encoded).decode('ascii')))
    _check_source(reviews, prepared, revision)
    return dict(prepared_id=prepared['id'], source_revision=revision, episode_index=episode,
                frame_index=local_frame, index=index, timestamp_seconds=stamp, fps=float(fps), frames=images)
