"""Reserve MCAP evaluation sources, then import pending frames into a separate Review workspace."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_app import ReviewStore
import review_ingest
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store', 'state', 'catalog', 'classes', 'catalog-sha256', 'classes-sha256'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    print(json.dumps(start(args.store, args.state, args.catalog, args.classes,
                           catalog_sha256=args.catalog_sha256,
                           classes_sha256=args.classes_sha256), sort_keys=True))


if __name__ == '__main__':
    main()
