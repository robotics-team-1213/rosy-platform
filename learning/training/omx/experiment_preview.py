"""Read exact native RGB views from one row bound to a preparation revision."""
import base64
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from experiment_native import native

MAX_CAMERAS = 8
MAX_PIXELS = 16_000_000
MAX_JPEG_BYTES = 8 * 1024 * 1024
WORKER_BYTES = 12 * 1024 * 1024
WORKER_TIMEOUT = 30


def read_in_worker(python, prepared, revision, episode, local_frame, cameras, *, grouped=False):
    """Fixed source worker and interpreter; no client command or module selection."""
    request = dict(prepared={key: prepared[key] for key in ('id', 'kind', 'path')},
                   revision=revision, episode=episode, local_frame=local_frame, cameras=cameras, grouped=grouped)
    raw = json.dumps(request, allow_nan=False).encode()
    if len(raw) > 65536:
        raise ValueError('bounded preview request required')
    env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME') if key in os.environ}
    env.update(PATH='/usr/bin:/bin', HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
               PYTHONDONTWRITEBYTECODE='1')
    try:
        with tempfile.TemporaryFile() as output:
            subprocess.run([python, '-I', '-B', str(Path(__file__).resolve()), '--worker'], input=raw,
                           stdout=output, stderr=subprocess.DEVNULL, cwd=str(Path(__file__).resolve().parent),
                           env=env, timeout=WORKER_TIMEOUT, check=True)
            output.seek(0)
            raw = output.read(WORKER_BYTES + 1)
        if len(raw) > WORKER_BYTES:
            raise ValueError('oversized preview response')
        result = json.loads(raw)
        if grouped:
            if not isinstance(result, dict) or not isinstance(result.get('frames'), list):
                raise ValueError('invalid grouped preview')
            return result
        image = base64.b64decode(result['jpeg_base64'], validate=True)
        if not image or len(image) > MAX_JPEG_BYTES:
            raise ValueError('invalid preview image')
        return image
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise ValueError('Native preview reader unavailable; check the configured ACT environment '
                         'and reload.') from None


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
    from PIL import Image
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
    result, _, _ = _encode(row, source['inspection']['camera_keys'][camera], MAX_PIXELS)
    if len(result) > MAX_JPEG_BYTES:
        raise ValueError('frame exceeds 8 MiB JPEG')
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


def main():
    import contextlib
    import resource
    from experiment_reviews import Reviews
    if sys.argv[1:] != ['--worker']:
        raise ValueError('fixed preview worker invocation required')
    resource.setrlimit(resource.RLIMIT_FSIZE, (WORKER_BYTES, WORKER_BYTES))
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError('bounded preview request required')
    request = json.loads(raw)
    if (not isinstance(request, dict) or set(request) != {
            'prepared', 'revision', 'episode', 'local_frame', 'cameras', 'grouped'}
            or type(request['grouped']) is not bool):
        raise ValueError('fixed preview request required')
    prepared = request['prepared']
    reviews = Reviews(Path(prepared['path']), None, None)
    with contextlib.redirect_stdout(sys.stderr):
        args = (reviews, prepared, request['revision'], request['episode'], request['local_frame'])
        if request['grouped']:
            result = frame_set(*args, request['cameras'])
        else:
            if not isinstance(request['cameras'], list) or len(request['cameras']) != 1:
                raise ValueError('one camera required')
            result = {'jpeg_base64': base64.b64encode(frame(*args, request['cameras'][0])).decode('ascii')}
    json.dump(result, sys.stdout, allow_nan=False)


if __name__ == '__main__':
    main()
