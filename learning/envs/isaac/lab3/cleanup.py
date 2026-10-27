"""Observe owned process and global GPU drain after a bounded installation check."""
import os
from pathlib import Path
import subprocess
import time


def snapshot():
    relative = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                    if line.startswith('0::'))
    scope = Path('/sys/fs/cgroup') / relative.lstrip('/')
    members = {int(pid) for path in scope.rglob('cgroup.procs') for pid in path.read_text().split()}
    gpu = subprocess.run(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader,nounits'],
                         capture_output=True, text=True, timeout=5)
    return {'owned_pids': sorted(members - {os.getpid()}),
            'gpu_pids': [int(line.strip()) for line in gpu.stdout.splitlines() if line.strip()],
            'gpu_query_exit': gpu.returncode}


def wait_for_cleanup(timeout=30, interval=.25):
    if timeout < 0 or interval <= 0:
        raise ValueError('invalid cleanup observation budget')
    start = time.monotonic()
    observations = []
    while True:
        state = snapshot()
        observations.append(state)
        clean = state['gpu_query_exit'] == 0 and not state['gpu_pids'] and not state['owned_pids']
        elapsed = time.monotonic() - start
        if clean or elapsed >= timeout:
            return {'clean': clean, 'elapsed_seconds': elapsed, 'observations': observations}
        time.sleep(min(interval, timeout - elapsed))
