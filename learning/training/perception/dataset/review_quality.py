"""Report lower-image clipping; optionally exclude pending review frames.

Usage: python review_quality.py --state <review-state> --threshold 0.15 [--apply]
The threshold is chosen from a measured session, not a universal camera setting.
"""
import argparse
import json

import cv2
import numpy as np

from review_app import ReviewStore


def triage(store, threshold, *, apply=False):
    if not 0 < threshold < 1:
        raise ValueError('threshold must be between 0 and 1')
    rows = []
    for frame in store.list_frames():
        raw = store.image(frame['index']).read_bytes()
        photo = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if photo is None or photo.shape[:2] != (frame['source']['height'], frame['source']['width']):
            raise ValueError('source image dimensions differ')
        gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
        fraction = float(np.mean(gray[gray.shape[0] // 2:] >= 245))
        candidate = fraction >= threshold
        changed = bool(apply and candidate and frame['status'] == 'pending')
        if changed:
            store.update(frame['index'], {'version': frame['version'], 'action': 'exclude'})
        rows.append({'frame': frame['index'], 'clipped_fraction': round(fraction, 4),
                     'candidate': candidate, 'status': 'excluded' if changed else frame['status'],
                     'changed': changed})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--threshold', required=True, type=float)
    parser.add_argument('--apply', action='store_true', help='exclude pending candidates in the review ledger')
    args = parser.parse_args()
    rows = triage(ReviewStore(args.state), args.threshold, apply=args.apply)
    print(json.dumps({'threshold': args.threshold, 'applied': args.apply, 'frames': rows},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
