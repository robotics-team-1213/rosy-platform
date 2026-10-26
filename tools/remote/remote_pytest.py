"""Run pytest for one commit on the model PC, AI PC or site PC (D-568), not on this laptop.

    python tools/remote/remote_pytest.py [--sha REV] [--log-dir DIR] [--affected-json FILE|-]
                                         [--skip PATH ...] [-- <pytest paths/args>]
    python tools/remote/remote_pytest.py --pick sim     # print the host a Gazebo run should use

Only the committed ``--sha`` (default HEAD) is tested: uncommitted changes are not
shipped. The commit travels as a git bundle (so guard tests that run git see a real
``.git``) into ``~/rosy-test/repo``, a clone of the public origin, and is checked out
as a detached worktree under ``~/rosy-test/runs/``, removed afterwards. Venvs
under ``~/rosy-test/venvs/<deps-sha>`` follow the CI install step
(``.github/workflows/ci.yml``); different dependency versions can run together.
Each pytest runs under a 6 GB memory cap, nice 15 and idle I/O, detached from ssh
(``remote_job.py``): the laptop follows its log with short polls and rides out a dropped
link for ``ROSY_TEST_RECONNECT`` s (default 600); past that the invocation exits 255 and the
job is left running on the host.

Hosts: ``ROSY_TEST_HOSTS`` (space separated), default model PC, AI PC, site PC. Each
host is measured (cores, load, memory, free disk, ``~/rosy-jobs/*.lock``, ``~/rosy-jobs/busy``)
and the ones above the class floor are used, most headroom first (a pytest host with 4-6 GB is light:
serial, capped at its free GB, smallest invocations); the site PC only when no other host qualifies (D-568).
An invocation gets pytest-xdist ``-n`` unless ``xdist_plan.py`` keeps it serial. Several invocations
share one queue over the chosen hosts (D-553): each host runs one at a time and takes the next
when free, largest test files first. Pytest never runs on this machine (D-584): when no host is reachable
the probe is retried every ``--retry-poll`` s (default 30) for ``--wait`` s (default 600), then the
gate fails with "no test host reachable (D-584)". ``--local`` and ``ROSY_TEST_LOCAL`` are rejected.
Logs land in ``--log-dir`` (default ``$ROSY_SCRATCH/remote-pytest/<sha>``, or the system
temp directory without ``ROSY_SCRATCH``), one
``run-<n>.txt`` per invocation. Exit code: the worst pytest exit (5, nothing
collected, counts as 0). Leading ``ROSY_*=value`` words of an invocation are its environment
on the host: ``-- ROSY_RUN_BROWSER_TESTS=1 <paths>`` runs the real-Chromium tests, and the job
installs Chromium for the venv's playwright first. Standard library only.
"""

from __future__ import annotations

import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[2] / "test"))
import known_failures  # noqa: E402
import lab_hosts  # noqa: E402
import memory_history  # noqa: E402
import remote_job  # noqa: E402
import remote_test_tools  # noqa: E402
from host_probe import DISK_FLOOR_GB, PROBE, disk_full, parse_probe  # noqa: E402,F401
import xdist_plan  # noqa: E402
from work_queue import ALONE_ENV, BROWSER_ENV, Gate, Work, cost, guard, wanted, workers  # noqa: E402,F401

CANCELLED = remote_job.CANCELLED

# A Windows console or pipe encodes with the legacy code page (cp1252), so printing a
# UTF-8 pytest tail that carries Korean operator text raised UnicodeEncodeError at the
# final print and threw away a finished run (2026-10-24). Unencodable characters become
# "?" instead; the on-disk logs stay byte-for-byte UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

# Live Fleet host: last resort, Fleet reserve, CPU cap (D-568 3).
# The address is ROSY_SITE_HOST, else gitignored private/lab-hosts.json (D-226).
_LAB = lab_hosts.load()
SITE_HOST = os.environ.get("ROSY_SITE_HOST", "").strip() or str(_LAB.get("site_host") or "").strip()
# Site hosts: SITE_HOST plus every host whose probe finds ~/rosy-jobs/site (any ssh name).
SITES = {SITE_HOST} if SITE_HOST else set()
_FILE_HOSTS = _LAB.get("test_hosts") or []
if not isinstance(_FILE_HOSTS, list):
    raise SystemExit("lab-hosts.json test_hosts must be a list")
