"""Account-protected World experiment routes in the Learning application."""

PREFIX = '/api/learning/world-experiments'


def _principal(handler, collaboration, capability):
    principal = getattr(handler, 'learning_principal', None)
    if collaboration is None or principal is None:
        raise PermissionError('World experiments require an authenticated Learning session')
    collaboration.accounts.require(principal, capability)
    return principal


def get(handler, path, center, collaboration):
    if path != PREFIX:
        return False
    principal = _principal(handler, collaboration, 'view')
    snapshot = center.world_experiment() if center is not None else {'preset': None, 'runs': []}
    handler.send(dict(snapshot, can_manage='manage' in principal['capabilities']))
    return True


def post(handler, path, body, center, collaboration):
    operation = {PREFIX + '/start': 'start_world_experiment',
                 PREFIX + '/stop': 'stop_world_experiment'}.get(path)
    if operation is None:
        return False
    _principal(handler, collaboration, 'manage')
    if center is None:
        handler.send({'error': 'World 실험 실행기가 연결되지 않았습니다.'}, 503)
    else:
        handler.send(getattr(center, operation)(body))
    return True
