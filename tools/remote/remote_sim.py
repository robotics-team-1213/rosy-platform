"""Run a headless Gazebo bench for one commit on the team PC with the most free capacity (D-571).

    python tools/remote/remote_sim.py --check
    python tools/remote/remote_sim.py [--host HOST|ROLE] [--sha REV] [--log-dir DIR] [--minutes N]
                                      swarm_bench|map_v2_runner|fleet_trips [-- <bench args>]
    python tools/remote/remote_sim.py [...] cmd -- <shell command>

Use ``--durable`` for a long command that must survive an observer's SSH loss. The same
bounded native run detaches and reconnects; ``remote-run.json`` identifies it. On exhausted
contact or a missing terminal code, keep that run rather than submitting another. Its
``<run>.sim-job`` journal retains rc/log after successful source/output cleanup. To follow
the same actor later, load that metadata and call ``remote_sim_job.follow`` with its host,
name and a separate local log path; this never places, ships or starts a run.

Hosts: ``ROSY_SIM_HOSTS`` (space separated ``user@addr[=role]``), else ``sim_hosts`` in the
gitignored ``private/lab-hosts.json`` (D-226), else the pytest hosts of ``remote_pytest.py``.
The role (``model`` or ``ai``, default ``ai``) only picks the run's caps. The site PC is
production only and excluded from simulation (D-571, user 2026-10-09): ``=site``, the
configured site host and any host carrying ``~/rosy-jobs/site`` are never used, and
``--host site`` is refused. Placement is ``remote_pytest.py``'s (D-568): one ssh probe per
host, the ``sim`` floor (6 free cores, 8 GB) after ``~/rosy-jobs`` locks and reservations,
``~/rosy-jobs/busy``, most headroom first. ``ship`` reserves a pytest-sized budget until the run holds
``~/rosy-jobs/<run>.lock`` with its own caps. The committed sha travels like
``remote_pytest.py`` (git bundle into ``~/rosy-test``); the run builds ``gz_sim`` with colcon,
then runs the bench headless under ``systemd-run --user --scope`` (MemoryMax, CPUQuota, nice).
The remote shell stops that scope and frees the lock when it ends; then the outputs are fetched.
Logs and bench outputs land in ``--log-dir`` (default ``$ROSY_SCRATCH/remote-sim/<sha>``, else the system temp directory); the
run's files are removed after a good fetch and kept on the host when the fetch fails. Never run on the operator laptop (D-584).
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remote_pytest as rp  # noqa: E402

# D-571: production only, never a sim host (user 2026-10-09 "관제 PC는 시뮬레이션에서 제외").
PRODUCTION_REFUSAL = "production only, excluded from simulation (D-571)"
# D-571 4: memory cap (GB) and CPU cap (cores) for one run, by role. A host without a role
# gets the shared-PC ("ai") caps.
PROFILES = {"model": {"mem_gb": 6, "cpus": 8}, "ai": {"mem_gb": 4, "cpus": 4}}

# CORE's pip pins, the Fleet pins CORE's set lacks (one interpreter runs CORE and a SIM Fleet; CORE's
# pins win, as remote_pytest.py VENV does with the device set), wheel build tools, and the D-373
# learned-perception lock in its own prefix (ROSY_LEARNED_SITE, as on the robot). Cached by those
# files and the install recipe. A failed install is never stamped .ok. Runs inside the scope (INNER),
# so the caps and the wall limit cover it.
DEPS = r"""( flock -w 600 9 || exit 1
  [ -f "$PYDEPS/.ok" ] && exit 0
  rm -rf "$PYDEPS.new"; mkdir -p "$PYDEPS.new"
  grep -viEf <(sed -n 's/^\([A-Za-z0-9._-]*\)==.*/^\1==/p' "$REQ") "$FLEET_REQ" > "$PYDEPS.new/fleet-extra.txt" \
    || [ $? = 1 ]
  UV=$(command -v uv || ls ~/.local/bin/uv 2>/dev/null || true)   # D-802: uv only, deployed by host-state
  [ -n "$UV" ] || { echo "[remote-sim] uv missing (D-802): sudo python3 deploy/hosts/common/rosy-host-state install <role> --approve uv"; exit 1; }
  PIP() { "$UV" pip install -q --python /usr/bin/python3 "$@"; }
  PIP --target "$PYDEPS.new" -r "$REQ" -r "$PYDEPS.new/fleet-extra.txt" httpx 'setuptools>=68' wheel \
    && PIP --target "$PYDEPS.new/learned" --require-hashes --no-deps --only-binary :all: -r "$LEARNED_REQ" \
    && touch "$PYDEPS.new/.ok" && rm -rf "$PYDEPS" && mv "$PYDEPS.new" "$PYDEPS"
) 9>"${PYDEPS%/*}/.lock" || { echo "[remote-sim] CORE pip deps failed"; exit 1; }
"""

# Runs inside the scope, in the shipped checkout. $OUT holds every output.
INNER = r"""set -eo pipefail
export PATH=/usr/bin:/bin:$PATH  # ~/.local/bin may hold another python3 (Isaac's 3.11 on the model PC)
""" + DEPS + r"""source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PYDEPS${PYTHONPATH:+:$PYTHONPATH}" ROSY_LEARNED_SITE="$PYDEPS/learned"
COLCON_ROOTS="$(python3 tools/harness/colcon_roots.py)"
DEFAULT_ROBOT="$(PYTHONPATH="contracts/foundation:$PYTHONPATH" python3 -c 'from core_common.profile import DEFAULT_ROBOT; print(DEFAULT_ROBOT)')"
colcon --log-base "$OUT/colcon-log" build --base-paths $COLCON_ROOTS --packages-up-to gz_sim "$DEFAULT_ROBOT" \
  --parallel-workers "$CPUS" --build-base "$OUT/build" --install-base "$OUT/install" \
  > "$OUT/colcon.txt" 2>&1 || { tail -40 "$OUT/colcon.txt"; exit 1; }
