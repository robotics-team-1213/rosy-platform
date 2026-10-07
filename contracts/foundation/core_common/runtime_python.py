"""CORE-only signed auxiliary package path; D189 base runtime stays unchanged."""
import os
from pathlib import Path
import re
import stat
import sys

RELEASE = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}")
TOP = re.compile(r"(?:cryptography|cffi|pycparser|_cffi_backend[.][A-Za-z0-9_.-]+[.]so|"
                 r"(?:cryptography-50[.]0[.]0|cffi-2[.]1[.]1|pycparser-3[.]0)[.]dist-info)")


def activate_core_auxiliary(entry_file, *, releases_root=Path('/opt/rosy/releases')):
    """Called only by CORE main before importing its API, never by ROS/learning units."""
    entry = Path(entry_file).resolve(strict=True)
    installs = [p for p in entry.parents if p.name == 'install']
    if len(installs) != 1:
        raise RuntimeError('CORE installed release path required')
    release = installs[0].parent
    if release.parent != Path(releases_root).resolve() or not RELEASE.fullmatch(release.name):
        raise RuntimeError('CORE release location rejected')
    auxiliary = release / 'runtime-python'
    if auxiliary.is_symlink() or not auxiliary.is_dir():
        raise RuntimeError('CORE auxiliary Python runtime unavailable')
    for node in [auxiliary, *auxiliary.rglob('*')]:
        info = node.lstat()
        if node.is_symlink() or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise RuntimeError('unsafe auxiliary Python entry')
        if os.name == 'posix' and (info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022):
            raise RuntimeError('auxiliary Python must remain root owned and immutable')
        if node.suffix == '.pth':
            raise RuntimeError('auxiliary Python startup hooks forbidden')
    if not all(TOP.fullmatch(p.name) for p in auxiliary.iterdir()):
        raise RuntimeError('unexpected auxiliary Python package')
    if not all((auxiliary / name).is_dir() for name in ('cryptography', 'cffi', 'pycparser')):
        raise RuntimeError('incomplete auxiliary Python closure')
    sys.path.insert(0, str(auxiliary))
    return auxiliary
