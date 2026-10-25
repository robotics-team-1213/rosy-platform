"""OMX intake inspection and immutable human grasp-segment reviews; no device action.

Dataset step (D-857 P0): python learning/curation/perception/omx_web.py export-segments
  --db <review state>/reviews.sqlite3 --id <registered set id> --out <new folder>
exports the latest saved segment review exactly as native_segments.py does for a downloaded JSON.
"""
import argparse
from contextlib import closing
import io
import json
import sqlite3
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'omx'))
from native_review import reviewed_splits  # noqa: E402

STATIC = Path(__file__).with_name('review_app_web')
PAGES = {'/learning/omx': ('omx.html', 'text/html; charset=utf-8'),
         '/omx-profiles.js': ('omx-profiles.js', 'text/javascript; charset=utf-8'),
         '/omx-review.js': ('omx-review.js', 'text/javascript; charset=utf-8'),
         '/omx.js': ('omx.js', 'text/javascript; charset=utf-8')}
LIMIT = 8 * 1024 * 1024


def _read(root, name):
    """One JSON document directly inside a registered folder, or None when it is absent."""
    file = root / name
    try:
        if not file.exists() and not file.is_symlink():
            return None
        if (file.is_symlink() or not file.is_file() or file.resolve().parent != root.resolve()
                or file.stat().st_size > LIMIT):
            raise ValueError('bounded regular file required')
        return json.loads(file.read_bytes().decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'{name}: 등록된 JSON 파일을 읽을 수 없습니다.') from exc


def _verdicts(setup, index):
    rows = {row['episode_index']: row['checks'] for row in (setup or {}).get('episodes', [])}
    return {role: {'before': check['before']['verdict'], 'after': check['after']['verdict'],
                   'pose_error_rad': check['before']['pose_error_rad']}
            for role, check in rows.get(index, {}).items()}


def prepared_set(row, workspace=None, center=None):
    """One registered row as the page shows it, or None when it is not a prepared intake folder."""
    import native_segments as segments
    root = Path(row['path'])
    try:
        if _read(root, 'intake-receipt.json') is None:
            return None
        inspection, decisions = _read(root, 'inspection.json'), _read(root, 'decisions.json')
        setup = _read(root, 'camera-setup.json')
        if (not isinstance(inspection, dict) or not isinstance(inspection.get('episodes'), list)
                or not all(isinstance(e, dict) for e in inspection['episodes'])
                or not isinstance(decisions, list) or not all(isinstance(e, dict) for e in decisions)
                or (setup is not None and not isinstance(setup, dict))):
            raise ValueError('invalid intake metadata shape')
        keys = inspection.get('camera_keys', [])
        if (not isinstance(keys, list) or not all(isinstance(key, str) and key for key in keys)
                or not decisions or any(type(e.get('episode_index')) is not int or e['episode_index'] < 0
                                        or type(e.get('frames')) is not int or e['frames'] < 1 for e in decisions)):
            raise ValueError('invalid camera keys or episode identity')
        try:
            splits = reviewed_splits(inspection, decisions)
            trainable = {'ok': True, 'counts': {name: len(splits[name]) for name in ('train', 'eval', 'test')
                                                if isinstance(splits.get(name), list)}}
        except (KeyError, TypeError, ValueError) as exc:
            trainable = {'ok': False, 'reason': str(exc)}
        episodes = [{key: decision.get(key) for key in ('episode_index', 'session_id', 'cycle_id', 'content_sha256', 'frames', 'split', 'outcome',
                                                        'object_result', 'reviewer', 'reason')}
                    | {'camera': _verdicts(setup, decision.get('episode_index'))}
                    for decision in decisions or []]
        review_fields = {}
        if center:
            try:
                review = center.review(row)
                trainable = review['trainable']
                review_fields = {key: review[key] for key in ('latest_review_id', 'source_revision', 'fixture_only')}
                episodes = [dict(decision, camera=_verdicts(setup, decision['episode_index'])) for decision in review['decisions']]
            except (ValueError, OSError) as exc:
                trainable = {'ok': False, 'reason': str(exc)}
        review = latest(workspace, row['id']) if workspace else {'version': 0, 'document': None}
        if review['document'] is not None:
            try:
                segments.validate_selection(inspection, review['document'], require_splits=False)
            except ValueError:
                return {'id': row['id'], 'name': row['name'], 'error': '원본이 바뀌어 기존 구간 검수와 일치하지 않습니다.'}
        return {'id': row['id'], 'name': row['name'], 'trainable': trainable, 'episodes': episodes, **review_fields,
                'segment_review': review, 'camera_keys': inspection.get('camera_keys', []),
                'camera_setup': None if setup is None else {'mode': setup.get('mode'), 'references': setup.get('references'),
                                                            'camera_info_sha256': setup.get('camera_info_sha256')}}
    except (AttributeError, KeyError, TypeError, OSError, ValueError):
        return {'id': row['id'], 'name': row['name'], 'error': '등록 자료가 불완전하거나 손상됐습니다. 원본 검증을 다시 실행하세요.'}


