"""Offline, unreviewed transfer metadata packages; no labels or training admission."""
import argparse
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omx_output_paths import in_source_checkout

LIMIT = 8 * 1024 * 1024
TOTAL_LIMIT = 128 * 1024 * 1024
FLAGS = dict(scope='unreviewed_metadata_only', raw_camera_bytes_available=False,
             behavior_training_eligible=False)


def _read(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('regular review files without links required')
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if not raw or len(raw) > LIMIT:
        raise ValueError('nonempty review file at most 8 MiB required')
    return raw


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('nonfinite JSON value')

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite JSON number')
        return number

    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=nonfinite, parse_float=finite)


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value)


def _inspect(raw):
    doc = _json(raw)
    if (not isinstance(doc, dict) or doc.get('schema') != 'rosy.transfer-outcome-export/2'
            or any(type(doc.get(k)) is not type(v) or doc[k] != v for k, v in FLAGS.items())
            or not _identifier(doc.get('mission_id')) or not isinstance(doc.get('outcomes'), list)
            or not isinstance(doc.get('execution_review'), dict)):
        raise ValueError('unreviewed transfer-outcome-export/2 metadata required')
    mission, line = doc['mission_id'], doc.get('recovery_lineage')
    if (not isinstance(line, dict) or set(line) != {'root_mission_id', 'parent_mission_id',
            'child_mission_id', 'attempt_index', 'recovery_limit'}
            or not _identifier(line.get('root_mission_id'))
            or type(line.get('attempt_index')) is not int or line['attempt_index'] not in (0, 1)
            or type(line.get('recovery_limit')) is not int or line['recovery_limit'] != 1):
        raise ValueError('bounded recovery lineage required')
    root, parent, child = (line[k] for k in ('root_mission_id', 'parent_mission_id', 'child_mission_id'))
    unlinked = parent is None and child is None and mission == root and line['attempt_index'] == 0
    linked = (parent == root and _identifier(child) and child != root
              and mission == (root if line['attempt_index'] == 0 else child))
    if not (unlinked or linked):
        raise ValueError('inconsistent recovery lineage')
    return mission, line


def _records(items):
    if not items or len(items) > 1000 or sum(len(raw) for _, raw in items) > TOTAL_LIMIT:
        raise ValueError('1..1000 review exports totalling at most 128 MiB required')
    records, missions, groups, members, splits = [], set(), {}, {}, set()
    for number, (split, raw) in enumerate(items):
        if split not in ('train', 'eval'):
            raise ValueError('explicit train/eval partition required')
        mission, line = _inspect(raw)
        if mission in missions:
            raise ValueError('duplicate mission in review package')
        missions.add(mission)
        root = line['root_mission_id']
        binding = (split, line['parent_mission_id'], line['child_mission_id'])
        if root in groups:
            if groups[root][0] != split:
                raise ValueError('same root cannot cross partition boundaries')
            if groups[root] != binding:
                raise ValueError('conflicting recovery lineage within root')
        groups[root] = binding
        for member in (root, line['child_mission_id']):
            if member is not None:
                if member in members and members[member] != root:
                    raise ValueError('conflicting recovery lineage across mission identities')
                members[member] = root
        splits.add(split)
        records.append(dict(source_file=f'{number:04}.json', source_sha256=sha256(raw).hexdigest(),
                            mission_id=mission, root_mission_id=root, split=split))
    if splits != {'train', 'eval'}:
        raise ValueError('nonempty train and eval partitions required')
    return records


def load(package):
    """Check copied bytes and declared groups; hashes do not authenticate the source."""
    package = Path(package)
    manifest = _json(_read(package / 'manifest.json'))
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'records', *FLAGS}
            or manifest['schema'] != 'rosy.transfer-review-package/1'
            or any(type(manifest[k]) is not type(v) or manifest[k] != v for k, v in FLAGS.items())
            or not isinstance(manifest['records'], list) or not 1 <= len(manifest['records']) <= 1000):
        raise ValueError('unreviewed transfer review manifest required')
    items, total = [], 0
    for number, record in enumerate(manifest['records']):
        if (not isinstance(record, dict) or set(record) != {'source_file', 'source_sha256',
                'mission_id', 'root_mission_id', 'split'} or record['source_file'] != f'{number:04}.json'):
            raise ValueError('bounded local source record required')
        raw = _read(package / record['source_file'])
        total += len(raw)
        if total > TOTAL_LIMIT:
            raise ValueError('review package exceeds 128 MiB')
        items.append((record['split'], raw))
    if _records(items) != manifest['records']:
        raise ValueError('review source digest or identity changed')
    expected = {'manifest.json', *(r['source_file'] for r in manifest['records'])}
    if {p.name for p in package.iterdir()} != expected:
        raise ValueError('unexpected review package files')
    return manifest


def prepare(output, *, train, evaluation):
    """Copy exact exports into a new external directory, publishing the manifest last."""
    output = Path(output)
    if in_source_checkout(output):
        raise ValueError('review output must stay outside source checkouts')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if any(p.is_symlink() for p in output.absolute().parents):
        raise ValueError('review output ancestors must not be links')
    if not train or not evaluation or len(train) + len(evaluation) > 1000:
        raise ValueError('nonempty bounded train and eval inputs required')
    items, total = [], 0
    for split, paths in [('train', train), ('eval', evaluation)]:
        for path in paths:
            raw = _read(path)
            total += len(raw)
            if total > TOTAL_LIMIT:
                raise ValueError('review inputs exceed 128 MiB')
            items.append((split, raw))
    records = _records(items)
    manifest = dict(schema='rosy.transfer-review-package/1', records=records, **FLAGS)
    output.mkdir()
    files = [(r['source_file'], raw) for r, (_, raw) in zip(records, items)]
    files.append(('manifest.json', (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                             allow_nan=False, indent=2) + '\n').encode()))
    for name, raw in files:
        with (output / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return load(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', nargs='?', type=Path)
    parser.add_argument('--train', nargs='+', type=Path)
    parser.add_argument('--eval', nargs='+', type=Path, dest='evaluation')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify and not any([args.output, args.train, args.evaluation]):
            result = load(args.verify)
        elif args.output and args.train and args.evaluation and not args.verify:
            result = prepare(args.output, train=args.train, evaluation=args.evaluation)
        else:
            parser.error('use OUTPUT --train FILE... --eval FILE..., or --verify PACKAGE')
    except (ValueError, OSError, RecursionError) as exc:
        parser.exit(2, f'review package refused ({type(exc).__name__}); verify inputs and use a new output\n')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
