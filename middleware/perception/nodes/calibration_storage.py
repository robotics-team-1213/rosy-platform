"""Atomic updates to explicitly configured calibration files (no ROS dependency)."""
import math
import os
import tempfile
from pathlib import Path

import yaml
from .calibration_record import HEADER, MAX_BYTES, decode_record, encode_record, validate_context, runtime_calibration_path
from .calibration_lock import calibration_lock


def single_calibration_path(save_path, sign_path, context=None, runtime_generation=None):
    """Compatibility inputs must identify one commit, never two files."""
    if any(not isinstance(value, str) or not value.strip() for value in (save_path, sign_path)):
        raise ValueError('Calibration destination is not configured')
    destination = Path(save_path).resolve()
    if destination != Path(sign_path).resolve():
        raise ValueError('Cliff and drive calibration must use one calibration_path')
    if context is not None:
        validate_context(context)
        if runtime_generation is not None:
            runtime_calibration_path(str(destination), context, runtime_generation)
        if destination.exists():
            if destination.stat().st_size > MAX_BYTES:
                raise ValueError('Calibration file exceeds size limit')
            _, parameters = decode_record(destination.read_text(encoding='utf-8'), context)
            _parameters(parameters)
    return str(destination)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Calibration contains a non-finite value')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _parameters(document):
    if not isinstance(document, dict) or not document:
        raise ValueError('Calibration must be a nonempty node mapping')
    for name, content in document.items():
        if not isinstance(name, str) or not isinstance(content, dict):
            raise ValueError('Calibration node settings must be a mapping')
        if not isinstance(content.get('ros__parameters'), dict):
            raise ValueError('Calibration parameters must be a mapping')
    _finite(document)


def calibration_revision(destination, context):
    """Snapshot the validated revision before collecting a new trial."""
    path = Path(destination)
    validate_context(context)
    if not path.exists():
        return 0
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Calibration file exceeds size limit')
    metadata, parameters = decode_record(path.read_text(encoding='utf-8'), context)
    _parameters(parameters)
    return metadata['revision']


def merge_calibration(destination, updates, *, context=None, actor=None, expected_revision=None, create_only=False):
    """Serialize cooperating writers and optionally reject a stale trial."""
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError('Calibration destination is not configured')
    path = Path(destination).resolve()
    with calibration_lock(path):
        if create_only and path.exists():
            raise ValueError('Calibration destination already exists')
        return _merge_calibration(str(path), updates, context=context, actor=actor,
                                  expected_revision=expected_revision)


def _merge_calibration(destination, updates, *, context=None, actor=None, expected_revision=None):
    """Merge measured fields only; the caller selects the active generation path.

    A supplied context requires matching versioned provenance. The caller still
    owns activation-path authorization and policy adoption acknowledgement.
    """
    if not isinstance(destination, str) or not destination.strip():
        raise ValueError('Calibration destination is not configured')
    path = Path(destination)
    incoming = yaml.safe_load(updates)
    _parameters(incoming)
    existing = {}
    previous = None
    if context is not None:
        validate_context(context)
    if path.exists():
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Calibration file exceeds size limit')
        original = path.read_text(encoding='utf-8')
        if context is not None:
            previous, existing = decode_record(original, context)
        else:
            if original.startswith(HEADER):
                raise ValueError('Bound calibration requires matching writer context')
            existing = yaml.safe_load(original)
        _parameters(existing)
    if expected_revision is not None:
        if (context is None or type(expected_revision) is not int or expected_revision < 0
                or expected_revision != (previous['revision'] if previous else 0)):
            raise ValueError('Calibration revision conflict')
    # A bare ROS selector only matches the root namespace. Keep the file
    # device-local, but let its node settings survive a robot namespace.
    def scoped(document):
        result = {}
        for name, content in document.items():
            selector = '/**/' + name if '/' not in name else name
            if selector in result:
                raise ValueError('Ambiguous calibration node selectors')
            result[selector] = content
        return result

    existing = scoped(existing)
    incoming = scoped(incoming)
    for name, content in incoming.items():
        owner = existing.setdefault(name, {'ros__parameters': {}})
        owner['ros__parameters'].update(content['ros__parameters'])
    payload = (encode_record(existing, context, actor, previous) if context is not None else
               yaml.safe_dump(existing, sort_keys=False, allow_unicode=True))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', dir=path.parent, encoding='utf-8', delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return (previous['revision'] + 1 if previous else 1) if context is not None else None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