source "$OUT/install/setup.bash"
bash deploy/robot/pinky_pro/image/install-motion-contracts.sh "$PWD" "$OUT/install"
CONTRACT_SITE="$OUT/install/lib/python$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
export PYTHONPATH="$CONTRACT_SITE:$PYTHONPATH"
eval "$BENCH_CMD"
"""

# NAME MEM_GB CPUS MINUTES BENCH_CMD [bench args]. Isolated per run: own GZ_PARTITION, loopback-only
# discovery and a random ROS_DOMAIN_ID in 1-19: inside the Linux-safe 0-101 and clear of 0 (default),
# 20-79 (tools/run_fleet_sim.sh, OMX 30/31/75-77), 41+ (robots, 40 + N) and 80-99 (fleet_gazebo).
# This shell stays alive as the job lock's pid and cleans up when it ends, whatever ended it (a lost
# laptop: at the wall limit at the latest): it stops only this run's scope, frees the lock and drops
# build, install and tmp (the run's tokens). Logs and the checkout stay for the laptop to fetch and remove.
SIM = r"""set -uo pipefail
R=~/rosy-test; NAME=$1; MEM=$2G; export CPUS=$3; SECS=$(($4 * 60)); export BENCH_CMD=$5; shift 5
SRC=$R/runs/$NAME; OUT=$R/runs/$NAME-out
cleanup() {
  systemctl --user stop "rosy-sim-$NAME.scope" 2>/dev/null
  rm -f ~/rosy-jobs/"$NAME".lock; rm -rf "$OUT/build" "$OUT/install" "$OUT/tmp"
}
trap cleanup EXIT; trap 'exit 129' HUP; trap 'exit 143' TERM
mkdir -p "$OUT/tmp" "$R/sim-pydeps"; printf '%s' "$INNER" > "$OUT/inner.sh"; cd "$SRC"
# D-568 2: the job lock holds this shell's pid; it replaces ship's reservation.
mkdir -p ~/rosy-jobs; echo "$$ sim $CPUS ${MEM%G}" > ~/rosy-jobs/"$NAME".lock; rm -f ~/rosy-jobs/"$NAME".resv
export GZ_PARTITION=$NAME GZ_IP=127.0.0.1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_DOMAIN_ID=$((1 + RANDOM % 19))
export REQ=deploy/robot/pinky_pro/requirements-core.txt OUT TMPDIR=$OUT/tmp ROS_LOG_DIR=$OUT/ros-log
export FLEET_REQ=deploy/site/requirements-fleet.txt LEARNED_REQ=deploy/robot/pinky_pro/image/learned-perception-requirements.txt
export PYDEPS=$R/sim-pydeps/$( { sha256sum "$REQ" "$FLEET_REQ" "$LEARNED_REQ"; printf '%s' "$INNER"; } | sha256sum | cut -c1-12)
timeout -k 30 "$SECS" systemd-run --user --scope -q --unit "rosy-sim-$NAME" \
  -p MemoryMax="$MEM" -p CPUQuota="$((CPUS * 100))%" nice -n 10 bash "$OUT/inner.sh" "$@" &
