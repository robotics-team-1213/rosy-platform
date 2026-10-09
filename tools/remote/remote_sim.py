"""Run a headless Gazebo bench for one commit on the team PC with the most free capacity (D-571).

    python tools/remote/remote_sim.py --check
    python tools/remote/remote_sim.py [--host HOST|ROLE] [--sha REV] [--log-dir DIR] [--minutes N]
                                      swarm_bench|map_v2_runner [-- <bench args>]
    python tools/remote/remote_sim.py [...] cmd -- <shell command>

Hosts: ``ROSY_SIM_HOSTS`` (space separated ``user@addr=role``), default model PC then AI PC.
The site PC is production only and excluded from simulation (D-571, user 2026-10-09): it is
never a candidate, ``--host site`` is refused, and any host running Fleet is refused too.
Each host is probed over ssh (a nonce guards against stale output) for readiness (native
Jazzy ros_gz + Nav2 + gz_ros2_control) and capacity (load per core, MemAvailable, GPU use,
running ``gz sim`` and other heavy processes). The committed sha travels like
``remote_pytest.py`` (git bundle into ``~/rosy-test``); the run builds ``gz_sim`` with colcon,
then runs the bench headless under ``systemd-run --user --scope`` (MemoryMax, CPUQuota, nice).
Logs and bench outputs land in ``--log-dir`` (default ``X:/DevTemp/remote-sim/<sha>``); the
run's scope and its files are removed after. Standard library only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import os
import secrets
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remote_pytest as rp  # noqa: E402

DEFAULT_HOSTS = "rosy@100.98.162.71=model ai@100.108.76.123=ai"
# D-571: production only, never a sim host (user 2026-10-09 "관제 PC는 시뮬레이션에서 제외").
PRODUCTION = {"site", "robttt@100.82.51.8"}
PRODUCTION_REFUSAL = "production only, excluded from simulation (D-571)"
# Per role: memory cap (GB) and CPU cap (cores) for one run; refuse below min_free_gb free
# memory or above max_load per core.
PROFILES = {
    "model": {"mem_gb": 6, "cpus": 8, "min_free_gb": 4, "max_load": 0.9},
    "ai": {"mem_gb": 4, "cpus": 4, "min_free_gb": 4, "max_load": 0.9},
}

# Read only. `[g]z sim` keeps pgrep from matching this script's own command line.
PROBE = r"""echo "nonce=$1"
echo "cores=$(nproc)"
echo "load=$(cut -d' ' -f1 /proc/loadavg)"
echo "mem_kb=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)"
echo "gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)"
n=0; for p in ros_gz_sim nav2_bringup gz_ros2_control; do [ -f /opt/ros/jazzy/share/$p/package.xml ] && n=$((n+1)); done
echo "native=$([ $n = 3 ] && echo 1 || echo 0)"
echo "fleet=$(docker ps --format '{{.Image}}' 2>/dev/null | grep -c '^rosy-site-fleet')"
echo "gz=$(pgrep -fc '[g]z sim')"
echo "heavy=$(ps -eo pcpu=,args= | awk '$1 >= 50 && $0 !~ /rosy-test\/runs\/sim-/' | wc -l)"
"""

# Runs inside the scope, in the shipped checkout. $OUT holds every output.
INNER = r"""set -eo pipefail
export PATH=/usr/bin:/bin:$PATH  # ~/.local/bin may hold another python3 (Isaac's 3.11 on the model PC)
source /opt/ros/jazzy/setup.bash
export PYTHONPATH="$PYDEPS${PYTHONPATH:+:$PYTHONPATH}"
COLCON_ROOTS="$(python3 tools/harness/colcon_roots.py)"
colcon --log-base "$OUT/colcon-log" build --base-paths $COLCON_ROOTS --packages-up-to gz_sim \
  --build-base "$OUT/build" --install-base "$OUT/install" > "$OUT/colcon.txt" 2>&1 || { tail -40 "$OUT/colcon.txt"; exit 1; }
