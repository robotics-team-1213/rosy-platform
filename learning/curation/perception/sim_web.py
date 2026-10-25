"""Existing Learning HTTP routes and a fixed, local JSON subprocess adapter."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

STATIC = Path(__file__).with_name('review_app_web')
PREFIX = '/api/learning/sim/'
ID = '[0-9a-f]{32}'
ARTIFACT_TYPES = {
    'import-report': 'application/json', 'contact-report': 'application/json',
    **{name: 'image/png' for name in (
        'pinky_initial', 'out_lift', 'conveyor_settle', 'back_lift', 'pinky_settle')},
}


class LocalRuns:
    def __init__(self, config_file, workspace_id):
        config = Path(config_file)
        info = config.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 65536 or config.resolve() != config):
            raise ValueError('Unsafe SIM operator configuration')
        value = json.loads(config.read_text(encoding='utf-8'))
        keys = {'workspace_id', 'source_sha', 'source_root', 'binding_file', 'binding_sha256', 'entry_sha256'}
        if (set(value) != keys or value['workspace_id'] != workspace_id
                or not re.fullmatch('[0-9a-f]{40}', value['source_sha'])
                or not re.fullmatch('[0-9a-f]{64}', value['entry_sha256'])
                or not re.fullmatch('[0-9a-f]{64}', value['binding_sha256'])):
            raise ValueError('SIM binding differs from this review workspace')
        self.source_sha = value['source_sha']
        self.source = Path(value['source_root'])
        self.binding = Path(value['binding_file'])
        self.entry = self.source / 'learning/envs/isaac/run_control.py'
        self.entry_sha256 = value['entry_sha256']
        self.binding_sha256 = value['binding_sha256']

    def call(self, payload):
        try:
            if (self.source.resolve() != self.source or self.binding.resolve() != self.binding
                    or self.entry.resolve() != self.entry
                    or hashlib.sha256(self.entry.read_bytes()).hexdigest() != self.entry_sha256):
                raise ValueError('Changed SIM source binding')
            raw_binding = self.binding.read_bytes()
            if hashlib.sha256(raw_binding).hexdigest() != self.binding_sha256:
                raise ValueError('Changed operator binding')
            binding = json.loads(raw_binding)
            if binding['source_sha'] != self.source_sha or binding['source_root'] != str(self.source):
                raise ValueError('Changed SIM source identity')
            sha = subprocess.run(['git', '-C', str(self.source), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, timeout=10, check=True).stdout.strip()
            clean = subprocess.run(['git', '-C', str(self.source), 'status', '--porcelain'],
                capture_output=True, text=True, timeout=10, check=True).stdout
            if sha != self.source_sha or clean:
                raise ValueError('Changed SIM checkout')
            env = {key: os.environ[key] for key in ('HOME', 'USER', 'LOGNAME', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS')
                   if key in os.environ}
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
            result = subprocess.run(['/usr/bin/python3', str(self.entry), '--binding', str(self.binding),
                '--expected-binding-sha256', self.binding_sha256],
                input=json.dumps(payload, allow_nan=False).encode(), capture_output=True,
                env=env, timeout=40, check=True)
            if len(result.stdout) > 2 * 1024 * 1024:
                raise ValueError('Oversized SIM response')
            return json.loads(result.stdout)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            raise ValueError('SIM 실행 연결을 확인하세요. 같은 run을 다시 조회하세요.') from None


def public(row):
    keys = ('run_id', 'request_id', 'parent_run_id', 'revision', 'status', 'phase',
            'input_sha256', 'created_at', 'updated_at', 'snapshot', 'cleanup')
    result = {key: row[key] for key in keys if key in row}
    inputs = row.get('input', {})
    result['input'] = {key: inputs[key] for key in ('scenario_id', 'source_sha', 'config',
                      'assets_sha256', 'verifier_sha256') if key in inputs}
    if row.get('error'):
        result['error'] = '실행 결과·소유권 확인이 필요합니다. 기존 run을 조회하세요.'
    if 'result' in row:
        allowed = ('status', 'stage', 'task_success', 'import_verified', 'completed_frames',
                   'exit_code', 'reason', 'cleanup', 'video_unavailable_reason', 'gpu')
        result['result'] = {key: row['result'][key] for key in allowed if key in row['result']}
    if 'artifacts' in row:
        result['artifacts'] = row['artifacts']
    return result


def get(handler, path, runs):
    if path in {'/learning/sim', '/sim.js'}:
        file = STATIC / ('sim.html' if path == '/learning/sim' else 'sim.js')
        handler.send(file.read_bytes(), mime=('text/html' if path == '/learning/sim' else 'text/javascript') + '; charset=utf-8')
    elif not path.startswith(PREFIX):
        return False
    elif runs is None:
        handler.send({'error': 'SIM 실행 연결이 설정되지 않았습니다.'}, 503)
    elif path == PREFIX + 'catalog':
        handler.send({'scenarios': runs.call({'action': 'catalog'}), 'source_sha': runs.source_sha})
    elif path == PREFIX + 'runs':
        handler.send({'runs': [public(row) for row in runs.call({'action': 'list'})]})
    elif match := re.fullmatch(PREFIX + 'runs/(' + ID + ')', path):
        handler.send(public(runs.call({'action': 'status', 'run_id': match[1]})))
    elif match := re.fullmatch(PREFIX + 'runs/(' + ID + ')/artifacts/(' + '|'.join(ARTIFACT_TYPES) + ')', path):
        blob = runs.call({'action': 'artifact', 'run_id': match[1], 'artifact_id': match[2]})
        media_type = ARTIFACT_TYPES[match[2]]
        if (blob['media_type'] != media_type or type(blob['bytes']) is not int
                or not 0 <= blob['bytes'] <= 1048576
                or len(blob['data_base64']) > 4 * ((blob['bytes'] + 2) // 3)):
            raise ValueError('SIM 증거 형식이 올바르지 않습니다.')
        raw = base64.b64decode(blob['data_base64'], validate=True)
        if len(raw) != blob['bytes'] or hashlib.sha256(raw).hexdigest() != blob['sha256']:
            raise ValueError('SIM 보고서 지문이 달라졌습니다.')
        handler.send(raw, mime=media_type + ('; charset=utf-8' if media_type == 'application/json' else ''))
    else:
        handler.send({'error': 'SIM 경로를 확인하세요.'}, 404)
    return True


def post(handler, path, body, runs, collaboration):
    if not path.startswith(PREFIX):
        return False
    if not collaboration:
        raise PermissionError('SIM control requires an authenticated project manager')
    collaboration.accounts.require(handler.learning_principal, 'manage')
    if runs is None:
        handler.send({'error': 'SIM 실행 연결이 설정되지 않았습니다.'}, 503)
        return True
    action = path.removeprefix(PREFIX)
    required = {'check': {'scenario_id', 'config'},
                'start': {'request_id', 'scenario_id', 'config', 'expected_input_sha256'},
                'stop': {'run_id', 'expected_revision'}}.get(action)
    optional = {'source_sha', 'parent_run_id'} if action == 'start' else {'source_sha'} if action == 'check' else set()
    if required is None or not required <= body.keys() or body.keys() - required - optional:
        raise ValueError('SIM 요청 필드를 확인하세요.')
    if 'source_sha' in body and body['source_sha'] != runs.source_sha:
        raise ValueError('SIM 실행 소스가 바뀌었습니다. 조건을 다시 확인하세요.')
    if action == 'stop':
        if (not re.fullmatch(ID, str(body['run_id'])) or type(body['expected_revision']) is not int
                or body['expected_revision'] < 0):
            raise ValueError('SIM run과 현재 revision이 필요합니다.')
        payload = dict(body, action='stop')
    else:
        value = dict(body, source_sha=runs.source_sha)
        payload = dict(value, action='check') if action == 'check' else {'action': 'start', 'request': value}
    row = runs.call(payload)
    handler.send(row if action == 'check' else public(row))
    return True