DEFAULT_HOSTS = " ".join(str(item).strip() for item in _FILE_HOSTS if str(item).strip())
# Tailscale profile (`tailscale switch --list` ID) the test PCs are on; absent -> not checked.
TAILSCALE_PROFILE = str(_LAB.get("tailscale_profile") or "").strip()
# D-568 2: (free cores, free GB) a host needs for one job of the class.
NEEDS = {"pytest": (2, 6), "sim": (6, 8)}
# A host with this many GB (under NEEDS) is "light": serial, MemoryMax = its free GB, smallest invocations first.
LIGHT_GB = {"pytest": 4}
HEADROOM: dict[str, dict] = {}  # place(): measured free cores/GB of each placed host, for xdist_plan
SITE_RESERVE = (2, 4)
SITE_CPU_QUOTA = "400%"
# Seconds a placement reservation (~/rosy-jobs/<name>.resv) counts before the job lock replaces it:
# pytest waits up to 600 s for the repo lock and 3600 s for a venv build; --pick gives the script 10 min.
RESERVE_S = {"pytest": 4500, "pick": 600}
PUBLIC = "https://github.com/robotics-team-1213/rosy-platform.git"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
       "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
# --rootdir=. (the run worktree): node ids stay repo-relative; without it the first arg's nearest
# pyproject.toml (even one with no pytest section) became rootdir and FAILED ids lost their root.
ROOTDIR = "--rootdir=."
PYTEST_TAIL = ["-q", "-rfE", "-p", "no:cacheprovider", ROOTDIR, *known_failures.NO_ROS_LAUNCH_PLUGINS]
# Leading words of an invocation that remote_job.JOB exports instead of passing to pytest.
ENV_ARG = re.compile(r"^ROSY_[A-Z0-9_]*=")
CI = ".github/workflows/ci.yml"
DEVICE_REQ = "deploy/robot/pinky_pro/image/device-python-requirements.txt"
CRYPTO_REQ = "deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt"
FLEET_REQ = "deploy/site/requirements-fleet.txt"
VISION_REQ = "deploy/site/requirements-vision.txt"
TAIL_LINES = 25
# Seconds before one pytest invocation counts as hung (a failure).
PYTEST_TIMEOUT = int(os.environ.get("ROSY_TEST_TIMEOUT", "5400"))
# D-584: how long run() waits for a test host before failing, and the poll interval (seconds).
WAIT_S, POLL_S = 600.0, 30.0
STEP_TIMEOUT = {"ship": 900, "venv": 3600, "cleanup": 120}

# Fetch public main, unpack the bundle (stdin), check the commit out. Exit 3 = the
# bundle's prerequisite commit is missing there; the caller resends a full bundle.
SHIP = r"""set -euo pipefail
R=~/rosy-test; NAME=$1; SHA=$2
umask 022  # the checkout keeps git modes; 0002 would leave 0664 files for mode-asserting tests
mkdir -p ~/rosy-jobs; echo "$(( $(date +%s) + $4 )) pytest 2 6" > ~/rosy-jobs/"$NAME".resv  # D-568 2
mkdir -p "$R/runs"
trap 'rm -f "$R/runs/$NAME.bundle"' EXIT
# Read the bundle before taking the lock, bounded: a half-open link once left `cat` holding it for hours.
timeout 600 cat > "$R/runs/$NAME.bundle"
exec 8>"$R/repo.lock"  # concurrent runs fetching into one repo race on ref locks
flock -w 600 8 || { echo "[remote] $R/repo.lock still held after 600 s (lsof it)" >&2; exit 1; }
[ -d "$R/repo/.git" ] || git clone -q --no-checkout "$3" "$R/repo"
cd "$R/repo"
git fetch -q "$3" +refs/heads/main:refs/remotes/origin/main || echo "[remote] fetching public main failed" >&2
git bundle verify -q "$R/runs/$NAME.bundle" >/dev/null 2>&1 || exit 3
git fetch -q "$R/runs/$NAME.bundle" "+refs/remote-pytest/$NAME:refs/remote-pytest/$NAME"
""" + remote_job.SWEEP + r"""chmod -R u+rwX -- "$R/runs/$NAME" 2>/dev/null || true
git worktree remove -f -f "$R/runs/$NAME" 2>/dev/null || rm -rf "$R/runs/$NAME"  # a retried ship; -f -f: locked
git worktree prune
git worktree add -q --detach "$R/runs/$NAME" "$SHA"
"""

