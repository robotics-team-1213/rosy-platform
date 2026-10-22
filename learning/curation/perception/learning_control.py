"""Private owner binding to one signed pipeline unit; never a data admission."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
from learning_pipeline import snapshot


class ControlConflict(ValueError):
    pass


def _bytes(path, limit=65536):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('학습 제어 binding은 일반 파일이어야 합니다.')
    if path.stat().st_size > limit:
        raise ValueError('학습 제어 파일이 너무 큽니다.')
    return path.read_bytes()


class Control:
    def __init__(self, file, workspace_id, *, home=None, runner=None):
        self.file = Path(file).absolute()
        self.home = Path.home() if home is None else Path(home)
        self.runner = subprocess.run if runner is None else runner
        self.lock = threading.RLock()
        raw = _bytes(self.file)
        binding = json.loads(raw)
        expected = {'schema', 'workspace_id', 'service', 'config_path', 'out_path'}
        if (set(binding) != expected or binding['schema'] != 'rosy.learning.control/1'
                or binding['workspace_id'] != workspace_id
                or not isinstance(binding['service'], str)
                or not re.fullmatch(r'rosy-review-pipeline(?:-[a-z0-9]{1,32})?\.service', binding['service'])):
            raise ValueError('이 작업대의 소유 학습 실행기 binding이 아닙니다.')
        self.service = binding['service']; self.timer = self.service.replace('.service', '.timer')
        self.config = Path(binding['config_path']); self.out = Path(binding['out_path'])
        for path in (self.config, self.out):
            if (not path.is_absolute() or any(c.isspace() for c in str(path))
                    or any(p.is_symlink() for p in (path, *path.parents))):
                raise ValueError('학습 실행 경로는 링크 없는 절대 경로여야 합니다.')
        config_raw = _bytes(self.config)
        config = json.loads(config_raw)
        if config['cycle']['authority']['workspace_id'] != workspace_id or not self.out.is_dir():
            raise ValueError('학습 설정과 결과 폴더의 작업대가 다릅니다.')
        self.max_attempts = config['cycle']['max_attempts']
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError('학습 시도 한도가 필요합니다.')
        units = self.home / '.config/systemd/user'
        self.unit_files = {name: units / name for name in (self.service, self.timer)}
        self.command = (f'{self.home}/rosy-ml/.venv/bin/python -I '
            f'{self.home}/.local/lib/rosy-model-code/rosy_model_code.py '
            f'--config {self.home}/.config/rosy/model-code.json exec training/review_pipeline.py '
            f'{self.config} --out {self.out} --once')
        service_raw = _bytes(self.unit_files[self.service])
        commands = [line.partition('=')[2].replace('%h', str(self.home))
                    for line in service_raw.decode().splitlines() if line.startswith('ExecStart=')]
        if commands != [self.command]:
            raise ValueError('서비스가 고정 서명 실행기와 소유 config/out을 사용하지 않습니다.')
        timer_raw = _bytes(self.unit_files[self.timer])
        targets = [line.partition('=')[2] for line in timer_raw.decode().splitlines() if line.startswith('Unit=')]
        if targets and targets != [self.service]:
            raise ValueError('자동 확인 타이머의 실행 대상이 다릅니다.')
        self.pinned = {self.file: raw, self.config: config_raw,
                       self.unit_files[self.service]: service_raw, self.unit_files[self.timer]: timer_raw}

    def _run(self, *args):
        try:
            result = self.runner(['systemctl', '--user', *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('학습 실행 서비스에 연결할 수 없습니다.') from exc
        if result.returncode:
            raise ValueError('학습 서비스 요청이 실패했습니다. 서비스 로그를 확인하세요.')
        return result.stdout

    def _show(self, unit):
        raw = self._run('show', unit, '--property=ActiveState,SubState,Result,ExecMainStatus,InvocationID,'
            'UnitFileState,FragmentPath,DropInPaths,Triggers,ExecStart,KillMode,ExecStartPre,ExecStartPost,ExecStop,ExecStopPost')
        value = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        if value.get('FragmentPath') != str(self.unit_files[unit]) or value.get('DropInPaths'):
            raise ValueError('실제 학습 서비스 binding이 변경되었습니다.')
        if unit == self.service:
            command = value.get('ExecStart', '').partition('argv[]=')[2].partition(' ;')[0].strip()
            if value.get('ExecStart', '').count('argv[]=') != 1 or command != self.command:
                raise ValueError('적재된 서비스가 소유 서명 실행기와 다릅니다.')
            if (value.get('KillMode') != 'control-group' or
                    any(value.get(key) for key in ('ExecStartPre', 'ExecStartPost', 'ExecStop', 'ExecStopPost'))):
                raise ValueError('학습 중지는 추가 명령 없이 소유 control group만 종료해야 합니다.')
        elif value.get('Triggers') != self.service:
            raise ValueError('적재된 타이머의 실행 대상이 다릅니다.')
        return value

    def _snapshot(self):
        for file, raw in self.pinned.items():
            if _bytes(file) != raw:
                raise ValueError('학습 제어 binding이 변경되었습니다. 운영 설정을 다시 연결하세요.')
        service, timer = self._show(self.service), self._show(self.timer)
        active = service['ActiveState'] in ('active', 'activating', 'deactivating', 'reloading')
        automatic = timer['ActiveState'] == 'active'
        state = self.out / 'state.json'
        # shortcut: bound ledger reads to 16 MiB; use a compact projection for larger histories.
        ledger_error = None
        try:
            ledger = json.loads(_bytes(state, 16 * 1024 * 1024)) if state.exists() else {}
            evidence = snapshot(ledger)
            cycles = ledger.get('cycles', {})
            pipeline = ledger.get('review_autobuild', {})
            keys = pipeline.get('cycle_keys')
            if keys is not None and (not isinstance(keys, list) or not all(isinstance(key, str) and key for key in keys)):
                raise ValueError('invalid current cycle references')
            rows = [cycles.get(key, {'status': 'pending', 'attempts': 0}) for key in keys] if keys else list(cycles.values())
            retry = pipeline.get('status') == 'held' or not rows or any(row.get('status') in ('pending', 'retry', 'running')
                and type(row.get('attempts')) is int and row['attempts'] < self.max_attempts for row in rows)
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            retry = False
            evidence = None
            ledger_error = '학습 실행 기록을 읽지 못했습니다. 중지는 가능하며 재시도 전에 기록을 확인하세요.'
        reasons = {'start': '실행 중이거나 자동 확인이 이미 켜져 있습니다.',
                   'stop': '현재 실행기와 자동 확인이 모두 중지되어 있습니다.',
                   'retry': '완료·품질 거절·시도 한도 소진 작업은 재시도할 수 없습니다.'}
        if active: reasons['retry'] = '실행기를 중지하거나 현재 처리가 끝난 뒤 재시도하세요.'
        if ledger_error: reasons.update(start=ledger_error, retry=ledger_error)
        result = dict(available=True, out_path=str(self.out), automatic=automatic, active=active,
            state='stopping' if service['ActiveState'] == 'deactivating' else
                  'running' if active else 'waiting' if automatic else 'stopped',
            can_start=not active and not automatic and not ledger_error, can_stop=active or automatic,
            can_retry=not active and retry, reasons=reasons, error=ledger_error, pipeline=evidence)
        result['version'] = hashlib.sha256(json.dumps({'service': {k: service.get(k) for k in
            ('ActiveState', 'SubState', 'Result', 'ExecMainStatus', 'InvocationID')},
            'automatic': automatic, 'retry': retry, 'ledger_valid': not ledger_error}, sort_keys=True).encode()).hexdigest()
        return result

    def status(self):
        with self.lock:
            try:
                return self._snapshot()
            except (ValueError, KeyError, TypeError, OSError) as exc:
                return dict(available=False, out_path=str(self.out), active=False, automatic=False,
                    can_start=False, can_stop=False, can_retry=False, error=str(exc), version=None)

    def action(self, body):
        if (set(body) != {'action', 'version'} or body['action'] not in ('start', 'stop', 'retry')
                or not isinstance(body['version'], str) or not re.fullmatch(r'[0-9a-f]{64}', body['version'])):
            raise ValueError('학습 제어 요청은 action과 현재 version만 받습니다.')
        with self.lock:
            current = self._snapshot()
            if body['version'] != current['version']:
                raise ControlConflict('실행 상태가 바뀌었습니다. 최신 상태를 확인하세요.')
            action = body['action']
            if not current['can_' + action]:
                raise ValueError(current['reasons'][action])
            if action == 'start':
                self._run('enable', '--now', self.timer)
                self._run('start', '--no-block', self.service)
            elif action == 'stop':
                self._run('disable', '--now', self.timer)
                self._run('stop', '--no-block', self.service)
            else:
                self._run('start', '--no-block', self.service)
            return self._snapshot()
