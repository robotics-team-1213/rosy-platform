"""Captured offline evidence verification, not live authentication or training GT."""
import base64
import hashlib
import json
import tempfile
from pathlib import Path

from core_common.protocol.schemas import DeviceActionReceipt
from rosy.contracts.learning import validate_episode
from rosy.contracts.learning.artifacts import episode_profile_validators
from rosy.contracts.learning.fleet_export import encoded, export_metadata

PROFILES = episode_profile_validators()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('nonfinite JSON value: ' + value)


def decode(raw):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)


def _read(path, root):
    path, root = Path(path), Path(root).resolve()
    if any(item.is_symlink() or item.is_junction() for item in (path, *path.parents)):
        raise ValueError('evidence symlink rejected')
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('evidence escapes root or is missing')
    return path.read_bytes()


def _references(episode):
    refs = {}
    for ref in episode['sources'] + list(episode['streams'].values()) + episode['outcome']['evidence']:
        prior = refs.setdefault(ref['path'], ref)
        if encoded(prior) != encoded(ref):
            raise ValueError('conflicting role references')
    return refs


def capture(export_file, episode_file, receipt_file):
    """Read once; all subsequent validation and storage use these exact bytes."""
    export_file, episode_file, receipt_file = map(Path, (export_file, episode_file, receipt_file))
    root = episode_file.parent.resolve()
    headers = {name: _read(path, path.parent) for name, path in (
        ('export', export_file), ('manifest', episode_file), ('receipt', receipt_file))}
    episode = validate_episode(decode(headers['manifest']))
    if episode['profile'] not in PROFILES:
        raise ValueError('unsupported Episode profile')
    sources = {name: _read(root/name, root) for name in _references(episode)}
    return dict(headers=headers, sources=sources)


def pack(bundle):
    return encoded({group: {name: base64.b64encode(raw).decode('ascii')
                           for name, raw in items.items()} for group, items in bundle.items()})


def unpack(raw):
    value = decode(raw)
    if (not isinstance(value, dict) or set(value) != {'headers', 'sources'}
            or not isinstance(value['headers'], dict) or not isinstance(value['sources'], dict)
            or set(value['headers']) != {'export', 'manifest', 'receipt'}):
        raise ValueError('exact captured bundle fields required')
    return {group: {name: base64.b64decode(blob, validate=True)
                    for name, blob in items.items()} for group, items in value.items()}


def verify(bundle, scratch):
    headers, sources = bundle['headers'], bundle['sources']
    episode = validate_episode(decode(headers['manifest']))
    refs = _references(episode)
    if set(sources) != set(refs) or episode['profile'] not in PROFILES:
        raise ValueError('exact supported source coverage required')
    for name, raw in sources.items():
        if len(raw) != refs[name]['bytes'] or hashlib.sha256(raw).hexdigest() != refs[name]['sha256']:
            raise ValueError('captured source hash differs')
    # The existing profile validators inspect a private copy of the captured
    # bytes, never the sender's mutable paths after capture.
    with tempfile.TemporaryDirectory(prefix='.learning-check-', dir=scratch) as directory:
        root = Path(directory)
        for name, raw in sources.items():
            target = root/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        validate_episode(episode, root=root)
        PROFILES[episode['profile']](episode, root=root)
    wire = DeviceActionReceipt.model_validate(decode(headers['receipt'])).model_dump(mode='json')
    # Preserve the profile's declared source order, rather than pack's sorted keys.
    preserved = [DeviceActionReceipt.model_validate(decode(sources[ref['path']])).model_dump(mode='json')
                 for ref in episode['sources'] if ref['path'].startswith('owner-receipts/')]
    expected = export_metadata(episode, wire, preserved, headers['manifest'], headers['receipt'])
    actual = decode(headers['export'])
    if encoded(actual) != encoded(expected):
        raise ValueError('export differs from captured source/receipt binding')
    return actual