source "$OUT/install/setup.bash"
eval "$BENCH_CMD"
"""

# NAME MEM_GB CPUS MINUTES BENCH_CMD [bench args]. Isolated per run: own GZ_PARTITION,
# random ROS_DOMAIN_ID, discovery on loopback only.
SIM = r"""set -uo pipefail
R=~/rosy-test; NAME=$1; MEM=$2G; CPUS=$3; SECS=$(($4 * 60)); export BENCH_CMD=$5; shift 5
SRC=$R/runs/$NAME; OUT=$R/runs/$NAME-out
mkdir -p "$OUT/tmp"; printf '%s' "$INNER" > "$OUT/inner.sh"; cd "$SRC"
export GZ_PARTITION=$NAME GZ_IP=127.0.0.1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_DOMAIN_ID=$((120 + RANDOM % 100))
REQ=deploy/robot/pinky_pro/requirements-core.txt
export PYDEPS=$R/sim-pydeps/$(sha256sum "$REQ" | cut -c1-12) OUT TMPDIR=$OUT/tmp ROS_LOG_DIR=$OUT/ros-log
mkdir -p "$R/sim-pydeps"
( flock -w 600 9
  if [ ! -f "$PYDEPS/.ok" ]; then
    rm -rf "$PYDEPS.new"
    UV=$(command -v uv || ls ~/.local/bin/uv 2>/dev/null || true)
    if [ -n "$UV" ]; then "$UV" pip install -q --python /usr/bin/python3 --target "$PYDEPS.new" -r "$REQ" httpx
    else /usr/bin/python3 -m pip install -q --target "$PYDEPS.new" -r "$REQ" httpx; fi
    touch "$PYDEPS.new/.ok"; rm -rf "$PYDEPS"; mv "$PYDEPS.new" "$PYDEPS"
  fi ) 9>"$R/sim-pydeps/.lock" || { echo "[remote-sim] CORE pip deps failed"; exit 1; }
exec timeout -k 30 "$SECS" systemd-run --user --scope -q --unit "rosy-sim-$NAME" \
  -p MemoryMax="$MEM" -p CPUQuota="$((CPUS * 100))%" nice -n 10 bash "$OUT/inner.sh" "$@"
"""

# Outputs without the build, install and tmp (tmp holds the run's robots.yaml tokens).
FETCH = r"""cd ~/rosy-test/runs/"$1"-out && tar -cf - --exclude=./build --exclude=./install --exclude=./tmp ."""

# Only this run's scope: never another user's or session's processes.
STOP = r"""systemctl --user stop "rosy-sim-$1.scope" 2>/dev/null
rm -rf ~/rosy-test/runs/"$1"-out
true"""

BENCHES = {
    # gz_multi writes robots.yaml under TMPDIR (tempfile.mkdtemp); the bench waits for it.
    "swarm_bench": r"""ros2 launch gz_sim gz_multi.launch.py robots:=3 headless:=true core:=true > "$OUT/launch.txt" 2>&1 &
for i in $(seq 180); do Y=$(ls "$TMPDIR"/rosy_gz_multi_*/robots.yaml 2>/dev/null | head -1); [ -n "$Y" ] && break; sleep 1; done
[ -n "$Y" ] || { echo "[remote-sim] no robots.yaml after 180 s"; tail -40 "$OUT/launch.txt"; exit 1; }
sleep 30
ros2 run gz_sim swarm_bench.py --robots "$Y" --out "$OUT/swarm_bench.csv" "$@"
""",
    # The acceptance launch starts Gazebo, CORE and map_v2_runner; extra args are launch args.
    "map_v2_runner": r"""ros2 launch gz_sim pinky_integrated_acceptance.launch.py gazebo_gui:=false "$@" 2>&1 | tee "$OUT/launch.txt"
