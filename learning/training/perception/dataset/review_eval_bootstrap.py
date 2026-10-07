"""Reserve MCAP evaluation sources, then import pending frames into a separate Review workspace."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_app import ReviewStore
import review_evidence
import review_ingest
import review_masks
from mcap_proof import prove_frames
from store import Store


def start(store_root, state_dir, catalog, classes, *, catalog_sha256, classes_sha256):
    catalog = Path(catalog)
    classes = Path(classes)
    raw = review_ingest.bounded(catalog)
    if hashlib.sha256(raw).hexdigest() != catalog_sha256:
        raise ValueError('frozen evaluation catalog hash differs')
    class_raw = review_ingest.bounded(classes, 1024 * 1024)
    if hashlib.sha256(class_raw).hexdigest() != classes_sha256:
        raise ValueError('frozen evaluation classes hash differs')
    rows = [json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    if not 1 <= len(rows) <= 2000:
        raise ValueError('bounded evaluation catalog required')
    groups = {}
    for row in rows:
        if row.get('source_kind') != 'mcap' or row.get('fixed_eval_overlap') is not True:
            raise ValueError('evaluation catalog requires reserved MCAP frames')
        session, group = row.get('source_session'), row.get('capture_group')
        if session in groups and groups[session] != group:
            raise ValueError('one capture group required per session')
        groups[session] = group
    source_store = Store(store_root)
    existing = source_store.eval_reservations()
    for session, group in sorted(groups.items()):
        if session in existing:
            if existing[session] != group:
                raise ValueError('existing evaluation reservation differs')
        else:
            source_store.reserve_eval_source(session, group)
    state_dir = Path(state_dir)
    review = ReviewStore(state_dir, empty_eval=not (state_dir / 'reviews.sqlite3').exists())
    result = review_ingest.import_frames(review, {'path': str(catalog), 'classes': str(classes)})
    if hashlib.sha256(catalog.read_bytes()).hexdigest() != catalog_sha256:
        raise ValueError('evaluation catalog changed during import')
    if hashlib.sha256(classes.read_bytes()).hexdigest() != classes_sha256:
        raise ValueError('evaluation classes changed during import')
    return {'state': str(review.state), 'sessions': groups, 'frames': len(review.list_frames()),
            'added': result['added'], 'catalog_sha256': catalog_sha256}


def ready(store_root, state_dir, scratch):
    """Gate before building a human fixed eval; re-prove every source."""
    if not (Path(state_dir) / 'reviews.sqlite3').is_file():
        raise ValueError('existing evaluation workspace required')
    review = ReviewStore(state_dir)
    if review_evidence.metadata(review, 'workspace_kind') != 'evaluation':
        raise ValueError('separate evaluation workspace required')
    captured = review_evidence.snapshot(review)
    authority = captured['authority']
    review_evidence.validate_authority(authority)
    binding = captured['classes']
    if not binding or authority['pixel_classes_sha256'] != binding['sha256']:
        raise ValueError('frozen pixel classes required')
    class_file = review.state / 'pixel' / (binding['sha256'] + '.yaml')
    if class_file.is_symlink() or hashlib.sha256(class_file.read_bytes()).hexdigest() != binding['sha256']:
        raise ValueError('frozen pixel class file changed')
    reservations = Store(store_root).eval_reservations()
    groups = {}
    if len(captured['frames']) != len(authority['frames']):
        raise ValueError('evaluation frame authority differs')
    for frame, row in zip(captured['frames'], authority['frames']):
        source = frame['source']
        if row['frame'] != frame['index'] or source.get('source_kind') != 'mcap':
            raise ValueError('MCAP frame authority required')
        session, group = source.get('source_session'), source.get('capture_group')
        mcap = source.get('mcap')
        if (source.get('fixed_eval_overlap') is not True or reservations.get(session) != group
                or not isinstance(mcap, dict) or Path(mcap['session_dir']).name != session):
            raise ValueError('reserved MCAP session/group required')
        if frame['status'] == 'excluded' or row['mask_decision'] != 'approved':
            raise ValueError('every evaluation frame needs an approved mask')
        mask = captured['masks'].get(frame['index'])
        approval = row['pixel_approval']
        if (not mask or not approval or mask['sha256'] != row['mask_sha256']
                or approval.get('mask_version') != mask['version']
                or approval.get('image_sha256') != row['image_sha256']
                or approval.get('mask_sha256') != mask['sha256']
                or approval.get('classes_sha256') != binding['sha256']
                or approval.get('classes_signature') != authority['classes_signature']
                or approval.get('complete_frame_review') is not True
                or approval.get('background_reviewed') is not True):
            raise ValueError('approved pixel binding changed')
        pixels = review_masks.pixels(review, dict(mask, width=row['width'], height=row['height']))
        unknown = int((pixels == 255).sum())
        if (unknown == pixels.size or unknown != approval.get('reviewed_unknown_count', 0)
                or (unknown and approval.get('unknown_pixels_reviewed') is not True)):
            raise ValueError('approved unknown pixel count differs')
        if not np.isin(pixels, [c['index'] for c in binding['classes']] + [255]).all():
            raise ValueError('approved mask has an unknown class index')
        image = review.image(frame['index'])
        review_ingest.image(image.read_bytes(), row['image_sha256'], row['width'], row['height'])
        groups.setdefault(mcap['session_dir'], []).append((source, {**mcap['frame'], 'image': str(image)}))
    if not captured['frames']:
        raise ValueError('approved MCAP frames required')
    for session, entries in groups.items():
        first = entries[0][0]['mcap']
        if any(source['mcap']['metadata_sha256'] != first['metadata_sha256']
               or source['mcap']['bags'] != first['bags'] for source, _ in entries):
            raise ValueError('MCAP bag inventory differs within session')
        proof = prove_frames(session, [selector for _, selector in entries], scratch, expected=first)
        for (source, _), proven in zip(entries, proof['frames']):
            if proven != source['mcap']['frame'] or proof['decoder'] != source['mcap']['decoder']:
                raise ValueError('MCAP source proof differs from review authority')
    if review_evidence.decisions(review)['decision_sha256'] != authority['decision_sha256']:
        raise ValueError('review authority changed during proof')
    return {'frames': len(captured['frames']),
            'sessions': {Path(s).name: entries[0][0]['capture_group'] for s, entries in groups.items()},
            'decision_sha256': authority['decision_sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store', 'state'):
        parser.add_argument('--' + name, required=True)
    for name in ('catalog', 'classes', 'catalog-sha256', 'classes-sha256'):
        parser.add_argument('--' + name)
    parser.add_argument('--ready', action='store_true')
    parser.add_argument('--scratch', default='X:/DevTemp')
    args = parser.parse_args()
    if args.ready:
        result = ready(args.store, args.state, args.scratch)
    else:
        if not all((args.catalog, args.classes, args.catalog_sha256, args.classes_sha256)):
            parser.error('--catalog, --classes, and their SHA-256 values are required for import')
        result = start(args.store, args.state, args.catalog, args.classes,
                       catalog_sha256=args.catalog_sha256, classes_sha256=args.classes_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
