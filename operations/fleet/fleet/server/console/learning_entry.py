"""Fleet launch documents for operator-configured Learning apps; targets own access."""

import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse


def _origin(value):
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) > 126 for c in value):
        raise ValueError('Learning origin must be an HTTPS origin')
    if any(c in value for c in ('@', '\\', '?', '#', '*', '%')):
        raise ValueError('Learning origin must not contain credentials or URL suffixes')
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        port = url.port
    except ValueError:
        raise ValueError('Invalid Learning origin') from None
    if (url.scheme != 'https' or not value.startswith('https://') or not host
            or url.path or url.netloc.endswith(':') or port == 0):
        raise ValueError('Learning origin must be an HTTPS origin without a path')
    if host in {'localhost', 'localdomain'} or host.endswith(('.localhost', '.localdomain')):
        raise ValueError('Learning origin must not be local')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Browsers accept short, octal and hex IPv4; reject ambiguous numeric hosts.
        last = host.rsplit('.', 1)[-1]
        if (re.fullmatch(r'[0-9]+|0x[0-9a-f]+', last)
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host)
                or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                       for label in host.split('.'))):
            raise ValueError('Invalid Learning hostname') from None
    else:
        address = getattr(address, 'ipv4_mapped', None) or address
        if address.is_loopback or address.is_unspecified:
            raise ValueError('Learning origin must not be loopback or unspecified')
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate Learning configuration key')
        result[key] = value
    return result


def _load_apps():
    path = os.environ.get('ROSY_LEARNING_APPS_CONFIG')
    if not path:
        return {}
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique)
    except (OSError, UnicodeError, ValueError):
        raise ValueError('Learning configuration must be a readable JSON object') from None
    if not isinstance(config, dict) or set(config) - {'model', 'ai'}:
        raise ValueError('Learning configuration permits only model and ai origins')
    return {host: _origin(origin) for host, origin in config.items()}


def install_learning_routes(app, web_root, csp):
    apps = _load_apps()
    template = (web_root / 'learning.html').read_text(encoding='utf-8')
    headers = {'Cache-Control': 'no-store', 'Content-Security-Policy': csp,
               'Referrer-Policy': 'no-referrer'}

    def document(status_code):
        html = template
        for host in ('model', 'ai'):
            html = html.replace('{{' + host + '_status}}',
                                '운영 연결 등록됨' if host in apps else '운영 연결 준비 중')
        return HTMLResponse(html, status_code=status_code, headers=headers)

    @app.get('/console/learning', include_in_schema=False)
    def learning():
        return document(200 if apps else 503)

    def target(host):
        def redirect(request: Request):
            if request.url.query:
                raise HTTPException(status_code=400, detail='Learning entry does not accept query parameters')
            if host not in apps:
                return document(503)
            return RedirectResponse(apps[host] + '/learning', status_code=303, headers=headers)
        return redirect

    for host in ('model', 'ai'):
        app.add_api_route('/console/learning/' + host, target(host), methods=['GET'],
                          include_in_schema=False, name='learning-entry:' + host)
