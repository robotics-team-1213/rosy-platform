"""HTTP routes for the OMX canonical start-pose pipeline, mounted inside omx_center_web.

Zero-flag read-only built-in spec works even when omx_center or canonical config is absent.
All POST actions require project manager authorization ('manage' + CSRF) under collaboration.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACTS_SRC = _ROOT / 'contracts' / 'learning' / 'src'
_OMX_TRAINING_SRC = _ROOT / 'learning' / 'training' / 'omx'
for _p in (str(_CONTRACTS_SRC), str(_OMX_TRAINING_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rosy.contracts.learning.omx_canonical import (  # noqa: E402
    AUTHORITY_STAMP,
    canonical_spec_sha256,
    default_canonical_spec,
)

STATIC = Path(__file__).with_name('review_app_web')
PAGES = {
    '/learning/canonical': ('canonical.html', 'text/html'),
    '/canonical.js': ('canonical.js', 'text/javascript'),
    '/canonical-monitor.js': ('canonical-monitor.js', 'text/javascript'),
    '/canonical.css': ('canonical.css', 'text/css'),
}
PREFIX = '/api/learning/canonical'
_UUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
_ID_RE = r'[A-Za-z0-9_][A-Za-z0-9._-]{0,63}'
_DEFAULT_TELEMETRY = None


def _default_telemetry_snapshot():
    global _DEFAULT_TELEMETRY
    if _DEFAULT_TELEMETRY is None:
        try:
            from canonical_telemetry import HostTelemetry
            _DEFAULT_TELEMETRY = HostTelemetry(Path.home)
        except ImportError:
            return None
    return _DEFAULT_TELEMETRY.snapshot()


def _default_spec_payload() -> dict:
    spec = default_canonical_spec()
    return {
        'schema': spec['schema'], 'spec_sha256': canonical_spec_sha256(spec),
        'source': 'builtin', 'spec': spec, **AUTHORITY_STAMP,
    }


def _default_snapshot() -> dict:
    spec_doc = _default_spec_payload()
    return {
        'configured': False, 'writable': False, 'host_id': None,
        'spec_sha256': spec_doc['spec_sha256'], 'spec': spec_doc['spec'], 'spec_source': 'builtin',
        'named_sources': {}, 'gpu_lock': {'busy': False, 'holders': []},
        'runs': [], 'watched': {}, 'peers': {}, 'host_telemetry': _default_telemetry_snapshot(), **AUTHORITY_STAMP,
    }


def _service(center):
    return getattr(center, 'canonical', None) if center is not None else None


def peer_intake_ok(handler, path: str, center) -> bool:
    if path != PREFIX + '/intake':
        return False
    service = _service(center)
    return bool(service is not None and service.configured and service.verify_peer_bearer(handler.headers.get('Authorization')))


def get(handler, path: str, center, accounts=None) -> bool:
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC / name).read_bytes(), mime=mime + '; charset=utf-8')
        return True
    if path != PREFIX and not path.startswith(PREFIX + '/'):
        return False
    service = _service(center)

    if path == PREFIX:
        handler.send(service.snapshot() if service is not None else _default_snapshot())
        return True
    if path == PREFIX + '/spec':
        handler.send(service.spec_payload() if service is not None else _default_spec_payload())
        return True
    if path == PREFIX + '/peer-summary':
        if accounts is not None and getattr(handler, 'service_principal', None) is None:
            accounts.require(handler.learning_principal, 'view')
        elif getattr(handler, 'learning_principal', None) is None and getattr(handler, 'service_principal', None) is None:
            if service is None or not service.verify_peer_bearer(handler.headers.get('Authorization')):
                handler.send({'error': '피어 인증 토큰을 확인하세요.'}, 403)
                return True
        handler.send(_default_snapshot() if service is None else service.peer_summary())
        return True

    if service is None or not service.configured:
        handler.send({'error': '표준 시작 자세 파이프라인이 설정되지 않았습니다.'}, 404)
        return True

    if match := re.fullmatch(PREFIX + r'/runs/(' + _UUID_RE + r')', path):
        try:
            handler.send(service.get_run(match[1]))
        except KeyError:
            handler.send({'error': '실행 기록을 찾을 수 없습니다.'}, 404)
        return True
    if match := re.fullmatch(PREFIX + r'/runs/(' + _UUID_RE + r'|' + _ID_RE + r')/bundle-manifest', path):
        try:
            handler.send(service.bundle_manifest(match[1]))
        except KeyError:
            handler.send({'error': '실행 번들을 찾을 수 없습니다.'}, 404)
        return True
    if match := re.fullmatch(PREFIX + r'/runs/(' + _UUID_RE + r'|' + _ID_RE + r')/file/(.{1,256})', path):
        try:
            handler.send(service.bundle_file(match[1], match[2]), mime='application/octet-stream')
        except (KeyError, FileNotFoundError):
            handler.send({'error': '번들 파일을 찾을 수 없습니다.'}, 404)
        return True
    if match := re.fullmatch(PREFIX + r'/watched/(' + _ID_RE + r')', path):
        try:
            handler.send(service.get_watched(match[1]))
        except KeyError:
            handler.send({'error': '관찰 폴더를 찾을 수 없습니다.'}, 404)
        return True
    if match := re.fullmatch(PREFIX + r'/peers/(' + _ID_RE + r')', path):
        try:
            handler.send(service.get_peer(match[1]))
        except KeyError:
            handler.send({'error': '피어 호스트를 찾을 수 없습니다.'}, 404)
        return True
    handler.send({'error': '표준 시작 자세 경로를 확인하세요.'}, 404)
    return True


def post(handler, path: str, body: dict, center, accounts=None) -> bool:
    if not path.startswith(PREFIX + '/'):
        return False
    service = _service(center)
    peer_ok = path == PREFIX + '/intake' and service is not None and service.configured and service.verify_peer_bearer(handler.headers.get('Authorization'))
    if accounts is not None and not peer_ok and getattr(handler, 'service_principal', None) is None:
        accounts.require(handler.learning_principal, 'manage')
    if service is None or not service.configured:
        handler.send({'error': '표준 시작 자세 파이프라인이 설정되지 않았습니다.'}, 503)
        return True

    try:
        if path == PREFIX + '/intake':
            handler.send(service.intake_collection(body))
            return True
        if path == PREFIX + '/jobs':
            handler.send(service.start_job(body))
            return True
        if match := re.fullmatch(PREFIX + r'/jobs/(' + _UUID_RE + r')/cancel', path):
            if body:
                raise ValueError('중지 요청 본문은 비어 있어야 합니다.')
            try:
                handler.send(service.cancel_job(match[1]))
            except KeyError:
                handler.send({'error': '실행 기록을 찾을 수 없습니다.'}, 404)
            return True
        if match := re.fullmatch(PREFIX + r'/peers/(' + _ID_RE + r')/refresh', path):
            if body:
                raise ValueError('피어 새로고침 본문은 비어 있어야 합니다.')
            try:
                handler.send(service.refresh_peer(match[1]))
            except KeyError:
                handler.send({'error': '피어 호스트를 찾을 수 없습니다.'}, 404)
            return True
    except ValueError as exc:
        if type(exc).__name__ == 'BusyConflict':
            handler.send({'error': str(exc)}, 409)
            return True
        raise
    handler.send({'error': '표준 시작 자세 경로를 확인하세요.'}, 404)
    return True
