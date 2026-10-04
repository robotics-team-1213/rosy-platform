"""Stable source/evaluation provenance capture; never approval or publication."""
import hashlib
import json
from pathlib import Path
import re
import stat


def _stable_bytes(path):
    path = Path(path).absolute()
    for part in [path, *path.parents]:
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('source proof links refused')
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('regular source proof artifact required')
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('source proof artifact changed while captured')
    return raw


def _proof_path(value, proof):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('source proof artifact path required')
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('source proof path traversal refused')
    if not path.is_absolute():
        if '..' in path.parts:
            raise ValueError('source proof path traversal refused')
        path = proof.parent / path
    return path.absolute()


def _capture_proofs(paths):
    proofs, observed = {}, {}
    for value in paths:
        path = Path(value).absolute(); raw = _stable_bytes(path); observed[path] = raw
        doc = json.loads(raw)
        if not isinstance(doc, dict) or doc.get('schema') != 'rosy.pinky-review-source-proof/1':
            raise ValueError('source proof schema required')
        for name in ('source_session', 'capture_group'):
            if not isinstance(doc.get(name), str) or not doc[name].strip():
                raise ValueError('source proof session/group required')
        if not isinstance(doc.get('video_sha256'), str) or re.fullmatch('[0-9a-f]{64}', doc['video_sha256']) is None:
            raise ValueError('source proof video digest required')
        video_path = _proof_path(doc.get('video_path'), path)
        video = _stable_bytes(video_path); observed[video_path] = video
        if hashlib.sha256(video).hexdigest() != doc['video_sha256']:
            raise ValueError('source proof actual video hash differs')
        side_fields = {'sidecar_path', 'sidecar_sha256'} & set(doc)
        if side_fields:
            if side_fields != {'sidecar_path', 'sidecar_sha256'}:
                raise ValueError('source proof sidecar pair required')
            side_path = _proof_path(doc['sidecar_path'], path)
            side = _stable_bytes(side_path); observed[side_path] = side
            if (not isinstance(doc['sidecar_sha256'], str)
                    or re.fullmatch('[0-9a-f]{64}', doc['sidecar_sha256']) is None
                    or hashlib.sha256(side).hexdigest() != doc['sidecar_sha256']):
                raise ValueError('source proof actual sidecar hash differs')
        key = (doc['source_session'], doc['capture_group'], doc['video_sha256'])
        if key in proofs:
            raise ValueError('duplicate source proof binding')
        proofs[key] = {'record': doc, 'bytes': raw, 'sha256': hashlib.sha256(raw).hexdigest(), 'video': video,
                       'suffix': video_path.suffix}
    return proofs, observed