# The CI test-job install (ci.yml "Install colcon & tools", receiver crypto, platform
# wheels) plus the deploy/site/requirements-fleet.txt pins the device set lacks
# (cryptography 50: Ubuntu's 41 has no x509.verification) and pip numpy/pillow/
# opencv-python-headless for CI's apt python3-opencv/python3-pil, and the playwright
# package because *_browser.py modules import it at collection (Chromium: remote_job.JOB). No system
# site-packages: they leak Ubuntu's old cryptography/Jinja2 and give no rclpy.
# Each dependency hash has its own venv and lock. Old ~/rosy-test/venv remains for
# other sessions that use it directly; a new hash never waits for their tests.
VENV = remote_test_tools.VENV

# --pick: reserve the class budget on the chosen host until the Gazebo script writes its own lock.
RESERVE = r"""mkdir -p ~/rosy-jobs; echo "$(( $(date +%s) + $4 )) $1 $2 $3" > ~/rosy-jobs/pick-$(date +%s%N).resv"""

CLEANUP = r"""R=~/rosy-test
rm -f ~/rosy-jobs/"$1".lock ~/rosy-jobs/"$1".resv
# Release/rollback tests leave read-only dirs (product behaviour); without u+w rm -rf leaves them behind.
chmod -R u+rwX -- "$R/runs/$1" "$R/runs/$1.jobs" 2>/dev/null || true
git -C "$R/repo" worktree remove --force "$R/runs/$1" 2>/dev/null || rm -rf "$R/runs/$1"
git -C "$R/repo" worktree prune
git -C "$R/repo" update-ref -d "refs/remote-pytest/$1" 2>/dev/null || true
rm -rf "$R/runs/$1.bundle" "$R/runs/$1.jobs"
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def capped(host: str) -> str:
    """Command prefix for repo copy, venv build and cleanup: low priority, site hosts also capped (D-568 3-4)."""
    scope = (f"systemd-run --user --scope -q -p MemoryMax=6G -p CPUQuota={SITE_CPU_QUOTA} -- "
             if host in SITES else "")
    return scope + "nice -n 15 ionice -c3 "


def remote(host: str, script: str, *args: str, timeout: float, **kw) -> subprocess.CompletedProcess:
    """Run script on host under capped(host); a timeout is a failed step (exit 124), never a pass."""
    command = capped(host) + "bash -c " + shlex.quote(script) + " remote " + " ".join(map(shlex.quote, args))
    if "input" not in kw:
        kw["stdin"] = subprocess.DEVNULL
    try:
        return subprocess.run([*SSH, host, command], timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        print(f"[remote-pytest] {host}: step timed out after {timeout:.0f} s", file=sys.stderr, flush=True)
        return subprocess.CompletedProcess([], 124, b"", b"")


def probe(host: str) -> dict | None:
    """Measured headroom inputs of host (PROBE), or None when it does not answer."""
    try:
        out = subprocess.run([*SSH, host, "bash -c " + shlex.quote(PROBE)], stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_probe(out)


def place(cls: str, hosts: list[str], probes: list[dict | None]) -> tuple[list[str], list[str]]:
    """(hosts above the cls floor, most headroom first, light ones after, the site PC only when no other fits; notes)."""
    need_c, need_m = NEEDS[cls]
    floor_m = LIGHT_GB.get(cls, need_m)
    ranked, notes = [], []
    for i, (host, p) in enumerate(zip(hosts, probes)):
        if p is None:
            notes.append(f"{host}: unreachable")
            continue
        site = host in SITES or p.get("site", False)
        cores = p["nproc"] - max(p["load1"], p["lock_cores"]) - (SITE_RESERVE[0] if site else 0)
        mem = min(p["avail_gb"], p["total_gb"] - p["lock_gb"]) - (SITE_RESERVE[1] if site else 0)
        why = ("marked busy (~/rosy-jobs/busy)" if p["busy"] else f"no {cls} capability" if not p[cls]
               else f"below disk floor {DISK_FLOOR_GB} GB" if disk_full(p)
               else f"below {cls} floor {need_c} cores/{floor_m} GB" if cores < need_c or mem < floor_m
               else f"light (under {need_m} GB): serial, smallest invocations" if mem < need_m else "ok")
        disk = f", disk {p['disk_free_gb']:.1f} GB free ({p['disk_use']}%)" if "disk_free_gb" in p else ""
        stale = f"; busy marker {p['busy_ignored']} (ignored)" if p.get("busy_ignored") else ""
        notes.append(f"{host}: {cores:.1f} cores, {mem:.1f} GB free{disk}{' (site PC)' if site else ''} - {why}{stale}")
        if why == "ok" or why.startswith("light"):
            HEADROOM[host] = {"cores": cores, "mem": mem, "site": site, "light": mem < need_m,
                              "sim_held": p.get("sim_held", 0), "browser_jobs": p.get("browser_jobs", 0)}
            ranked.append((site, mem < need_m, -min(cores / need_c, mem / need_m), i, host))
    ranked.sort()
    return [r[-1] for r in ranked if not r[0]] or [r[-1] for r in ranked], notes


LOCAL_REFUSED = ("[remote-pytest] {what} is removed (D-584): tests never run on the operator laptop."
                 " Wait for a test host or report the tests as not run.")


def refuse_local() -> None:
    """D-584: a leftover ROSY_TEST_LOCAL is an error, not a silent pass."""
    if os.environ.get("ROSY_TEST_LOCAL") is not None:
        raise SystemExit(LOCAL_REFUSED.format(what="ROSY_TEST_LOCAL"))


def current_profile(listing: str) -> list[str]:
    """`tailscale switch --list` -> the columns of the row marked `*` (ID first), [] if none."""
    for line in listing.splitlines()[1:]:
        if "*" in line:
            return line.replace("*", " ").split()
    return []


def check_tailscale_profile(expected: str | None = None, which=shutil.which, run=subprocess.run) -> None:
    """Fail fast when this PC's Tailscale profile is not the one the test PCs are on. Never switches it.

    An explicit ROSY_TEST_HOSTS is a manual override: those hosts may be on any tailnet."""
    expected = TAILSCALE_PROFILE if expected is None else expected
    if not expected or os.environ.get("ROSY_TEST_HOSTS") is not None or not which("tailscale"):
        return
    try:
        listing = run(["tailscale", "switch", "--list"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"[remote-pytest] tailscale profile not checked: {error}", file=sys.stderr, flush=True)
        return
    current = current_profile(listing.stdout or "")
    if listing.returncode == 0 and current and expected not in current:
        raise SystemExit(f"[remote-pytest] wrong Tailscale profile: current {current[0]} ({' '.join(current[1:])}),"
                         f" expected {expected} (lab-hosts.json tailscale_profile); the test PCs are not on this"
                         f" tailnet. Switch by hand: tailscale switch {expected}")


def placed_hosts(cls: str = "pytest", hosts: list[str] | None = None) -> list[str]:
    """Hosts for cls by measured headroom (D-568), printing why; empty when none fits."""
    refuse_local()
    check_tailscale_profile()
    if hosts is None:
        hosts = os.environ.get("ROSY_TEST_HOSTS", DEFAULT_HOSTS).split()
    if not hosts:
        print(f"[remote-pytest] {cls} -> no host: set ROSY_TEST_HOSTS or copy "
              "tools/remote/hosts.example.json to private/lab-hosts.json",
              file=sys.stderr, flush=True)
        return []
    with ThreadPoolExecutor(len(hosts)) as pool:
        probes = list(pool.map(probe, hosts))
    SITES.update(h for h, p in zip(hosts, probes) if p and p.get("site"))
    chosen, notes = place(cls, hosts, probes)
    for note in notes:
        print(f"[remote-pytest] {note}", file=sys.stderr, flush=True)
    if not chosen and cls == "pytest":
        # D-568 7: busy hosts must not stop the gate; the site PC and a full disk never take this fallback.
        chosen = [h for h, p in zip(hosts, probes)
                  if p and p["pytest"] and not p["busy"] and not disk_full(p) and h not in SITES]
        if chosen:
            print("[remote-pytest] WARNING: no host above the pytest floor; using the reachable ones anyway",
                  file=sys.stderr, flush=True)
    print(f"[remote-pytest] {cls} -> {' '.join(chosen) or 'no host'}", file=sys.stderr, flush=True)
    return chosen


def bundle_base(repo: Path, sha: str) -> str | None:
    """The commit the remote is expected to have already: sha's merge base with origin/main."""
    result = subprocess.run(["git", "-C", str(repo), "merge-base", sha, "origin/main"],
                            capture_output=True, text=True)
    return result.stdout.strip() or None


