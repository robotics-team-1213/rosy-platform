"""Independent checks of the 10/6 MCAP candidate pack; no label inference."""
import csv
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path('X:/DevTemp/rosy-lane-1006-mcap-review-20261008')
VIDEO = Path('X:/DevTemp/rosy-lane-1006-review-candidates-20261008')
rows = list(csv.DictReader((ROOT / 'mcap-candidate-review-queue.csv').open(encoding='utf-8', newline='')))
old = list(csv.DictReader((VIDEO / 'candidate-review-queue.csv').open(encoding='utf-8', newline='')))
receipt = json.loads((ROOT / 'receipt.json').read_text(encoding='utf-8'))
assert len(rows) == len(old) == receipt['rows'] == 178
assert hashlib.sha256((ROOT / 'mcap-candidate-review-queue.csv').read_bytes()).hexdigest() == receipt['queue_sha256']
assert hashlib.sha256((ROOT / 'mcap-candidate-gallery.html').read_bytes()).hexdigest() == receipt['gallery_sha256']
gallery = (ROOT / 'mcap-candidate-gallery.html').read_text(encoding='utf-8')
assert gallery.count('<img src=') == len(rows)
assert all(all(not row[name] for name in ('same_lane_pair', 'boundary_id_left', 'boundary_id_right',
                                         'loss_cause', 'reappearance_frame', 'visible_drivable',
                                         'reviewer', 'reviewed_at', 'notes')) for row in rows)
pixel_equal, abs_errors, proof_count = 0, [], 0
for sid in {r['source_session'] for r in rows}:
    prefix = sid[9:15]
    proof_path = ROOT / f'proof-{prefix}.json'
    assert hashlib.sha256(proof_path.read_bytes()).hexdigest() == receipt['sessions'][sid]['proof_sha256']
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['source_session'] == sid and proof['metadata_sha256'] == receipt['sessions'][sid]['source_metadata_sha256']
    by_stamp = {p['header_stamp_ns']: p for p in proof['frames']}
    assert len(by_stamp) == len(proof['frames']) == receipt['sessions'][sid]['selected']
    proof_count += len(by_stamp)
    for row in (r for r in rows if r['source_session'] == sid):
        orig = next(r for r in old if r['source_session'] == sid and r['frame_index'] == row['frame_index'])
        assert row['header_stamp_ns'] == orig['header_stamp_ns']
        image = ROOT / row['image']
        assert image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest() == row['image_sha256']
        assert row['image'] in gallery
        p = by_stamp[int(row['header_stamp_ns'])]
        assert (p['image_sha256'], p['log_ns'], p['bag'], p['channel_id'], p['message_ordinal']) == (
            row['image_sha256'], int(row['log_ns']), row['bag'], int(row['channel_id']), int(row['message_ordinal']))
        a = cv2.imread(str(image), cv2.IMREAD_COLOR)
        b = cv2.imread(str(VIDEO / orig['image']), cv2.IMREAD_COLOR)
        assert a is not None and b is not None and a.shape == b.shape
        pixel_equal += int(np.array_equal(a, b))
        abs_errors.append(float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()))
print(json.dumps({'rows': len(rows), 'proved_frames': proof_count, 'missing_or_bad_images': 0,
                  'filled_human_rows': 0, 'pixel_equal_to_mp4': pixel_equal,
                  'mean_absolute_channel_difference_median': float(np.median(abs_errors)),
                  'mean_absolute_channel_difference_max': max(abs_errors)}, indent=2))
