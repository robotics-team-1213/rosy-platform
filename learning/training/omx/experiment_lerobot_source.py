"""Bounded local LeRobot v3 uploads and generic, train-only ACT derivatives."""
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path, PurePosixPath
import re

from experiment_io import read_json
import experiment_robot_adapters as robots

REPO = 'rosy-upload/local-demonstrations'
TOTAL_BYTES = 2 * 1024**3
FILE_BYTES = 512 * 1024**2
DATA_PATH = 'data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet'
VIDEO_PATH = 'videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4'
SIDECARS = {'README.md', 'LICENSE', 'LICENCE', 'LICENSE.txt', 'LICENSE.md',
            'UPSTREAM_README.md', 'source-provenance.json'}
CAMERA = r'observation\.images\.[A-Za-z0-9][A-Za-z0-9_.-]{0,127}'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def allowed(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 256:
        raise ValueError('bounded relative dataset path required')
    path = PurePosixPath(name)
    if ('\\' in name or ':' in name or path.is_absolute() or str(path) != name
            or any(p in ('.', '..') or p.startswith('.') for p in path.parts)):
        raise ValueError('unsafe dataset path')
    if not (name in SIDECARS or name in {'meta/info.json', 'meta/stats.json', 'meta/tasks.parquet'}
            or re.fullmatch(r'(data|meta/episodes)/chunk-\d{3}/file-\d{3}\.parquet', name)
            or re.fullmatch(r'videos/'+CAMERA+r'/chunk-\d{3}/file-\d{3}\.mp4', name)):
        raise ValueError('unsupported dataset file')
    return name


def validate_files(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 10000:
        raise ValueError('dataset manifest requires 1..10000 files')
    result, seen, total = [], set(), 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {'name', 'size', 'sha256'}:
            raise ValueError('dataset manifest fields differ')
        name = allowed(item['name'])
        if name.casefold() in seen:
            raise ValueError('duplicate or case-colliding dataset paths')
        seen.add(name.casefold())
        if type(item['size']) is not int or not 0 <= item['size'] <= FILE_BYTES:
            raise ValueError('dataset file exceeds 512 MiB')
        if not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError('dataset file SHA256 required')
        total += item['size']
        result.append(dict(item))
    if total > TOTAL_BYTES or 'meta/info.json' not in seen:
        raise ValueError('dataset exceeds 2 GiB or lacks meta/info.json')
    return sorted(result, key=lambda row: row['name'])


def manifest_revision(files):
    return digest(validate_files(files))


def hashes(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('regular owned directory required')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('dataset/artifact links are forbidden')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('regular dataset/artifact file required')
        with path.open('rb') as stream:
            result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def verify_files(root, files):
    files = validate_files(files)
    actual = hashes(root)
    if actual != {row['name']: row['sha256'] for row in files}:
        raise ValueError('uploaded source bytes or file set changed')
    if any((Path(root)/row['name']).stat().st_size != row['size'] for row in files):
        raise ValueError('uploaded source size changed')
    return manifest_revision(files)


def check_recipe(values):
    """The optional ACT recipe values; a run that names neither keeps the shipped recipe."""
    if 'optimizer_lr' in values and (type(values['optimizer_lr']) is not float or not 1e-6 <= values['optimizer_lr'] <= 1e-3):
        raise ValueError('study learning rate outside allowed range')
    if 'chunk_size' in values and (type(values['chunk_size']) is not int or not 1 <= values['chunk_size'] <= 100):
        raise ValueError('study chunk size outside allowed range')


def validate_split(selection, inspection):
    keys = {'train', 'validation', 'eval'}
    if not isinstance(selection, dict) or set(selection) != keys:
        raise ValueError('train/validation/eval episode arrays required')
    known = {row['index'] for row in inspection['episodes']}
    seen, result = set(), {}
    for key in ('train', 'validation', 'eval'):
        values = selection[key]
        if (not isinstance(values, list) or any(type(i) is not int for i in values)
                or values != sorted(set(values)) or not set(values) <= known
                or seen.intersection(values) or (key != 'validation' and not values)):
            raise ValueError('sorted unique disjoint known episodes required; train/eval cannot be empty')
        result[key] = list(values)
        seen.update(values)
    result['revision'] = digest(dict(inspection_revision=inspection['revision'], **result))
    return result


def check_info(info):
    if (not isinstance(info, dict) or info.get('codebase_version') != 'v3.0'
            or type(info.get('fps')) is not int or not 1 <= info['fps'] <= 240
            or type(info.get('total_episodes')) is not int or not 2 <= info['total_episodes'] <= 1000
            or type(info.get('total_frames')) is not int
            or not info['total_episodes'] <= info['total_frames'] <= 200000):
        raise ValueError('complete LeRobot v3, 1..240 fps, 2..1000 episodes, <=200000 frames required')
    if (info.get('data_path') != DATA_PATH or info.get('video_path') not in (None, VIDEO_PATH)):
        raise ValueError('canonical local v3 data/video path templates required')
    robot = info.get('robot_type')
    if robot is not None and (not isinstance(robot, str) or len(robot) > 256):
        raise ValueError('bounded robot type required')
    features = info.get('features', {})
    if not isinstance(features, dict):
        raise ValueError('feature metadata required')
    for key, maximum in [('observation.state', 128), ('action', 64)]:
        feature = features.get(key, {})
        shape, names = feature.get('shape'), feature.get('names')
        if (feature.get('dtype') != 'float32' or not isinstance(shape, list) or len(shape) != 1
                or type(shape[0]) is not int or not 1 <= shape[0] <= maximum):
            raise ValueError('bounded float32 state/action vectors required')
        if names is not None and (not isinstance(names, list) or len(names) != shape[0]
                or any(not isinstance(n, str) or not n or len(n) > 256 for n in names)):
            raise ValueError('feature names must match actual dimensions')
    cameras = {k: v for k, v in features.items() if k.startswith('observation.images.')}
    if set(features) - {'observation.state', 'action', 'timestamp', 'frame_index',
                         'episode_index', 'index', 'task_index'} - set(cameras):
        raise ValueError('unsupported additional features')
    if not 1 <= len(cameras) <= 8:
        raise ValueError('1..8 RGB cameras required')
    pixels = 0
    for key, feature in cameras.items():
        shape = feature.get('shape', [])
        if (not re.fullmatch(CAMERA, key) or feature.get('dtype') not in ('image', 'video')
                or len(shape) != 3 or any(type(n) is not int or n < 1 for n in shape)
                or shape[2] != 3):
            raise ValueError('bounded HWC RGB image/video camera features required')
        pixels += shape[0] * shape[1]
        if feature['dtype'] == 'video' and info.get('video_path') != VIDEO_PATH:
            raise ValueError('video camera requires canonical video path template')
    if pixels > 16000000:
        raise ValueError('camera pixels exceed 16M')
    return info


def check_image_cell(cell, feature):
    from PIL import Image
    if not isinstance(cell, dict) or set(cell) - {'path', 'bytes'}:
        raise ValueError('embedded image bytes required')
    path, raw = cell.get('path'), cell.get('bytes')
    if path is not None and (not isinstance(path, str) or '\\' in path or ':' in path
            or PurePosixPath(path).name != path or path in ('.', '..')):
        raise ValueError('external image paths are forbidden')
    if not isinstance(raw, bytes) or not 0 < len(raw) <= min(FILE_BYTES, 3*math.prod(feature['shape'])+1048576):
        raise ValueError('bounded embedded image bytes required')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.size != (feature['shape'][1], feature['shape'][0]) or image.mode != 'RGB':
                raise ValueError('embedded RGB image header differs from metadata')
            image.verify()
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError('invalid bounded embedded image') from exc


def parquet_rows(path, numeric_shapes=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    parquet = pq.ParquetFile(path)
    for key, shape in (numeric_shapes or {}).items():
        field = parquet.schema_arrow.field(key).type
        vector = (pa.types.is_list(field) or pa.types.is_fixed_size_list(field)) and pa.types.is_float32(field.value_type)
        if not vector and not (shape == [1] and pa.types.is_float32(field)):
            raise ValueError('raw numeric Parquet values must match float32 vector metadata')
    if parquet.metadata.num_rows > 200000 or len(parquet.schema.names) > 256:
        raise ValueError('bounded raw Parquet rows/columns required')
    if any(parquet.metadata.row_group(i).total_byte_size > FILE_BYTES
           for i in range(parquet.metadata.num_row_groups)):
        raise ValueError('raw Parquet row group exceeds memory budget')
    for batch in parquet.iter_batches(batch_size=1):
        if batch.nbytes > 128*1024**2:
            raise ValueError('raw Parquet row exceeds memory budget')
        yield batch.to_pylist()[0]


def check_video_header(path, feature):
    import av
    with av.open(str(path)) as container:
        streams = list(container.streams.video)
        if len(streams) != 1:
            raise ValueError('one local video stream required')
        codec = streams[0].codec_context
        if [codec.height, codec.width, 3] != feature['shape']:
            raise ValueError('video header dimensions differ from declared RGB shape')


def raw_check(root, info, files):
    """Check local references and image cells before datasets can decode images."""
    import numpy as np
    names = {row['name'] for row in files}
    for name in ('meta/info.json', 'meta/stats.json'):
        if name in names and (root/name).stat().st_size > 8*1024**2:
            raise ValueError('bounded JSON metadata required')
    if 'meta/tasks.parquet' not in names:
        raise ValueError('local v3 task metadata required')
    for row in parquet_rows(root/'meta/tasks.parquet'):
        if any(isinstance(v, str) and len(v) > 10000 for v in row.values()):
            raise ValueError('bounded raw task metadata required')
    cameras = {k: v for k, v in info['features'].items() if k.startswith('observation.images.')}
    for name in sorted(names):
        if name.startswith('videos/'):
            key = name.split('/')[1]
            if key not in cameras or cameras[key]['dtype'] != 'video':
                raise ValueError('video file has no declared camera')
            check_video_header(root/name, cameras[key])
    metadata = []
    for name in sorted(names):
        if not name.startswith('meta/episodes/'):
            continue
        for row in parquet_rows(root/name):
            index = row.get('episode_index')
            if type(index) is not int or index != len(metadata) or type(row.get('length')) is not int or row['length'] < 1:
                raise ValueError('complete ordered episode metadata required')
            for prefix, template in [('data', DATA_PATH), *[(f'videos/{k}', VIDEO_PATH)
                    for k, v in cameras.items() if v['dtype'] == 'video']]:
                chunk, file = row.get(prefix+'/chunk_index'), row.get(prefix+'/file_index')
                if any(type(i) is not int or not 0 <= i <= 999 for i in (chunk, file)):
                    raise ValueError('bounded integer metadata file references required')
                key = prefix.removeprefix('videos/')
                referenced = template.format(chunk_index=chunk, file_index=file, video_key=key)
                if referenced not in names:
                    raise ValueError('episode references missing local data/video')
            metadata.append(row)
    if len(metadata) != info['total_episodes'] or sum(r['length'] for r in metadata) != info['total_frames']:
        raise ValueError('episode metadata count/length differs')
    counts, total, current = [0]*len(metadata), 0, 0
    for name in sorted(names):
        if not name.startswith('data/'):
            continue
        for row in parquet_rows(root/name, {k:info['features'][k]['shape'] for k in ('observation.state','action')}):
            if set(row) - {'observation.state', 'action', 'timestamp', 'frame_index',
                           'episode_index', 'index', 'task_index'} - set(cameras):
                raise ValueError('unsupported raw Parquet columns')
            episode, frame, index = (row.get(k) for k in ('episode_index', 'frame_index', 'index'))
            if (any(type(i) is not int for i in (episode, frame, index)) or index != total
                    or not 0 <= episode < len(counts) or frame != counts[episode]
                    or episode != current):
                raise ValueError('raw frame/episode/index order differs')
            stamp = row.get('timestamp')
            if type(row.get('task_index')) is not int or row['task_index'] < 0:
                raise ValueError('raw task index must be a nonnegative integer')
            if type(stamp) not in (float,int) or not math.isfinite(stamp) or abs(stamp-frame/info['fps']) > 1e-3:
                raise ValueError('raw timestamp differs from fps')
            for key in ('action', 'observation.state'):
                value = np.asarray(row.get(key))
                if value.shape == () and info['features'][key]['shape'] == [1]:
                    value = value.reshape(1)
                if value.shape != tuple(info['features'][key]['shape']) or not np.isfinite(value).all():
                    raise ValueError('raw numeric feature differs or is nonfinite')
            for key, feature in cameras.items():
                if feature['dtype'] == 'image':
                    check_image_cell(row.get(key), feature)
            counts[episode] += 1
            if counts[episode] == metadata[episode]['length']:
                current += 1
            total += 1
    if counts != [r['length'] for r in metadata]:
        raise ValueError('raw episode rows differ from complete metadata')
    return metadata


def reader(root, episodes=None):
    if importlib.metadata.version('lerobot') != '0.4.4':
        raise ValueError('pinned lerobot==0.4.4 required')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    return LeRobotDataset(REPO, root=Path(root), episodes=episodes,
        download_videos=False, video_backend='pyav')


def inspect(root, files):
    import numpy as np
    root = Path(root)
    verify_files(root, files)
    info = check_info(read_json(root/'meta/info.json'))
    robots.check(info)  # here, not in check_info: results of earlier runs must stay verifiable
    raw_check(root, info, files)
    data, episodes = reader(root), []
    cameras = [dict(key=k, shape=v['shape'], dtype=v['dtype']) for k, v in sorted(info['features'].items())
               if k.startswith('observation.images.')]
    for index in range(len(data)):
        row = data[index]
        episode, frame = int(row['episode_index'].item()), int(row['frame_index'].item())
        if not episodes or episodes[-1]['index'] != episode:
            if episode != len(episodes) or frame != 0:
                raise ValueError('official reader episode order differs')
            # The inspection is a bounded display preview; derivative task labels stay intact.
            episodes.append(dict(index=episode, frames=0, task=row['task'][:256]))
        if frame != episodes[-1]['frames'] or int(row['index'].item()) != index:
            raise ValueError('official reader frame order differs')
        if abs(float(row['timestamp'].item())-frame/info['fps']) > 1e-3:
            raise ValueError('official reader timestamp differs')
        for key in ('action', 'observation.state', *(c['key'] for c in cameras)):
            value = row[key].numpy()
            shape = info['features'][key]['shape']
            if key.startswith('observation.images.'):
                shape = [3, shape[0], shape[1]]
            if value.size != math.prod(shape) or not np.isfinite(value).all():
                raise ValueError('official reader numeric/image values differ')
            if key.startswith('observation.images.') and (list(value.shape) != shape or value.min() < 0 or value.max() > 1):
                raise ValueError('official reader RGB shape/range differs')
        if not isinstance(row['task'], str) or not 1 <= len(row['task']) <= 10000:
            raise ValueError('bounded task description required')
        episodes[-1]['frames'] += 1
    if len(episodes) != info['total_episodes'] or len(data) != info['total_frames']:
        raise ValueError('official reader complete frame/episode counts differ')
    result = dict(robot_type=info.get('robot_type'), fps=info['fps'], total_episodes=len(episodes),
        total_frames=len(data), state=layout(info['features']['observation.state']),
        action=layout(info['features']['action']), cameras=cameras, episodes=episodes,
        units='dataset-native/unverified', capture_session_independence='unknown')
    result['revision'] = digest(result)
    verify_files(root, files)
    return result


def layout(feature):
    return dict(shape=feature['shape'], names=feature.get('names') or
                [str(i) for i in range(feature['shape'][0])])


def derive(root, output, inspection, split):
    import numpy as np
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    info = check_info(read_json(root/'meta/info.json'))
    cameras = [c['key'] for c in inspection['cameras']]
    features = {k: dict(dtype='float32', shape=tuple(info['features'][k]['shape']),
                       names=info['features'][k].get('names')) for k in ('action', 'observation.state')}
    features.update({k: dict(dtype='image', shape=(128,128,3), names=['height','width','channels']) for k in cameras})
    children = {name: LeRobotDataset.create(REPO, fps=info['fps'], features=features,
        root=output/name, robot_type=info.get('robot_type'), use_videos=False,
        image_writer_threads=2) for name in ('dataset', 'train-dataset')}
    selected = sorted(set(split['train']+split['validation']+split['eval']))
    data = reader(root)
    offsets, offset = {}, 0
    for episode in inspection['episodes']:
        offsets[episode['index']] = offset
        offset += episode['frames']
    mapping, derived_start, train_start = [], 0, 0
    try:
        for derived_episode, episode in enumerate(selected):
            frames = inspection['episodes'][episode]['frames']
            training = episode in split['train']
            entry = dict(source_episode=episode, derived_episode=derived_episode,
                source_start=offsets[episode], derived_start=derived_start, frames=frames,
                train_episode=split['train'].index(episode) if training else None,
                train_start=train_start if training else None)
            mapping.append(entry)
            for frame in range(frames):
                row = data[offsets[episode]+frame]
                values = {k: row[k].numpy().reshape(features[k]['shape']).copy()
                          for k in ('action', 'observation.state')}
                for key in cameras:
                    image = torch.nn.functional.interpolate(row[key][None], size=(128,128),
                        mode='bilinear', align_corners=False)[0].permute(1,2,0).numpy()
                    values[key] = np.rint(np.clip(image,0,1)*255).astype(np.uint8)
                values['task'] = row['task']
                children['dataset'].add_frame(dict(values))
                if training:
                    children['train-dataset'].add_frame(dict(values))
            children['dataset'].save_episode()
            if training:
                children['train-dataset'].save_episode()
                train_start += frames
            derived_start += frames
    finally:
        for child in children.values():
            child.finalize()
    for name in children:
        actual = reader(output/name)
        expected_count = derived_start if name == 'dataset' else train_start
        if len(actual) != expected_count:
            raise ValueError('derived reader frame count differs')
        for entry in mapping:
            start = entry['derived_start'] if name == 'dataset' else entry['train_start']
            if start is None:
                continue
            for frame in range(entry['frames']):
                original, written = data[entry['source_start']+frame], actual[start+frame]
                for key in ('action', 'observation.state'):
                    np.testing.assert_array_equal(original[key].numpy(), written[key].numpy())
                for key in cameras:
                    if tuple(written[key].shape) != (3,128,128):
                        raise ValueError('derived camera dimensions differ')
    return dict(reader_verified=True, source_info=info, episode_mapping=mapping,
        files=hashes(output/'dataset'), train_files=hashes(output/'train-dataset'),
        normalization_fit='train only', split=split, inspection_revision=inspection['revision'],
        units=inspection['units'], resize=dict(method='bilinear', color='RGB', shape=[128,128]),
        capture_session_independence='unknown', physical_learning_verified=False)