wait $!
"""

# Outputs without the build, install and tmp (tmp holds the run's robots.yaml tokens).
FETCH = r"""cd ~/rosy-test/runs/"$1"-out && tar -cf - --exclude=./build --exclude=./install --exclude=./tmp ."""

# Only this run's scope: never another user's or session's processes. Repeats SIM's cleanup for an
# ssh that died before it ran; the logs stay until they are fetched.
STOP = r"""systemctl --user stop "rosy-sim-$1.scope" 2>/dev/null
O=~/rosy-test/runs/"$1"-out; rm -rf "$O/build" "$O/install" "$O/tmp"
true"""

DROP = r"""rm -rf ~/rosy-test/runs/"$1"-out"""

BENCHES = {
    # gz_multi writes robots.yaml under TMPDIR (tempfile.mkdtemp); the bench waits for it.
    "swarm_bench": r"""ros2 launch gz_sim gz_multi.launch.py robots:=3 headless:=true core:=true > "$OUT/launch.txt" 2>&1 &
for i in $(seq 180); do Y=$(ls "$TMPDIR"/rosy_gz_multi_*/robots.yaml 2>/dev/null | head -1) || true; [ -n "$Y" ] && break; sleep 1; done
[ -n "$Y" ] || { echo "[remote-sim] no robots.yaml after 180 s"; tail -40 "$OUT/launch.txt"; exit 1; }
sleep 30
ros2 run gz_sim swarm_bench.py --robots "$Y" --out "$OUT/swarm_bench.csv" "$@"
""",
    # The acceptance launch starts Gazebo, CORE and map_v2_runner; extra args are launch args.
    "map_v2_runner": r"""ros2 launch gz_sim pinky_integrated_acceptance.launch.py gazebo_gui:=false "$@" 2>&1 | tee "$OUT/launch.txt"
""",
    # Two robots + Fleet on map_v2_fleet, one lane trip each; exit 0 only when both arrive.
    "fleet_trips": r"""python3 tools/sim/fleet_trips.py --out "$OUT/trips" "$@"