""",
}


def parse_probe(text: str, nonce: str) -> dict | None:
    """key=value lines -> numbers; None unless the output carries this probe's nonce."""
    raw = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    if raw.get("nonce") != nonce:
        return None
    num = {}
    for key in ("cores", "mem_kb", "native", "fleet", "gz", "heavy"):
        num[key] = int(raw.get(key, "").strip() or 0)
    num["load"] = float(raw.get("load", "").strip() or 0)
    gpu = raw.get("gpu", "").strip()
    num["gpu"] = int(gpu) if gpu.isdigit() else None
    return num


def placement(probe: dict | None, role: str) -> tuple[bool, float, str]:
    """(accepted, score, reason). Higher score = more free run slots."""
    if role in PRODUCTION or (probe and probe["fleet"] > 0):
        return False, 0.0, PRODUCTION_REFUSAL
    if probe is None:
        return False, 0.0, "unreachable or stale probe"
    if not probe["native"]:
        return False, 0.0, "not ready: no native ros_gz+nav2+gz_ros2_control"
    prof = PROFILES.get(role, PROFILES["ai"])
    cores = max(probe["cores"], 1)
    per_core = probe["load"] / cores
    free_gb = probe["mem_kb"] / 1e6
    if per_core > prof["max_load"]:
        return False, 0.0, f"busy: load/core {per_core:.2f} > {prof['max_load']}"
    if free_gb < prof["min_free_gb"]:
        return False, 0.0, f"low memory: {free_gb:.1f} GB free < {prof['min_free_gb']}"
    slots = min((cores - probe["load"]) / prof["cpus"], free_gb / prof["mem_gb"])
    # heavy (lifetime >= 50 % CPU) is shown, not scored: the load average already counts it.
    score = slots - probe["gz"]
    if probe["gpu"] is not None and probe["gpu"] >= 90:
        score -= 1
    if score <= 0:
        return False, score, "no free capacity after running sims and heavy jobs"
    return True, score, "ok"


def hosts_from_env() -> list[tuple[str, str]]:
    """Candidate hosts; production hosts are dropped even when listed."""
    specs = os.environ.get("ROSY_SIM_HOSTS", DEFAULT_HOSTS).split()
    hosts = [(s.partition("=")[0], s.partition("=")[2] or "ai") for s in specs]
    return [(h, role) for h, role in hosts if not ({h, role} & PRODUCTION)]