def deps(repo: Path, sha: str, test_tools: str | None = None) -> tuple[str, list[str]]:
    """(hash of the CI install inputs at sha, the platform wheel dirs ci.yml builds)."""
    remote_test_tools.validate(test_tools)
    ci = git(repo, "show", f"{sha}:{CI}")
    match = re.search(r'--wheel-dir "\$wheelhouse" \\\n\s*(.+)', ci)
    if not match:
        raise SystemExit(f"[remote-pytest] no `pip3 wheel ... --wheel-dir` line in {CI}; update VENV")
    dirs = match.group(1).split()
    ids = [git(repo, "rev-parse", f"{sha}:{p}") for p in (CI, DEVICE_REQ, CRYPTO_REQ, FLEET_REQ, VISION_REQ, *dirs)]
    # Lock/swap changes do not change installed packages or need another venv build.
    install = VENV.split("UV=", 1)[1].split('echo "$DEPS"', 1)[0]
    key = hashlib.sha256("\n".join([install, *ids]).encode()).hexdigest()[:16]
    if test_tools:
        blob = "\n".join(git(repo, "rev-parse", f"{sha}:{path}")
                         for path in remote_test_tools.inputs(test_tools))
        key = remote_test_tools.identity(key, blob, profile=test_tools)
    return key, dirs


