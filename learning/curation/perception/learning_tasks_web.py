"""Common learning metadata; enclosing review app owns auth, CSRF and origin checks."""
from pathlib import Path
from datetime import datetime, timezone
import re
import sim_web
from urllib.parse import parse_qs, urlparse

import owner_robots
from learning_workflow import method_catalog, project_task
from learning_native_catalog import list_inputs, bind_summaries

STATIC = Path(__file__).with_name('review_app_web')


def _task(tasks, uid):
    found = next((task for task in tasks.snapshot()['tasks'] if task['id'] == uid), None)
    if found is None:
        raise ValueError('registered project learning task required')
    return found


def get(handler, path, tasks, center, token, workspace=None, native_cache=None, sim_runs=None, owners=None):
    native_cache = native_cache if native_cache is not None else {}
    if path in ('/learning/tasks', '/workflow.js', '/workflow.css', '/learning/tasks/manage', '/tasks.js',
                '/learning/public', '/public-learning.js', '/public-learning.css',
                '/learning/imitate', '/imitate.js', '/imitate.css'):
        name = {'/learning/tasks': 'workflow.html', '/workflow.js': 'workflow.js',
                '/learning/tasks/manage': 'tasks.html', '/tasks.js': 'tasks.js', '/workflow.css': 'workflow.css',
                '/learning/public': 'public-learning.html', '/public-learning.js': 'public-learning.js',
                '/public-learning.css': 'public-learning.css', '/learning/imitate':'imitate.html',
                '/imitate.js':'imitate.js', '/imitate.css':'imitate.css'}[path]
        mime = ('text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html') + '; charset=utf-8'
        handler.send((STATIC / name).read_bytes(), mime=mime)
    elif path == '/api/learning/tasks':
        snapshot = center.snapshot() if center else {}
        profiles = center.profiles.list() if center and hasattr(center, 'profiles') else []
        state = tasks.snapshot()
        bindings = tasks.native_bindings()
        inputs = bind_summaries(native_cache.get('inputs', []), bindings)
        methods = snapshot.get('methods', {})
        host = getattr(center, 'host_id', None)
        workflows = {task['id']: project_task(task, inputs, snapshot.get('runs', []), methods, host)
                     for task in state['tasks']}
        handler.send(dict(state, project_id=tasks.project_id, token=token,
                          host_id=getattr(center, 'host_id', None), center_configured=center is not None,
                          profiles=profiles, datasets=snapshot.get('datasets', []),
                          runs=snapshot.get('runs', []), methods=methods,
                          sim_configured=sim_runs is not None, physical_learning_verified=False,
                          native_inputs=inputs, native_inputs_checked_at=native_cache.get('checked_at'),
                          native_inputs_cached=True, capabilities=method_catalog(methods), workflows=workflows))
    elif path == '/api/learning/tasks/native-inputs':
        inputs = list_inputs(workspace, center, tasks.native_bindings())
        native_cache['inputs'] = inputs
        native_cache['checked_at'] = datetime.now(timezone.utc).isoformat()
        handler.send(dict(native_inputs=inputs, checked_at=native_cache['checked_at']))
    elif path == '/api/learning/tasks/recording-card':
        query = parse_qs(urlparse(handler.path).query, strict_parsing=True, keep_blank_values=True)
        if set(query) != {'task_id'} or len(query['task_id']) != 1:
            raise ValueError('one registered task identity required')
        task = _task(tasks, query['task_id'][0])
        handler.send(dict(task_id=task['id'], scope='preparation_only', device_execution=False,
            requires_owner_preflight=True, task_card=None,
            required_options=['root_prefix', 'episode_time_s', 'reset_time_s', 'num_episodes']))
    elif path == '/api/learning/robot-candidates':
        handler.send(owner_robots.candidates(owners, (r['device_id'] for r in tasks.snapshot()['robots'])))
    elif path == '/api/learning/tasks/export':
        query = parse_qs(urlparse(handler.path).query, strict_parsing=True, keep_blank_values=True)
        if set(query) != {'id'} or len(query['id']) != 1:
            raise ValueError('one task identity required')
        handler.send(tasks.export_task(query['id'][0]))
    else:
        return False
    return True


def post(handler, path, body, tasks, center, collaboration, workspace=None, sim_runs=None, owners=None):
    actor = handler.learning_principal if collaboration else None
    if path == '/api/learning/robots' and isinstance(body, dict) and 'owner' in body:
        if set(body) != {'request_id', 'owner', 'device_id'} or body['owner'] != 'fleet':
            raise ValueError('owner registration takes only request identity, owner and device ID')
        stored = next((r for r in tasks.snapshot()['robots'] if r['id'] == body['request_id']), None)
        if stored is not None:   # replay after a lost reply; Fleet may have renamed the device since
            if stored['device_id'] != body['device_id'] or stored.get('owner', {}).get('source') != 'fleet':
                raise ValueError('learning request identity reused with changed content or actor')
            robot = {key: stored[key] for key in ('request_id', 'name', 'kind', 'model_revision', 'device_id')}
            handler.send(tasks.robot(robot, actor, stored['owner']))
            return True
        if owners is None:
            raise ValueError(owner_robots.REASONS['unconfigured'])
        # Fields come from a fresh owner read, never from the browser.
        row, checked_at = owners.confirm(body['device_id'])
        robot = {key: row[key] for key in ('name', 'kind', 'model_revision', 'device_id')}
        result = tasks.robot(dict(robot, request_id=body['request_id']), actor,
                             dict(source='fleet', checked_at=checked_at, listed_by=row['sources']))
    elif path == '/api/learning/robots':
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
    elif path == '/api/learning/tasks/native-input':
        if set(body) != {'task_id', 'prepared_id', 'source_revision', 'request_id'}:
            raise ValueError('fixed registered task and native source association required')
        if center is None or workspace is None:
            raise ValueError('registered native review workspace and center required')
        from omx_center_web import _registered
        from experiment_native import validate_source_profile
        prepared = _registered(workspace, body['prepared_id'])
        source = center.reviews.source(prepared)
        if source['fixture_only'] or source['source_revision'] != body['source_revision']:
            raise ValueError('current non-fixture native source required')
        task = _task(tasks, body['task_id'])
        profile = (task.get('profile') or {}).get('profile')
        if not profile:
            raise ValueError('task with a pinned OMX profile required')
        validate_source_profile(profile, source['inspection'], source['root'])
        result = tasks.bind_native(task['id'], prepared['id'], source['source_revision'],
            task['profile_revision'], [arm['id'] for arm in profile['arms']], actor,
            request_id=body['request_id'])
    elif path == '/api/learning/tasks/recording-card':
        if set(body) != {'task_id', 'record'}:
            raise ValueError('registered task and explicit recorder preparation required')
        from learning_recording_card import make_card
        task = _task(tasks, body['task_id'])
        if not task.get('runnable') or task.get('adapter') != 'omx':
            raise ValueError('native recording preparation requires an OMX task')
        card = make_card(task, body['record'])
        result = dict(card=card, filename=card['task_id']+'.json', device_execution=False,
                      requires_owner_preflight=True)
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
