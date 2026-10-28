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

import remote_test_tools

POLL_S = 10.0
LAST_POLL = 0.0  # monotonic time of the latest poll in this process (land_watchdog reads it)
BACKOFF = (5, 10, 20, 30)
RECONNECT_S = float(os.environ.get("ROSY_TEST_RECONNECT", "600"))
CALL_TIMEOUT = 60

# $1 run, $2 deps, $3 CPUQuota ('' = none), $4 job k, $5 timeout s, then [ROSY_*=value ...] pytest args.
# The lock pid is this shell's: it lives until pytest ends (the trap keeps bash from exec'ing).
JOB = r"""R=~/rosy-test; V=$R/venvs/$2; CPU=$3; D=$R/runs/$1.jobs; K=$4; T=$5; L=~/rosy-jobs/$1.lock
echo "$$ pytest 2 6" > "$L"; echo $$ > "$D/$K.pid"; rm -f ~/rosy-jobs/"$1".resv
# The next invocation reuses L; release it before publishing completion.
trap 'c=$?; [ $c = 124 ] && echo "[remote-pytest] timed out after $T s"
[ -z "${B:-}" ] || { chmod -R u+rwX -- "$B"; rm -rf -- "$B"; } 2>/dev/null  # tests leave read-only dirs
echo $c > "$D/$K.rc.tmp"; rm -f "$L"; mv -f "$D/$K.rc.tmp" "$D/$K.rc"' EXIT
trap 'exit 143' TERM INT  # runs once timeout/pytest have ended; else $? would still be 0
""" + remote_test_tools.DEFAULT_CONTEXT + r"""shift 5
export PYTHONPATH="$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1
# Leading ROSY_*=value args are this job's environment (remote_pytest.ENV_ARG), not pytest args.
while [ $# -gt 0 ] && [[ $1 =~ ^ROSY_[A-Z0-9_]*= ]]; do export "$1"; shift; done
# xdist_plan job words: an xdist job's workers and a light host's memory cap, for the lock and MemoryMax.
# ROSY_JOB_RESERVE_GB: the lock budget placement counts (laptop memory history), apart from the MemoryMax cap.
# ROSY_JOB_RESERVE_CORES: the lock's cores from the laptop's cpu history; -n stays ROSY_JOB_CORES.
C=${ROSY_JOB_CORES:-2}; M=${ROSY_JOB_MEM_GB:-6}; G=${ROSY_JOB_RESERVE_GB:-$M}; RC=${ROSY_JOB_RESERVE_CORES:-$C}
[[ $C$M$G$RC =~ ^[0-9]+$ ]] || { echo "[remote-pytest] ROSY_JOB_CORES/_MEM_GB/_RESERVE_* must be whole numbers"; exit 2; }
X=pytest; [ "${ROSY_RUN_BROWSER_TESTS:-}" = 1 ] && X=browser  # PROBE counts browser locks per host
echo "$$ $X $RC $G" > "$L"
# Browser jobs: Chromium for the venv's playwright into the shared ~/.cache/ms-playwright (a no-op when present).
[ "${ROSY_RUN_BROWSER_TESTS:-}" = 1 ] && { timeout 900 nice -n 15 "$V/bin/python" -m playwright install chromium \
  > /dev/null || echo "[remote-pytest] playwright install chromium failed; browser tests will error"; }
umask 022  # tests assume the robot umask; a host login umask 0002 makes 0664 files
# tmp_path root per job, removed by the EXIT trap: /tmp/pytest-of-<user> garbage filled a host disk (2026-10-26).
# Short and 0700 under /tmp, not the run dir: AF_UNIX paths stop at 108 bytes and TLS file checks refuse
# group-writable ancestors (login umask 0002 makes the run dir 0775).
B=$(mktemp -d /tmp/rosy-pytest-XXXXXX) || exit 1
# TMPDIR beside the basetemp, not in it (pytest wipes --basetemp at start): TEMP-or-/tmp tests leak otherwise.
mkdir -m 700 "$B/p" "$B/t"; export TMPDIR=$B/t TEMP=$B/t TMP=$B/t
# The deps hash names the inputs, not what unpinned pip picked; installed dist-info names do (one per run).
echo "[remote-pytest] env ${V##*/} freeze $(cd "$V" && ls -d lib/python3*/site-packages/*.dist-info \
  receiver-crypto/*.dist-info 2>/dev/null | sha256sum | cut -c1-16)"
# Best-effort lowest, not idle (-c3): idle gets no disk time while any other process writes, so a timing
# test's SQLite fsync stalled for seconds on a busy AI PC (g1 contact gap p99 4.7-5.7 s, 2026-10-26).
# The scope's cgroup ends with pytest, so a watcher inside it reads memory.peak (kernel >= 5.19) after pytest is
# gone; pytest stays exec'd, so timeout's TERM/KILL still reach it directly. No memory.peak: an empty first line.
# Lines 2-3: cpu.stat usage_usec and the wall time in us, so the laptop learns the cores a job really used.
W='f=$1; shift; P=$$; s=$(date +%s%N); cg=${ROSY_CGROUP_FS:-/sys/fs/cgroup}$(cut -d: -f3 /proc/self/cgroup)
{ while kill -0 $P 2>/dev/null; do sleep 0.5; done; { cat "$cg/memory.peak" || echo
  sed -n "s/^usage_usec //p" "$cg/cpu.stat"; echo $(( ($(date +%s%N) - s) / 1000 )); } > "$f.tmp"
  mv -f "$f.tmp" "$f"; } < /dev/null > /dev/null 2>&1 & exec "$@"'
timeout --foreground -k 30 "$T" systemd-run --user --scope -q -p MemoryMax=${M}G ${CPU:+-p CPUQuota=$CPU} -- \
  bash -c "$W" peak "$B/peak" nice -n 15 ionice -c2 -n7 "$V/bin/python" -m pytest --basetemp "$B/p" "$@"
c=$?
for _ in $(seq 25); do [ -e "$B/peak" ] && break; sleep 0.2; done  # remote_pytest reads this line (memory_history)
p=; u=; w=; { read -r p; read -r u; read -r w; } < "$B/peak" 2>/dev/null
[[ $p =~ ^[0-9]+$ ]] && echo "[remote-pytest] memory peak $((p / 1048576)) MiB"
[[ $u =~ ^[0-9]+$ && $w =~ ^[1-9][0-9]*$ ]] && echo "[remote-pytest] cpu $((u / 1000)) ms over $((w / 1000)) ms"
# warning only: what the job left directly in /tmp (the four TEMP-fallback browser tests did)
find /tmp -mindepth 1 -maxdepth 1 -user "$(id -u)" -newer "$L" ! -name 'rosy-pytest-*' \
  -printf '[remote-pytest] leaked into /tmp: %p\n' 2>/dev/null | head -n 20
exit $c
"""

