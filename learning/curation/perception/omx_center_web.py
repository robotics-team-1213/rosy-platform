"""Learning-center routes; review_app owns authentication and bounded JSON parsing."""
import re

PREFIX = '/api/learning/omx/center'


def _registered(workspace, prepared_id):
    found = next((row for row in workspace.list()
                  if row['id'] == prepared_id and row['kind'] == 'omx'), None) if workspace else None
    if found is None:
        raise ValueError('registered OMX prepared set required')
    return found


def get(handler, path, center, workspace=None):
    owner = re.fullmatch(PREFIX + r'/owner-status/([A-Za-z0-9_][A-Za-z0-9_.-]{0,63})', path)
    if owner:
        if center is None:
            raise ValueError('이 작업대에 OMX 학습 실행기가 연결되지 않았습니다.')
        handler.send(center.read_owner_status(owner[1]))
        return True
    profile = re.fullmatch(PREFIX + r'/profile/([0-9a-f-]{36})', path)
    if profile or path == PREFIX + '/profiles':
        if center is None:
            raise ValueError('이 작업대에 OMX 학습 실행기가 연결되지 않았습니다.')
        handler.send(center.profiles.get(profile[1])['profile'] if profile else {'profiles': center.profiles.list()})
        return True
    review = re.fullmatch(PREFIX + r'/review/([0-9a-f]{32})', path)
    frame = re.fullmatch(PREFIX + r'/review-frame/([0-9a-f]{32})/([0-9a-f]{64})/(\d{1,9})/(\d{1,9})/(\d{1,4})', path)
    frame_set = re.fullmatch(PREFIX + r'/review-frame-set/([0-9a-f]{32})/([0-9a-f]{64})/(\d{1,9})/(\d{1,9})/(\d{1,4}(?:,\d{1,4}){0,7})', path)
    if review or frame or frame_set:
        if center is None:
            raise ValueError('이 작업대에 OMX 학습 실행기가 연결되지 않았습니다.')
        match = review or frame or frame_set
        prepared = _registered(workspace, match[1])
        if frame_set:
            handler.send(center.review_frame_set(prepared, match[2], int(match[3]), int(match[4]),
                                                [int(value) for value in match[5].split(',')]))
        elif frame:
            handler.send(center.review_frame(prepared, match[2], *map(int, match.groups()[2:])), mime='image/jpeg')
        else:
            handler.send(center.review(prepared))
        return True
    match = re.fullmatch(PREFIX + r'/artifact/([0-9a-f-]{36})', path)
    if match:
        if center is None:
            raise ValueError('이 작업대에 OMX 학습 실행기가 연결되지 않았습니다.')
        handler.send(center.artifact(match[1]), mime='application/zip')
        return True
    if path != PREFIX:
        return False
    handler.send(center.snapshot() if center else {'datasets': [], 'runs': [], 'methods': {},
                                                 'status': 'not_configured'})
    return True


def post(handler, path, body, center, workspace=None):
    if not path.startswith(PREFIX + '/'):
        return False
    if center is None:
        raise ValueError('이 작업대에 OMX 학습 실행기가 연결되지 않았습니다.')
    if path == PREFIX + '/profile':
        handler.send(center.profiles.save(body, getattr(handler, 'learning_principal', None)))
        return True
    if path in (PREFIX + '/export', PREFIX + '/review'):
        prepared = _registered(workspace, body.get('prepared_id'))
        if path.endswith('/review'):
            actor = getattr(handler, 'learning_principal', None)
            if actor:
                body = dict(body, reviewer=actor['user_id'])
            handler.send(center.save_review(body, prepared, actor))
            return True
        handler.send(center.start_export(body, prepared))
        return True
    name = {PREFIX + '/upload': 'upload',
            PREFIX + '/publish': 'publish',
            PREFIX + '/run': 'start',
            PREFIX + '/online-run': 'start_online',
            PREFIX + '/experience': 'experience',
            PREFIX + '/stop': 'stop'}.get(path)
    if name is None:
        return False
    handler.send(getattr(center, name)(body))
    return True
