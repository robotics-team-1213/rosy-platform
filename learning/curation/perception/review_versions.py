"""Read-only, bounded review history and immutable snapshot previews."""
import json

import cv2
import numpy as np

import review_masks


def _table(lane):
    if lane not in ('object', 'pixel'):
        raise ValueError('object or pixel lane required')
    return 'events' if lane == 'object' else 'pixel_events'


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2147483647:
        raise ValueError('bounded non-negative integer required')
    return value


def _event(row, lane):
    detail = json.loads(row['review'])
    result = {key: row[key] for key in ('version', 'action', 'ts')}
    actor = detail.get('last_actor' if lane == 'object' else 'actor')
    if actor:
        result['actor'] = actor
    return result


def page(store, lane, index, before=None, limit=20):
    table = _table(lane)
    store.get(_integer(index))
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('history limit must be 1..100')
    if before is not None:
        _integer(before, 1)
    with store.connect() as db:
        rows = db.execute(f'SELECT version,action,ts,review FROM {table} WHERE frame=? '
                          'AND (? IS NULL OR version<?) ORDER BY version DESC LIMIT ?',
                          (index, before, before, limit + 1)).fetchall()
    return {'events': [_event(row, lane) for row in rows[:limit]],
            'next_before': rows[limit - 1]['version'] if len(rows) > limit else None}


def _snapshot(store, lane, index, number):
    table = _table(lane)
    frame = store.get(_integer(index))
    _integer(number)
    with store.connect() as db:
        row = db.execute(f'SELECT version,action,ts,review FROM {table} WHERE frame=? AND version=? '
                         'ORDER BY id DESC LIMIT 1', (index, number)).fetchone()
        result = dict(_event(row, lane) if row else {}, lane=lane, index=index, version=number,
                      image_sha256=frame['source']['image_sha256'], available=False)
        if lane == 'object':
            if row is None:
                return result, None
            detail = json.loads(row['review'])
            if detail.get('image_sha256') != result['image_sha256']:
                raise ValueError('snapshot source image differs')
            store.validate_boxes(frame['source'], detail['boxes'], classes=store.object_classes())
            status = ('excluded' if detail.get('disposition') == 'excluded_by_user' else
                      'approved' if detail.get('review_status') == 'approved' and
                      detail.get('complete_frame_review') is True else 'pending')
            result.update(available=True, boxes=detail['boxes'], status=status)
            return result, None
        review = review_masks.get(store, index)
        snapshot = review if review['version'] == number else None
        if snapshot is None:
            # Legacy pixel events record the previous mask, not the newly saved mask.
            for later in db.execute('SELECT review FROM pixel_events WHERE frame=? AND version>? '
                                    'ORDER BY version ASC', (index, number)):
                prior = json.loads(later['review'])
                if prior.get('version') == number:
                    snapshot = dict(review, path=prior.get('path'), sha256=prior.get('sha256'))
                    break
        if snapshot is None or not snapshot.get('path') or not review['classes']:
            return result, None
        try:
            pixels = review_masks.pixels(store, snapshot)
        except FileNotFoundError:
            return result, None
        allowed = {entry['index'] for entry in review['classes']['classes']} | {255}
        if not set(np.unique(pixels)).issubset(allowed):
            raise ValueError('snapshot contains unknown class index')
        result.update(available=True, mask_sha256=snapshot['sha256'], width=review['width'],
                      height=review['height'], classes=review['classes'],
                      current=number == review['version'])
        if number == review['version']:
            result['status'] = review['status']
        elif row:
            result['status'] = {'approve': 'approved', 'exclude': 'excluded'}.get(row['action'], 'pending')
        return result, pixels


def version(store, lane, index, version):
    with store.lock:
        result, _ = _snapshot(store, lane, index, version)
        return result


def image(store, index, version):
    with store.lock:
        result, mask = _snapshot(store, 'pixel', index, version)
        if not result['available']:
            raise ValueError('historical mask snapshot unavailable')
        photo = cv2.imdecode(np.frombuffer(store.image(index).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if photo is None or photo.shape[:2] != mask.shape:
            raise ValueError('source image dimensions differ')
        overlay = photo.copy()
        for entry in result['classes']['classes']:
            selected = mask == entry['index']
            overlay[selected] = np.array(entry['color'][::-1], dtype=np.uint8)
        return review_masks.encode(cv2.addWeighted(photo, .5, overlay, .5, 0))
