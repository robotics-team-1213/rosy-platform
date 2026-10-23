"""Opt-in detached observer for the unchanged, bounded native simulation body."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import time

import remote_job


IDENTITY = r"""
alive=0
if read -r pid < "$D/0.pid" 2>/dev/null && [[ "$pid" =~ ^[0-9]+$ ]] &&
   read -r expected < "$D/0.starttime" 2>/dev/null &&
   stat=$(cat "/proc/$pid/stat" 2>/dev/null); then
  stat=${stat##*) }; read -ra fields <<< "$stat"
  if [ "${fields[19]:-}" = "$expected" ] && [ "${fields[2]:-}" = "$pid" ]; then alive=1; fi
fi
"""

START = r"""set -euo pipefail
umask 077
R=~/rosy-test; D=$R/runs/$1.sim-job; binding=$2; J=$3; shift 3
mkdir -p "$D"; cd "$R/runs/$1"
exec 9>"$D/start.lock"; flock -x 9
if [ -e "$D/binding.sha256" ]; then
  [ "$(cat "$D/binding.sha256")" = "$binding" ] || exit 3
else
  printf '%s' "$binding" > "$D/binding.sha256"
fi
""" + IDENTITY + r"""
if [ -f "$D/0.rc" ] || [ "$alive" = 1 ]; then exit 0; fi
# A claimed launch without a live identity or rc is uncertain, never a reason to replace it.
mkdir "$D/submitted" 2>/dev/null || exit 254
: > "$D/0.log"
setsid nohup bash -c "$J" remote "$@" 9>&- >> "$D/0.log" 2>&1 < /dev/null &
"""

SUPERVISOR = r"""set -uo pipefail
D=~/rosy-test/runs/$1.sim-job
trap 'c=$?; trap - EXIT; printf "%s" "$c" > "$D/0.rc.tmp"; mv "$D/0.rc.tmp" "$D/0.rc"; exit "$c"' EXIT
trap 'exit 143' TERM INT
stat=$(cat /proc/$$/stat); stat=${stat##*) }; read -ra fields <<< "$stat"
printf '%s' "${fields[19]}" > "$D/0.starttime"
printf '%s' "$$" > "$D/0.pid.tmp"; mv "$D/0.pid.tmp" "$D/0.pid"
"""

POLL = r"""set -euo pipefail
D=~/rosy-test/runs/$1.sim-job
[ "$(cat "$D/binding.sha256")" = "$2" ] || exit 3
rc=; [ ! -f "$D/0.rc" ] || rc=$(cat "$D/0.rc")
""" + IDENTITY + r"""
[ "$(stat -c %s "$D/0.log")" -ge "$3" ] || exit 3
echo "ROSYJOB ${rc:--} $alive"; tail -c +$(($3 + 1)) "$D/0.log"
"""

KILL = r"""set -euo pipefail
D=~/rosy-test/runs/$1.sim-job
[ "$(cat "$D/binding.sha256")" = "$2" ] || exit 3
[ ! -f "$D/0.rc" ] || exit 0
""" + IDENTITY + r"""
[ "$alive" = 1 ] || exit 3
kill -TERM -- "-$pid"
"""


def _identity(host: str, name: str, metadata: dict) -> None:
    assert re.fullmatch(r'sim-[0-9a-f]{10}-[0-9a-f]{6}', name)
    assert metadata['host'] == host and metadata['name'] == name
    assert metadata['role'] in ('model', 'ai')
    assert re.fullmatch(r'[0-9a-f]{40}', metadata['source_revision'])
    assert name.startswith('sim-' + metadata['source_revision'][:10] + '-')
    assert re.fullmatch(r'[0-9a-f]{64}', metadata['command_sha256'])
    assert all(type(metadata[k]) is int and metadata[k] > 0 for k in ('cpus', 'memory_gib', 'minutes'))


def follow(host: str, name: str, log: Path, metadata: dict, *, ssh: list[str],
           call=remote_job.ssh_call, sleep=time.sleep, clock=time.monotonic, budget=None) -> int:
    """Follow one bound actor, including a completed one; never place, ship or START."""
    _identity(host, name, metadata)
    binding = hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    budget = remote_job.RECONNECT_S if budget is None else budget
    log.parent.mkdir(parents=True, exist_ok=True)
    offset = log.stat().st_size if log.exists() else 0
    gone = 0

    def poll():
        result = call(ssh, host, POLL, name, binding, str(offset))
        if result is not None and result.returncode == 3:
            raise remote_job.Lost(f'[remote-sim] {name}: bound identity/log mismatch; preserved')
        return remote_job.parse_poll(result.stdout) if result is not None and result.returncode == 0 else None

    try:
        with log.open('ab') as out:
            while True:
                got, lost = remote_job.retrying(poll, 'simulation poll', host, budget, sleep, clock)
                if got is None:
                    raise remote_job.Lost(f'[remote-sim] lost {host} for {lost:.0f}s; preserved {name}.sim-job')
                rc, alive, data = got
                out.write(data)
                out.flush()
                offset += len(data)
                if rc is not None:
                    return rc
                gone = 0 if alive else gone + 1
                if gone == 2:
                    out.write(b'\n[remote-sim] actor ended without terminal rc; preserved, not restarted\n')
                    return remote_job.VANISHED_EXIT
                sleep(remote_job.POLL_S)
    except KeyboardInterrupt:
        result = call(ssh, host, KILL, name, binding)
        if result is None or result.returncode != 0:
            raise remote_job.Lost(f'[remote-sim] {name}: cancellation unconfirmed; preserved') from None
        raise


def run(host: str, name: str, args: list[str], inner: str, sim: str, log: Path, metadata: dict,
        *, ssh: list[str], call=remote_job.ssh_call, sleep=time.sleep,
        clock=time.monotonic, budget=None) -> int:
    """Claim once, detach the native SIM supervisor, then follow its atomic terminal rc."""
    _identity(host, name, metadata)
    assert args and args[0] == name
    metadata = {**metadata, 'transport_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'arguments_sha256': hashlib.sha256(json.dumps(args).encode()).hexdigest(),
                'inner_sha256': hashlib.sha256(inner.encode()).hexdigest(),
                'sim_sha256': hashlib.sha256(sim.encode()).hexdigest()}
    raw = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()
    binding = hashlib.sha256(raw).hexdigest()
    log.parent.mkdir(parents=True, exist_ok=True)
    with (log.parent / 'remote-run.json').open('xb') as stream:
        stream.write(raw)
    body = SUPERVISOR + '\nINNER=' + shlex.quote(inner) + ' bash -c ' + shlex.quote(sim) + ' remote "$@"\n'
    budget = remote_job.RECONNECT_S if budget is None else budget
    try:
        started, lost = remote_job.retrying(
            lambda: call(ssh, host, START, name, binding, body, *args),
            'simulation start', host, budget, sleep, clock)
        if started is None:
            raise remote_job.Lost(f'[remote-sim] start reply lost for {lost:.0f}s; preserved {name}.sim-job')
        if started.returncode != 0:
            raise remote_job.Lost(f'[remote-sim] {name}: uncertain start ({started.returncode}); preserved')
    except KeyboardInterrupt:
        result = call(ssh, host, KILL, name, binding)
        if result is None or result.returncode != 0:
            raise remote_job.Lost(f'[remote-sim] {name}: start cancellation unconfirmed; preserved') from None
        raise
    return follow(host, name, log, metadata, ssh=ssh, call=call, sleep=sleep, clock=clock, budget=budget)
