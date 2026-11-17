"""Local observer recording routes; review_app owns project authorization and CSRF."""
from pathlib import Path
import json
import os
import re
import stat
from urllib.parse import parse_qs, urlsplit


PREFIX = '/api/learning/recording'
STATIC = Path(__file__).with_name('review_app_web')
PAGES = {'/learning/record': ('record.html', 'text/html'),
         '/record.js': ('record.js', 'text/javascript'),
         '/record-review.js': ('record-review.js', 'text/javascript'),
         '/record.css': ('record.css', 'text/css'),
         '/incidents': ('incidents.html', 'text/html'),
         '/incidents.js': ('incidents.js', 'text/javascript')}
INCIDENT_LIMIT = 256 * 1024


def incident_feedback_binding(body):
    """Bind an operator's Fleet incidents export to harvested stuck markers.

    Validation only mirrors the CLI tool: malformed input must surface as
    ValueError (HTTP 400), never an AttributeError or TypeError from bind().
    Nothing is stored and no label is created.
    """
    import incident_feedback
    if set(body) != {'incidents', 'markers'}:
        raise ValueError('incident feedback requires incidents and markers objects')
    pair = []
    for key in ('incidents', 'markers'):
        value = body[key]
        if not isinstance(value, dict) or len(json.dumps(
                value, ensure_ascii=False).encode('utf-8')) > INCIDENT_LIMIT:
            raise ValueError(f'{key} must be a JSON object of at most 256 KiB')
        pair.append(value)
    try:
        return incident_feedback.bind(*pair)
    except (TypeError, AttributeError) as exc:
        raise ValueError(f'invalid {exc}') from None


def create(store, center, config):
    from learning_recordings import Recordings
    return Recordings(store, center, config)


def load_config(path, parser):
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        parser.error(f'--recording-config: {exc}')


def send_file(handler, path, *, filename):
    with Path(path).open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 2*1024**3:
            raise ValueError('bounded regular recording archive required')
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/zip')
        handler.send_header('Content-Length', str(info.st_size))
        handler.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        for name, value in getattr(handler, 'extra_headers', []):
            handler.send_header(name, value)
        handler.end_headers()
        remaining = info.st_size
        try:
            while remaining:
                chunk = stream.read(min(256*1024, remaining))
                if not chunk:
                    handler.close_connection = True
                    return
                handler.wfile.write(chunk)
                remaining -= len(chunk)
        except OSError:
            # Headers already describe the archive; close a failed transfer without a second response.
            handler.close_connection = True


def get(handler, path, recordings):
    if path in PAGES:
        name, mime = PAGES[path]
        handler.send((STATIC/name).read_bytes(), mime=mime+'; charset=utf-8')
        return True
    if path == PREFIX+'/snapshot':
        handler.send(recordings.snapshot())
        return True
    if path == PREFIX+'/profiles':
        handler.send({'profiles': recordings.profiles.list()})
        return True
    if path.startswith(PREFIX+'/review'):
        match = re.fullmatch(PREFIX+r'/review/([0-9a-f-]{36})/([0-9a-f-]{36})', path)
        query = parse_qs(urlsplit(handler.path).query, strict_parsing=True, keep_blank_values=True)
        if match:
            if query not in ({}, {'refresh': ['1']}):
                raise ValueError('fixed saved review query required')
            handler.send(recordings.review(*match.groups(), refresh=bool(query)))
            return True
        match = re.fullmatch(PREFIX+r'/review-(frame|image)/([0-9a-f-]{36})/([0-9a-f-]{36})/'
            r'([0-9a-f]{64})/([0-9]{1,6})(?:/([A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?', path)
        if not match or query:
            raise ValueError('fixed saved review selection required')
        kind, session, episode, revision, index, camera = match.groups()
        if kind == 'frame' and camera is None:
            handler.send(recordings.review_frame(session, episode, revision, int(index)))
        elif kind == 'image' and camera is not None:
            handler.send(recordings.review_image(session, episode, revision, int(index), camera), mime='image/jpeg')
        else:
            raise ValueError('fixed saved review selection required')
        return True
    preview = re.fullmatch(PREFIX+r'/preview/([A-Za-z0-9_][A-Za-z0-9_.-]{0,63})', path)
    if preview:
        handler.send(recordings.preview(preview[1]), mime='image/jpeg')
        return True
    match = re.fullmatch(PREFIX+r'/(profile|session|artifact)/([0-9a-f-]{36})', path)
    if not match:
        return False
    kind, uid = match.groups()
    if kind == 'profile':
        handler.send(recordings.profiles.get(uid))
    elif kind == 'session':
        handler.send(recordings.get(uid))
    else:
        send_file(handler, recordings.artifact(uid), filename=uid+'.zip')
    return True


def post(handler, path, body, recordings):
    actor = getattr(handler, 'learning_principal', None)
    if path == PREFIX+'/incident-feedback':
        handler.send(incident_feedback_binding(body))
        return True
    if path == PREFIX+'/profile':
        handler.send(recordings.profiles.save(body, actor))
        return True
    action = {PREFIX+'/session': 'create', PREFIX+'/start': 'start', PREFIX+'/stop': 'stop',
              PREFIX+'/keep': 'keep', PREFIX+'/discard': 'discard', PREFIX+'/export': 'export',
              PREFIX+'/publish': 'publish', PREFIX+'/review-close': 'review_close'}.get(path)
    if action is None:
        return False
    handler.send(getattr(recordings, action)(body, actor))
    return True
