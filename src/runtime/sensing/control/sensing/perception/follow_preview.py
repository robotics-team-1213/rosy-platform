"""Subject: explain frame-matched following and foreground evidence, no motion.

Boxes are foreground/dark regions, not semantic object identities or tracks.
The dotted arrow is a target guide in image space, not a predicted motor path.
"""
from collections import deque
import math

import cv2
import numpy as np


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class FrameEvidence:
    """Small capture-stamp join; receipt time never substitutes for capture time."""

    def __init__(self):
        self._samples = {key: deque(maxlen=8) for key in ('keep', 'line', 'objects', 'road_state')}

    def add(self, kind, sample):
        if isinstance(sample, dict) and _number(sample.get('stamp')):
            self._samples[kind].append(sample)

    def for_frame(self, kind, stamp):
        if not _number(stamp):
            return None
        return next((doc for doc in reversed(self._samples[kind])
                     if abs(doc['stamp'] - stamp) <= 1e-6), None)

    def select_frame(self, frames):
        """Prefer a recently completed frame over a newer in-flight callback."""
        latest = frames[-1]
        for frame in reversed(frames):
            if 0 <= latest[3] - frame[3] <= .5 and (
                    self.for_frame('keep', frame[3]) is not None
                    or self.for_frame('line', frame[3]) is not None):
                return frame
        return latest


def predicted_road(state):
    """Near-field lane-centre model used by road_state (D-384), metres, left +.

    This is estimated road geometry, never an object's future motion or a command.
    Stay inside the estimator's 0.33 m near-field measurement domain.
    """
    if not isinstance(state, dict) or state.get('level') not in ('TRACK', 'COAST', 'SLOW'):
        return None
    if state.get('calibration_suspect'):
        return None
    if not all(_number(state.get(k)) for k in ('d', 'phi', 'kappa', 'w')) or state['w'] <= 0:
        return None
    return [(float(x), float(-state['d'] - x * state['phi'] + state['kappa'] * x * x / 2))
            for x in np.linspace(0, .33, 18)]


