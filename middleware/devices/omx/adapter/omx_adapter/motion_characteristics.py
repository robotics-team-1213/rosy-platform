"""Compatibility imports and atomic file storage for measured motion characteristics."""
import os
from pathlib import Path
import tempfile

from rosy.contracts.motion.characteristics import (  # noqa: F401
    SCHEMA, BINDING_FIELDS, MAX_BYTES, _canonical, _text, _bounds, _count, parse_json,
    _joint_map, document_digest, characteristics_digest, validate_characteristics,
)


def load_json(path):
    """Bounded strict JSON for explicit local inputs; never resolve evidence references."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('expected regular JSON file')
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('JSON file exceeds size limit')
    return parse_json(raw)


def write_json(path, document):
    """Replace one explicit canonical file only after serialization succeeds."""
    text = _canonical(document) + '\n'
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('JSON file exceeds size limit')
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path:
        raise ValueError('output requires a canonical path without symlinks')
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_characteristics(path):
    return validate_characteristics(load_json(path))


def save_characteristics(path, document):
    data = validate_characteristics(document)
    write_json(path, data)
    return document_digest(data)
