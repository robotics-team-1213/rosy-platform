"""Same-account admission shared with signed code updates and learning jobs."""
from contextlib import contextmanager
import csv
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess


def gpu_state(*, runner=subprocess.run):
    """Unknown observations and any compute owner fail closed."""
    try:
        def query(fields):
            result = runner(['nvidia-smi', fields, '--format=csv,noheader,nounits'],
                            capture_output=True, text=True, timeout=5, check=False)
            if result.returncode:
                raise ValueError('GPU observation failed')
            return result.stdout.strip()

        raw = query('--query-gpu=uuid,name,driver_version,memory.total,memory.free,utilization.gpu')
        rows = list(csv.reader(raw.splitlines(), skipinitialspace=True))
        if len(rows) != 1 or len(rows[0]) != 6:
            raise ValueError('Exactly one observed GPU is required')
        identifier, name, driver, total, free, utilization = rows[0]
        total, free, utilization = int(total), int(free), int(utilization)
        if not identifier or not name or not driver or not (0 <= free <= total) or total <= 0:
            raise ValueError('Invalid GPU observation')
        owners = query('--query-compute-apps=pid')
        if owners or not 0 <= utilization <= 100 or free < 4096:
            raise ValueError('GPU is occupied or has insufficient free memory')
        return {'ready': True, 'uuid': identifier, 'name': name, 'driver': driver,
                'total_mib': total, 'free_mib': free}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'ready': False, 'reason': 'GPU unavailable, occupied, or observation failed'}


def _root(binding):
    if type(binding.get('uid')) is not int or binding['uid'] != os.getuid():
        raise ValueError('Runner account differs from the approved binding')
    config = Path.home() / '.config/rosy/model-code.json'
    try:
        installed = json.loads(config.read_text(encoding='utf-8'))['root']
        root = Path(binding['model_code_root'])
        if not root.is_absolute() or str(root) != installed or root.resolve() != root:
            raise ValueError('Model-code root differs from the installed owner')
        info = root.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Unsafe model-code owner directory')
        return root
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('Installed model-code owner is unavailable') from exc


@contextmanager
def acquire(binding, *, probe=None):
    """Close our descriptors only: a surviving SDK child retains both leases."""
    root = _root(binding)
    cache = Path.home() / '.cache/rosy-learning'
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache.resolve() != cache or cache.stat().st_uid != os.getuid() or cache.stat().st_mode & 0o022:
        raise ValueError('Unsafe learning lease directory')
    descriptors = []
    try:
        for path in (root / 'work.lock', cache / 'gpu.lock'):
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            descriptors.append(fd)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or info.st_mode & 0o022):
                raise ValueError('Unsafe owner lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('Another model-code or learning owner is active') from exc
        if (probe or gpu_state)().get('ready') is not True:
            raise ValueError('GPU admission refused')
        yield tuple(descriptors)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
