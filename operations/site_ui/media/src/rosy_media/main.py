"""Production composition: CORE validation, the exact MediaMTX kick, and the HTTP adapter.

Config is one JSON file outside the repository (template: deploy/site/media-authority.example.json).
Robot CORE origins are fixed here; nothing in a request selects an upstream.
"""

import json
from pathlib import Path
import re
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from .authority import MediaAuthority
from .backend import MediaMTXClient


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read(path, limit=16384):
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > limit:
        raise ValueError('invalid media configuration file')
    return file.read_bytes()


def _origin(url, what):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError(what + ' must be a fixed HTTPS origin')
    return url.rstrip('/')


def _post_json(http, url, token):
    """(status, dict) of one bounded POST; (None, {}) when unreachable or malformed."""
    request = Request(url, data=b'{}', method='POST', headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        # Under the one-second recheck; an unreachable peer fails closed (MediaAuthority closes).
        with http.open(request, timeout=.75) as response:
            raw = response.read(16385)
            if response.headers.get_content_type() != 'application/json' or len(raw) > 16384:
                return response.status, {}
            result = json.loads(raw)
            return response.status, result if isinstance(result, dict) else {}
    except HTTPError as exc:
        return exc.code, {}
    except (URLError, OSError, TimeoutError, ValueError):
        return None, {}


def _https(cafile):
    return build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=cafile)))


class CoreValidator:
    """Rechecks a media delegation at the CORE that issued it (POST .../vision/media/validate)."""

    def __init__(self, robots):
        self._robots = {robot_id: (_origin(robot['core_url'], 'robot CORE origin') + '/api/v1/vision/media/validate',
                                   _https(robot.get('core_ca'))) for robot_id, robot in robots.items()}

    def __call__(self, robot_id, token, now):
        status, result = _post_json(*reversed(self._robots[robot_id]), token)
        return result if status == 200 and result else {'active': False}

    def media_enabled(self, robot_id):
        """D-801 robot veto: CORE answers its validate route only while its media is on (503 when off)."""
        status, result = _post_json(*reversed(self._robots[robot_id]), 'site-veto-probe')
        return status == 200 and result.get('active') is False


class SiteValidator:
    """D-801: a site-issued READ grant is live only if Fleet still authorizes its browser credential
    and the robot's CORE has not turned media off."""

    def __init__(self, fleet_url, fleet_ca, core):
        self._url = _origin(fleet_url, 'Fleet origin') + '/api/fleet/media/validate'
        self._http, self._core = _https(fleet_ca), core

    def __call__(self, robot_id, token, now):
        if not self._core.media_enabled(robot_id):
            return {'active': False}
        status, result = _post_json(self._http, self._url, token)
        return result if status == 200 and result else {'active': False}


def _issuer(token):
    import base64
    try:
        part = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))).get('iss')
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def build(config):
    """Return (authority, admin_token, listen_port); the authority's kick IS MediaMTXClient.kick."""
    admin = _read(config['admin_token_file']).decode('ascii').strip()
    robots = config['robots']
    if not isinstance(robots, dict) or any(not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', key) for key in robots):
        raise ValueError('invalid robot list')
    keys = {robot_id: {kid: _read(path) for kid, path in robot['keys'].items()}
            for robot_id, robot in robots.items()}
    backend = MediaMTXClient(config.get('mediamtx_api', 'http://127.0.0.1:9997'), admin)
    core, site = CoreValidator(robots), config.get('site_issuer')
    site_keys, validate = {}, core
    if site:
        site_keys = {kid: _read(path) for kid, path in site['keys'].items()}
        by_site = SiteValidator(site['fleet_url'], site.get('fleet_ca'), core)

        def validate(robot_id, token, now):
            # The issuer only routes the recheck; MediaAuthority already verified the signature.
            issuer = _issuer(token)
            return by_site(robot_id, token, now) if issuer == config['audience'] else core(robot_id, token, now)
    authority = MediaAuthority(audience=config['audience'], public_keys=keys, site_keys=site_keys,
                               validate_online=validate, kick=backend.kick)
    port = int(config.get('listen_port', 9121))
    return authority, admin, port


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit('usage: python -m rosy_media.main <media-authority.json>')
    import uvicorn
    from .server import create_app
    authority, admin, port = build(json.loads(_read(argv[0], 65536)))
    # Loopback only: the TLS media gateway exposes /v1/*, never /auth or /health.
    uvicorn.run(create_app(authority, admin_token=admin), host='127.0.0.1', port=port,
                log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