def ship(repo: Path, host: str, sha: str, name: str) -> None:
    ref = f"refs/remote-pytest/{name}"
    git(repo, "update-ref", ref, sha)
    try:
        base0 = bundle_base(repo, sha)
        # A sha that is the base or behind it gives an empty bundle, which git refuses.
        if base0 and subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, base0]).returncode == 0:
            base0 = None
        for base in (base0, None):
            data = subprocess.run(["git", "-C", str(repo), "bundle", "create", "-", ref,
                                   *([f"^{base}"] if base else [])], capture_output=True, check=True).stdout
            for attempt in range(3):  # a dropped link (ssh 255) ships again from scratch
                result = remote(host, SHIP, name, sha, PUBLIC, str(RESERVE_S["pytest"]), input=data,
                                capture_output=True, timeout=STEP_TIMEOUT["ship"])
                if result.returncode != 255 or attempt == 2:
                    break
                print(f"[remote-pytest] shipping to {host} lost the link; retrying", file=sys.stderr, flush=True)
                time.sleep(remote_job.BACKOFF[attempt])
            if result.returncode == 0:
                return
            if result.returncode != 3 or not base:
                raise SystemExit(f"[remote-pytest] shipping {sha[:10]} to {host} failed (exit {result.returncode}):\n"
                                 + result.stderr.decode(errors="replace"))
            print(f"[remote-pytest] {host} lacks {base[:10]}; sending the full history", flush=True)
    finally:
        git(repo, "update-ref", "-d", ref)


def capture(command: list[str], log: Path, cwd: Path | None = None) -> int:
    """Run, write all output to log, print the tail; return the exit code."""
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1"},
                              timeout=PYTEST_TIMEOUT)
        code, out = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        code, out = 124, (exc.stdout or b"") + f"\n[remote-pytest] timed out after {PYTEST_TIMEOUT} s\n".encode()
    text = out.decode("utf-8", errors="replace")
    log.write_text(text, encoding="utf-8")
    print("".join(collections.deque(text.splitlines(keepends=True), TAIL_LINES)), end="", flush=True)
    return code


