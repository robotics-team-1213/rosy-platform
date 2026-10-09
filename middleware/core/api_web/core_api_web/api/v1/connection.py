"""D-432 LAN lobby admission; client setup files are not part of the operator flow."""

import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core_api_web.api.deps import (
    TOKEN_WRITE_LOCK, CoreServicesLike, auth_entries, generate_token, get_services,
    new_token_record, persist_token_records, utc_after,
    development_link_enabled, is_expired,
)
from core_api_web.api.errors import ReasonError
from core_api_web.api.v1.auth import NO_STORE, _Window, _error, _pairing, client_allowed
from core_api_web.api.v1.host import BOOT_STATUS_FILE, read_boot_status
from core_common.protocol.access import ConnectionInfo

connection_router = APIRouter(prefix='/api/v1/auth', tags=['auth'])


def development_enabled(config: dict) -> bool:
    return development_link_enabled(config)


def local_authority(request: Request, svc: CoreServicesLike) -> bool:
    host = request.url.hostname or ''
    names = {str(svc.identity.robot_name).rstrip('.').lower() + '.local',
             socket.gethostname().rstrip('.').lower()}
    names.update(name + '.local' for name in tuple(names) if not name.endswith('.local'))
    try:
        address = ipaddress.ip_address(host)
        valid = client_allowed(str(address))
    except ValueError:
        valid = host.lower().rstrip('.') in names
    origin = request.headers.get('origin')
    if origin is not None:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        valid = valid and parsed.scheme == request.url.scheme and parsed.netloc == request.url.netloc
    return valid


#: D-535: bump when the reason contract (connect-reasons vector) changes meaning.
CONNECT_CONTRACT = 1
#: D-535 reachability reads per source per minute. The answer is public anyway (mDNS TXT
#: carries stage, release and tls_host); the limit bounds work, not secrecy. No global
#: window: one LAN host with a few aliases must not lock every Pilot out (review M1).
PER_SOURCE_LIMIT, WINDOW_S = 30, 60.0
_rates_lock = threading.Lock()


def _admit(request: Request, host: str):
    state = request.app.state
    with _rates_lock:
        if not hasattr(state, 'connection_rates'):
            state.connection_rates = {}
        sources = state.connection_rates
        now = time.monotonic()
        if len(sources) > 1024:
            sources.clear()  # ponytail: >1024 private sources forget their windows; each answer is a small read
        window = sources.setdefault(host, _Window(PER_SOURCE_LIMIT, WINDOW_S))
        wait = window.retry_after(now)
        if wait:
            raise ReasonError(429, 'RATE_LIMITED', None, {'retry_after_s': int(wait) + 1},
                              {'Retry-After': str(int(wait) + 1)})
        window.hits.append(now)


def _pairing_word(request: Request, tls: bool) -> str:
    if not tls or request.url.scheme != 'https':
        return 'unavailable'
    from core_api_web.api.peer_pairing.receiver_initializer import get_receiver
    try:
        return get_receiver(request).pairing_state()
    except Exception:  # A reachability read never fails because pairing cannot start (review M2).
        return 'unavailable'


@connection_router.get('/connection', response_model=ConnectionInfo)
def connection(request: Request, svc: CoreServicesLike = Depends(get_services)):
    host = request.client.host if request.client else ''
    if not client_allowed(host):
        raise ReasonError(403, 'LAN_REQUIRED', None)
    _admit(request, host)
    tls = bool((svc.config.get('network') or {}).get('tls'))
    path = str(((svc.config.get('hardware_probe') or {}).get('boot_status_path')) or BOOT_STATUS_FILE)
    boot = read_boot_status(path)
    # Same rule as host status-summary: CORE answering without the indicator file is ready.
    stage = boot['stage'] if boot else 'CORE_READY'
    return JSONResponse(headers=NO_STORE, content={
        'mode': 'development' if development_enabled(svc.config) else 'paired',
        'robot_id': svc.identity.robot_id,
        'transport': 'https' if tls else 'http',
        'connect_contract': CONNECT_CONTRACT,
        'api': 'v1',
        'core_ready': stage == 'CORE_READY',
        'stage': stage,
        'release': boot['release_id'] if boot else None,
        'tls_hostname': (socket.gethostname().lower().removesuffix('.local') + '.local') if tls else None,
        'pairing': _pairing_word(request, tls),
    })


@connection_router.post('/development-session', status_code=201)
def development_session(request: Request, svc: CoreServicesLike = Depends(get_services)):
    host = request.client.host if request.client else ''
    if not client_allowed(host) or not development_enabled(svc.config) or not local_authority(request, svc):
        return _error(403, 'FORBIDDEN', 'this robot requires pairing')
    if _pairing(request).admit(host) is not None:
        return _error(429, 'RATE_LIMITED', 'too many connection attempts', {'Retry-After': '60'})
    token = generate_token()
    record = new_token_record(token, 'operator', 'Pilot development session',
                              source='pair-development', expires_at=utc_after(3600))
    with TOKEN_WRITE_LOCK:
        records = auth_entries(svc.config)
        records = [item for item in records if item['source'] != 'pair-development' or not is_expired(item)]
        previous = [item for item in records if item['source'] == 'pair-development']
        if len(previous) >= 8:
            return _error(429, 'RATE_LIMITED', 'too many development sessions', {'Retry-After': '60'})
        persist_token_records(svc, records + [record])
    svc.events.publish('auth.paired', severity='warning', source='api', data={
        'id': record['id'], 'role': 'operator', 'source': 'pair-development', 'expires_at': record['expires_at'],
    })
    return JSONResponse(status_code=201, headers=NO_STORE, content={
        'id': record['id'], 'token': token, 'role': 'operator', 'label': record['label'],
        'source': record['source'], 'expires_at': record['expires_at'],
    })
