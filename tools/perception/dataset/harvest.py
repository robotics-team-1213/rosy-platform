"""Pull finished, un-harvested recording sessions from a robot over ssh/scp.

Usage: harvest.py <host> [--user pinky] [--remote-root /var/lib/rosy/recordings]
                  [--dest data/perception/raw]
"""
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

# session.json keys, as written by control/recording.py (not imported: keep
# this tool usable without the sensing tree on sys.path).
ENDED_KEY = "ended_at"
HARVESTED_KEY = "harvested"

_LIST_PY = (
    "import json,sys,glob,os;r=[]\n"
    "for p in sorted(glob.glob(os.path.join(sys.argv[1],'*','session.json'))):\n"
    " try:\n"
    "  d=json.load(open(p));d['name']=os.path.basename(os.path.dirname(p));r.append(d)\n"
    " except Exception:pass\n"
    "print(json.dumps(r))"
)
_MARK_PY = (
    "import json,os,sys;p=sys.argv[1];d=json.load(open(p));d['" + HARVESTED_KEY + "']=True;"
    "t=p+'.tmp';f=open(t,'w');json.dump(d,f,indent=2);f.flush();os.fsync(f.fileno());"
    "f.close();os.replace(t,p)"
)


def sessions_to_fetch(listing: list[dict]) -> list[str]:
    return [s["name"] for s in listing
            if s.get(ENDED_KEY) is not None and s.get(HARVESTED_KEY) is not True]


def verify_tree(local, remote_sums: dict[str, str]) -> list[str]:
    """Return relative paths whose local sha256 differs from or is missing vs remote."""
    local = Path(local)
    bad = []
    for rel, want in sorted(remote_sums.items()):
        f = local / rel
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != want:
            bad.append(rel)
    return bad


def _ssh(target: str, command: str) -> str:
    r = subprocess.run(["ssh", target, command], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed ({r.returncode}): {r.stderr.strip()}")
    return r.stdout


def _remote_sums(target: str, remote: str) -> dict[str, str]:
    out = _ssh(target, f"cd {shlex.quote(remote)} && find . -type f -exec sha256sum {{}} +")
    sums = {}
    for line in out.splitlines():
        digest, _, path = line.partition("  ")
        if path:
            sums[path[2:] if path.startswith("./") else path] = digest
    return sums


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("host")
    ap.add_argument("--user", default="pinky")
    ap.add_argument("--remote-root", default="/var/lib/rosy/recordings")
    ap.add_argument("--dest", default="data/perception/raw")
    args = ap.parse_args(argv)
    target = f"{args.user}@{args.host}"
    root = args.remote_root.rstrip("/")
    listing = json.loads(_ssh(target, f"python3 -c {shlex.quote(_LIST_PY)} {shlex.quote(root)}"))
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name in sessions_to_fetch(listing):
        remote = f"{root}/{name}"
        r = subprocess.run(["scp", "-r", f"{target}:{remote}", str(dest)])
        if r.returncode != 0:
            print(f"scp failed: {name}", file=sys.stderr)
            failed += 1
            continue
        bad = verify_tree(dest / name, _remote_sums(target, remote))
        if bad:
            print(f"checksum mismatch in {name}: {bad}", file=sys.stderr)
            failed += 1
            continue
        _ssh(target, f"python3 -c {shlex.quote(_MARK_PY)} {shlex.quote(remote + '/session.json')}")
        print(f"harvested {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
