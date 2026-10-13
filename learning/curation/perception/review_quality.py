"""Report lower-image clipping for human labelability review.

Usage: python review_quality.py --state <review-state> --threshold 0.15
The threshold is chosen from a measured session, not a universal camera setting.
"""
import argparse
import json

import cv2
import numpy as np

from review_app import ReviewStore


def triage(store, threshold):
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
        rows.append({'frame': frame['index'], 'clipped_fraction': round(fraction, 4),
                     'candidate': candidate, 'status': frame['status']})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--threshold', required=True, type=float)
    args = parser.parse_args()
    rows = triage(ReviewStore(args.state), args.threshold)
    print(json.dumps({'threshold': args.threshold, 'frames': rows},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
