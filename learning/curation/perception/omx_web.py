"""D-792 S4: read-only OMX imitation-learning page for review_app.py (no writes, no device action).

Lists prepared intake folders that are registered as ``omx`` learning rows: per episode the review
decision, whether the set would train (the same ``reviewed_splits`` rule training uses), and the
D-792 shadow camera setup checks. Keep/drop writes, ACT start/stop and promotion are not here.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'omx'))
from native_review import reviewed_splits  # noqa: E402

STATIC = Path(__file__).with_name('review_app_web')
PAGES = {'/learning/omx': ('omx.html', 'text/html; charset=utf-8'),
         '/omx.js': ('omx.js', 'text/javascript; charset=utf-8')}
LIMIT = 8 * 1024 * 1024


def _read(root, name):
    """One JSON document directly inside a registered folder, or None when it is absent."""
    file = root / name
    if not file.exists() and not file.is_symlink():
        return None
    if file.is_symlink() or file.resolve().parent != root.resolve() or file.stat().st_size > LIMIT:
        raise ValueError(f'{name} must be a regular JSON file under 8 MiB in the registered folder')
    return json.loads(file.read_bytes().decode('utf-8'))


def _verdicts(setup, index):
    rows = {row['episode_index']: row['checks'] for row in (setup or {}).get('episodes', [])}
    return {role: {'before': check['before']['verdict'], 'after': check['after']['verdict'],
                   'pose_error_rad': check['before']['pose_error_rad']}
            for role, check in rows.get(index, {}).items()}


def prepared_set(row):
    """One registered row as the page shows it, or None when it is not a prepared intake folder."""
    root = Path(row['path'])
    try:
        if _read(root, 'intake-receipt.json') is None:
            return None
        inspection, decisions = _read(root, 'inspection.json'), _read(root, 'decisions.json')
        setup = _read(root, 'camera-setup.json')
    except (OSError, ValueError) as exc:
        return {'id': row['id'], 'name': row['name'], 'error': str(exc)}
    try:
        splits = reviewed_splits(inspection, decisions)
        trainable = {'ok': True, 'counts': {name: len(splits[name]) for name in ('train', 'eval', 'test')
                                            if isinstance(splits.get(name), list)}}
    except (KeyError, TypeError, ValueError) as exc:
        trainable = {'ok': False, 'reason': str(exc)}
    episodes = [{key: decision.get(key) for key in ('episode_index', 'session_id', 'frames', 'split', 'outcome',
                                                    'object_result', 'reviewer', 'reason')}
                | {'camera': _verdicts(setup, decision.get('episode_index'))}
                for decision in decisions or []]
    return {'id': row['id'], 'name': row['name'], 'trainable': trainable, 'episodes': episodes,
            'camera_setup': None if setup is None else {'mode': setup.get('mode'), 'references': setup.get('references'),
                                                        'camera_info_sha256': setup.get('camera_info_sha256')}}


def get(handler, path, workspace):
    """Serve the OMX page and its read; False leaves the path to review_app."""
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif path == '/api/learning/omx':
        rows = [row for row in workspace.list() if row['kind'] == 'omx']
        handler.send({'sets': [s for s in map(prepared_set, rows) if s is not None]})
    else:
        return False
    return True
