"""Persistent first-smoke cap: uncertain submissions consume the single allowance."""
import hashlib
import json
import os
from pathlib import Path
import stat

from rosy.decision.deliberation import canonical

MARKER = Path('/var/lib/rosy-deliberation/smoke/glm-first-review.spent')


def claim(body):
    digest = hashlib.sha256(canonical(json.loads(body)).encode()).hexdigest()
    parent = MARKER.parent
    if parent.resolve() != parent:
        raise ValueError('SMOKE_BOUNDARY_FAILED')
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('SMOKE_BOUNDARY_FAILED')
        try:
            fd = os.open(MARKER.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
        except FileExistsError:
            raise ValueError('SMOKE_ALREADY_CLAIMED') from None
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(canonical({'job_sha256': digest, 'state': 'SUBMISSION_UNKNOWN'}).encode())
            output.flush()
            os.fsync(output.fileno())
        os.fsync(directory)
    finally:
        os.close(directory)
