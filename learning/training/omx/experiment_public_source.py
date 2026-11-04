"""Fixed public SO100 input, without robot capture or calibration claims."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from experiment_io import read_json, write_json

REPO = 'lerobot/svla_so100_pickplace'
REVISION = '728583b5eaf9e739a7f119e2def466fa1d552402'
DERIVED_REPO = 'rosy-public-study/svla-so100-pickplace-128'
LIMIT = 1024 * 1024 * 1024
NAMES = ['main_shoulder_pan', 'main_shoulder_lift', 'main_elbow_flex',
         'main_wrist_flex', 'main_wrist_roll', 'main_gripper']
CAMERAS = ['observation.images.top', 'observation.images.wrist']
RECIPE = dict(train_episodes=list(range(8)), validation_episodes=[8], eval_episodes=[9],
              image_shape=[128, 128], steps=1000, batch_size=4)


def descriptor():
    return dict(repo_id=REPO, revision=REVISION, license='Apache-2.0', robot_type='so100',
                episodes=50, recipe=RECIPE, units='dataset-native/unverified', offline_only=True)


def check_info(info):
    if (info.get('codebase_version') != 'v3.0' or info.get('robot_type') != 'so100'
            or info.get('total_episodes') != 50 or info.get('fps') != 30):
        raise ValueError('fixed public source metadata differs')
    for key in ('action', 'observation.state'):
        feature = info['features'][key]
        if feature['names'] != NAMES or feature['shape'] != [6] or feature['dtype'] != 'float32':
            raise ValueError('original SO100 joint layout differs')
    for key in CAMERAS:
        if info['features'][key]['shape'] != [480, 640, 3]:
            raise ValueError('original SO100 camera shape differs')
    return info


def allowed(name):
    if not isinstance(name, str):
        raise ValueError('unsafe public source path')
    path = PurePosixPath(name)
    if (not isinstance(name, str) or '\\' in name or ':' in name or path.is_absolute()
            or '..' in path.parts or str(path) != name):
        raise ValueError('unsafe public source path')
    if not (name == 'README.md' or re.fullmatch(r'meta/[a-zA-Z0-9_./-]+\.(json|jsonl|parquet)', name)
            or re.fullmatch(r'data/chunk-\d{3}/file-\d{3}\.parquet', name)
            or re.fullmatch(r'videos/observation\.images\.(top|wrist)/chunk-\d{3}/file-\d{3}\.mp4', name)):
        raise ValueError('unsupported public source file')
    return name


def hashes(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('owned artifact root must not be a link')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('public artifacts must not contain links')
        if path.is_file():
            with path.open('rb') as stream:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def probe():
    from huggingface_hub import HfApi, hf_hub_download
    api = HfApi(token=False)
    card = api.dataset_info(REPO, revision=REVISION, token=False)
    if card.sha != REVISION or (card.card_data or {}).get('license') != 'apache-2.0':
        raise ValueError('fixed public revision or upstream license differs')
    path = hf_hub_download(REPO, 'meta/info.json', repo_type='dataset', revision=REVISION, token=False)
    info = check_info(json.loads(Path(path).read_bytes()))
    return dict(descriptor(), source_info=info, available=True, reason=None)


def download(root):
    from huggingface_hub import HfApi, hf_hub_download
    source = probe()
    entries = [entry for entry in HfApi(token=False).list_repo_tree(
        REPO, repo_type='dataset', revision=REVISION, recursive=True, token=False)
        if hasattr(entry, 'size') and entry.path != '.gitattributes']
    if not entries or len(entries) > 1024 or sum(entry.size for entry in entries) > LIMIT:
        raise ValueError('public source exceeds download budget')
    root.mkdir()
    for entry in entries:
        name = allowed(entry.path)
        path = Path(hf_hub_download(REPO, name, repo_type='dataset', revision=REVISION,
                                    token=False, local_dir=root))
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size != entry.size:
            raise ValueError('public downloaded file differs from bounded source')
        raw = path.read_bytes()
        lfs = entry.lfs
        expected = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
        digest = hashlib.sha256(raw).hexdigest() if expected else hashlib.sha1(
            b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if digest != (expected or entry.blob_id):
            raise ValueError('public source file hash differs from pinned Hub tree')
    # Hub download bookkeeping is outside the source manifest and never published.
    source['files'] = {entry.path: hashlib.sha256((root/entry.path).read_bytes()).hexdigest() for entry in entries}
    check_info(read_json(root/'meta/info.json'))
    return source


def derive(source_root, output):
    import numpy as np
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    info = check_info(read_json(source_root/'meta/info.json'))
    source = LeRobotDataset(REPO, root=source_root, episodes=list(range(10)),
                            download_videos=False, video_backend='pyav')
    features = {key: dict(dtype='float32', shape=(6,), names=NAMES)
                for key in ('action', 'observation.state')}
    features.update({key: dict(dtype='image', shape=(128, 128, 3), names=['height', 'width', 'channels'])
                     for key in CAMERAS})
    datasets = {}
    for name in ('dataset', 'train-dataset'):
        datasets[name] = LeRobotDataset.create(DERIVED_REPO, fps=30, features=features,
            root=output/name, robot_type=info['robot_type'], use_videos=False,
            image_writer_threads=2)
    previous, mappings, count = None, [], 0
    for index in range(len(source)):
        frame = source[index]
        episode = int(frame['episode_index'].item())
        if episode not in range(10):
            raise ValueError('source reader returned an unselected episode')
        if previous is not None and episode != previous:
            datasets['dataset'].save_episode()
            if previous < 8:
                datasets['train-dataset'].save_episode()
        if episode != previous:
            mappings.append(dict(source_episode=episode, derived_episode=len(mappings)))
        previous = episode
        values = {key: frame[key].numpy().copy() for key in ('action', 'observation.state')}
        if any(not np.isfinite(values[key]).all() for key in values):
            raise ValueError('source contains nonfinite joint values')
        for key in CAMERAS:
            image = torch.nn.functional.interpolate(frame[key][None], size=(128, 128),
                mode='bilinear', align_corners=False)[0].permute(1, 2, 0).numpy()
            values[key] = np.rint(np.clip(image, 0, 1)*255).astype(np.uint8)
        values['task'] = frame['task']
        datasets['dataset'].add_frame(dict(values))
        if episode < 8:
            datasets['train-dataset'].add_frame(dict(values))
        count += 1
    if previous != 9 or [m['source_episode'] for m in mappings] != list(range(10)):
        raise ValueError('first ten source episodes must be complete and ordered')
    datasets['dataset'].save_episode()
    for dataset in datasets.values():
        dataset.finalize()
    derived_info = read_json(output/'dataset/meta/info.json')
    derived_info['splits'] = dict(train='0:8', validation='8:9', test='9:10')
    write_json(output/'dataset/meta/info.json', derived_info)
    write_json(output/'dataset/source-provenance.json', dict(source=descriptor(),
        episode_mapping=mappings, upstream_info=info, recipe=RECIPE,
        units='dataset-native/unverified', physical_learning_verified=False))
    # Read the written derivative rather than trusting the writer or metadata alone.
    derived = LeRobotDataset(DERIVED_REPO, root=output/'dataset', download_videos=False, video_backend='pyav')
    if len(derived) != count or derived.num_episodes != 10:
        raise ValueError('derived reader frame/episode counts differ')
    for index in range(count):
        original, actual = source[index], derived[index]
        for key in ('action', 'observation.state'):
            np.testing.assert_array_equal(actual[key].numpy(), original[key].numpy())
        for key in CAMERAS:
            if tuple(actual[key].shape) != (3, 128, 128):
                raise ValueError('derived reader camera shape differs')
    return dict(reader_verified=True, source_info=info, episode_mapping=mappings, frames=count,
                recipe=RECIPE, normalization_fit='train episodes 0..7 only',
                units='dataset-native/unverified', resize=dict(method='bilinear', color='RGB', shape=[128, 128]),
                split_independence='episode only; capture-session independence unverified',
                files=hashes(output/'dataset'), train_files=hashes(output/'train-dataset'))
