"""Linux process proof for the learning worker; a PID alone never grants stop authority."""
import os
from pathlib import Path


def process_stamp(pid, request=None):
    try:
        proc = Path('/proc') / str(pid)
        command = (proc / 'cmdline').read_bytes().split(b'\0')
        if request is not None and os.fsencode(str(request)) not in command:
            return None
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z' or (request is not None and os.getpgid(pid) != pid):
            return None
        return {'pid': pid, 'start': fields[19],
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, ValueError):
        return None