""",
}


def candidates(want: str | None = None) -> list[tuple[str, str]]:
    """(host, role) sim candidates, narrowed to the named host or role; a site host is refused."""
    specs = (os.environ.get("ROSY_SIM_HOSTS") or " ".join(map(str, rp._LAB.get("sim_hosts") or []))
             or os.environ.get("ROSY_TEST_HOSTS", rp.DEFAULT_HOSTS)).split()
    hosts = [(s.partition("=")[0], s.partition("=")[2] or "ai") for s in specs]
    site = {"site", rp.SITE_HOST}
    if want in site:
        raise SystemExit(f"[remote-sim] {want}: {PRODUCTION_REFUSAL}")
    hosts = [(h, role) for h, role in hosts if not ({h, role} & site)]
    if want:
        hosts = [(h, role) for h, role in hosts if want in (h, role)]
        if not hosts:
            raise SystemExit(f"[remote-sim] {want} is not a sim host (ROSY_SIM_HOSTS)")
    return hosts


def ranked(hosts: list[tuple[str, str]]) -> list[str]:
    """Hosts above the D-568 sim floor, most headroom first; a host with ~/rosy-jobs/site is dropped."""
    return [h for h in rp.placed_hosts("sim", [h for h, _ in hosts]) if h not in rp.SITES]


def run_sim(host: str, role: str, bench_cmd: str, bench_args: list[str], sha: str,
            repo: Path, log_dir: Path, minutes: int, *, durable: bool = False) -> int:
    prof = PROFILES.get(role, PROFILES["ai"])
    name = f"sim-{sha[:10]}-{secrets.token_hex(3)}"
    print(f"[remote-sim] {sha[:10]} on {host} (native, {prof['cpus']} CPU, {prof['mem_gb']} GB)", flush=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    terminal, fetched_ok = not durable, False
    try:
        try:
            rp.ship(repo, host, sha, name)  # writes <run>.resv, which SIM's job lock replaces
            args = [name, str(prof["mem_gb"]), str(prof["cpus"]), str(minutes), bench_cmd, *bench_args]
            command = ("INNER=" + shlex.quote(INNER) + " bash -c " + shlex.quote(SIM) + " remote "
                       + " ".join(map(shlex.quote, args)))
            if durable:
                import remote_job
                import remote_sim_job
                metadata = dict(name=name, host=host, role=role, source_revision=sha,
                    command_sha256=hashlib.sha256(json.dumps([bench_cmd, *bench_args]).encode()).hexdigest(),
                    cpus=prof['cpus'], memory_gib=prof['mem_gb'], minutes=minutes)
                try:
                    code = remote_sim_job.run(host, name, args, INNER, SIM, log_dir / 'run.txt', metadata,
                                              ssh=rp.SSH)
                except remote_job.Lost as exc:
                    print(str(exc), file=sys.stderr, flush=True)
                    return 255
                if code == remote_job.VANISHED_EXIT:
                    return code
                terminal = True
                text = (log_dir / 'run.txt').read_bytes()
            else:
                try:
                    proc = subprocess.run([*rp.SSH, host, command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, timeout=minutes * 60 + 300)
                    code, text = proc.returncode, proc.stdout
                except subprocess.TimeoutExpired as exc:
                    code, text = 124, (exc.stdout or b"") + b"\n[remote-sim] ssh timed out\n"
        finally:
            # Before the fetch: a bench's background launch still writes logs until its scope stops.
            if terminal:
                rp.remote(host, STOP, name, capture_output=True, timeout=120)
        (log_dir / "run.txt").write_bytes(text)
        enc = sys.stdout.encoding or "utf-8"  # a cp949 console must not stop the fetch
        print(text.decode("utf-8", "replace")[-3000:].encode(enc, "replace").decode(enc), flush=True)
        fetched = rp.remote(host, FETCH, name, capture_output=True, timeout=600)
        if fetched.returncode == 0 and fetched.stdout:
            with tarfile.open(fileobj=io.BytesIO(fetched.stdout)) as tar:
                # Skip links: ROS and colcon "latest" links are absolute paths on the host.
                tar.extractall(log_dir / "out", filter=lambda m, path: None if m.issym() or m.islnk()
                               else tarfile.data_filter(m, path))
            fetched_ok = True
            rp.remote(host, DROP, name, capture_output=True, timeout=120)
        else:
            print(f"[remote-sim] fetching outputs failed (exit {fetched.returncode}): "
                  f"{(fetched.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}\n"
                  f"[remote-sim] kept on {host}: ~/rosy-test/runs/{name}-out", file=sys.stderr, flush=True)
        return code
    finally:
        if not durable or (terminal and fetched_ok):
            rp.remote(host, rp.CLEANUP, name, capture_output=True, timeout=120)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="print each host's headroom, run nothing")
    parser.add_argument("--host", help="host address or role (model, ai) instead of the best")
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--minutes", type=int, default=45, help="wall limit, compile time included")
    parser.add_argument("--durable", action="store_true", help="detach and reconnect to the same bounded run on SSH loss")
    parser.add_argument("bench", nargs="?", choices=[*BENCHES, "cmd"])
    parser.add_argument("bench_args", nargs="*", help="after --: bench args, or the command for cmd")
    args = parser.parse_args(argv)
    hosts = candidates(args.host)
    chosen = ranked(hosts)
    print(f"[remote-sim] site PC: {PRODUCTION_REFUSAL}", file=sys.stderr, flush=True)
    if args.check:
        return 0
    if not args.bench or (args.bench == "cmd" and not args.bench_args):
        parser.error("name a bench (or cmd -- <command>)")
    if not chosen:
        raise SystemExit("[remote-sim] no host can take a sim now (reasons above); nothing ran")
    host, role = chosen[0], dict(hosts)[chosen[0]]
    repo = Path(rp.git(Path.cwd(), "rev-parse", "--show-toplevel"))
    sha = rp.git(repo, "rev-parse", f"{args.sha}^{{commit}}")
    if args.bench == "cmd":
        bench_cmd, bench_args = " ".join(args.bench_args), []
    else:
        bench_cmd, bench_args = BENCHES[args.bench], args.bench_args
    base = os.environ.get("ROSY_SIM_LOGS") or rp.log_root("remote-sim")
    log_dir = args.log_dir or Path(base) / sha[:12]
    if args.durable:
        code = run_sim(host, role, bench_cmd, bench_args, sha, repo, log_dir, args.minutes, durable=True)
    else:
        code = run_sim(host, role, bench_cmd, bench_args, sha, repo, log_dir, args.minutes)
    print(f"[remote-sim] exit {code} on {host} ({log_dir})")
    return code


if __name__ == "__main__":
    sys.exit(main())
