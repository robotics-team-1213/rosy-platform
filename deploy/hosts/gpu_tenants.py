"""D-958 stage 1 on a lab PC: role services keep the GPU; experiments get it only while the role is idle.

    gpu_tenants.py idle  UNIT...   prints idle|busy for the units' role
    gpu_tenants.py claim UNIT...   if idle: stop the units, leave ~/rosy-jobs/paused-<unit> (15 min, renewed per claim)
    gpu_tenants.py release UNIT... start the units again and clear the marks
    gpu_tenants.py tick            (timer, every minute) release a paused unit when its role has work again or
                                   its mark expired, after the admitted GPU job releases the host

Restoring is the host's job, so a laptop or batch that dies never leaves a role service off. Standard library only.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

JOBS = Path.home() / 'rosy-jobs'
GPU_LOCK = Path.home() / '.cache/rosy-learning/gpu.lock'
HOLD_S = 900
IDLE_S = 600
# AI PC: the situation service (D-577) drops to `shared` (rules only, no GPU) while Ollama is lent out.
OWNER_MODE = Path.home() / '.config/rosy/situation-owner-mode'
SITUATION = Path(os.environ.get('ROSY_SITUATION_STATE', Path.home() / '.local/state/rosy-situation')) / 'logs'


def _tail(path, size=1 << 20):
    """Last complete JSON line of a large append-only log."""
    with open(path, 'rb') as stream:
        stream.seek(max(0, os.path.getsize(path) - size))
        lines = stream.read().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def situation_busy(now):
    """Busy while any robot is online or the service proposed something in the last 10 minutes."""
    try:
        inputs = sorted(SITUATION.glob('*-input.jsonl'))
        latest = _tail(inputs[-1]) if inputs else None
    except OSError:
        latest = None
    if not latest or now - float(latest.get('observed_at', 0)) > 120:
        return 'no fresh situation input'  # unknown is busy: never lend the GPU blind
    if any(robot.get('online') for robot in (latest.get('state') or {}).get('robots') or []):
        return 'robot online'
    for path in SITUATION.glob('*-proposals.jsonl'):
        if now - path.stat().st_mtime < IDLE_S:
            return 'recent proposal'
    return None


# shortcut: one role rule per lending unit; add a rule here before marking another unit idle-yield in services.yaml.
ROLES = {'rosy-ollama.service': situation_busy}


def busy(units, now):
    for unit in units:
        if unit not in ROLES:
            return f'{unit} is not declared idle-yield'
        reason = ROLES[unit](now)
        if reason:
            return reason
    return None


def gpu_held(now):
    """Include the worker's authoritative flock: it can outlive the client's reservation."""
    import fcntl

    try:
        with GPU_LOCK.open('r') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except FileNotFoundError:
        pass
    except OSError:
        return True
    for path in JOBS.glob('*.resv'):
        try:
            if path.name.startswith('isaac-') and float(path.read_text().split()[0]) > now:
                return True
        except (OSError, ValueError, IndexError):
            continue
    for path in JOBS.glob('*.lock'):
        try:
            pid, kind = path.read_text().split()[:2]
            if kind == 'gpu' and Path(f'/proc/{int(pid)}').exists():
                return True
        except (OSError, ValueError):
            continue
    return False


def systemctl(action, unit):
    subprocess.run(['systemctl', '--user', action, unit], check=action != 'is-active', timeout=90,
                   capture_output=True)


def mark(unit):
    return JOBS / f'paused-{unit}'


def claim(units, now):
    reason = busy(units, now)
    if reason:
        return f'busy {reason}'
    JOBS.mkdir(exist_ok=True)
    for unit in units:
        previous = json.loads(mark(unit).read_text()) if mark(unit).exists() else None
        before = previous['owner_mode'] if previous else _owner_mode()
        revision = previous.get('owner_revision') if previous else None
        if not previous and unit == 'rosy-ollama.service' and before == 'available':
            _set_owner_mode('shared')
            revision = OWNER_MODE.stat().st_mtime_ns
        mark(unit).write_text(json.dumps({'until': now + HOLD_S, 'owner_mode': before, 'owner_revision': revision}))
        if not previous:
            systemctl('stop', unit)
    return 'claimed'


def release(units):
    if gpu_held(time.time()):
        return 'busy GPU held'
    for unit in units:
        if not mark(unit).exists():
            continue
        previous = json.loads(mark(unit).read_text())
        systemctl('start', unit)
        if (unit == 'rosy-ollama.service' and previous.get('owner_mode') == 'available'
                and _owner_mode() == 'shared' and OWNER_MODE.stat().st_mtime_ns == previous.get('owner_revision')):
            _set_owner_mode('available')
        mark(unit).unlink()
    return 'released'


def tick(now):
    done = []
    for path in JOBS.glob('paused-*.service'):
        unit = path.name[len('paused-'):]
        expired = json.loads(path.read_text()).get('until', 0) < now
        if ((unit in ROLES and ROLES[unit](now)) or expired) and not gpu_held(now):
            if release([unit]) == 'released':
                done.append(unit)
    return 'released ' + ' '.join(done) if done else 'nothing'


def _owner_mode():
    try:
        return OWNER_MODE.read_text().strip()
    except OSError:
        return None


def _set_owner_mode(value):
    temporary = OWNER_MODE.with_name('.' + OWNER_MODE.name + '.pending')
    temporary.write_text(value + '\n')
    os.replace(temporary, OWNER_MODE)


def main(argv):
    action, units, now = argv[0], argv[1:], time.time()
    if action == 'tick':
        return tick(now)
    if not units or any(not u.endswith('.service') or '/' in u for u in units):
        raise SystemExit('usage: gpu_tenants.py idle|claim|release UNIT.service...')
    if action == 'idle':
        reason = busy(units, now)
        return f'busy {reason}' if reason else 'idle'
    return {'claim': claim, 'release': lambda u, _: release(u)}[action](units, now)


if __name__ == '__main__':
    print(main(sys.argv[1:]))
