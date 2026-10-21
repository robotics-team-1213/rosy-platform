"""Bounded JSON and request identities shared by the host learning workspace."""
import json
import os
import uuid


def identifier(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('canonical UUID required')
    return value


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise ValueError('bounded regular result required')
    return json.loads(path.read_bytes())


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