def run(invocations: list[list[str]], logs: list[Path], sha: str = "HEAD", repo: Path | None = None,
        label: str | None = None, wait: float = WAIT_S, poll: float = POLL_S, sleep=time.sleep,
        clock=time.monotonic, test_tools: str | None = None, on_done=None) -> list[int | str]:
    """Run each pytest invocation for commit sha on a test host; one exit code per invocation.

    No host: retry every poll s for up to wait s, then fail (D-584); never runs pytest here.
    on_done(invocation, log_path) -> bool is asked after each finished invocation (not a lost one); True or an
    exception cancels the rest: queued ones never start, visible running jobs are TERMed, both come back CANCELLED.
    """
    remote_test_tools.validate(test_tools)
    refuse_local()
    repo = Path(git(repo or Path.cwd(), "rev-parse", "--show-toplevel"))
    sha = git(repo, "rev-parse", f"{sha}^{{commit}}")
    if not invocations:
        return []
    deadline = clock() + wait
    hosts = placed_hosts("pytest")
    while not hosts:
        if clock() + poll > deadline:
            raise SystemExit(f"[remote-pytest] no test host reachable (D-584) after {wait:.0f} s;"
                             " the tests did not run. Report them as not run; do not land or push.")
        print(f"[remote-pytest] no test host reachable; retrying in {poll:.0f} s (D-584)", file=sys.stderr, flush=True)
        sleep(poll)
        hosts = placed_hosts("pytest")
    plan = workers(hosts[:len(invocations)], invocations, HEADROOM)  # (host, kind): browser lanes beside main
    if len(plan) == 1:
        codes = run_on(plan[0][0], invocations, logs, sha, repo, label,
                       **({"test_tools": test_tools} if test_tools else {}), **({"on_done": on_done} if on_done else {}))
        return cancelled(invocations, codes) if on_done else codes
    # D-553 4: every host ships and builds its venv once, then takes the next invocation when free.
    work = Work(sorted(range(len(invocations)), key=lambda i: -cost(repo, invocations[i])), on_done)
    gates = {host: Gate() for host, _ in plan}

    def attempt(slot):
        host, kind = slot
        try:
            run_on(host, invocations, logs, sha, repo, label, work, kind=kind, gate=gates[host],
                   **({"test_tools": test_tools} if test_tools else {}))
            return True
        except SystemExit as error:  # ship/venv failed; pytest failures are exit codes, not this
            print(f"[remote-pytest] {host} failed ({error}); the other hosts take its invocations",
                  file=sys.stderr, flush=True)
            return False

    with ThreadPoolExecutor(len(plan)) as pool:
        ok = list(pool.map(attempt, plan))
    while work.todo and not work.stop.is_set():  # handed back after a mid-run failure, or left by a lost host, once the rest were done
        working = [h for (h, _), good in zip(plan, ok) if good and h not in work.lost]
        if not working:
            if not any(ok):
                raise SystemExit("[remote-pytest] every test host failed to set up")
            for i in work.todo:  # the only hosts that set up went silent: as run_on reports a lost host
                work.codes[i] = remote_job.LOST_EXIT
            break
        run_on(working[0], invocations, logs, sha, repo, label, work,
               **({"test_tools": test_tools} if test_tools else {}))
    if on_done:
        return cancelled(invocations, [work.codes.get(i) for i in range(len(invocations))])
    return [work.codes[i] for i in range(len(invocations))]


def cancelled(invocations: list[list[str]], codes: list) -> list[int | str]:
    """codes with every invocation that never ran (None) marked CANCELLED, each one printed."""
    for inv, code in zip(invocations, codes):
        if code in (None, CANCELLED):
            print(f"[remote-pytest] cancelled after a failure: {' '.join(inv)}", flush=True)
    return [CANCELLED if code is None else code for code in codes]


def quarantine(repo: Path, sha: str) -> dict[str, str]:
    """test/flaky_quarantine.txt as committed at sha (D-762 stage 1); empty when absent."""
    result = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:test/flaky_quarantine.txt"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return known_failures.load_known(result.stdout) if result.returncode == 0 else {}


