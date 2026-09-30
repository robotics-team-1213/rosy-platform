"""Pull finished, un-harvested recording sessions from a robot over ssh/scp.

Usage: harvest.py <host> [--user rosy] [--identity KEY] [--known-hosts FILE]
                  [--remote-root /var/lib/rosy/camera/recordings] [--dest data/perception/raw]
                  (--core-token-file FILE | --assume-idle) [--core-url http://<host>:8080]

D-136: recordings leave the robot only while it is not driving. Before each
session this asks CORE `GET /api/v1/robot/state` (viewer token, read from a
file or ROSY_CORE_TOKEN_FILE, never argv) and stops with exit 4 unless the robot
is idle. --assume-idle skips the check for bench use.

SSH is the operator's (D-373 decision 6, operator_ssh.py). Recordings belong
to rosy-camera, so marking a session harvested runs through `sudo -n` and keeps
session.json's owner and mode.

Exit codes: 0 all fetched, 1 some session failed, 2 bad arguments, 4 robot
moving or not proven idle (nothing further transferred)."""
import argparse
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

_PERCEPTION = Path(__file__).resolve().parents[1]
if str(_PERCEPTION) not in sys.path:
    sys.path.insert(0, str(_PERCEPTION))

import operator_ssh  # noqa: E402

# session.json keys, as written by control/recording.py (not imported: keep
# this tool usable without the sensing tree on sys.path).
ENDED_KEY = "ended_at"
HARVESTED_KEY = "harvested"
REMOTE_ROOT = "/var/lib/rosy/camera/recordings"
EXIT_NOT_IDLE = 4
TOKEN_ENV = "ROSY_CORE_TOKEN_FILE"
# CORE StateSnapshot (core_common.protocol.schemas): what counts as not driving.
_IDLE_NAVIGATION = {"IDLE", "ARRIVED", "CANCELED", "FAILED"}
_STILL = 0.01  # m/s and rad/s

_LIST_PY = (
    "import json,sys,glob,os;r=[]\n"
    "for p in sorted(glob.glob(os.path.join(sys.argv[1],'*','session.json'))):\n"
    " try:\n"
    "  d=json.load(open(p));d['name']=os.path.basename(os.path.dirname(p));r.append(d)\n"
    " except Exception:pass\n"
    "print(json.dumps(r))"
)
# Runs as root via sudo -n: the replacement keeps the recorder's owner and mode.
_MARK_PY = (
    "import json,os,sys;p=sys.argv[1];st=os.stat(p);d=json.load(open(p));"
    "d['" + HARVESTED_KEY + "']=True;"
    "t=p+'.tmp';f=open(t,'w');json.dump(d,f,indent=2);f.flush();os.fsync(f.fileno());"
    "f.close();os.chown(t,st.st_uid,st.st_gid);os.chmod(t,st.st_mode&0o7777);os.replace(t,p)"
)


def sessions_to_fetch(listing: list[dict]) -> list[str]:
    return [s["name"] for s in listing
            if s.get(ENDED_KEY) is not None and s.get(HARVESTED_KEY) is not True]


def safe_name(name) -> bool:
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._-]+", name) is not None \
        and not name.startswith("-") and name not in (".", "..")


def safe_component(text) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]", "_", str(text or ""))
    return out or "unknown"


def idle_verdict(state) -> tuple[bool, str]:
    """(idle, reason) from a CORE /api/v1/robot/state body. Unknown is not idle."""
    if not isinstance(state, dict):
        return False, "no CORE state"
    mode = state.get("mode")
    if mode != "IDLE":
        return False, f"mode {mode}"
    nav = state.get("navigation")
    if nav not in _IDLE_NAVIGATION:
        return False, f"navigation {nav}"
    lf = state.get("line_follow")  # absent before API v1.10: no line follow to run
    if lf is not None and (not isinstance(lf, dict) or lf.get("mode") != "OFF"):
        return False, f"line_follow mode {lf.get('mode') if isinstance(lf, dict) else lf}"
    vel = state.get("velocity")
    try:
        lin, ang = float(vel["linear"]), float(vel["angular"])
    except (TypeError, KeyError, ValueError):
        return False, f"velocity unknown {vel!r}"
    if not (math.isfinite(lin) and math.isfinite(ang)) or abs(lin) > _STILL or abs(ang) > _STILL:
        return False, f"velocity linear={lin} angular={ang}"
    return True, "idle"


