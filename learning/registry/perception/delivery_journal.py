"""Private local lifecycle evidence; never device/task acceptance or authority.

Each attempt has its own exclusive JSONL file. A started attempt without a
finished record is unknown, including crashes between remote writes/readback.
No command text, keys, stdout, stderr or tokens are retained.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path


class JournalError(RuntimeError):
    pass


def default_root():
    configured = os.environ.get('ROSY_MODEL_DELIVERY_JOURNAL_DIR')
    if configured:
        return Path(configured)
    if os.name == 'nt':
        return Path('X:/DevTemp/rosy-model-delivery-journal')
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'rosy/model-delivery'


class Attempt:
    def __init__(self, root, args):
        self.id, self.sequence = uuid.uuid4().hex, 0
        self.action = args.action
        self.uncertain = False
        self.path = Path(root) / (self.id + '.jsonl')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            self.write('started', action=args.action, task=args.task, target=args.host,
                       revision=getattr(args, 'revision', None), slot=getattr(args, 'slot', 'shadow'))
            if os.name != 'nt':
                fd = os.open(self.path.parent, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
        except OSError as exc:
            raise JournalError('local delivery journal unavailable') from exc

    def write(self, event, **fields):
        row = dict(schema='rosy.model-delivery-attempt/1', attempt_id=self.id, sequence=self.sequence,
                   ts=dt.datetime.now(dt.timezone.utc).isoformat(), event=event, **fields)
        data = (json.dumps(row, allow_nan=False) + '\n').encode()
        try:
            with self.path.open('ab') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            raise JournalError('local delivery journal append failed; remote outcome may be unknown') from exc
        self.sequence += 1

    def runner(self, runner):
        def invoke(command, **kwargs):
            if command[0] == 'scp': phase = 'transfer'
            elif 'mktemp -d /tmp/rosy-model.' in command[-1]: phase = 'prepare'
            elif command[-1].startswith('rm -rf -- '): phase = 'cleanup'
            else: phase = self.action
            self.write('step_started', phase=phase)
            try:
                result = runner(command, **kwargs)
            except BaseException as exc:
                self.uncertain = True
                self.write('step_interrupted', phase=phase, outcome='unknown', exception=type(exc).__name__)
                raise
            if result.returncode != 0 and phase in ('push', 'rollback', 'promote', 'release-hold'):
                self.uncertain = True
            self.write('step_finished', phase=phase, raw_exit_code=result.returncode)
            return result
        return invoke

    def finish(self, code):
        outcome = 'succeeded' if code == 0 else 'refused' if code in (2, 75, 76) else 'failed'
        self.write('finished', outcome='unknown' if self.uncertain else outcome,
                   command_outcome=outcome, exit_code=code,
                   device_acceptance_verified=False, physical_task_verified=False)

    def interrupted(self, exc):
        self.write('interrupted', outcome='unknown', exception=type(exc).__name__)