# Job k is alive while the pid in <k>.pid (the lock's pid, but k-specific) answers kill -0.
ALIVE = r"""alive=0; if read -r pid < "$D/$K.pid" 2>/dev/null && kill -0 "$pid" 2>/dev/null; then alive=1; fi"""

# Same args as JOB with the JOB text inserted as $6. A retried start (dropped link) that finds the
# job's exit code or its live pid starts nothing.
START = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; D=$R/runs/$1.jobs; J=$6; K=$4
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] || { echo "[remote] venv hash mismatch" >&2; exit 1; }
mkdir -p ~/rosy-jobs "$D"; cd "$R/runs/$1"
""" + ALIVE + r"""
if [ -e "$D/$K.rc" ] || [ $alive = 1 ]; then exit 0; fi
set -- "$1" "$2" "$3" "$4" "$5" "${@:7}"
: > "$D/$4.log"  # exists before START returns, so the first poll finds it
setsid nohup bash -c "$J" job "$@" >> "$D/$4.log" 2>&1 < /dev/null &
"""

# The exit code is read before the log, so a poll that sees it also gets the whole log.
POLL = r"""D=~/rosy-test/runs/$1.jobs; K=$2; rc=; [ -f "$D/$2.rc" ] && rc=$(cat "$D/$2.rc")
""" + ALIVE + r"""
echo "ROSYJOB ${rc:--} $alive"; tail -c +$(($3 + 1)) "$D/$2.log"
"""

# SHIP: runs left behind after lost contact (an exit code, no live job, untouched for 2 h; the laptop
# fetches the log as the job ends, so a finished run holds nothing it still needs).
# Only <label>-<6 hex> runs that have a <run>.jobs dir, i.e. this runner's; never sim-* or anything else.
SWEEP = r"""for J in "$R"/runs/*-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].jobs; do
  [ -d "$J" ] && compgen -G "$J/*.rc" > /dev/null && [ -n "$(find "$J" -maxdepth 0 -mmin +120)" ] || continue
  n=$(basename "$J" .jobs); live=0
  case $n in sim-*) continue;; esac  # remote_sim.py runs clean up themselves
  for p in "$J"/*.pid ~/rosy-jobs/"$n".lock; do
    if [ -f "$p" ] && read -r q _ < "$p" && kill -0 "$q" 2>/dev/null; then live=1; fi
  done
  [ $live = 0 ] || continue
  echo "[remote] removing $n, left after lost contact" >&2
  chmod -R u+rwX -- "$R/runs/$n" "$J" 2>/dev/null || true  # tests leave read-only dirs; rm -rf cannot enter them
  git worktree remove -f -f "$R/runs/$n" 2>/dev/null || rm -rf "$R/runs/$n"
  git update-ref -d "refs/remote-pytest/$n" 2>/dev/null || true
  rm -rf "$J"
done  # SHIP runs git worktree prune next
"""

# Ctrl-C / laptop deadline: TERM the job's process group (setsid made its pid the group id).
KILL = r"""read -r pid _ < ~/rosy-jobs/"$1".lock 2>/dev/null && kill -TERM -- "-$pid" 2>/dev/null; true"""


LOST_EXIT = 255  # what land.py sees for an invocation whose host went silent
VANISHED_EXIT = 254  # the job ended without an exit code (host reboot, SIGKILL, START cut off)
CANCELLED = "cancelled"  # not an int: a cancelled invocation never reads as a pass or a cached result
ARGV_MAX = 8000  # remote command bytes passed as an ssh argument; ssh.exe cut at ~8,190 (measured 2026-10-26)


class Lost(Exception):
    """No contact with the host for the reconnect budget; the job keeps running there."""


def command(script: str, args, prefix: str = "") -> str:
    return prefix + "bash -c " + shlex.quote(script) + " remote " + " ".join(map(shlex.quote, args))


def argv_command(script: str, args, prefix: str = "") -> str:
    """command() for one ssh argument: Git for Windows' ssh.exe started from Python cuts its remote command at
    about 8,190 bytes without an error (2026-10-26), so a longer one is refused, never sent."""
    text = command(script, args, prefix)
    if len(text) > ARGV_MAX:
        raise SystemExit(f"[remote-pytest] remote command of {len(text)} bytes is over {ARGV_MAX}; send it on stdin")
    return text


def ssh_call(ssh: list[str], host: str, script: str, *args: str) -> subprocess.CompletedProcess | None:
    """One short ssh call, or None when the link failed (ssh exit 255, timeout).

    The command goes on stdin (argv_command's limit): a FULL landing's gate word dropped every pytest path after it."""
    command_text = command(script, args)
    try:
        result = subprocess.run([*ssh, host, "bash -s"], input=command_text.encode(), capture_output=True,
                                timeout=CALL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if result.returncode == 255 else result


def step(argv: list[str], timeout: float | None = None, **kw) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, timeout=timeout, **kw)`` that marks LAST_POLL every POLL_S while the child runs, so
    land_watchdog sees a long silent step (venv setup up to 3,600 s, size_range over thousands of commits) as alive.
    TimeoutExpired kills the child and is raised, as subprocess.run does."""
    global LAST_POLL
    data = kw.pop("input", None)
    if kw.pop("capture_output", False):
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if data is not None:
        kw["stdin"] = subprocess.PIPE
    deadline = None if timeout is None else time.monotonic() + timeout
    with subprocess.Popen(argv, **kw) as proc:
        while True:
            LAST_POLL = time.monotonic()
            wait = POLL_S if deadline is None else max(0.0, min(POLL_S, deadline - time.monotonic()))
            try:
                out, err = proc.communicate(data, timeout=wait)
                break
            except subprocess.TimeoutExpired:
                data = None  # written on the first call; a retry must not send it again
                if deadline is not None and time.monotonic() >= deadline:
                    proc.kill()
                    proc.communicate()
                    raise subprocess.TimeoutExpired(argv, timeout) from None
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


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


def parse_poll(out: bytes) -> tuple[int | None, bool, bytes] | None:
    """(exit code or None, job pid alive, new log bytes) from POLL output; None if malformed."""
    at = out.find(b"ROSYJOB ")  # login chatter before it is dropped
    end = out.find(b"\n", at)
    fields = out[at + 8:end].split()
    if at < 0 or end < 0 or len(fields) != 2:
        return None
    rc = fields[0]
    return (int(rc) if rc.lstrip(b"-").isdigit() else None), fields[1] == b"1", out[end + 1:]


def run(host: str, name: str, k: int, log: Path, job_args: list[str], pytest_args: list[str], timeout_s: int,
        ssh: list[str], call=ssh_call, sleep=time.sleep, clock=time.monotonic, budget: float | None = None,
        stop=None) -> int | str:
    """Start job k of run name on host and copy its log to log as it grows; its exit code.

    stop (a threading.Event): once set, the next poll that reaches the job TERMs it and returns CANCELLED.

    Raises Lost after budget s without contact, KeyboardInterrupt after TERMing the job.
    """
    budget = RECONNECT_S if budget is None else budget
    where = f"{host}:~/rosy-test/runs/{name}.jobs/{k}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes(b"")
    profile = job_args[3] if len(job_args) == 4 else None
    if len(job_args) not in (3, 4):
        raise SystemExit("[remote-pytest] invalid test-tools job context")
    body = remote_test_tools.render_job(JOB, profile)
    args = [*job_args[:3], str(k), str(timeout_s), body, *pytest_args]

    def poll():
        result = call(ssh, host, POLL, name, str(k), str(offset))
        return parse_poll(result.stdout) if result is not None and result.returncode == 0 else None

    offset, gone = 0, 0
    try:  # START too: Ctrl-C in its backoff must not leave a job running under the caller's cleanup
        started, lost = retrying(lambda: call(ssh, host, START, *args), "start", host, budget, sleep, clock)
        if started is None:
            raise Lost(f"[remote-pytest] lost contact with {host} for {lost:.0f} s while starting; "
                       f"the run may continue there: {where}")
        if started.returncode != 0:
            log.write_bytes(started.stdout + started.stderr)
            return started.returncode
        deadline = clock() + timeout_s + 120  # the job's own timeout fires first
        with log.open("ab") as out:
            while True:
                global LAST_POLL
                LAST_POLL = time.monotonic()  # progress for land_watchdog: a job is still being followed
                got, lost = retrying(poll, "poll", host, budget, sleep, clock)
                if got is None:
                    raise Lost(f"[remote-pytest] lost contact with {host} for {lost:.0f} s; "
                               f"the run continues there: {where}")
                rc, alive, data = got
                out.write(data)
                out.flush()
                offset += len(data)
                if rc is not None:
                    return rc
                gone = 0 if alive else gone + 1  # twice: the launch or the exit trap may be mid-way
                if gone == 2:
                    out.write(f"\n[remote-pytest] the job on {host} ended without an exit code (host reboot or"
                              f" killed); exit {VANISHED_EXIT}: {where}\n".encode())
                    return VANISHED_EXIT
                if clock() > deadline:
                    call(ssh, host, KILL, name)
                    return 124
                if stop is not None and stop.is_set():  # only a job this poll just saw; a lost one is left alone
                    call(ssh, host, KILL, name)
                    out.write(f"\n[remote-pytest] cancelled after a failure elsewhere: {where}\n".encode())
                    return CANCELLED
                sleep(POLL_S)
    except KeyboardInterrupt:
        call(ssh, host, KILL, name)  # as before: the caller's cleanup then removes the run
        raise