def fetch_core_state(url: str, token: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (operator URL)
        return json.loads(resp.read().decode("utf-8"))


def verify_tree(local, remote_sums: dict[str, str]) -> list[str]:
    """Relative paths that differ, are missing locally, or exist only locally."""
    local = Path(local)
    bad = set()
    for rel, want in remote_sums.items():
        f = local / rel
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != want:
            bad.add(rel)
    for f in local.rglob("*"):
        if f.is_file():
            rel = f.relative_to(local).as_posix()
            if rel not in remote_sums:
                bad.add(rel)
    return sorted(bad)


def _ssh(base: list[str], target: str, command: str) -> str:
    r = subprocess.run([*base, target, command], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def _remote_sums(base, target: str, remote: str) -> dict[str, str]:
    out = _ssh(base, target, f"cd {shlex.quote(remote)} && find . -type f -exec sha256sum {{}} +")
    sums = {}
    for line in out.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            sums[path[2:] if path.startswith("./") else path] = digest
    return sums


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host")
    ap.add_argument("--user", default=operator_ssh.USER)
    ap.add_argument("--remote-root", default=REMOTE_ROOT)
    ap.add_argument("--dest", default="data/perception/raw")
    ap.add_argument("--core-url", help="CORE base URL (default http://<host>:8080)")
    ap.add_argument("--core-token-file", help=f"viewer token file (env {TOKEN_ENV})")
    ap.add_argument("--assume-idle", action="store_true",
                    help="bench only: skip the CORE idle check (D-136)")
    operator_ssh.add_arguments(ap)
    args = ap.parse_args(argv)
    if args.host.startswith("-") or args.user.startswith("-"):
        print("host and user must not start with '-'", file=sys.stderr)
        return 2
    try:
        opts = operator_ssh.options(*operator_ssh.resolve(args.identity, args.known_hosts))
    except operator_ssh.SshConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    token_file = args.core_token_file or os.environ.get(TOKEN_ENV)
    if args.assume_idle:
        print("WARNING: --assume-idle: not asking CORE whether the robot is driving (D-136). "
              "Bench use only.", file=sys.stderr)
        token = None
    elif not token_file:
        print(f"refused: the D-136 idle check needs --core-token-file or {TOKEN_ENV} "
              "(or --assume-idle on a bench)", file=sys.stderr)
        return 2
    else:
        try:
            token = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"refused: cannot read CORE token file: {exc}", file=sys.stderr)
            return 2
    state_url = (args.core_url or f"http://{args.host}:8080").rstrip("/") + "/api/v1/robot/state"

    def still_idle() -> bool:
        if args.assume_idle:
            return True
        try:
            idle, why = idle_verdict(fetch_core_state(state_url, token, 5.0))
        except (OSError, ValueError) as exc:
            idle, why = False, f"CORE state unavailable: {exc}"
        if not idle:
            print(f"skipping {args.host}: not idle ({why}); harvest only while parked (D-136)",
                  file=sys.stderr)
        return idle

    ssh = ["ssh", *opts, "--"]
    target = f"{args.user}@{args.host}"
    root = args.remote_root.rstrip("/")
    listing = json.loads(_ssh(ssh, target,
                              f"python3 -c {shlex.quote(_LIST_PY)} {shlex.quote(root)}"))
    by_name = {s.get("name"): s for s in listing}
    names = []
    for name in sessions_to_fetch(listing):
        if safe_name(name):
            names.append(name)
        else:
            print(f"skipping session with unsafe name: {name!r}", file=sys.stderr)
    failed = 0
    for name in names:
        if not still_idle():
            return EXIT_NOT_IDLE
        remote = f"{root}/{name}"
        local = Path(args.dest) / safe_component(by_name[name].get("device")) / name
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["scp", "-r", *opts, "--", f"{target}:{remote}",
                                str(local.parent)])
            if r.returncode != 0:
                raise RuntimeError("scp failed")
            bad = verify_tree(local, _remote_sums(ssh, target, remote))
            if bad:
                raise RuntimeError(f"checksum mismatch: {bad}")
            _ssh(ssh, target, f"sudo -n python3 -c {shlex.quote(_MARK_PY)} "
                              f"{shlex.quote(remote + '/session.json')}")
        except (RuntimeError, OSError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"harvested {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
