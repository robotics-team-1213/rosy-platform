"""Fixed native export worker for a registered, explicitly reviewed preparation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from experiment_io import identifier, read_json, write_json
from experiment_native import _profile, native
import collection_pipeline as pipeline
from experiment_reviews import canonical, source_revision

SCHEMA = 'rosy.omx.export-request/1'
LIMIT = 8 * 1024 * 1024


def _regular(path):
    if (any(part.is_symlink() for part in (path, *path.parents))
            or not path.is_file() or path.stat().st_size > LIMIT):
        raise ValueError('bounded regular native evidence without links required')


def _source(raw, profile, review=None):
    if not isinstance(raw, str) or len(raw) > 2048 or not Path(raw).is_absolute():
        raise ValueError('registered absolute native preparation required')
    root = Path(raw)
    if any(part.is_symlink() for part in (root, *root.parents)) or native._in_checkout(root):
        raise ValueError('native preparation must be outside source checkouts without links')
    root = root.resolve(strict=True)
    for name in pipeline.PREPARED_FILES:
        _regular(root / name)
    for folder in ('meta', 'data', 'videos'):
        if (root / folder).is_symlink():
            raise ValueError('native dataset links are not accepted')
        for current, directories, files in os.walk(root / folder, followlinks=False):
            if any((Path(current) / name).is_symlink() for name in (*directories, *files)):
                raise ValueError('native dataset links are not accepted')
    if review is not None:
        if (not isinstance(review, dict)
                or set(review) != {'id', 'source_revision', 'decisions', 'sha256', 'reviewer_identity'}):
            raise ValueError('fixed human review snapshot required')
        identifier(review['id'])
        decision_bytes = canonical(review['decisions'])
        if hashlib.sha256(decision_bytes).hexdigest() != review['sha256']:
            raise ValueError('human review snapshot hash changed')
        originals = {name: (root/name).read_bytes() for name in pipeline.PREPARED_FILES}
        originals, report, _, _ = pipeline._validate_review_inputs(originals, decision_bytes)
    else:
        originals, report, _, _ = pipeline._review_inputs(root, root / 'decisions.json')
    checked, layout = _profile(profile, report)
    files = native.dataset_files(root)
    if files != report.get('files'):
        raise ValueError('native preparation source bytes differ from inspection')
    info = read_json(root / 'meta/info.json')
    features = info.get('features', {})
    try:
        actual = native.joint_layout(info)
    except ValueError:
        actual = None
    if actual != layout:
        raise ValueError('native preparation joint order or metadata differs')
    cameras = {key: value.get('shape') for key, value in features.items()
               if key.startswith('observation.images.')}
    expected = {camera['input_key']: [*camera['shape'][1:], 3] for camera in checked['cameras']}
    if cameras != expected:
        raise ValueError('profile camera keys or shapes differ from prepared native metadata')
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()}
    if review is not None and source_revision(hashes, files) != review['source_revision']:
        raise ValueError('source changed since human review snapshot')
    return root, checked, hashes


def prepare_export(body, prepared_row, review=None):
    if (not isinstance(body, dict) or set(body) != {'prepared_id', 'name', 'profile', 'request_id'}
            or not isinstance(body['prepared_id'], str)
            or not re.fullmatch('[0-9a-f]{32}', body['prepared_id'])):
        raise ValueError('registered preparation identity and fixed export fields required')
    identifier(body['request_id'])
    if (not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 128
            or any(ord(char) < 32 for char in body['name'])):
        raise ValueError('export display name must contain 1..128 characters')
    if (not isinstance(prepared_row, dict) or prepared_row.get('id') != body['prepared_id']
            or prepared_row.get('kind') != 'omx'):
        raise ValueError('registered OMX preparation required')
    if len(json.dumps(body['profile'], allow_nan=False).encode()) > 1024 * 1024:
        raise ValueError('bounded learning profile required')
    root, profile, hashes = _source(prepared_row.get('path'), body['profile'], review)
    request = dict(schema=SCHEMA, prepared_root=str(root), prepared_files=hashes, profile=profile)
    fields = dict(
        prepared_id=body['prepared_id'], name=body['name'].strip(), source='reviewed_demonstration',
        method='act', execution_mode='native_export')
    if review is not None:
        request['review'] = review
        fields['review_id'] = review['id']
    return request, fields


def run_export(request, output):
    if (not isinstance(request, dict)
            or set(request) not in ({'schema', 'prepared_root', 'prepared_files', 'profile'},
                                   {'schema', 'prepared_root', 'prepared_files', 'profile', 'review'})
            or request['schema'] != SCHEMA):
        raise ValueError('unsupported fixed native export request')
    output = native._new_output(output, Path(request['prepared_root']))
    output.mkdir(parents=True)
    write_json(output / 'progress.json', {'phase': 'verifying'})
    review = request.get('review')
    root, profile, hashes = _source(request['prepared_root'], request['profile'], review)
    if request['prepared_files'] != hashes:
        raise ValueError('native preparation evidence changed after export admission')
    write_json(output / 'profile.json', profile)
    write_json(output / 'progress.json', {'phase': 'exporting'})
    decisions = root / 'decisions.json'
    if review is not None:
        decisions = output / 'reviewed-decisions.json'
        decisions.write_bytes(canonical(review['decisions']))
    receipt = pipeline.export_experiment(root, decisions, output / 'profile.json', output / 'export')
    _, _, current = _source(str(root), profile, review)
    if current != hashes:
        raise ValueError('native preparation evidence changed during export')
    result = dict(dataset_revision=receipt['dataset_revision'], act_only=True,
                  physical_learning_verified=False, policy_activation=False,
                  execution_mode='native_export')
    if review is not None:
        result['review_id'] = review['id']
    write_json(output / 'result.json', result)
    write_json(output / 'progress.json', {'phase': 'finished'})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise ValueError('new run-owned output directory required')
    request = read_json(args.request)
    # Establish an output that cannot modify the preparation before writing failure diagnostics.
    if not isinstance(request, dict) or not isinstance(request.get('prepared_root'), str):
        raise ValueError('registered native preparation required')
    output = native._new_output(args.out, Path(request['prepared_root']))
    try:
        run_export(request, output)
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / 'error.json', {'error': f'{type(exc).__name__}: {str(exc)[:500]}',
                                           'status': 'failed'})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
