#!/usr/bin/env python3
"""Hold optional camera startup after two unconfirmed host boots.

This guard detects an interrupted startup, not its electrical/kernel cause.
Only a 90-second surviving main process or a clean stop clears pending startup.
An operator resets the latch after hardware recovery with the camera stopped.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import sys

STATE = Path('/var/lib/rosy/camera/boot-guard.json')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id')
MAX_FAILURES = 2


def read(path: Path) -> dict:
    if not path.exists():
        return {'boot_id': '', 'failures': 0, 'pending': False}
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or not isinstance(data.get('boot_id'), str)
            or type(data.get('failures')) is not int or not 0 <= data['failures'] <= MAX_FAILURES
            or type(data.get('pending')) is not bool):
        raise ValueError('invalid camera boot guard state; operator inspection required')
    return data


def write(path: Path, data: dict) -> None:
    # fsync both the record and its rename before allowing hardware startup.
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name == 'posix':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def check(path: Path, boot: str) -> int:
    data = read(path)
    if data['boot_id'] != boot and data['pending']:
        data['failures'] = min(MAX_FAILURES, data['failures'] + 1)
    data['boot_id'] = boot
    data['pending'] = data['failures'] < MAX_FAILURES
    write(path, data)
    if not data['pending']:
        print('Camera startup HELD: two unconfirmed boots; inspect hardware, then reset guard', flush=True)
        return 1  # ExecCondition skips the optional unit, no reboot or restart loop.
    print('Camera startup recorded; waiting for stable process survival', flush=True)
    return 0


def healthy(path: Path, boot: str) -> None:
    data = read(path)
    if data['boot_id'] == boot and data['pending']:
        data.update(failures=0, pending=False)
        write(path, data)
        print('Camera startup survived 90 seconds (not sensor/field acceptance)', flush=True)


def stopped(path: Path, boot: str, result: str) -> None:
    data = read(path)
    if result == 'success' and data['boot_id'] == boot and data['pending']:
        data['pending'] = False
        write(path, data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'healthy', 'stopped', 'reset'])
    args = parser.parse_args()
    try:
        boot = BOOT_ID.read_text().strip()
        if args.action == 'check':
            return check(STATE, boot)
        if args.action == 'healthy':
            healthy(STATE, boot)
        elif args.action == 'stopped':
            stopped(STATE, boot, os.environ.get('SERVICE_RESULT', 'unknown'))
        else:
            # Administrative CLI only; stop camera before resetting its state.
            write(STATE, {'boot_id': boot, 'failures': 0, 'pending': False})
        return 0
    except (OSError, ValueError) as exc:
        print(f'Camera startup guard refused: {exc}', file=sys.stderr)
        return 255


if __name__ == '__main__':
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))
    sys.exit(main())
