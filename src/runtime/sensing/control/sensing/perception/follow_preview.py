"""Subject: explain frame-matched following and foreground evidence, no motion.

Boxes are foreground/dark regions, not semantic object identities or tracks.
The dotted arrow is a target guide in image space, not a predicted motor path.
D-423: a detection (object_detector.TOPIC) names a region it overlaps; the pairing is
for display only, and the range shown is the detection's own (never borrowed).
"""
from collections import deque
import math

import cv2
import numpy as np

from .lane_topology import lane_hypotheses


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value))


class FrameEvidence:
    """Small capture-stamp join; receipt time never substitutes for capture time."""

    def __init__(self):
        self._samples = {key: deque(maxlen=8)
                         for key in ('keep', 'line', 'objects', 'road_state', 'detections')}

    def add(self, kind, sample):
        if kind == 'detections' and isinstance(sample, dict) and 'stamp' not in sample:
            sample = dict(sample, stamp=sample.get('observed_at'))  # DetectionEvidence time
        if isinstance(sample, dict) and _number(sample.get('stamp')):
            self._samples[kind].append(sample)

    def for_frame(self, kind, stamp):
        if not _number(stamp):
            return None
        return next((doc for doc in reversed(self._samples[kind])
                     if abs(doc['stamp'] - stamp) <= 1e-6), None)

    def recent(self, kind, stamp, max_age):
        """Newest sample taken at or before `stamp`, at most max_age older (2 Hz detections)."""
        if not _number(stamp):
            return None
        return next((doc for doc in reversed(self._samples[kind])
                     if 0 <= stamp - doc['stamp'] <= max_age), None)

    def select_frame(self, frames):
        """Prefer a recently completed frame over a newer in-flight callback."""
        latest = frames[-1]
        for frame in reversed(frames):
            if 0 <= latest[3] - frame[3] <= .5 and (
                    self.for_frame('keep', frame[3]) is not None
                    or self.for_frame('line', frame[3]) is not None):
                return frame
        return latest


DETECTION_MIN_IOU = 0.3  # D-423 §2.3: below this a detection and a region are not one object


