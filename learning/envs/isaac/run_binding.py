"""Operator-owned SDK/source binding, separate from experiment request JSON."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def _owned(path, *, directory=False, allow_link=False):
    if not path.is_absolute() or (path.parent.resolve() != path.parent):
        raise ValueError('Binding paths must have canonical parents')
    if not allow_link and path.is_symlink():
        raise ValueError('Linked binding path')
    link = path.lstat()
    info = path.stat()
    allowed_owner = {os.getuid(), 0} if allow_link else {os.getuid()}
    if ((directory and not stat.S_ISDIR(info.st_mode))
            or (not directory and not stat.S_ISREG(info.st_mode))
            or info.st_uid not in allowed_owner or info.st_mode & 0o022
            or (allow_link and link.st_uid != os.getuid())):
        raise ValueError('Unsafe binding path owner or permissions')
    return path


def load_binding(path, sha=None, *, expected_digest=None):
    path = _owned(Path(path))
    if path.stat().st_size > 65536:
        raise ValueError('Oversized SDK binding')
    raw = path.read_bytes()
    if expected_digest is not None and hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('Operator binding fingerprint changed')
    value = json.loads(raw)
    keys = {'uid', 'source_root', 'source_sha', 'sdk_python', 'sdk_python_sha256',
            'sdk_version', 'model_code_root', 'data_root'}
    if (not isinstance(value, dict) or set(value) != keys or type(value['uid']) is not int
            or value['uid'] != os.getuid() or not re.fullmatch('[0-9a-f]{40}', value['source_sha'])
            or (sha is not None and sha != value['source_sha'])
            or not re.fullmatch('[0-9a-f]{64}', value['sdk_python_sha256'])
            or value['sdk_version'] not in {'5.1.0.0', '6.0.0.0'}):
        raise ValueError('Unapproved SDK or source binding')
    source = _owned(Path(value['source_root']), directory=True)
    if source != Path(__file__).resolve().parents[3]:
        raise ValueError('Runner source differs from the approved checkout')
    observed = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    clean = subprocess.run(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=normal'],
                           capture_output=True, text=True, timeout=10, check=True).stdout
    if observed != value['source_sha'] or clean:
        raise ValueError('Source checkout is changed or mismatched')
    python = _owned(Path(value['sdk_python']), allow_link=True)
    # A venv's bin/python is normally a symlink; pin its executable bytes too.
    if hashlib.sha256(python.read_bytes()).hexdigest() != value['sdk_python_sha256']:
        raise ValueError('SDK interpreter changed')
    data = _owned(Path(value['data_root']), directory=True)
    managed = _owned(Path(value['model_code_root']), directory=True)
    if data.is_relative_to(source) or data.is_relative_to(managed):
        raise ValueError('Run data must be outside source and signed code')
    return value


def sdk_check(binding):
    from run_admission import acquire, gpu_state
    with acquire(binding):
        result = subprocess.run([binding['sdk_python'], '-c',
            "import importlib.metadata as m;print(m.version('isaacsim'))"],
            capture_output=True, text=True, timeout=15, check=True)
        if result.stdout.strip() != binding['sdk_version']:
            raise ValueError('Installed SDK version differs from binding')
        return dict(gpu_state(), sdk_version=binding['sdk_version'])
