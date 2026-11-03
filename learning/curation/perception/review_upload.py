"""Import selected client bytes or operator-configured folders as pending images."""
import base64
import binascii
import json
import re
import tempfile
from pathlib import Path

import cv2
import numpy as np

import review_evidence
import review_ingest
import review_masks

IMAGE_LIMIT = 8 * 1024 * 1024
BODY_LIMIT = 12 * 1024 * 1024


def folders(store):
    values = json.loads(review_evidence.metadata(store, 'image_folders') or '[]')
    return [{'id': item['id'], 'label': item['label']} for item in values]


def _import_files(store, entries, actor, kind):
    if not review_masks.classes(store):
        raise ValueError('이 작업 공간의 픽셀 클래스셋을 먼저 설정하세요.')
    rows, upstream = [], {}
    for path, session, name in entries:
        raw = review_ingest.bounded(path, IMAGE_LIMIT)
        pixels = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ValueError(f'JPEG/PNG 사진을 읽을 수 없습니다: {name}')
        digest = review_masks.sha(raw)
        path = str(path)
        rows.append({'image': path, 'image_sha256': digest, 'width': pixels.shape[1],
                     'height': pixels.shape[0], 'source_session': session, 'capture_group': session})
        upstream[path] = {'provider': kind, 'path': name, 'sha256': digest,
                          'bytes': len(raw), 'registered_by': actor}
    if not 1 <= len(rows) <= 2000:
        raise ValueError('한 번에 원본 사진 1~2000장을 등록할 수 있습니다.')
    with tempfile.TemporaryDirectory(prefix='image-import-', dir=store.state) as temporary:
        catalog = Path(temporary) / 'verified-inputs.jsonl'
        catalog.write_text('\n'.join(json.dumps(row, sort_keys=True) for row in rows), encoding='utf-8')
        return review_ingest._import_frames(store, {'path': str(catalog)}, upstream,
                                            verified_kind=kind)


def import_image(store, body, actor):
    if not isinstance(body, dict) or set(body) - {'name', 'data', 'folder'} or not {'name', 'data'} <= set(body):
        raise ValueError('사진 이름과 파일 내용만 올리세요.')
    name, data, folder = body['name'], body['data'], body.get('folder', '')
    if (not isinstance(name, str) or not 1 <= len(name) <= 255 or
            '/' in name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name) or
            Path(name).suffix.lower() not in ('.jpg', '.jpeg', '.png')):
        raise ValueError('JPEG/PNG 파일 이름이 필요합니다.')
    if (not isinstance(folder, str) or len(folder) > 500 or folder.startswith('/') or
            '\\' in folder or ':' in folder or any(ord(c) < 32 for c in folder) or
            (folder and any(part in ('', '.', '..') for part in folder.split('/')))):
        raise ValueError('선택한 폴더 이름이 올바르지 않습니다.')
    if not isinstance(data, str) or len(data) > ((IMAGE_LIMIT + 2) // 3) * 4:
        raise ValueError('사진 한 장은 8 MiB 이하여야 합니다.')
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('사진 파일 전송 내용이 올바르지 않습니다.') from None
    if not raw or len(raw) > IMAGE_LIMIT:
        raise ValueError('사진 한 장은 8 MiB 이하여야 합니다.')
    if not (raw.startswith(b'\xff\xd8\xff') or raw.startswith(b'\x89PNG\r\n\x1a\n')):
        raise ValueError('JPEG/PNG 원본 파일만 올릴 수 있습니다.')
    with tempfile.TemporaryDirectory(prefix='image-upload-', dir=store.state) as temporary:
        path = Path(temporary) / name
        path.write_bytes(raw)
        return _import_files(store, [(path, 'upload:' + (folder or 'files'), name)],
                             actor, 'browser_upload')


def import_folder(store, body, actor):
    if not isinstance(body, dict) or set(body) != {'id'} or not isinstance(body['id'], str):
        raise ValueError('등록된 폴더를 선택하세요.')
    config = json.loads(review_evidence.metadata(store, 'image_folders') or '[]')
    selected = next((item for item in config if item['id'] == body['id']), None)
    if selected is None:
        raise ValueError('등록된 폴더를 선택하세요.')
    root = Path(selected['path'])
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('설정된 원본 폴더를 확인하세요.')
    pattern = selected['pattern']
    if not re.fullmatch(r'[A-Za-z0-9_*.-]+', pattern) or pattern in ('.', '..'):
        raise ValueError('설정된 촬영 폴더 패턴을 확인하세요.')
    entries = []
    for run in sorted(root.glob(pattern)):
        if run.is_symlink() or not run.is_dir():
            raise ValueError('원본 촬영 폴더는 링크일 수 없습니다.')
        for path in sorted(run.iterdir()):
            if path.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                if path.is_symlink() or not path.is_file():
                    raise ValueError('원본 사진은 일반 파일이어야 합니다.')
                entries.append((path, f"folder:{selected['id']}:{run.name}",
                                f'{run.name}/{path.name}'))
    return _import_files(store, entries, actor, 'local_folder')
