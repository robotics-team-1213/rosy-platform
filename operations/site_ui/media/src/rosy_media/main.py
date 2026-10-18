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


class CoreValidator:
    """Rechecks a media delegation at the CORE that issued it (POST .../vision/media/validate)."""

    def __init__(self, robots):
        self._robots = {}
        for robot_id, robot in robots.items():
            parsed = urlsplit(robot['core_url'])
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
                raise ValueError('robot CORE origin must be a fixed HTTPS origin')
            context = ssl.create_default_context(cafile=robot.get('core_ca'))
            self._robots[robot_id] = (robot['core_url'].rstrip('/') + '/api/v1/vision/media/validate',
                build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context)))

    def __call__(self, robot_id, token, now):
        url, http = self._robots[robot_id]
        request = Request(url, data=b'{}', method='POST', headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            # Under the one-second recheck; an unreachable CORE fails closed (MediaAuthority closes).
            with http.open(request, timeout=.75) as response:
                raw = response.read(16385)
                if response.headers.get_content_type() != 'application/json' or len(raw) > 16384:
                    return {'active': False}
                result = json.loads(raw)
                return result if isinstance(result, dict) else {'active': False}
        except (HTTPError, URLError, OSError, TimeoutError, ValueError):
            return {'active': False}


def build(config):
    """Return (authority, admin_token, listen_port); the authority's kick IS MediaMTXClient.kick."""
    admin = _read(config['admin_token_file']).decode('ascii').strip()
    robots = config['robots']
    if not isinstance(robots, dict) or any(not re.fullmatch(r'[A-Za-z0-9._-]{1,96}', key) for key in robots):
        raise ValueError('invalid robot list')
    keys = {robot_id: {kid: _read(path) for kid, path in robot['keys'].items()}
            for robot_id, robot in robots.items()}
    backend = MediaMTXClient(config.get('mediamtx_api', 'http://127.0.0.1:9997'), admin)
    authority = MediaAuthority(audience=config['audience'], public_keys=keys,
                               validate_online=CoreValidator(robots), kick=backend.kick)
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
