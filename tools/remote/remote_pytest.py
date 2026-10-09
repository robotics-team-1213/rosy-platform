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
Each pytest runs under a 6 GB memory cap, nice 15 and idle I/O.

Hosts: ``ROSY_TEST_HOSTS`` (space separated), default model PC, AI PC, site PC. Each
host is measured (cores, load, memory, ``~/rosy-jobs/*.lock``, ``~/rosy-jobs/busy``)
and the ones above the class floor are used, most headroom first; the site PC only
when no other host qualifies (D-568). Several invocations are spread over the chosen
hosts at once (D-553). A missing host fails the gate; ``--local`` or ``ROSY_TEST_LOCAL=1``
is for explicit diagnostics.
Logs land in ``--log-dir`` (default ``X:/DevTemp/remote-pytest/<sha>``), one
``run-<n>.txt`` per invocation. Exit code: the worst pytest exit (5, nothing
collected, counts as 0). Standard library only.
"""

from __future__ import annotations

import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

SITE_HOST = "robttt@100.82.51.8"  # live Fleet: last, Fleet reserve, CPU cap (D-568 3)
DEFAULT_HOSTS = f"rosy@100.98.162.71 ai@100.108.76.123 {SITE_HOST}"
# D-568 2: (free cores, free GB) a host needs for one job of the class.
NEEDS = {"pytest": (2, 6), "sim": (6, 8)}
SITE_RESERVE = (2, 4)
SITE_CPU_QUOTA = "400%"
PUBLIC = "https://github.com/robotics-team-1213/rosy-platform.git"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
       "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4"]
PYTEST_TAIL = ["-q", "-rfE", "-p", "no:cacheprovider"]
CI = ".github/workflows/ci.yml"
DEVICE_REQ = "deploy/robot/pinky_pro/image/device-python-requirements.txt"
CRYPTO_REQ = "deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt"
FLEET_REQ = "deploy/site/requirements-fleet.txt"
TAIL_LINES = 25
# Seconds before one pytest invocation counts as hung (a failure).
PYTEST_TIMEOUT = int(os.environ.get("ROSY_TEST_TIMEOUT", "5400"))
STEP_TIMEOUT = {"ship": 900, "venv": 3600, "cleanup": 120}

# Fetch public main, unpack the bundle (stdin), check the commit out. Exit 3 = the
# bundle's prerequisite commit is missing there; the caller resends a full bundle.
SHIP = r"""set -euo pipefail
R=~/rosy-test; NAME=$1; SHA=$2
mkdir -p "$R/runs"
trap 'rm -f "$R/runs/$NAME.bundle"' EXIT
exec 8>"$R/repo.lock"; flock -w 600 8  # concurrent runs fetching into one repo race on ref locks
[ -d "$R/repo/.git" ] || git clone -q --no-checkout "$3" "$R/repo"
cd "$R/repo"
git fetch -q "$3" +refs/heads/main:refs/remotes/origin/main || echo "[remote] fetching public main failed" >&2
cat > "$R/runs/$NAME.bundle"
git bundle verify -q "$R/runs/$NAME.bundle" >/dev/null 2>&1 || exit 3
git fetch -q "$R/runs/$NAME.bundle" "+refs/remote-pytest/$NAME:refs/remote-pytest/$NAME"
git worktree add -q --detach "$R/runs/$NAME" "$SHA"
"""

# The CI test-job install (ci.yml "Install colcon & tools", receiver crypto, platform
# wheels) plus the deploy/site/requirements-fleet.txt pins the device set lacks
# (cryptography 50: Ubuntu's 41 has no x509.verification) and pip numpy/pillow/
# opencv-python-headless for CI's apt python3-opencv/python3-pil, and the playwright
# package (no browser) because *_browser.py modules import it at collection. No system
# site-packages: they leak Ubuntu's old cryptography/Jinja2 and give no rclpy.
# Each dependency hash has its own venv and lock. Old ~/rosy-test/venv remains for
# other sessions that use it directly; a new hash never waits for their tests.
VENV = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; N=$R/venvs/.new-$DEPS; cd "$R/runs/$1"; shift 2
mkdir -p "$R/venvs"
exec 9>"$R/venvs/$DEPS.lock"; flock -x -w 600 9
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] && exit 0
echo "[remote] building $N (CI install inputs changed)"
rm -rf "$N"
# The site PC (Ubuntu 26.04) has no system 3.12; `uv python install 3.12` puts one in ~/.local/bin.
PY=/usr/bin/python3; "$PY" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null || PY=~/.local/bin/python3.12
UV=$(command -v uv || ls ~/.local/bin/uv 2>/dev/null || true)
if [ -n "$UV" ]; then "$UV" venv -q --seed -p "$PY" "$N"
else "$PY" -m venv "$N"; fi
P="$N/bin/python -m pip -q --disable-pip-version-check --no-cache-dir"
REQ=deploy/robot/pinky_pro/image/device-python-requirements.txt
$P install --require-hashes --no-deps --only-binary=:all: -r "$REQ"
grep -o '^[A-Za-z0-9._-]*==[^ ]*' "$REQ" > "$N/constraints.txt"
norm() { tr 'A-Z_.' 'a-z--'; }
cut -d= -f1 "$N/constraints.txt" | norm > "$N/pinned.txt"
while read -r line; do
  grep -qx "$(printf %s "${line%%==*}" | norm)" "$N/pinned.txt" || echo "$line"
done < deploy/site/requirements-fleet.txt > "$N/fleet-extra.txt"
$P install -c "$N/constraints.txt" -r "$N/fleet-extra.txt" pytest setuptools wheel flake8 httpx pyyaml \
  jsonschema ext4 numpy pillow opencv-python-headless playwright
$P install --require-hashes --no-deps --only-binary=:all: \
  --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  --target "$N/receiver-crypto" -r deploy/robot/pinky_pro/image/receiver-crypto-requirements.txt
$P wheel --no-deps --no-build-isolation --wheel-dir "$N/wheelhouse" "$@"
$P install --no-deps --no-index "$N"/wheelhouse/*.whl
$P check
echo "$DEPS" > "$N/.deps-sha"
grep -rlI --exclude-dir=__pycache__ "$N" "$N/bin" | xargs -r sed -i "s|$N|$V|g"
mv "$N" "$V"
echo "[remote] ready $V"
"""

# $3 = CPUQuota ('' = none). The job lock holds this shell's pid, which exec keeps.
PYTEST = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; CPU=$3; cd "$R/runs/$1"
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] || { echo "[remote] venv hash mismatch" >&2; exit 1; }
mkdir -p ~/rosy-jobs; echo "$$ pytest 2 6" > ~/rosy-jobs/"$1".lock; shift 3
export PYTHONPATH="$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1
exec systemd-run --user --scope -q -p MemoryMax=6G ${CPU:+-p CPUQuota=$CPU} -- \
  nice -n 15 ionice -c3 "$V/bin/python" -m pytest "$@" 2>&1
"""

# One line: ROSYPROBE nproc load1 avail_kb total_kb py312 sim busy lock_cores lock_gb. Dead-pid locks go.
PROBE = r"""J=~/rosy-jobs; c=0; m=0
for f in "$J"/*.lock; do
  [ -e "$f" ] || continue; read -r pid _ fc fm < "$f" || true
  case "$fc$fm" in ''|*[!0-9]*) fc=0 fm=0;; esac  # whole numbers only; never evaluate file text
  if kill -0 "$pid" 2>/dev/null; then c=$((c+${fc:-0})); m=$((m+${fm:-0})); else rm -f "$f"; fi
done
py=0; for p in /usr/bin/python3 ~/.local/bin/python3.12; do
  "$p" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null && py=1 && break; done
s=0; [ -f /opt/ros/jazzy/share/ros_gz_sim/package.xml ] && [ -f /opt/ros/jazzy/share/nav2_bringup/package.xml ] && s=1
b=0; [ -e "$J/busy" ] && b=1
echo "ROSYPROBE $(nproc) $(cut -d' ' -f1 /proc/loadavg)" \
  "$(awk '/^MemAvailable:/{a=$2} /^MemTotal:/{t=$2} END{print a, t}' /proc/meminfo) $py $s $b $c $m"
"""

CLEANUP = r"""R=~/rosy-test
rm -f ~/rosy-jobs/"$1".lock
git -C "$R/repo" worktree remove --force "$R/runs/$1" 2>/dev/null || rm -rf "$R/runs/$1"
git -C "$R/repo" worktree prune
git -C "$R/repo" update-ref -d "refs/remote-pytest/$1" 2>/dev/null || true
rm -f "$R/runs/$1.bundle"
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def remote(host: str, script: str, *args: str, timeout: float, **kw) -> subprocess.CompletedProcess:
    """Run script on host; a timeout is a failed step (exit 124), never a pass."""
    command = "bash -c " + shlex.quote(script) + " remote " + " ".join(map(shlex.quote, args))
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


def parse_probe(out: str) -> dict | None:
    """The ROSYPROBE line of PROBE output (login-shell chatter around it is ignored), or None."""
    try:
        line = [ln for ln in out.splitlines() if ln.startswith("ROSYPROBE ")][-1]
        n, load, avail, total, py, sim, busy, cores, gb = line.split()[1:]
        return {"nproc": int(n), "load1": float(load), "avail_gb": int(avail) / 2**20,
                "total_gb": int(total) / 2**20, "pytest": py == "1", "sim": sim == "1", "busy": busy == "1",
                "lock_cores": int(cores), "lock_gb": int(gb)}
    except (IndexError, ValueError):
        return None


def place(cls: str, hosts: list[str], probes: list[dict | None]) -> tuple[list[str], list[str]]:
    """(hosts above the cls floor, most headroom first, the site PC only when no other fits; a note per host)."""
    need_c, need_m = NEEDS[cls]
    ranked, notes = [], []
    for i, (host, p) in enumerate(zip(hosts, probes)):
        if p is None:
            notes.append(f"{host}: unreachable")
            continue
        site = host == SITE_HOST
        cores = p["nproc"] - max(p["load1"], p["lock_cores"]) - (SITE_RESERVE[0] if site else 0)
        mem = min(p["avail_gb"], p["total_gb"] - p["lock_gb"]) - (SITE_RESERVE[1] if site else 0)
        why = ("marked busy (~/rosy-jobs/busy)" if p["busy"] else f"no {cls} capability" if not p[cls]
               else f"below {cls} floor {need_c} cores/{need_m} GB" if cores < need_c or mem < need_m else "ok")
        notes.append(f"{host}: {cores:.1f} cores, {mem:.1f} GB free{' (site PC)' if site else ''} - {why}")
        if why == "ok":
            ranked.append((site, -min(cores / need_c, mem / need_m), i, host))
    ranked.sort()
    return [r[3] for r in ranked if not r[0]] or [r[3] for r in ranked], notes


def placed_hosts(cls: str = "pytest", hosts: list[str] | None = None) -> list[str]:
    """Hosts for cls by measured headroom (D-568), printing why; empty when forced local or none fits."""
    if os.environ.get("ROSY_TEST_LOCAL") == "1":
        return []
    if hosts is None:
        hosts = os.environ.get("ROSY_TEST_HOSTS", DEFAULT_HOSTS).split()
    if not hosts:
        return []
    with ThreadPoolExecutor(len(hosts)) as pool:
        probes = list(pool.map(probe, hosts))
    chosen, notes = place(cls, hosts, probes)
    for note in notes:
        print(f"[remote-pytest] {note}", file=sys.stderr, flush=True)
    if not chosen and cls == "pytest":
        # D-568 7: busy hosts must not stop the gate; the site PC never takes this fallback.
        chosen = [h for h, p in zip(hosts, probes) if p and p["pytest"] and not p["busy"] and h != SITE_HOST]
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


def deps(repo: Path, sha: str) -> tuple[str, list[str]]:
    """(hash of the CI install inputs at sha, the platform wheel dirs ci.yml builds)."""
    ci = git(repo, "show", f"{sha}:{CI}")
    match = re.search(r'--wheel-dir "\$wheelhouse" \\\n\s*(.+)', ci)
    if not match:
        raise SystemExit(f"[remote-pytest] no `pip3 wheel ... --wheel-dir` line in {CI}; update VENV")
    dirs = match.group(1).split()
    ids = [git(repo, "rev-parse", f"{sha}:{p}") for p in (CI, DEVICE_REQ, CRYPTO_REQ, FLEET_REQ, *dirs)]
    # Lock/swap changes do not change installed packages or need another venv build.
    install = VENV.split("UV=", 1)[1].split('echo "$DEPS"', 1)[0]
    return hashlib.sha256("\n".join([install, *ids]).encode()).hexdigest()[:16], dirs


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
            result = remote(host, SHIP, name, sha, PUBLIC, input=data, capture_output=True,
                            timeout=STEP_TIMEOUT["ship"])
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
        local: bool = False, label: str | None = None, require_host: bool = True) -> list[int]:
    """Run each pytest invocation for commit sha; one exit code per invocation."""
    repo = Path(git(repo or Path.cwd(), "rev-parse", "--show-toplevel"))
    sha = git(repo, "rev-parse", f"{sha}^{{commit}}")
    if not invocations:
        return []
    hosts = [] if local else placed_hosts("pytest")
    if not hosts:
        if require_host and not local and os.environ.get("ROSY_TEST_LOCAL") != "1":
            raise SystemExit("[remote-pytest] no test host reachable; a local run would test the working"
                             " tree, not the commit. Use --local only for explicit diagnostics.")
        if not local and os.environ.get("ROSY_TEST_LOCAL") != "1":
            print("[remote-pytest] WARNING: no test host reachable; running pytest on this machine"
                  " (working tree, not only the commit)", file=sys.stderr, flush=True)
        return [capture([sys.executable, "-m", "pytest", *inv, *PYTEST_TAIL], log, cwd=repo)
                for inv, log in zip(invocations, logs)]
    hosts = hosts[:len(invocations)]
    if len(hosts) == 1:
        return run_on(hosts[0], invocations, logs, sha, repo, label)
    # D-553 4: invocation k runs on hosts[k % n]; each host ships and builds its venv once.
    n = len(hosts)

    def attempt(i):
        try:
            return run_on(hosts[i], invocations[i::n], logs[i::n], sha, repo, label)
        except SystemExit as error:  # ship/venv failed; pytest failures are exit codes, not this
            print(f"[remote-pytest] {hosts[i]} failed ({error}); another host takes its share",
                  file=sys.stderr, flush=True)
            return None

    with ThreadPoolExecutor(n) as pool:
        parts = list(pool.map(attempt, range(n)))
    working = [h for h, part in zip(hosts, parts) if part is not None]
    if not working:
        raise SystemExit("[remote-pytest] every test host failed to set up")
    for i, part in enumerate(parts):
        if part is None:
            parts[i] = run_on(working[0], invocations[i::n], logs[i::n], sha, repo, label)
    return [parts[k % n][k // n] for k in range(len(invocations))]


def run_on(host: str, invocations: list[list[str]], logs: list[Path], sha: str, repo: Path,
           label: str | None) -> list[int]:
    name = f"{label or sha[:10]}-{secrets.token_hex(3)}"
    print(f"[remote-pytest] {sha[:10]} on {host} (~/rosy-test/runs/{name})", flush=True)
    try:
        ship(repo, host, sha, name)
        deps_sha, dirs = deps(repo, sha)
        if remote(host, VENV, name, deps_sha, *dirs, timeout=STEP_TIMEOUT["venv"]).returncode != 0:
            raise SystemExit(f"[remote-pytest] venv setup on {host} failed")
        codes = []
        for inv, log in zip(invocations, logs):
            print(f"[remote-pytest] pytest {' '.join(inv)}  -> {log}", flush=True)
            cpu = SITE_CPU_QUOTA if host == SITE_HOST else ""
            codes.append(capture([*SSH, host, "bash -c " + shlex.quote(PYTEST) + " remote "
                                  + " ".join(map(shlex.quote, [name, deps_sha, cpu, *inv, *PYTEST_TAIL]))], log))
        return codes
    finally:
        remote(host, CLEANUP, name, capture_output=True, timeout=STEP_TIMEOUT["cleanup"])


def affected_invocations(selection: dict, skip: set[str]) -> list[list[str]]:
    """`rosy_harness.py affected --json` -> invocations, as `affected --run` picks them."""
    invocations = selection["local_invocations" if selection["mode"] == "full" else "invocations"]
    return [kept for kept in ([p for p in inv if p not in skip] for inv in invocations) if kept]


def worst(codes: list[int]) -> int:
    """Any failure is nonzero: 5 (nothing collected) passes, a signal (negative code) fails."""
    return max((0 if c == 5 else 1 if c < 0 else c for c in codes), default=0)


def default_log_dir(sha: str) -> Path:
    base = os.environ.get("ROSY_TEST_LOGS") or ("X:/DevTemp/remote-pytest" if os.name == "nt"
                                                 else "/tmp/remote-pytest")
    return Path(base) / sha[:12]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", default="HEAD", help="commit to test (default HEAD)")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--affected-json", help="`rosy_harness.py affected --json` output file, or -")
    parser.add_argument("--skip", action="append", default=[], help="drop this path from the affected set")
    parser.add_argument("--local", action="store_true", help="run here (same as ROSY_TEST_LOCAL=1)")
    parser.add_argument("--require-host", action="store_true",
                        help="fail instead of running locally when no host answers (ROSY_TEST_LOCAL=1 overrides)")
    parser.add_argument("--pick", choices=sorted(NEEDS),
                        help="only print the host with the most headroom for this job class (D-568)")
    parser.add_argument("pytest_args", nargs="*", help="one pytest invocation (after --)")
    args = parser.parse_args(argv)
    if args.pick:
        chosen = placed_hosts(args.pick)
        if chosen:
            print(chosen[0])
        return 0 if chosen else 1
    invocations = [args.pytest_args] if args.pytest_args else []
    if args.affected_json:
        text = sys.stdin.read() if args.affected_json == "-" else Path(args.affected_json).read_text("utf-8")
        invocations += affected_invocations(json.loads(text), set(args.skip))
    sha = git(Path.cwd(), "rev-parse", f"{args.sha}^{{commit}}")
    log_dir = args.log_dir or default_log_dir(sha)
    logs = [log_dir / f"run-{i}.txt" for i in range(1, len(invocations) + 1)]
    codes = run(invocations, logs, sha, local=args.local, require_host=args.require_host)
    for inv, code, log in zip(invocations, codes, logs):
        print(f"[remote-pytest] exit {code}: {' '.join(inv)} ({log})")
    return worst(codes)


if __name__ == "__main__":
    sys.exit(main())
