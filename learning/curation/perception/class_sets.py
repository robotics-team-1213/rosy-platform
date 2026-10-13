"""Immutable class sets the review app binds once per workspace (D-485).

Identity is the ordered class names and the task; display names, colours and
hotkeys are presentation and do not change the sha (renaming a label for people
must not invalidate approved reviews).
"""
import hashlib
import json

import yaml

from object_boxes import OBJECT_CLASSES, REJECT

# Shown when a class file names no display of its own; presentation only, never identity.
DEFAULT_DISPLAY = {'robot': '로봇', 'obstacle_box': '장애물 상자', 'cone': '콘', 'traffic_light': '신호등',
                   'sign': '표지판', 'person': '사람', 'person_feet': '사람 발',
                   'floor': '배경', 'background': '배경', 'lane_line': '차선', 'wall': '벽',
                   'drivable': '주행 영역', 'stop_line': '정지선', 'crosswalk': '횡단보도',
                   'lane_left': '왼쪽 차선', 'lane_right': '오른쪽 차선', 'speed_bump': '과속방지턱'}
TASKS = ('detect', 'semantic')


def _record(names, task, source, display=None, colors=None):
    if task not in TASKS:
        raise ValueError(f'task one of {TASKS}')
    if not names or len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
        raise ValueError('class names must be unique non-empty strings')
    if REJECT in names:
        raise ValueError(f'class name reserved: {REJECT!r} rejects a box')
    display = {} if display is None else display
    colors = {} if colors is None else colors
    if not isinstance(display, dict) or not isinstance(colors, dict):
        raise ValueError('display and colors must be mappings')
    if not all(isinstance(v, str) and v for v in display.values()):
        raise ValueError('display names must be non-empty strings')
    for c in colors.values():
        if not (isinstance(c, list) and len(c) == 3
                and all(type(v) is int and 0 <= v <= 255 for v in c)):
            raise ValueError('color must be [r, g, b] ints 0..255')
    identity = json.dumps({'task': task, 'names': list(names)}, ensure_ascii=False).encode()
    return {'task': task, 'source': source, 'sha256': hashlib.sha256(identity).hexdigest(),
            'classes': [{'index': i, 'name': n, 'display': display.get(n) or DEFAULT_DISPLAY.get(n, n),
                         'color': colors.get(n), 'hotkey': str(i + 1) if i < 9 else None}
                        for i, n in enumerate(names)]}


def from_data_yaml(raw, task):
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f'data.yaml is not valid YAML: {exc}') from exc
    names = doc.get('names') if isinstance(doc, dict) else None
    if isinstance(names, dict):
        if not all(type(k) is int for k in names) or sorted(names) != list(range(len(names))):
            raise ValueError('names indices must be dense 0..N-1')
        names = [names[i] for i in range(len(names))]
    if not isinstance(names, list):
        raise ValueError('data.yaml needs names')
    # Ultralytics writes the model task; only 'detect' matches a set here (its 'segment' is instance masks).
    file_task = doc.get('task')
    if isinstance(file_task, str) and {'detect': 'detect'}.get(file_task) != task:
        raise ValueError(f'data.yaml task {file_task!r} is not a {task} class set')
    return _record(names, task, {'kind': 'data_yaml', 'sha256': hashlib.sha256(raw).hexdigest()},
                   doc.get('display'), doc.get('colors'))


def legacy_object_set():
    return _record(list(OBJECT_CLASSES), 'detect', {'kind': 'd602_v1'})


def object_set(store):
    with store.connect() as db:
        row = db.execute("SELECT value FROM metadata WHERE key='object_class_set'").fetchone()
    return json.loads(row[0]) if row else legacy_object_set()


def bind_object_set(store, record, db=None):
    """With `db`, the caller owns the open write transaction (binding commits with its frames)."""
    if record.get('task') != 'detect':
        raise ValueError('object class set must be a detect set')
    names = [c['name'] for c in record['classes']]
    if _record(names, record['task'], record['source'])['sha256'] != record['sha256']:
        raise ValueError('class set sha256 does not match its names')
    if db is None:
        with store.connect() as own:
            own.execute('BEGIN IMMEDIATE')
            return bind_object_set(store, record, own)
    row = db.execute("SELECT value FROM metadata WHERE key='object_class_set'").fetchone()
    current = json.loads(row[0]) if row else legacy_object_set()
    if current['sha256'] != record['sha256'] and (row or db.execute('SELECT 1 FROM frames LIMIT 1').fetchone()):
        raise ValueError('workspace object classes differ; do not reinterpret labels')
    if not row:
        db.execute("INSERT INTO metadata VALUES ('object_class_set',?)", (json.dumps(record),))
        db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='generation'")
    return record
