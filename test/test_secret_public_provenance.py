"""Reviewed repository digests never excuse changed text or credential shapes."""
import hashlib
import json
from pathlib import Path

import pytest

from secret_scan import load_public_provenance, scan_files, scan_text


def test_reviewed_repository_inventory_has_no_stale_bindings():
    root = Path(__file__).resolve().parents[1]
    policy = load_public_provenance(root/'deploy/robot/pinky_pro/release/public_provenance.json')
    lines_by_path = {}
    for path, line_hash, value in policy:
        if path not in lines_by_path:
            lines_by_path[path] = {
                hashlib.sha256(line.encode()).hexdigest(): line
                for line in (root/path).read_text(encoding='utf-8').splitlines()}
        line = lines_by_path[path].get(line_hash)
        assert line is not None, (path, line_hash)
        assert value in line, (path, value)


def policy(tmp_path, line, path='docs/evidence.md', value=None):
    value = value or hashlib.sha256(b'public model artifact').hexdigest()
    record = {'path': path, 'line_sha256': hashlib.sha256(line.encode()).hexdigest(),
              'values': [value], 'reason': 'Reviewed model artifact checksum'}
    target = tmp_path/'provenance.json'
    target.write_text(json.dumps({'schema': 'rosy.public-provenance/1', 'records': [record]}), encoding='utf-8')
    return load_public_provenance(target)


def test_exact_reviewed_digest_requires_explicit_repository_policy(tmp_path):
    value = hashlib.sha256(b'public model artifact').hexdigest()
    line = f'Artifact `{value}`.'
    reviewed = policy(tmp_path, line)
    assert scan_text('docs/evidence.md', line)
    assert not scan_text('docs/evidence.md', line, public_provenance=reviewed)
    path = tmp_path/'docs/evidence.md'
    path.parent.mkdir()
    path.write_text(line, encoding='utf-8')
    assert scan_files([path], root=tmp_path)
    assert not scan_files([path], root=tmp_path, public_provenance=reviewed)


@pytest.mark.parametrize('change', ['text', 'path', 'same_line_token', 'new_line_token'])
def test_provenance_never_covers_unreviewed_text(tmp_path, change):
    value = hashlib.sha256(b'public model artifact').hexdigest()
    other = hashlib.sha256(b'unreviewed token').hexdigest()
    line = f'Artifact `{value}`.'
    reviewed = policy(tmp_path, line)
    path = 'docs/evidence.md'
    if change == 'text':
        line += ' changed'
    elif change == 'path':
        path = 'docs/other.md'
    elif change == 'same_line_token':
        line += f' {other}'
    else:
        line += f'\n{other}'
    assert scan_text(path, line, public_provenance=reviewed)


@pytest.mark.parametrize('kind', ['credential', 'wifi-psk', 'private-key', 'wifi-qr'])
def test_even_exact_reviewed_line_cannot_excuse_secret_matchers(tmp_path, kind):
    value = hashlib.sha256(b'public model artifact').hexdigest()
    lines = {'credential': ''.join(('api_', 'token=', value)),
             'wifi-psk': ''.join(('p', 'sk=', value)),
             'private-key': '-'*5+'BEGIN OPENSSH PRIVATE KEY'+'-'*5+f' {value}',
             'wifi-qr': ''.join(('WI', 'FI:T:WPA;S:test;', 'P:', value, ';;'))}
    line = lines[kind]
    reviewed = policy(tmp_path, line)
    assert scan_text('docs/evidence.md', line, public_provenance=reviewed)


@pytest.mark.parametrize('change', ['path', 'line_hash', 'token', 'duplicate', 'reason', 'schema'])
def test_malformed_public_provenance_fails_closed(tmp_path, change):
    value = hashlib.sha256(b'public model artifact').hexdigest()
    line = f'Artifact `{value}`.'
    policy(tmp_path, line)
    target = tmp_path/'provenance.json'
    doc = json.loads(target.read_text(encoding='utf-8'))
    item = doc['records'][0]
    if change == 'duplicate':
        doc['records'].append(dict(item))
    elif change == 'schema':
        doc['schema'] = 'other'
    else:
        field = {'path': 'path', 'line_hash': 'line_sha256', 'token': 'values', 'reason': 'reason'}[change]
        item[field] = {'path': '../escape', 'line_hash': 'invalid', 'token': ['invalid'], 'reason': ''}[change]
    target.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError):
        load_public_provenance(target)