def draw_follow_evidence(image, *, scale, keep=None, objects=None, road_state=None, line=None):
    """Draw evidence on a resized BGR frame. Missing means unknown, never clear."""
    h, w = image.shape[:2]
    white, bg = (245, 248, 250), (12, 18, 28)
    green, blue, magenta, orange = (60, 220, 60), (230, 120, 40), (230, 60, 230), (0, 140, 255)
    original_size = [int(round(w / scale)), int(round(h / scale))]

    def text(label, xy, colour=white):
        cv2.putText(image, label, xy, cv2.FONT_HERSHEY_SIMPLEX,
                    .34 if w < 400 else .46, colour, 1, cv2.LINE_AA)

    def point(raw):
        if (not isinstance(raw, (list, tuple)) or len(raw) != 2
                or not all(_number(v) for v in raw)):
            return None
        # Bound untrusted geometry before giving it to OpenCV's integer API.
        if any(abs(v * scale) > 4 * max(w, h) for v in raw):
            return None
        return tuple(int(round(v * scale)) for v in raw)

    def segment(record, colour, label):
        if not isinstance(record, dict):
            return
        ends = record.get('ends_px')
        if not isinstance(ends, (list, tuple)) or len(ends) != 2:
            return
        a, b = point(ends[0]), point(ends[1])
        if a is not None and b is not None:
            cv2.line(image, a, b, colour, 2)
            x, y = b
            text(label, (max(2, min(w - 100, x)), max(44, min(h - 64, y))), colour)

    def records(doc, key, limit):
        value = doc.get(key)
        return value[:limit] if isinstance(value, list) else []

    if not isinstance(keep, dict) or keep.get('image_size', original_size) != original_size:
        keep = None
    if keep is None and isinstance(line, dict) and line.get('source') == 'CAMERA_LINE':
        keep = dict(strategy='camera_line' if line.get('visible') is True else 'none',
                    error=line.get('error'), confidence=line.get('confidence'), reason='line lost')
    status = 'FOLLOW: unavailable (no same-frame evidence)'
    detail = 'No selected target'
    if keep is not None:
        for record in records(keep, 'boundaries', 24):
            side = record.get('side') if isinstance(record, dict) else None
            segment(record, green if side == 'left' else blue, str(side or 'boundary'))
        for record in records(keep, 'candidates', 24):
            if isinstance(record, dict) and record.get('rejected'):
                segment(record, orange, 'excluded: ' + str(record.get('reason') or 'unknown')[:24])
        strategy = str(keep.get('strategy') or 'none')
        error, confidence = keep.get('error'), keep.get('confidence')
        target = point(keep.get('target_px'))
        valid = (strategy != 'none' and _number(error) and -1 <= error <= 1
                 and _number(confidence) and 0 < confidence <= 1)
        if not valid:
            status = 'HOLD: ' + str(keep.get('reason') or 'no valid target')[:40]
        else:
            direction = 'RIGHT' if error > .05 else ('LEFT' if error < -.05 else 'CENTRE')
            status = f'FOLLOW {direction} | {strategy} | {confidence:.0%}'
            detail = f'error {error:+.2f} | target outside view'
            if target is not None and 0 <= target[0] < w and 28 <= target[1] < h:
                origin = np.array([w // 2, h - 62], dtype=float)
                end = np.array(target, dtype=float)
                # Discontinuous guide deliberately cannot be mistaken for a seen lane.
                for t in np.arange(0, 1, .13):
                    a = tuple(np.rint(origin + t * (end - origin)).astype(int))
                    b = tuple(np.rint(origin + min(t + .06, 1) * (end - origin)).astype(int))
                    cv2.line(image, a, b, magenta, 2)
                cv2.circle(image, target, 6, magenta, 2)
                text('TARGET', (max(2, min(w - 65, target[0] + 9)), max(43, target[1] - 8)), magenta)
                detail = f'error {error:+.2f} | dotted: target guide'

    # A separate top view makes the road estimate visually distinct from the
    # measured image boundaries and from the selected target guide.
    samples = predicted_road(road_state)
    if samples is not None and w >= 240 and h >= 180:
        size = min(100, int(w * .29), h - 100)
        x0, y0 = w - size - 5, 34
        cv2.rectangle(image, (x0, y0), (x0 + size, y0 + size), bg, -1)
        text('ROAD SHADOW', (x0 + 3, y0 + 12))
        def bev(x, y):
            return (x0 + size // 2 - int(round(np.clip(y / .25, -1, 1) * size / 2)),
                    y0 + size - 7 - int(round(x / .33 * (size - 27))))
        centre = np.array([bev(x, y) for x, y in samples], np.int32)
        for offset, colour in ((road_state['w'] / 2, green), (-road_state['w'] / 2, blue)):
            edge = np.array([bev(x, y + offset) for x, y in samples], np.int32)
            cv2.polylines(image, [edge], False, colour, 1)
        for index in range(0, len(centre) - 1, 2):
            cv2.line(image, tuple(centre[index]), tuple(centre[index + 1]), magenta, 2)
        cv2.drawMarker(image, bev(0, 0), white, cv2.MARKER_TRIANGLE_UP, 7, 1)
        text(str(road_state['level']) + ' 0.33m', (x0 + 3, y0 + size + 12))

    object_status = 'OBJECTS: unavailable'
    if (isinstance(objects, dict) and objects.get('image_size') == original_size
            and isinstance(objects.get('quality'), dict) and objects['quality'].get('valid') is True):
        regions = objects.get('regions')
        if isinstance(regions, list):
            object_status = f'REGIONS: {len(regions)} | class / motion unknown'
            labelled = 0
            for index, record in enumerate(regions[:48]):
                if not isinstance(record, dict):
                    continue
                box = record.get('b')
                if not isinstance(box, (list, tuple)) or len(box) != 4:
                    continue
                a, b = point(box[:2]), point(box[2:])
                if a is None or b is None or a[0] >= b[0] or a[1] >= b[1]:
                    continue
                near = record.get('n') == 1
                colour = (40, 70, 255) if near else orange
                cv2.rectangle(image, a, b, colour, 2)
                distance = record.get('m')
                ranged = f'{distance:.2f}m' if _number(distance) and distance > 0 else 'unranged'
                kind = 'D' if record.get('k') == 'd' else 'F'
                # Short, limited badges avoid covering the image with region
                # labels. Numbers are frame-local regions, never track IDs.
                if labelled < 3:
                    text(f'{kind}{index + 1} {ranged}' + (' NEAR' if near else ''),
                         (max(2, min(w - 110, a[0] + 3)), max(43, min(h - 66, a[1] + 12))), colour)
                    labelled += 1
    cv2.rectangle(image, (0, h - 59), (w - 1, h - 1), bg, -1)
    text(status, (6, h - 44))
    text(detail, (6, h - 29), magenta)
    text(object_status, (6, h - 15))
    prediction_status = 'PRED unavailable'
    if isinstance(road_state, dict):
        if samples is not None:
            prediction_status = 'PRED ' + str(road_state['level'])
        elif road_state.get('calibration_suspect'):
            prediction_status = 'PRED calibration suspect'
        elif road_state.get('level') == 'STOP':
            prediction_status = 'PRED STOP: ' + str(road_state.get('stop_reason') or 'no estimate')[:16]
    text(prediction_status + ' | guide != motor path', (6, h - 3))
