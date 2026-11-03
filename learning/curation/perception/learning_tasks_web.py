"""Common learning metadata; enclosing review app owns auth, CSRF and origin checks."""
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import sim_web

STATIC = Path(__file__).with_name('review_app_web')


def get(handler, path, tasks, center, token, sim_runs=None):
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
                          runs=snapshot.get('runs', []), methods=snapshot.get('methods', {}),
                          sim_configured=sim_runs is not None, physical_learning_verified=False))
    elif path == '/api/learning/tasks/export':
        query = parse_qs(urlparse(handler.path).query, strict_parsing=True, keep_blank_values=True)
        if set(query) != {'id'} or len(query['id']) != 1:
            raise ValueError('one task identity required')
        handler.send(tasks.export_task(query['id'][0]))
    else:
        return False
    return True


def post(handler, path, body, tasks, center, collaboration, sim_runs=None):
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
    elif path == '/api/learning/tasks/sim-context':
        if (set(body) != {'task_id', 'task_revision', 'run_id'}
                or not isinstance(body['run_id'], str) or not re.fullmatch(sim_web.ID, body['run_id'])):
            raise ValueError('task identity, revision and SIM run identity required')
        if sim_runs is None:
            handler.send({'error': 'SIM 실행 연결이 설정되지 않았습니다.'}, 503)
            return True
        try:
            row = sim_runs.call({'action': 'status', 'run_id': body['run_id']})
        except (ValueError, OSError):
            handler.send({'error': 'SIM 실행 연결을 확인한 뒤 다시 등록하세요.'}, 503)
            return True
        if (not isinstance(row, dict) or row.get('run_id') != body['run_id']
                or row.get('status') not in ('SUCCEEDED', 'FAILED', 'STOPPED')
                or row.get('snapshot') != 'FINAL'
                or type(row.get('revision')) is not int or row['revision'] < 0
                or not isinstance(row.get('input_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', row['input_sha256'])
                or not isinstance(row.get('input'), dict)
                or row['input'].get('source_sha') != sim_runs.source_sha
                or not isinstance(row.get('result'), dict)
                or row['result'].get('status') != row['status']):
            handler.send({'error': '종료된 SIM 기록의 식별자·출처·결과를 확인하세요.'}, 502)
            return True
        result = tasks.attach_sim_context(body, sim_web.public(row), actor)
    else:
        return False
    handler.send(result)
    return True
