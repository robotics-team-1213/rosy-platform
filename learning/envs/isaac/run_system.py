"""Fixed transient user units; no caller-provided executable or unit names."""
import os
from pathlib import Path
import re
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


class System:
    def check(self, binding):
        return sdk_check(binding)

    def launch(self, unit, binding_file, run_id):
        subprocess.run(['systemd-run', '--user', '--quiet', '--unit=' + _unit(unit),
            '--property=Type=exec', '--property=KillMode=control-group',
            '--property=RuntimeMaxSec=180', '--property=TimeoutStopSec=10',
            '--property=UMask=0077', '--property=MemoryMax=12G',
            '--property=StandardOutput=null', '--property=StandardError=null',
            '/usr/bin/python3', str(Path(__file__).with_name('run_control.py')),
            '--binding', str(binding_file), '--worker', run_id],
            capture_output=True, text=True, timeout=15, check=True)

    def observe(self, unit):
        result = subprocess.run(['systemctl', '--user', 'show', _unit(unit),
            '--property=InvocationID,ControlGroup,ActiveState,MainPID,Result,ExecMainStatus'],
            capture_output=True, text=True, timeout=10, check=True)
        values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        return {'unit': unit, 'invocation_id': values.get('InvocationID', ''),
                'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'cgroup': values.get('ControlGroup', ''),
                'active': values.get('ActiveState') in {'active', 'activating', 'deactivating'},
                'main_pid': int(values.get('MainPID', '0')), 'uid': os.getuid(),
                'exit_code': values.get('ExecMainStatus'), 'service_result': values.get('Result')}

    def stop(self, owner):
        if not same_owner(owner, self.observe(owner['unit'])):
            raise ValueError('Experiment unit ownership changed')
        # Units are never reset/reused; the deterministic ID has one launch intent.
        subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=SIGTERM',
                        _unit(owner['unit'])], capture_output=True, text=True, timeout=10, check=True)
