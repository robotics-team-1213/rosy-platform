"""Common run controller for the local web adapter and remote CLI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from run_binding import load_binding
from run_catalog import catalog
from run_store import RunConflict, RunStore, TERMINAL, input_snapshot
from run_system import System, same_owner


class Runner:
    def __init__(self, store, binding_file, *, system=None, expected_binding_sha256=None):
        self.store = store
        self.binding_file = Path(binding_file)
        self.expected_binding_sha256 = expected_binding_sha256
        self.system = system or System(expected_binding_sha256)

    def _binding(self, source_sha):
        options = {'expected_digest': self.expected_binding_sha256} if self.expected_binding_sha256 else {}
        return load_binding(self.binding_file, source_sha, **options)

    def check(self, scenario_id, config, source_sha):
        snapshot = input_snapshot(scenario_id, config, source_sha)
        binding = self._binding(source_sha)
        readiness = self.system.check(binding)
        return dict(snapshot, **readiness)

    def start(self, request):
        required = {'request_id', 'scenario_id', 'config', 'source_sha', 'expected_input_sha256'}
        if (not isinstance(request, dict) or not required <= request.keys()
                or request.keys() - required - {'parent_run_id'}):
            raise ValueError('Invalid experiment request')
        snapshot = input_snapshot(request['scenario_id'], request['config'], request['source_sha'])
        if request['expected_input_sha256'] != snapshot['input_sha256']:
            raise ValueError('Experiment input fingerprint changed')
        self._binding(request['source_sha'])
        row = self.store.create(request['request_id'], request['scenario_id'], request['config'],
                                request['source_sha'], parent_run_id=request.get('parent_run_id'))
        if row['revision'] != 0 or row['status'] != 'PENDING':
            return self.status(row['run_id'])
        unit = 'rosy-isaac-' + row['run_id'] + '.service'
        try:
            row = self.store.update(row['run_id'], 0,
                                    {'phase': 'LAUNCH_RESERVED', 'runtime': {'unit': unit}})
        except RunConflict:
            return self.status(row['run_id'])
        try:
            self.system.launch(unit, self.binding_file, row['run_id'])
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            self._unknown(row, 'launch response unavailable; observe existing run')
        return self.store.get(row['run_id'])

    def _unknown(self, row, reason):
        if row['status'] == 'UNKNOWN' and row.get('error') == reason:
            return row
        try:
            return self.store.update(row['run_id'], row['revision'], {'status': 'UNKNOWN', 'error': reason})
        except RunConflict:
            return self.store.get(row['run_id'])

    def list(self):
        return [self.status(row['run_id']) if 'input' in row else row for row in self.store.list()]

    def status(self, run_id):
        row = self.store.get(run_id)
        if row['status'] in TERMINAL or not row.get('runtime'):
            return row
        try:
            observed = self.system.observe(row['runtime']['unit'])
            if not observed.get('active'):
                return self._unknown(row, 'unit is inactive; cleanup and result unconfirmed')
            if row['runtime'].get('invocation_id') and not same_owner(row['runtime'], observed):
                return self._unknown(row, 'unit ownership changed; automatic restart refused')
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return self._unknown(row, 'unit observation unavailable')
        return row

    def stop(self, run_id, expected_revision):
        row = self.store.get(run_id)
        if row['revision'] != expected_revision or row['status'] in TERMINAL:
            raise RunConflict('Run revision changed or run is final')
        owner = row.get('runtime', {})
        if not same_owner(owner, self.system.observe(owner.get('unit', ''))):
            raise ValueError('Run ownership is unconfirmed; no stop signal sent')
        row = self.store.update(run_id, expected_revision, {'status': 'STOP_REQUESTED'})
        try:
            self.system.stop(owner)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return self._unknown(row, 'stop failed; termination remains unconfirmed')
        return self.store.get(run_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding', required=True, type=Path)
    parser.add_argument('--worker')
    parser.add_argument('--expected-binding-sha256')
    args = parser.parse_args()
    binding = load_binding(args.binding, expected_digest=args.expected_binding_sha256)
    store = RunStore(Path(binding['data_root']))
    if args.worker:
        from run_worker import execute
        return execute(store, args.binding, args.worker, expected_binding_sha256=args.expected_binding_sha256)
    request = json.loads(sys.stdin.buffer.read(1024 * 1024 + 1))
    if not isinstance(request, dict):
        raise ValueError('Request must be an object')
    runner = Runner(store, args.binding, expected_binding_sha256=args.expected_binding_sha256)
    action = request.get('action')
    if action == 'catalog':
        result = catalog()
    elif action == 'list':
        result = runner.list()
    elif action == 'check':
        result = runner.check(request['scenario_id'], request['config'], request['source_sha'])
    elif action == 'start':
        result = runner.start(request['request'])
    elif action == 'status':
        result = runner.status(request['run_id'])
    elif action == 'stop':
        result = runner.stop(request['run_id'], request['expected_revision'])
    elif action == 'artifact':
        import base64
        result = store.artifact(request['run_id'], request['artifact_id'])
        result['data_base64'] = base64.b64encode(result.pop('data')).decode('ascii')
    else:
        raise ValueError('Unknown experiment operation')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}))
        raise SystemExit(2)