def get(handler, path, workspace, center=None):
    """Serve the OMX page and its read; False leaves the path to review_app."""
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif path == '/api/learning/omx':
        rows = [row for row in workspace.list() if row['kind'] == 'omx']
        handler.send({'sets': [s for row in rows if (s := prepared_set(row, workspace, center)) is not None]})
    elif path == '/api/learning/omx/frame':
        import native_segments as segments
        query = parse_qs(urlparse(handler.path).query, strict_parsing=True)
        if set(query) != {'id', 'episode', 'frame', 'camera'} or any(len(v) != 1 for v in query.values()):
            raise ValueError('registered set and one episode/frame/camera required')
        row = registered(workspace, query['id'][0])
        root = Path(row['path'])
        report = _read(root, 'inspection.json')
        if segments.native.dataset_files(root) != report['files']:
            raise ValueError('source bytes changed since inspection')
        dataset = segments.native.load_dataset(root, report['repo_id'])
        frame = segments.frame_at(dataset, report, int(query['episode'][0]), int(query['frame'][0]))
        key = query['camera'][0]
        if key not in report['camera_keys']:
            raise ValueError('camera is not declared by original inspection')
        from PIL import Image
        pixels = segments.copy_frame(frame, {key: {}})[key]
        if segments.native.dataset_files(root) != report['files']:
            raise ValueError('source bytes changed while reading frame')
        output = io.BytesIO()
        Image.fromarray(pixels).save(output, format='JPEG', quality=95)
        handler.send(output.getvalue(), mime='image/jpeg', cache='no-store')
    else:
        return False
    return True


def registered(workspace, identifier):
    rows = [row for row in workspace.list() if row['id'] == identifier and row['kind'] == 'omx']
    if len(rows) != 1 or _read(Path(rows[0]['path']), 'intake-receipt.json') is None:
        raise ValueError('registered OMX intake required')
    return rows[0]


def review_db(workspace):
    db = sqlite3.connect(workspace.db)
    db.execute('CREATE TABLE IF NOT EXISTS omx_segment_reviews '
               '(id TEXT, version INTEGER, document TEXT, PRIMARY KEY(id,version))')
    return db


def latest(workspace, identifier):
    with review_db(workspace) as db:
        row = db.execute('SELECT version,document FROM omx_segment_reviews WHERE id=? '
                         'ORDER BY version DESC LIMIT 1', (identifier,)).fetchone()
    return {'version': row[0], 'document': json.loads(row[1])} if row else {'version': 0, 'document': None}


def post(handler, path, body, workspace, conflict):
    """Append reviewed selections after existing token/origin and project manage authorization."""
    if path != '/api/learning/omx/segments':
        return False
    import native_segments as segments
    actor = getattr(handler, 'learning_principal', {}).get('user_id')
    if set(body) != {'id', 'version', 'segments'} or type(body['version']) is not int:
        raise ValueError('registered id, integer review version and segments required')
    row = registered(workspace, body['id'])
    root = Path(row['path'])
    report = _read(root, 'inspection.json')
    document = segments.selection(report, body['segments'])
    if actor and isinstance(document['segments'], list):
        for segment in document['segments']:
            if not isinstance(segment, dict):
                raise ValueError('segment object required')
            segment['reviewer'] = actor
    segments.validate_selection(report, document, require_splits=False)
    with review_db(workspace) as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT COALESCE(MAX(version),0) FROM omx_segment_reviews WHERE id=?',
                             (row['id'],)).fetchone()[0]
        if current != body['version']:
            raise conflict('구간 검수가 바뀌었습니다. 다시 불러오세요.')
        db.execute('INSERT INTO omx_segment_reviews VALUES (?,?,?)',
                   (row['id'], current+1, json.dumps(document, ensure_ascii=False, allow_nan=False)))
    handler.send({'version': current+1, 'document': document})
    return True


def export_saved(db, identifier, output):
    """Latest saved human segment review -> the native_segments export; the review DB is opened read-only."""
    import native_segments as segments
    try:
        with closing(sqlite3.connect(Path(db).resolve(strict=True).as_uri() + '?mode=ro', uri=True)) as conn:
            link = conn.execute("SELECT path FROM learning_links WHERE id=? AND kind='omx'", (identifier,)).fetchone()
            review = conn.execute('SELECT document FROM omx_segment_reviews WHERE id=? '
                                  'ORDER BY version DESC LIMIT 1', (identifier,)).fetchone()
    except sqlite3.Error as exc:
        raise ValueError(f'review database with registered sets and segment reviews required ({exc})') from exc
    if link is None or _read(Path(link[0]), 'intake-receipt.json') is None:
        raise ValueError('registered OMX intake required')
    if review is None:
        raise ValueError('saved segment review required')
    root = Path(link[0])
    return segments.export_segments(root, _read(root, 'inspection.json'), json.loads(review[0]), output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export-segments', help='latest saved segment review -> train/eval datasets')
    export.add_argument('--db', type=Path, required=True)
    export.add_argument('--id', required=True)
    export.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        export_saved(args.db, args.id, args.out)
    except (ValueError, OSError, ImportError, AssertionError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(f'Written: {args.out}; offline segments, no upload or device action.')


if __name__ == '__main__':
    main()
