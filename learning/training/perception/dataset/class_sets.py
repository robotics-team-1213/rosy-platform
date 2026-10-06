"""Immutable class sets the review app binds once per workspace (D-485).

Identity is the ordered class names and the task; display names, colours and
hotkeys are presentation and do not change the sha (renaming a label for people
must not invalidate approved reviews).
"""
import hashlib
import json

import yaml

from object_boxes import OBJECT_CLASSES

KOREAN = {'robot': '로봇', 'obstacle_box': '장애물 상자', 'cone': '콘', 'traffic_light': '신호등',
          'sign': '표지판', 'person_feet': '사람 발'}
TASKS = ('detect', 'semantic')


def _record(names, task, source, display=None, colors=None):
    if task not in TASKS:
        raise ValueError(f'task one of {TASKS}')
    if not names or len(set(names)) != len(names) or not all(isinstance(n, str) and n for n in names):
        raise ValueError('class names must be unique non-empty strings')
    display = {} if display is None else display
    colors = {} if colors is None else colors
    if not isinstance(display, dict) or not isinstance(colors, dict):
        raise ValueError('display and colors must be mappings')
    for c in colors.values():
        if not (isinstance(c, list) and len(c) == 3
                and all(type(v) is int and 0 <= v <= 255 for v in c)):
            raise ValueError('color must be [r, g, b] ints 0..255')
    identity = json.dumps({'task': task, 'names': list(names)}, ensure_ascii=False).encode()
    return {'task': task, 'source': source, 'sha256': hashlib.sha256(identity).hexdigest(),
            'classes': [{'index': i, 'name': n, 'display': display.get(n, n),
                         'color': colors.get(n), 'hotkey': str(i + 1) if i < 9 else None}
                        for i, n in enumerate(names)]}


def from_data_yaml(raw, task):
    doc = yaml.safe_load(raw)
    names = doc.get('names') if isinstance(doc, dict) else None
    if isinstance(names, dict):
        if sorted(names) != list(range(len(names))):
            raise ValueError('names indices must be dense 0..N-1')
        names = [names[i] for i in range(len(names))]
    if not isinstance(names, list):
        raise ValueError('data.yaml needs names')
    return _record(names, task, {'kind': 'data_yaml', 'sha256': hashlib.sha256(raw).hexdigest()},
                   doc.get('display'), doc.get('colors'))


def legacy_object_set():
    return _record(list(OBJECT_CLASSES), 'detect', {'kind': 'd423_v1'}, KOREAN)