def run_on(host: str, invocations: list[list[str]], logs: list[Path], sha: str, repo: Path,
           label: str | None, work: Work | None = None, test_tools: str | None = None, on_done=None,
           kind: str = "any", gate: Gate | None = None) -> list[int]:
    """Run invocations on host, one at a time; one exit code per invocation.

    With a shared work (run() over several hosts) the host takes indices from it until none is left or the
    host is lost; an index that raises mid-run goes back for another host. Codes land in work.codes."""
    remote_test_tools.validate(test_tools)
    shared = work is not None
    work = work or Work(range(len(invocations)), on_done)
    name = f"{label or sha[:10]}-{secrets.token_hex(3)}"
    print(f"[remote-pytest] {sha[:10]} on {host} (~/rosy-test/runs/{name})", flush=True)
    lost = None
    try:
        ship(repo, host, sha, name)
        deps_sha, dirs = deps(repo, sha, test_tools=test_tools) if test_tools else deps(repo, sha)
        if test_tools:
            blobs = ",".join(git(repo, "rev-parse", f"{sha}:{path}")
                             for path in remote_test_tools.inputs(test_tools))
            field = "raw-blob" if test_tools == remote_test_tools.PROFILE else "input-blobs"
            print(f"[remote-pytest] test-tools={test_tools} tested={sha} deps={deps_sha} {field}={blobs}", flush=True)
        recipe = remote_test_tools.render_setup(VENV, test_tools)
        if remote(host, recipe, name, deps_sha, *dirs, timeout=STEP_TIMEOUT["venv"]).returncode != 0:
            raise SystemExit(f"[remote-pytest] venv setup on {host} failed")
        cpu = SITE_CPU_QUOTA if host in SITES else ""
        k = 0  # job number on this host's run dir
        pick = wanted(kind, invocations)
        take = work.take_small if HEADROOM.get(host, {}).get("light") else lambda: work.take(pick)
        while not (lost and shared) and (i := take()) is not None:
            inv, log = invocations[i], logs[i]
            print(f"[remote-pytest] pytest {' '.join(inv)}  -> {log}", flush=True)
            if lost:
                work.codes[i] = remote_job.LOST_EXIT
                continue
            try:
                context = [name, deps_sha, cpu, *([test_tools] if test_tools else [])]
                with guard(gate, kind, inv):
                    work.codes[i], lost = one(host, name, k, inv, log, context, repo, sha,
                                              **({"stop": work.stop} if work.on_done else {}))
            except BaseException:
                work.give_back(i)  # never dropped: another host (or run()'s fallback) runs it
                raise
            k += 1
            if not lost and work.codes[i] != CANCELLED:
                work.done(inv, log)
        if lost:
            work.lost.add(host)
        return [work.codes.get(i) for i in range(len(invocations))]
    finally:
        if lost:  # never kill or clean up a job we cannot see; its own trap drops the lock when it ends
            print(f"[remote-pytest] left ~/rosy-test/runs/{name} on {host}; remove it when the job is done",
                  file=sys.stderr, flush=True)
        else:
            remote(host, CLEANUP, name, capture_output=True, timeout=STEP_TIMEOUT["cleanup"])


def one(host: str, name: str, k: int, inv: list[str], log: Path, job: list[str], repo: Path,
        sha: str, **stop) -> tuple[int | str, str | None]:
    """(exit code, lost message or None) of invocation inv as job k of run dir name on host."""
    words, extra, note = xdist_plan.plan(inv, HEADROOM.get(host))
    history = memory_history.path(repo)
    reserve = memory_history.reserve_gb(history, inv)
    if reserve < xdist_plan.JOB_MEM_GB and not any(w.startswith("ROSY_JOB_MEM_GB=") for w in words):
        words = [*words, f"ROSY_JOB_RESERVE_GB={reserve}"]  # light hosts already reserve their smaller cap
        note += f", reserve {reserve} GB (memory history)"
    print(f"[remote-pytest] {note}", flush=True)
    try:
        code = remote_job.run(host, name, k, log, job, [*words, *inv, *extra, *PYTEST_TAIL], PYTEST_TIMEOUT, SSH, **stop)
    except remote_job.Lost as error:
        print(error, file=sys.stderr, flush=True)
        return remote_job.LOST_EXIT, str(error)
    if code == CANCELLED:
        return code, None
    text = log.read_bytes().decode("utf-8", errors="replace")
    print("".join(collections.deque(text.splitlines(keepends=True), TAIL_LINES)), end="", flush=True)
    if (peak := memory_history.peak_mib(text)) is not None:
        memory_history.record(history, inv, host, peak, sha)
    failed = known_failures.failed_ids(text)
    ids = known_failures.rerun_ids(text, quarantine(repo, sha)) if code == 1 and failed else []
    if not known_failures.should_rerun(code, failed, ids):  # D-762 stage 1: once, listed ids only
        return code, None
    print(f"[remote-pytest] rerunning {len(ids)} quarantined failure(s) once", flush=True)
    rerun, lost = log.with_name(log.stem + "-rerun.txt"), None
    try:
        env = [*words, *itertools.takewhile(ENV_ARG.match, inv)]  # serial: ids, never -n
        rerun_code = remote_job.run(host, name, f"{k}r", rerun, job, [*env, *ids, "-q", "-rA", "-p", "no:cacheprovider", ROOTDIR],
                                    PYTEST_TIMEOUT, SSH, **stop)
    except remote_job.Lost as error:
        lost, rerun_code = str(error), remote_job.LOST_EXIT
        print(lost, file=sys.stderr, flush=True)
    section = rerun.read_bytes() if rerun.is_file() else b"[remote-pytest] rerun lost\n"
    with log.open("ab") as out:
        out.write(f"\n{known_failures.RERUN_MARKER}\n".encode() + section)
    if known_failures.rerun_passed(code, failed, ids, rerun_code, section.decode("utf-8", errors="replace")):
        print(f"[remote-pytest] FLAKY (passed on rerun): {' '.join(ids)}", flush=True)
        code = 0  # pre-push reads this exit code
    return code, lost