def probe_host(host: str) -> dict | None:
    nonce = secrets.token_hex(6)
    try:
        result = subprocess.run([*rp.SSH, host, "bash -c " + shlex.quote(PROBE) + " probe " + nonce],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_probe(result.stdout, nonce)


def survey(hosts: list[tuple[str, str]]) -> list[tuple[str, str, dict | None, tuple]]:
    if not hosts:
        return []
    with ThreadPoolExecutor(len(hosts)) as pool:
        probes = list(pool.map(lambda h: probe_host(h[0]), hosts))
    return [(h, role, p, placement(p, role)) for (h, role), p in zip(hosts, probes)]


def table(rows) -> str:
    out = ["| host | role | ready | cores | load/core | free GB | GPU % | gz | heavy | verdict |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for host, role, p, (ok, score, reason) in rows:
        if p is None:
            out.append(f"| {host} | {role} | ? | | | | | | | {reason} |")
            continue
        verdict = f"native, score {score:.2f}" if ok else reason
        out.append(f"| {host} | {role} | {'native' if p['native'] else 'none'} | {p['cores']} | "
                   f"{p['load'] / max(p['cores'], 1):.2f} | {p['mem_kb'] / 1e6:.1f} | "
                   f"{'-' if p['gpu'] is None else p['gpu']} | {p['gz']} | {p['heavy']} | {verdict} |")
    out.append(f"| site PC | site | | | | | | | | {PRODUCTION_REFUSAL} |")
    return "\n".join(out)


def choose(rows, want: str | None):
    """The named host (by address or role) if it passes placement, else the best scoring host."""
    if want in PRODUCTION:
        raise SystemExit(f"[remote-sim] {want}: {PRODUCTION_REFUSAL}")
    if want:
        rows = [r for r in rows if want in (r[0], r[1])]
        if not rows:
            raise SystemExit(f"[remote-sim] {want} is not in ROSY_SIM_HOSTS")
    ok = [r for r in rows if r[3][0]]
    if not ok:
        raise SystemExit("[remote-sim] no host can take a sim now:\n" + table(rows))
    return max(ok, key=lambda r: r[3][1])


def run_sim(host: str, role: str, bench_cmd: str, bench_args: list[str], sha: str,
            repo: Path, log_dir: Path, minutes: int) -> int:
    prof = PROFILES.get(role, PROFILES["ai"])
    name = f"sim-{sha[:10]}-{secrets.token_hex(3)}"
    print(f"[remote-sim] {sha[:10]} on {host} (native, {prof['cpus']} CPU, {prof['mem_gb']} GB)", flush=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        rp.ship(repo, host, sha, name)
        args = [name, str(prof["mem_gb"]), str(prof["cpus"]), str(minutes), bench_cmd, *bench_args]
        command = ("INNER=" + shlex.quote(INNER) + " bash -c " + shlex.quote(SIM) + " remote "
                   + " ".join(map(shlex.quote, args)))
        try:
            proc = subprocess.run([*rp.SSH, host, command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=minutes * 60 + 300)
            code, text = proc.returncode, proc.stdout
        except subprocess.TimeoutExpired as exc:
            code, text = 124, (exc.stdout or b"") + b"\n[remote-sim] ssh timed out\n"
        (log_dir / "run.txt").write_bytes(text)
        print(text.decode("utf-8", "replace")[-3000:], flush=True)
        fetched = subprocess.run([*rp.SSH, host, "bash -c " + shlex.quote(FETCH) + " fetch " + name],
                                 stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        if fetched.returncode == 0 and fetched.stdout:
            with tarfile.open(fileobj=io.BytesIO(fetched.stdout)) as tar:
                # Skip links: ROS and colcon "latest" links are absolute paths on the host.
                tar.extractall(log_dir / "out", filter=lambda m, path: None if m.issym() or m.islnk()
                               else tarfile.data_filter(m, path))
        return code
    finally:
        rp.remote(host, STOP, name, capture_output=True, timeout=120)
        rp.remote(host, rp.CLEANUP, name, capture_output=True, timeout=120)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="print readiness and capacity, run nothing")
    parser.add_argument("--host", help="host address or role (model, ai) instead of the best")
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--minutes", type=int, default=45, help="wall limit, compile time included")
    parser.add_argument("bench", nargs="?", choices=[*BENCHES, "cmd"])
    parser.add_argument("bench_args", nargs="*", help="after --: bench args, or the command for cmd")
    args = parser.parse_args(argv)
    if args.host in PRODUCTION:
        raise SystemExit(f"[remote-sim] {args.host}: {PRODUCTION_REFUSAL}")
    rows = survey(hosts_from_env())
    print(table(rows), flush=True)
    if args.check:
        return 0
    if not args.bench or (args.bench == "cmd" and not args.bench_args):
        parser.error("name a bench (or cmd -- <command>)")
    host, role, _probe, _verdict = choose(rows, args.host)
    repo = Path(rp.git(Path.cwd(), "rev-parse", "--show-toplevel"))
    sha = rp.git(repo, "rev-parse", f"{args.sha}^{{commit}}")
    if args.bench == "cmd":
        bench_cmd, bench_args = " ".join(args.bench_args), []
    else:
        bench_cmd, bench_args = BENCHES[args.bench], args.bench_args
    base = os.environ.get("ROSY_SIM_LOGS") or ("X:/DevTemp/remote-sim" if os.name == "nt" else "/tmp/remote-sim")
    log_dir = args.log_dir or Path(base) / sha[:12]
    code = run_sim(host, role, bench_cmd, bench_args, sha, repo, log_dir, args.minutes)
    print(f"[remote-sim] exit {code} on {host} ({log_dir})")
    return code


if __name__ == "__main__":
    sys.exit(main())
