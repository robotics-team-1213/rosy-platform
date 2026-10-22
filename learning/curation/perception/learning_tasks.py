"""Project-scoped immutable learning references, without device or execution authority."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid


def _json(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False)
        encoded.encode('utf-8')
        return encoded
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise ValueError('JSON learning metadata required') from exc


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value, limit=1024):
    if (not isinstance(value, str) or not 1 <= len(value) <= limit
            or value != value.strip()
            or any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('bounded plain learning metadata required')
    return value


def _identifier(value):
    _text(value, 128)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', value):
        raise ValueError('learning identity must not contain paths or commands')
    return value


def _uuid(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError('canonical UUID required')
    except (ValueError, AttributeError) as exc:
        raise ValueError('canonical UUID required') from exc
    return value


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA256 revision required')
    return value


def _fields(body, required, optional=()):
    if (not isinstance(body, dict) or not set(required) <= set(body)
            or set(body) - set(required) - set(optional)):
        raise ValueError('fixed learning metadata request fields required')
    if len(_json(body).encode('utf-8')) > 1024 * 1024:
        raise ValueError('bounded learning metadata must not exceed 1 MiB')


def _creator(actor):
    if not isinstance(actor, dict):
        raise ValueError('authenticated learning creator required')
    return {'kind': 'authenticated', 'id': _text(actor.get('user_id'), 128)}


class Tasks:
    def __init__(self, db_path, project_id):
        self.db_path = db_path
        self.project_id = _identifier(project_id)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS learning_task_project ('
                       'singleton INTEGER PRIMARY KEY CHECK(singleton=1), project_id TEXT NOT NULL)')
            row = db.execute('SELECT project_id FROM learning_task_project WHERE singleton=1').fetchone()
            if row is not None and row[0] != self.project_id:
                raise ValueError('learning database belongs to another project')
            db.execute('INSERT OR IGNORE INTO learning_task_project VALUES (1,?)', (self.project_id,))
            db.execute('CREATE TABLE IF NOT EXISTS learning_task_records ('
                       'id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, '
                       'semantic TEXT NOT NULL, creator TEXT NOT NULL, document TEXT NOT NULL)')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS learning_robot_device '
                       "ON learning_task_records(json_extract(body,'$.device_id')) WHERE kind='robot'")
            db.execute('CREATE TABLE IF NOT EXISTS learning_task_datasets ('
                       'dataset_id TEXT PRIMARY KEY, dataset_revision TEXT UNIQUE NOT NULL, binding TEXT NOT NULL)')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _robot(self, body):
        _fields(body, ('request_id', 'name', 'kind', 'model_revision', 'device_id'))
        _uuid(body['request_id'])
        _text(body['name'])
        for field in ('kind', 'model_revision', 'device_id'):
            _identifier(body[field])
        return _hash({'project_id': self.project_id, 'robot': body})

    def _get(self, db, uid, kind):
        row = db.execute('SELECT kind,body,semantic,creator,document FROM learning_task_records WHERE id=?',
                         (_uuid(uid),)).fetchone()
        if row is None or row[0] != kind:
            raise ValueError('learning reference does not exist in this project')
        record = json.loads(row[4])
        body = json.loads(row[1])
        if (record.get('project_id') != self.project_id or record.get('id') != uid
                or record.get('revision') != row[2]
                or any(record.get(key) != value for key, value in body.items())
                or (kind == 'robot' and self._robot(body) != row[2])):
            raise ValueError('learning reference project or identity changed')
        return row, record

    def _task(self, body, profile, robots):
        _fields(body, ('request_id', 'name', 'objective', 'success', 'failure', 'reset',
                       'mode', 'participants', 'adapter'), ('profile_id',))
        _uuid(body['request_id'])
        for field in ('name', 'objective', 'success', 'failure', 'reset'):
            _text(body[field])
        _identifier(body['adapter'])
        if body['mode'] not in ('independent', 'cooperative'):
            raise ValueError('independent or cooperative task mode required')
        participants = body['participants']
        if not isinstance(participants, list) or not 1 <= len(participants) <= 32:
            raise ValueError('bounded task participants required')
        components, roles, identities = [], set(), set()
        for participant in participants:
            _fields(participant, ('robot_id', 'component_id', 'role'))
            robot_id = _uuid(participant['robot_id'])
            component = _identifier(participant['component_id'])
            role = _identifier(participant['role'])
            robot = robots.get(robot_id)
            if robot is None or robot['project_id'] != self.project_id:
                raise ValueError('participant robot does not exist in this project')
            identity = (robot['device_id'], component)
            if identity in identities or component in components or role in roles:
                raise ValueError('duplicate participant device/component or role')
            identities.add(identity)
            roles.add(role)
            components.append(component)
        if body['mode'] == 'cooperative' and len(components) < 2:
            raise ValueError('cooperative task requires at least two components')
        runnable = body['adapter'] == 'omx' and all(
            robots[p['robot_id']]['kind'] == 'omx' for p in participants)
        pinned = None
        if runnable:
            _uuid(body.get('profile_id'))
            _fields(profile, ('id', 'revision', 'profile'),
                    ('parent_id', 'created_at', 'created_by', 'physical_setup_verified', 'policy_activation'))
            if profile['id'] != body['profile_id']:
                raise ValueError('stored profile identity differs from task')
            _revision(profile['revision'])
            content = profile['profile']
            if (not isinstance(content, dict) or _hash(content) != profile['revision']
                    or content.get('mode') != body['mode'] or not isinstance(content.get('arms'), list)
                    or [arm.get('id') if isinstance(arm, dict) else None for arm in content['arms']] != components):
                raise ValueError('stored profile revision, mode or ordered components differ from task')
            pinned = {key: profile[key] for key in ('id', 'revision', 'profile')}
        elif profile is not None or 'profile_id' in body:
            raise ValueError('unsupported learning adapter cannot bind an OMX profile')
        semantic = dict(project_id=self.project_id, task=body, profile=pinned,
            robots=[robots[p['robot_id']]['revision'] for p in participants])
        return _hash(semantic), pinned, runnable

    def _save(self, db, kind, body, semantic, actor, extras=None, importing=False):
        creator = _creator(actor)
        uid = body['request_id']
        row = db.execute('SELECT kind,body,semantic,creator,document FROM learning_task_records WHERE id=?',
                         (uid,)).fetchone()
        if row:
            if (row[0] != kind or row[1] != _json(body) or row[2] != semantic
                    or (not importing and row[3] != _json(creator))):
                raise ValueError('learning request identity reused with changed content or actor')
            return self._get(db, uid, kind)[1]
        record = dict(body, id=uid, project_id=self.project_id, revision=semantic,
                      created_by=creator, created_at=datetime.now(timezone.utc).isoformat())
        record.update(extras or {})
        try:
            db.execute('INSERT INTO learning_task_records VALUES (?,?,?,?,?,?)',
                (uid, kind, _json(body), semantic, _json(creator), _json(record)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('duplicate learning device reference') from exc
        return json.loads(_json(record))

    def robot(self, body, actor):
        semantic = self._robot(body)
        with self._db() as db:
            return self._save(db, 'robot', body, semantic, actor, {'device_verified': False})

    def _robots(self, db):
        return {record['id']: record for _, record in (self._get(db, row[0], 'robot')
            for row in db.execute("SELECT id FROM learning_task_records WHERE kind='robot' ORDER BY rowid"))}

    def _save_task(self, db, body, actor, profile, importing=False):
        revision, pinned, runnable = self._task(body, profile, self._robots(db))
        return self._save(db, 'task', body, revision, actor,
            dict(profile=pinned, profile_revision=pinned['revision'] if pinned else None,
                 runnable=runnable, blocked_reason=None if runnable else 'Learning adapter is not supported'),
            importing=importing)

    def task(self, body, actor, profile=None):
        with self._db() as db:
            return self._save_task(db, body, actor, profile)

    def snapshot(self):
        with self._db() as db:
            return dict(robots=list(self._robots(db).values()), tasks=[self._get(db, row[0], 'task')[1]
                for row in db.execute("SELECT id FROM learning_task_records WHERE kind='task' ORDER BY rowid")])

    def resolve(self, task_id, dataset_id, dataset_revision, profile_revision, component_ids, host_id):
        _identifier(dataset_id)
        _revision(dataset_revision)
        _revision(profile_revision)
        if host_id not in ('model', 'ai'):
            raise ValueError('trusted model or ai host identity required')
        with self._db() as db:
            row, task = self._get(db, task_id, 'task')
            robots = self._robots(db)
            revision, _, _ = self._task(json.loads(row[1]), task['profile'], robots)
            if revision != task['revision']:
                raise ValueError('immutable task semantic revision changed')
            if not task['runnable'] or task['profile_revision'] != profile_revision:
                raise ValueError('runnable task and exact profile revision required')
            all_components = [p['component_id'] for p in task['participants']]
            if (not isinstance(component_ids, list)
                    or (task['mode'] == 'cooperative' and component_ids != all_components)
                    or (task['mode'] == 'independent' and (len(component_ids) != 1
                        or component_ids[0] not in all_components))):
                raise ValueError('selected ordered component group differs from task')
            dataset = dict(task_id=task_id, task_revision=task['revision'],
                project_id=self.project_id, dataset_id=dataset_id, dataset_revision=dataset_revision,
                profile_id=task['profile_id'], profile_revision=profile_revision,
                task_participants=task['participants'],
                robots=[{key: robots[uid][key] for key in
                    ('id', 'kind', 'model_revision', 'device_id', 'revision')}
                    for uid in dict.fromkeys(p['robot_id'] for p in task['participants'])])
            encoded = _json(dataset)
            prior = db.execute('SELECT binding FROM learning_task_datasets '
                'WHERE dataset_id=? OR dataset_revision=?', (dataset_id, dataset_revision)).fetchall()
            if any(item[0] != encoded for item in prior):
                raise ValueError('dataset identity or revision is already bound to another task or revision')
            if not prior:
                db.execute('INSERT INTO learning_task_datasets VALUES (?,?,?)',
                           (dataset_id, dataset_revision, encoded))
            return dict(dataset, compute_host=host_id, component_ids=list(component_ids),
                participants=[p for p in task['participants'] if p['component_id'] in component_ids])

    def export_task(self, task_id):
        with self._db() as db:
            row, task = self._get(db, task_id, 'task')
            ids = list(dict.fromkeys(p['robot_id'] for p in task['participants']))
            robots = [json.loads(self._get(db, uid, 'robot')[0][1]) for uid in ids]
            package = dict(schema='rosy.learning.task-transfer/1', project_id=self.project_id,
                robots=robots, task=json.loads(row[1]), profile=task['profile'], task_revision=task['revision'])
            if len(_json(package).encode('utf-8')) > 1024 * 1024:
                raise ValueError('bounded task transfer must not exceed 1 MiB')
            return package

    def import_task(self, package, actor):
        _fields(package, ('schema', 'project_id', 'robots', 'task', 'profile', 'task_revision'))
        _creator(actor)
        if package['schema'] != 'rosy.learning.task-transfer/1' or package['project_id'] != self.project_id:
            raise ValueError('task transfer schema or project differs')
        if not isinstance(package['robots'], list) or not 1 <= len(package['robots']) <= 32:
            raise ValueError('bounded task transfer robot references required')
        robots = {}
        for body in package['robots']:
            revision = self._robot(body)
            if body['request_id'] in robots or any(r['device_id'] == body['device_id'] for r in robots.values()):
                raise ValueError('duplicate task transfer robot or device identity')
            robots[body['request_id']] = dict(body, id=body['request_id'],
                                            project_id=self.project_id, revision=revision)
        revision, _, _ = self._task(package['task'], package['profile'], robots)
        if _revision(package['task_revision']) != revision:
            raise ValueError('task transfer semantic revision differs')
        if set(robots) != {p['robot_id'] for p in package['task']['participants']}:
            raise ValueError('task transfer includes unrelated robot references')
        with self._db() as db:
            for body in package['robots']:
                self._save(db, 'robot', body, robots[body['request_id']]['revision'], actor,
                           {'device_verified': False}, importing=True)
            return self._save_task(db, package['task'], actor, package['profile'], importing=True)
