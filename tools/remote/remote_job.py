"""One detached pytest job on a test host, followed over short ssh calls (remote_pytest.run_on).

START launches JOB with setsid/nohup, so the job outlives the ssh session and a dropped link
(the hosts need ``loginctl enable-linger`` so the ``systemd-run --user`` scope survives the
session; all three have it). JOB holds ``~/rosy-jobs/<run>.lock`` with its own pid, writes
stdout+stderr to ``~/rosy-test/runs/<run>.jobs/<k>.log`` and on exit writes the exit code to
``<k>.rc`` (temp file then rename) and removes the lock. The laptop polls (POLL) every
``POLL_S`` s for new log bytes from its offset and the exit code; a failed call is retried with
``BACKOFF`` until ``ROSY_TEST_RECONNECT`` s (default 600) pass without contact, then ``Lost``
is raised and the job is left running. Standard library only.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

POLL_S = 10.0
BACKOFF = (5, 10, 20, 30)
RECONNECT_S = float(os.environ.get("ROSY_TEST_RECONNECT", "600"))
CALL_TIMEOUT = 60

# $1 run, $2 deps, $3 CPUQuota ('' = none), $4 job k, $5 timeout s, then pytest args.
# The lock pid is this shell's: it lives until pytest ends (the trap keeps bash from exec'ing).
JOB = r"""R=~/rosy-test; V=$R/venvs/$2; CPU=$3; D=$R/runs/$1.jobs; K=$4; T=$5; L=~/rosy-jobs/$1.lock
echo "$$ pytest 2 6" > "$L"; rm -f ~/rosy-jobs/"$1".resv
trap 'c=$?; [ $c = 124 ] && echo "[remote-pytest] timed out after $T s"
echo $c > "$D/$K.rc.tmp"; mv -f "$D/$K.rc.tmp" "$D/$K.rc"; rm -f "$L"' EXIT
shift 5
export PYTHONPATH="$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1
umask 022  # tests assume the robot umask; a host login umask 0002 makes 0664 files
timeout --foreground -k 30 "$T" systemd-run --user --scope -q -p MemoryMax=6G ${CPU:+-p CPUQuota=$CPU} -- \
  nice -n 15 ionice -c3 "$V/bin/python" -m pytest "$@"
"""

# Same args as JOB with the JOB text inserted as $6. A retried start (dropped link) finds the log.
START = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; D=$R/runs/$1.jobs; J=$6
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] || { echo "[remote] venv hash mismatch" >&2; exit 1; }
mkdir -p ~/rosy-jobs "$D"; cd "$R/runs/$1"
[ -e "$D/$4.log" ] && exit 0
set -- "$1" "$2" "$3" "$4" "$5" "${@:7}"
setsid nohup bash -c "$J" job "$@" > "$D/$4.log" 2>&1 < /dev/null &
"""

# The exit code is read before the log, so a poll that sees it also gets the whole log.
POLL = r"""D=~/rosy-test/runs/$1.jobs; rc=; [ -f "$D/$2.rc" ] && rc=$(cat "$D/$2.rc")
echo "ROSYJOB ${rc:--}"; tail -c +$(($3 + 1)) "$D/$2.log"
"""

# Ctrl-C / laptop deadline: TERM the job's process group (setsid made its pid the group id).
KILL = r"""read -r pid _ < ~/rosy-jobs/"$1".lock 2>/dev/null && kill -TERM -- "-$pid" 2>/dev/null; true"""


LOST_EXIT = 255  # what land.py sees for an invocation whose host went silent


class Lost(Exception):
    """No contact with the host for the reconnect budget; the job keeps running there."""


def ssh_call(ssh: list[str], host: str, script: str, *args: str) -> subprocess.CompletedProcess | None:
    """One short ssh call, or None when the link failed (ssh exit 255, timeout)."""
    command = "bash -c " + shlex.quote(script) + " remote " + " ".join(map(shlex.quote, args))
    try:
        result = subprocess.run([*ssh, host, command], stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=CALL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if result.returncode == 255 else result


def retrying(call, what: str, host: str, budget: float, sleep, clock):
    """call() until it returns non-None, backing off; (result, None) or (None, seconds without contact)."""
    start, n = clock(), 0
    while (result := call()) is None:
        lost = clock() - start
        if lost >= budget:
            return None, lost
        wait = min(BACKOFF[min(n, len(BACKOFF) - 1)], budget - lost)
        print(f"[remote-pytest] {host}: {what} failed; retrying in {wait} s ({lost:.0f} s without contact)",
              file=sys.stderr, flush=True)
        sleep(wait)
        n += 1
    return result, None


def parse_poll(out: bytes) -> tuple[int | None, bytes] | None:
    """(exit code or None while running, new log bytes) from POLL output; None if malformed."""
    at = out.find(b"ROSYJOB ")  # login chatter before it is dropped
    end = out.find(b"\n", at)
    if at < 0 or end < 0:
        return None
    rc = out[at + 8:end].strip()
    return (int(rc) if rc.lstrip(b"-").isdigit() else None), out[end + 1:]


def run(host: str, name: str, k: int, log: Path, job_args: list[str], pytest_args: list[str], timeout_s: int,
        ssh: list[str], call=ssh_call, sleep=time.sleep, clock=time.monotonic, budget: float | None = None) -> int:
    """Start job k of run name on host and copy its log to log as it grows; its exit code.

    Raises Lost after budget s without contact, KeyboardInterrupt after TERMing the job.
    """
    budget = RECONNECT_S if budget is None else budget
    where = f"{host}:~/rosy-test/runs/{name}.jobs/{k}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")
    args = [*job_args, str(k), str(timeout_s), JOB, *pytest_args]
    started, lost = retrying(lambda: call(ssh, host, START, *args), "start", host, budget, sleep, clock)
    if started is None:
        raise Lost(f"[remote-pytest] lost contact with {host} for {lost:.0f} s while starting; "
                   f"the run may continue there: {where}")
    if started.returncode != 0:
        log.write_bytes(started.stdout + started.stderr)
        return started.returncode

    def poll():
        result = call(ssh, host, POLL, name, str(k), str(offset))
        return parse_poll(result.stdout) if result is not None and result.returncode == 0 else None

    offset, deadline = 0, clock() + timeout_s + 120  # the job's own timeout fires first
    try:
        with log.open("ab") as out:
            while True:
                got, lost = retrying(poll, "poll", host, budget, sleep, clock)
                if got is None:
                    raise Lost(f"[remote-pytest] lost contact with {host} for {lost:.0f} s; "
                               f"the run continues there: {where}")
                rc, data = got
                out.write(data)
                out.flush()
                offset += len(data)
                if rc is not None:
                    return rc
                if clock() > deadline:
                    call(ssh, host, KILL, name)
                    return 124
                sleep(POLL_S)
    except KeyboardInterrupt:
        call(ssh, host, KILL, name)  # as before: the caller's cleanup then removes the run
        raise
