"""Fixed transient user units; no caller-provided executable or unit names."""
import os
from pathlib import Path
import re
import signal
import subprocess

from run_binding import sdk_check


def _unit(unit):
    if not re.fullmatch(r'rosy-isaac-[0-9a-f]{32}\.service', unit):
        raise ValueError('Invalid experiment unit')
    return unit


def same_owner(expected, observed):
    return (bool(expected.get('invocation_id')) and bool(expected.get('cgroup'))
            and all(expected.get(k) == observed.get(k)
                    for k in ('unit', 'invocation_id', 'boot_id', 'cgroup')))


def _identity(pid):
    path = Path('/proc') / str(pid)
    fields = (path / 'stat').read_text().rsplit(') ', 1)[1].split()
    groups = (path / 'cgroup').read_text().splitlines()
    cgroup = next((line[3:] for line in groups if line.startswith('0::')), '')
    return {'pid_start': fields[19], 'uid': path.stat().st_uid, 'cgroup': cgroup}


class System:
    def __init__(self, expected_binding_sha256=None):
        self.expected_binding_sha256 = expected_binding_sha256

    def check(self, binding):
        return sdk_check(binding)

    def launch(self, unit, binding_file, run_id):
        from run_binding import load_binding
        from run_store import RunStore
        binding = load_binding(binding_file)
        scenario = RunStore(Path(binding['data_root'])).get(run_id)['input']['scenario_id']
        timeout = 900 if scenario == 'omx-stacking-rl' else 180
        command = ['systemd-run', '--user', '--quiet', '--unit=' + _unit(unit),
            '--property=Type=exec', '--property=KillMode=control-group',
            '--property=RuntimeMaxSec='+str(timeout), '--property=TimeoutStopSec=10',
            '--property=UMask=0077', '--property=MemoryMax=12G',
            '--property=StandardOutput=null', '--property=StandardError=null',
            '/usr/bin/python3', str(Path(__file__).with_name('run_control.py')),
            '--binding', str(binding_file), '--worker', run_id]
        if self.expected_binding_sha256:
            command += ['--expected-binding-sha256', self.expected_binding_sha256]
        subprocess.run(command,
            capture_output=True, text=True, timeout=15, check=True)

    def observe(self, unit):
        result = subprocess.run(['systemctl', '--user', 'show', _unit(unit),
            '--property=InvocationID,ControlGroup,ActiveState,MainPID,Result,ExecMainStatus'],
            capture_output=True, text=True, timeout=10, check=True)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        pid = int(values.get('MainPID', '0'))
        identity = _identity(pid) if pid else {'pid_start': None, 'uid': os.getuid()}
        return {'unit': unit, 'invocation_id': values.get('InvocationID', ''),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'cgroup': values.get('ControlGroup', ''),
                'active': values.get('ActiveState') in {'active', 'activating', 'deactivating'},
                'main_pid': pid, 'uid': identity['uid'], 'pid_start': identity['pid_start'],
                'exit_code': values.get('ExecMainStatus'), 'service_result': values.get('Result')}

    def stop(self, owner):
        pid = owner.get('main_pid')
        if type(pid) is not int or pid <= 0 or not owner.get('pid_start'):
            raise ValueError('Worker process identity is unconfirmed')
        fd = os.pidfd_open(pid)
        try:
            identity = _identity(pid)
            if (not same_owner(owner, self.observe(owner['unit']))
                    or any(owner.get(k) != identity.get(k) for k in ('pid_start', 'uid', 'cgroup'))):
                raise ValueError('Experiment worker ownership changed')
            # A reused unit or PID cannot redirect this already-open process handle.
            signal.pidfd_send_signal(fd, signal.SIGUSR1)
        finally:
            os.close(fd)