def affected_invocations(selection: dict, skip: set[str]) -> list[list[str]]:
    """`rosy_harness.py affected --json` -> invocations, as `affected --run` picks them."""
    invocations = selection["local_invocations" if selection["mode"] == "full" else "invocations"]
    return [kept for kept in ([p for p in inv if p not in skip] for inv in invocations) if kept]


def worst(codes: list[int]) -> int:
    """Any failure is nonzero: 5 (nothing collected) passes, a signal (negative code) fails."""
    return max((0 if c == 5 else 1 if c < 0 else c for c in codes), default=0)


def log_root(name: str) -> Path:
    """$ROSY_SCRATCH/<name>, else the system temp directory."""
    return Path(os.environ.get("ROSY_SCRATCH") or tempfile.gettempdir()) / name


def default_log_dir(sha: str) -> Path:
    base = os.environ.get("ROSY_TEST_LOGS") or log_root("remote-pytest")
    return Path(base) / sha[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", default="HEAD", help="commit to test (default HEAD)")
    parser.add_argument("--test-tools", choices=[remote_test_tools.PROFILE, remote_test_tools.SD_PROFILE],
                        help="optional native test dependency profile")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--affected-json", help="`rosy_harness.py affected --json` output file, or -")
    parser.add_argument("--skip", action="append", default=[], help="drop this path from the affected set")
    parser.add_argument("--local", action="store_true", help=argparse.SUPPRESS)  # removed, rejected (D-584)
    parser.add_argument("--require-host", action="store_true", help="no-op: always the behaviour (D-584)")
    parser.add_argument("--wait", type=float, default=WAIT_S, help="seconds to wait for a test host (default 600)")
    parser.add_argument("--retry-poll", type=float, default=POLL_S, help="seconds between host probes (default 30)")
    parser.add_argument("--pick", choices=sorted(NEEDS),
                        help="only print the host with the most headroom for this job class (D-568)")
    parser.add_argument("pytest_args", nargs="*", help="one pytest invocation (after --)")
    args = parser.parse_args(argv)
    if args.local:
        raise SystemExit(LOCAL_REFUSED.format(what="--local"))
    if args.pick:
        chosen = placed_hosts(args.pick)
        if chosen:
            remote(chosen[0], RESERVE, args.pick, *map(str, NEEDS[args.pick]), str(RESERVE_S["pick"]),
                   capture_output=True, timeout=STEP_TIMEOUT["cleanup"])
            print(chosen[0])
        return 0 if chosen else 1
    invocations = [args.pytest_args] if args.pytest_args else []
    if args.affected_json:
        text = sys.stdin.read() if args.affected_json == "-" else Path(args.affected_json).read_text("utf-8")
        invocations += affected_invocations(json.loads(text), set(args.skip))
    sha = git(Path.cwd(), "rev-parse", f"{args.sha}^{{commit}}")
    log_dir = args.log_dir or default_log_dir(sha)
    logs = [log_dir / f"run-{i}.txt" for i in range(1, len(invocations) + 1)]
    codes = run(invocations, logs, sha, wait=args.wait, poll=args.retry_poll,
                **({"test_tools": args.test_tools} if args.test_tools else {}))
    for inv, code, log in zip(invocations, codes, logs):
        print(f"[remote-pytest] exit {code}: {' '.join(inv)} ({log})")
    return worst(codes)


if __name__ == "__main__":
    sys.exit(main())
