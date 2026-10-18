"""Optional CORE media authority wiring; missing media config never blocks CORE."""

import hashlib
import hmac
from pathlib import Path
from urllib.parse import urlsplit

from .deps import MediaGrantService, auth_entries, token_alive
from .errors import ApiError


def _secret(path):
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > 16384:
        raise ValueError('invalid media secret file')
    return file.read_bytes()


def install_media(app, config, services):
    app.state.media_grants = None
    app.state.media_site_url = None
    app.state.media_source_digest = None
    media = (config.get('vision') or {}).get('media') or {}
    # D-789 rollout (2026-10-18): WebRTC is the default wherever a site media server is
    # configured; `enabled: false` opts a robot out. Without site_url the robot stays on JPEG.
    if media.get('enabled') is False or not media.get('site_url'):
        return
    try:
        site_url = media['site_url']
        site = urlsplit(site_url)
        if (site.scheme != 'https' or not site.hostname or site.username or site.password
                or site.query or site.fragment or site.path not in ('', '/')):
            raise ValueError('invalid media site URL')
        private = _secret(media['signing_key_file'])
        source_file = media.get('source_credential_file')
        source = _secret(source_file).strip() if source_file else None
        if source is not None and not 32 <= len(source) <= 512:
            raise ValueError('invalid media source credential')
        source_digest = hashlib.sha256(source).digest() if source else None
        robot_id = services.identity.robot_id

        def owner_allowed(owner, action):
            if owner == 'source:' + robot_id:
                return (action == 'publish' and source_digest is not None
                        and hmac.compare_digest(hashlib.sha256(_secret(source_file).strip()).digest(), source_digest))
            if action != 'read':
                return False
            if owner.startswith('account-cookie:'):
                account = app.state.account_client
                return account is not None and account.media_session_active(owner.split(':', 1)[1])
            return token_alive(services.config, owner) and any(
                record['id'] == owner and record['role'] in ('viewer', 'operator', 'administrator')
                for record in auth_entries(services.config))

        service = MediaGrantService(robot_id=robot_id, audience=media['audience'],
            private_key=private, key_id=media['key_id'], owner_allowed=owner_allowed)
        app.state.media_grants = service
        app.state.media_site_url = site_url.rstrip('/')
        app.state.media_source_digest = source_digest
    except (KeyError, OSError, TypeError, ValueError):
        # No credentials, media URLs or key paths in status/errors/logs.
        app.state.media_grants = None


def owner_id(request, auth):
    if auth.account is None:
        return auth.token_id
    cookie = request.cookies.get('rosy_app_account')
    if not cookie or request.headers.get('authorization'):
        raise ApiError('MEDIA_BROWSER_SESSION_REQUIRED', 403, 'Media requires a bound Account browser session')
    session_id = hashlib.sha256(cookie.encode()).hexdigest()
    account = request.app.state.account_client
    if account is None or not account.media_session_active(session_id):
        raise ApiError('FORBIDDEN', 403, 'Original media authority is unavailable')
    return 'account-cookie:' + session_id