def _box_iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    inter = max(w, 0) * max(h, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _detection_box(detection, size):
    values = [detection.get(k) for k in ('x', 'y', 'w', 'h')] if isinstance(detection, dict) else []
    if len(values) != 4 or not all(_number(v) for v in values):
        return None
    x, y, w, h = values
    return [x * size[0], y * size[1], (x + w) * size[0], (y + h) * size[1]]


def pair_detections(regions, detections, size, min_iou=DETECTION_MIN_IOU):
    """{region index: detection index}, greedy by IoU, each used once, IoU >= min_iou."""
    pairs = []
    for di, detection in enumerate(detections):
        box = _detection_box(detection, size)
        for ri, region in enumerate(regions):
            rb = region.get('b') if isinstance(region, dict) else None
            if box is not None and isinstance(rb, (list, tuple)) and len(rb) == 4:
                iou = _box_iou(box, rb)
                if iou >= min_iou:
                    pairs.append((iou, ri, di))
    out, used = {}, set()
    for _, ri, di in sorted(pairs, reverse=True):
        if ri not in out and di not in used:
            out[ri] = di
            used.add(di)
    return out


def _range_label(record):
    distance = record.get('m') if isinstance(record, dict) else None
    if not (_number(distance) and distance > 0):
        return 'unranged'
    source = record.get('s')
    return f'{distance:.2f}m' + (f' {source}' if source in ('L', 'G') else '')


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


def draw_follow_evidence(image, *, scale, keep=None, objects=None, road_state=None, line=None, tags=None,
                         detections=None):
    """Explain chosen boundaries, visible lane candidates and camera objects."""
    h, w = image.shape[:2]
    white, bg, muted = (245, 248, 250), (12, 18, 28), (140, 155, 168)
    green, blue, magenta, orange = (60, 220, 60), (230, 120, 40), (230, 60, 230), (0, 140, 255)
    original_size = [int(round(w / scale)), int(round(h / scale))]

    def text(label, xy, colour=white, font=.38, badge=False):
        font *= max(1, w / 400)
        x, y = xy
        if badge:
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, 1)
            x = max(2, min(w - tw - 3, x)); y = max(th + 3, min(h - 60, y))
            cv2.rectangle(image, (x - 2, y - th - 3), (x + tw + 2, y + 3), bg, -1)
        cv2.putText(image, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font, colour, 1, cv2.LINE_AA)

    def point(raw):
        if (not isinstance(raw, (list, tuple)) or len(raw) != 2
                or not all(_number(v) for v in raw)
                or any(abs(v * scale) > 4 * max(w, h) for v in raw)):
            return None
        return tuple(int(round(v * scale)) for v in raw)

    def records(doc, key, limit):
        value = doc.get(key)
        return value[:limit] if isinstance(value, list) else []

    def ends(record):
        raw = record.get('ends_px') if isinstance(record, dict) else None
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            return None
        a, b = point(raw[0]), point(raw[1])
        return (a, b) if a is not None and b is not None else None

    def dashed(a, b, colour, thickness=1):
        start, delta = np.array(a, float), np.array(b, float) - a
        for t in np.arange(0, 1, .13):
            cv2.line(image, tuple(np.rint(start + t * delta).astype(int)),
                     tuple(np.rint(start + min(t + .06, 1) * delta).astype(int)), colour, thickness)

    if not isinstance(keep, dict) or keep.get('image_size', original_size) != original_size:
        keep = None
    if keep is None and isinstance(line, dict) and line.get('source') == 'CAMERA_LINE':
        keep = dict(strategy='camera_line' if line.get('visible') is True else 'none',
                    error=line.get('error'), confidence=line.get('confidence'), reason='line lost')
    strategy = str((keep or {}).get('strategy') or 'none')
    error, confidence = (keep or {}).get('error'), (keep or {}).get('confidence')
    valid = (strategy != 'none' and _number(error) and -1 <= error <= 1
             and _number(confidence) and 0 < confidence <= 1)
    boundaries = records(keep or {}, 'boundaries', 24)
    selected = {r.get('side'): r for r in boundaries
                if valid and isinstance(r, dict) and r.get('selected') is True}
    lanes = lane_hypotheses(keep)
    for lane in lanes:
        le, re = ends(lane['left']), ends(lane['right'])
        if le is None or re is None:
            continue
        # Only the seen stretch is shaded. Never extrapolate a lane polygon.
        points = np.array(sorted(le, key=lambda p: -p[1]) + sorted(re, key=lambda p: p[1]), np.int32)
        tint = image.copy()
        cv2.fillConvexPoly(tint, points, green if lane['selected'] else muted)
        cv2.addWeighted(tint, .16 if lane['selected'] else .07, image, .84 if lane['selected'] else .93, 0, image)
        if not lane['selected']:
            label = ('LEFT' if lane['relation'] == 'left' else 'RIGHT' if lane['relation'] == 'right' else 'LANE') + ' CANDIDATE'
            centre = np.mean(points, axis=0).astype(int)
            text(label, (int(centre[0]) - 40, int(centre[1])), muted, .30, True)

    object_status = 'REGIONS: unavailable'
    if (isinstance(objects, dict) and objects.get('image_size') == original_size
            and isinstance(objects.get('quality'), dict)
            and objects['quality'].get('valid') is False
            and objects['quality'].get('reason') in ('low_light', 'underexposed')):
        object_status = 'LOW LIGHT: visibility unavailable'
    found = []
    if (isinstance(detections, dict) and [detections.get('input_width'), detections.get('input_height')]
            == original_size):
        found = records(detections, 'detections', 64)
    found_ranges = records(detections, 'ranges', 64) if found else []
    paired = {}
    if (isinstance(objects, dict) and objects.get('image_size') == original_size
            and isinstance(objects.get('quality'), dict) and objects['quality'].get('valid') is True):
        regions = records(objects, 'regions', 48)
        object_status = f'REGIONS: {len(regions)} unclassified'
        paired = pair_detections(regions, found, original_size)
        labelled = 0
        badges = []
        for index, record in enumerate(regions):
            if not isinstance(record, dict):
                continue
            box = record.get('b')
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            a, b = point(box[:2]), point(box[2:])
            if a is None or b is None or a[0] >= b[0] or a[1] >= b[1]:
                continue
            colour = (40, 70, 255) if record.get('n') == 1 else orange
            cv2.rectangle(image, a, b, colour, 2)
            if labelled < 3:
                ranged = _range_label(record)  # D-423: L LiDAR, G ground plane
                prefix = 'REGION'
                kind = 'DARK' if record.get('k') == 'd' else 'UNCLASSIFIED'
                if index in paired:  # the detection names it and brings its own range
                    di = paired[index]
                    prefix = 'DET'
                    kind = str(found[di].get('label'))[:16]
                    ranged = _range_label(found_ranges[di] if di < len(found_ranges) else None)
                # Fixed separate rows stay readable when foreground boxes overlap.
                badges.append((f'{prefix} {index + 1} {kind} {ranged}' + (' NEAR' if record.get('n') == 1 else ''),
                               (6, 65 + labelled * int(17 * max(1, w / 400))), colour))
                text(str(index + 1), (a[0] + 4, max(145, a[1] + 14)), colour, .32, True)
                labelled += 1
        for label, location, colour in badges:
            text(label, location, colour, .32, True)
    lone = [di for di in range(len(found)) if di not in paired.values()]
    for row, di in enumerate(lone[:3]):
        box = _detection_box(found[di], original_size)
        a, b = (point(box[:2]), point(box[2:])) if box else (None, None)
        if a is None or b is None:
            continue
        cv2.rectangle(image, a, b, (0, 220, 255), 1)
        label = f'DET {str(found[di].get("label"))[:16]} ' + _range_label(
            found_ranges[di] if di < len(found_ranges) else None)
        text(label, (max(6, w - 150), 65 + row * int(17 * max(1, w / 400))), (0, 220, 255), .32, True)
    if found:
        object_status += f' | {len(found)} detected'
    for tag in tags[:8] if isinstance(tags, list) else []:
        if not isinstance(tag, dict) or not _number(tag.get('tag_id')):
            continue
        corners = tag.get('corners_px')
        if not isinstance(corners, list) or len(corners) != 4:
            continue
        points = [point(p) for p in corners]
        if any(p is None for p in points):
            continue
        cv2.polylines(image, [np.array(points, np.int32)], True, (255, 220, 0), 2)
        text(f'TAG {int(tag["tag_id"])}', (points[0][0], max(66, points[0][1] - 6)), (255, 220, 0), .40, True)

    for record in boundaries:
        segment = ends(record)
        if segment is None:
            continue
        colour = green if record.get('side') == 'left' else blue
        if record.get('selected') is True and valid:
            cv2.line(image, *segment, colour, 3)
        else:
            dashed(*segment, muted)
    for record in records(keep or {}, 'candidates', 24):
        if not isinstance(record, dict) or not record.get('rejected'):
            continue
        segment = ends(record)
        if segment is not None:
            dashed(*segment, orange)
            text('EXCLUDED ' + str(record.get('reason') or 'unknown')[:16],
                 (segment[1][0], max(82, segment[1][1])), orange, .27, True)
    cv2.rectangle(image, (0, 29), (w - 1, 50), bg, -1)
    for side, colour in (('left', green), ('right', blue)):
        seen = side in selected
        label = side.upper() + ' LANE' + ('' if seen else ': UNSEEN')
        font = .43 if seen else .30
        width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font * max(1, w / 400), 1)[0][0]
        text(label, (5 if side == 'left' else max(5, w - width - 5), 45),
             colour if seen else muted, font)

    status = 'FOLLOW: unavailable'
    detail = 'No selected target'
    if keep is not None:
        if not valid:
            status = 'HOLD: ' + str(keep.get('reason') or 'no valid target')[:34]
        else:
            direction = 'RIGHT' if error > .05 else ('LEFT' if error < -.05 else 'STRAIGHT')
            status = f'FOLLOW {direction}  {confidence:.0%}'
            mode = {'both': 'CURRENT LANE', 'left_only': 'LEFT LANE ONLY', 'right_only': 'RIGHT LANE ONLY',
                    'corner_left': 'TURN LEFT', 'corner_right': 'TURN RIGHT', 'corner_ahead': 'CORNER AHEAD',
                    'camera_line': 'LINE OBSERVATION'}.get(strategy, 'TARGET OBSERVATION')
            detail = f'{mode} | {len(lanes)} lane candidates' if lanes else f'{mode} | error {error:+.2f}'
            target = point(keep.get('target_px'))
            if target is not None and 0 <= target[0] < w and 55 <= target[1] < h - 59:
                dashed((w // 2, h - 60), target, magenta, 2)
                cv2.circle(image, target, 6, magenta, 2)
                text('TARGET', (target[0] + 9, target[1] - 8), magenta, .36, True)
                text('FOLLOW PATH', (w // 2 - 52, h - 67), magenta, .39, True)

    samples = predicted_road(road_state)
    prediction_status = 'PRED unavailable'
    if isinstance(road_state, dict):
        prediction_status = ('PRED ' + str(road_state['level']) if samples is not None else
                             'PRED calibration suspect' if road_state.get('calibration_suspect') else
                             'PRED STOP' if road_state.get('level') == 'STOP' else 'PRED unavailable')
    if samples is not None and w >= 240 and h >= 180:
        size = min(84, int(w * .26), h - 126)
        x0, y0 = (w - size) // 2, 54
        cv2.rectangle(image, (x0, y0), (x0 + size, y0 + size), bg, -1)
        text('ROAD ESTIMATE', (x0 + 2, y0 + 10), (255, 220, 0), .25)
        def bev(x, y):
            return (x0 + size // 2 - int(round(np.clip(y / .25, -1, 1) * size / 2)),
                    y0 + size - 5 - int(round(x / .33 * (size - 22))))
        for offset, colour in ((road_state['w'] / 2, green), (-road_state['w'] / 2, blue), (0, (255, 220, 0))):
            edge = np.array([bev(x, y + offset) for x, y in samples], np.int32)
            cv2.polylines(image, [edge], False, colour, 1)
        cv2.drawMarker(image, bev(0, 0), white, cv2.MARKER_TRIANGLE_UP, 7, 1)
    cv2.rectangle(image, (0, h - 59), (w - 1, h - 1), bg, -1)
    text(status, (6, h - 42), white, .47 if w >= 320 else .34)
    text(detail, (6, h - 25), magenta, .35)
    text(object_status + ' | ' + prediction_status, (6, h - 9), white, .31)
