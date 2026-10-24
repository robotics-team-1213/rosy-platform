"""Common learning metadata; enclosing review app owns auth, CSRF and origin checks."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).with_name('review_app_web')


def get(handler, path, tasks, center, token):
    if path in ('/learning/tasks', '/tasks.js'):
        name, mime = ('tasks.html', 'text/html; charset=utf-8') if path == '/learning/tasks' else (
            'tasks.js', 'text/javascript; charset=utf-8')
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif path == '/api/learning/tasks':
        snapshot = center.snapshot() if center else {}
        profiles = center.profiles.list() if center and hasattr(center, 'profiles') else []
        handler.send(dict(tasks.snapshot(), project_id=tasks.project_id, token=token,
                          host_id=getattr(center, 'host_id', None), center_configured=center is not None,
                          profiles=profiles, datasets=snapshot.get('datasets', []),
                          runs=snapshot.get('runs', []), methods=snapshot.get('methods', {})))
    elif path == '/api/learning/tasks/export':
        query = parse_qs(urlparse(handler.path).query, strict_parsing=True, keep_blank_values=True)
        if set(query) != {'id'} or len(query['id']) != 1:
            raise ValueError('one task identity required')
        handler.send(tasks.export_task(query['id'][0]))
    else:
        return False
    return True


def post(handler, path, body, tasks, center, collaboration):
    actor = handler.learning_principal if collaboration else None
    if path == '/api/learning/robots':
        result = tasks.robot(body, actor)
    elif path == '/api/learning/tasks':
        profile = None
        if 'profile_id' in body:
            if not center or not hasattr(center, 'profiles'):
                raise ValueError('configure a learning center and save its profile first')
            profile = center.profiles.get(body['profile_id'])
        result = tasks.task(body, actor, profile)
    elif path == '/api/learning/tasks/import':
        result = tasks.import_task(body, actor)
    else:
        return False
    handler.send(result)
    return True
