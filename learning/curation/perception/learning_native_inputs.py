"""Append-only native source associations and standalone worker lineage checks."""
from datetime import datetime, timezone
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import re
import uuid


@lru_cache(maxsize=1)
def _api():
    spec = importlib.util.spec_from_file_location('rosy_native_task_contract',
        Path(__file__).with_name('learning_tasks.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepared(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError('registered native prepared identity required')
    return value


def _context(store, db, task_id, profile_revision, component_ids):
    row, task = store._get(db, task_id, 'task')
    robots = store._robots(db)
    revision, _, runnable = store._task(json.loads(row[1]), task['profile'], robots)
    if revision != task['revision']:
        raise ValueError('immutable native task revision changed')
    if not runnable or task['profile_revision'] != profile_revision:
        raise ValueError('runnable native task and exact profile revision required')
    if component_ids != [p['component_id'] for p in task['participants']]:
        raise ValueError('native source requires the full ordered task layout')
    records = [robots[uid] for uid in dict.fromkeys(p['robot_id'] for p in task['participants'])]
    return task, records


def _reference(task, records):
    return dict(task_id=task['id'], task_revision=task['revision'], project_id=task['project_id'],
        profile_id=task['profile_id'], profile_revision=task['profile_revision'],
        task_participants=task['participants'],
        component_ids=[p['component_id'] for p in task['participants']],
        robots=[{key: robot[key] for key in ('id', 'kind', 'model_revision', 'device_id', 'revision')}
                for robot in records], task=task, robot_records=records)


def check_binding(binding, *, resolved=False):
    """Recompute task/profile/robot semantics without a live review database."""
    api = _api()
    required = {'attachment_kind', 'task_id', 'task_revision', 'project_id', 'prepared_id',
        'source_revision', 'profile_id', 'profile_revision', 'task_participants', 'component_ids',
        'robots', 'task', 'robot_records', 'request_id', 'created_by', 'created_at'}
    if resolved:
        required |= {'compute_host', 'participants'}
    api._fields(binding, required)
    if binding['attachment_kind'] != 'historical_native_attachment':
        raise ValueError('explicit historical native association required')
    _prepared(binding['prepared_id'])
    api._revision(binding['source_revision'])
    api._uuid(binding['request_id'])
    api._text(binding['created_at'], 128)
    creator = binding['created_by']
    api._fields(creator, ('kind', 'id'))
    api._text(creator['id'], 128)
    if creator['kind'] not in ('authenticated', 'local_unverified'):
        raise ValueError('native association creator required')
    store = object.__new__(api.Tasks)
    store.project_id = api._identifier(binding['project_id'])
    records = binding['robot_records']
    if not isinstance(records, list) or not 1 <= len(records) <= 32:
        raise ValueError('bounded native task robot snapshots required')
    robots = {}
    for record in records:
        fields = {'request_id', 'name', 'kind', 'model_revision', 'device_id'}
        api._fields(record, fields | {'id', 'project_id', 'revision', 'created_by', 'created_at', 'device_verified'})
        body = {key: record[key] for key in fields}
        if (record['id'] != body['request_id'] or record['project_id'] != store.project_id
                or record['revision'] != store._robot(body) or record['device_verified'] is not False
                or record['id'] in robots):
            raise ValueError('native task robot identity or revision changed')
        robots[record['id']] = record
    task = binding['task']
    fields = {'request_id', 'name', 'objective', 'success', 'failure', 'reset',
              'mode', 'participants', 'adapter', 'profile_id'}
    api._fields(task, fields | {'id', 'project_id', 'revision', 'created_by', 'created_at',
                              'profile', 'profile_revision', 'runnable', 'blocked_reason'})
    body = {key: task[key] for key in fields}
    revision, pinned, runnable = store._task(body, task['profile'], robots)
    if (task['id'] != body['request_id'] or task['project_id'] != store.project_id
            or task['revision'] != revision or not runnable or task['runnable'] is not True
            or task['profile_revision'] != pinned['revision'] or task['blocked_reason'] is not None
            or list(robots) != list(dict.fromkeys(p['robot_id'] for p in task['participants']))):
        raise ValueError('native task immutable semantic snapshot changed')
    if any(binding[key] != value for key, value in _reference(task, records).items()):
        raise ValueError('native task source/profile/participant lineage changed')
    if resolved and (binding['compute_host'] not in ('model', 'ai')
                     or binding['participants'] != task['participants']):
        raise ValueError('trusted native task host and full participants required')
    return binding


def _stored(row):
    binding = check_binding(json.loads(row[3]))
    if tuple(binding[key] for key in ('prepared_id', 'source_revision', 'request_id')) != tuple(row[:3]):
        raise ValueError('stored native association indexed identity changed')
    return binding


def bind_native(store, task_id, prepared_id, source_revision, profile_revision,
                component_ids, actor, request_id=None):
    api = _api()
    _prepared(prepared_id)
    api._revision(source_revision)
    api._revision(profile_revision)
    creator = api._creator(actor)
    if request_id is None:
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, api._json(
            [store.project_id, task_id, prepared_id, source_revision, profile_revision, component_ids, creator])))
    api._uuid(request_id)
    with store._db() as db:
        task, records = _context(store, db, task_id, profile_revision, component_ids)
        binding = dict(_reference(task, records), attachment_kind='historical_native_attachment',
            prepared_id=prepared_id, source_revision=source_revision, request_id=request_id,
            created_by=creator, created_at=datetime.now(timezone.utc).isoformat())
        prior = db.execute('SELECT prepared_id,source_revision,request_id,binding FROM learning_task_native_inputs '
            'WHERE prepared_id=? OR source_revision=? OR request_id=?',
            (prepared_id, source_revision, request_id)).fetchall()
        for row in prior:
            saved = _stored(row)
            if any(saved[key] != value for key, value in binding.items() if key != 'created_at'):
                raise ValueError('native source identity, revision or request already bound with different content or actor')
        if prior:
            return _stored(prior[0])
        check_binding(binding)
        db.execute('INSERT INTO learning_task_native_inputs VALUES (?,?,?,?)',
                   (prepared_id, source_revision, request_id, api._json(binding)))
        return json.loads(api._json(binding))


def native_bindings(store, task_id=None):
    if task_id is not None:
        _api()._uuid(task_id)
    with store._db() as db:
        result = [_stored(row) for row in db.execute(
            'SELECT prepared_id,source_revision,request_id,binding FROM learning_task_native_inputs ORDER BY rowid')]
        for binding in result:
            task, records = _context(store, db, binding['task_id'], binding['profile_revision'], binding['component_ids'])
            if any(binding[key] != value for key, value in _reference(task, records).items()):
                raise ValueError('stored native source task reference changed')
        return [binding for binding in result if task_id is None or binding['task_id'] == task_id]


def resolve_native(store, task_id, prepared_id, source_revision, profile_revision, component_ids, host_id):
    if host_id not in ('model', 'ai'):
        raise ValueError('trusted model or ai native host identity required')
    _prepared(prepared_id)
    _api()._revision(source_revision)
    _api()._revision(profile_revision)
    bindings = native_bindings(store, task_id)
    for binding in bindings:
        if (binding['prepared_id'] == prepared_id and binding['source_revision'] == source_revision
                and binding['profile_revision'] == profile_revision and binding['component_ids'] == component_ids):
            return check_binding(dict(binding, compute_host=host_id,
                                      participants=binding['task_participants']), resolved=True)
    raise ValueError('explicit matching native task source association required')
