"""Pull finished, un-harvested recording sessions from a robot over ssh/scp.

Usage: harvest.py <host> [--user pinky] [--remote-root /var/lib/rosy/recordings]
                  [--dest data/perception/raw]
"""
import argparse
import hashlib
import json
import re
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


def safe_name(name) -> bool:
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._-]+", name) is not None         and not name.startswith("-") and name not in (".", "..")


def safe_component(text) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]", "_", str(text or ""))
    return out or "unknown"


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


def _ssh(target: str, command: str) -> str:
    r = subprocess.run(["ssh", "--", target, command], capture_output=True, text=True)
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
    if args.host.startswith("-") or args.user.startswith("-"):
        print("host and user must not start with '-'", file=sys.stderr)
        return 2
    target = f"{args.user}@{args.host}"
    root = args.remote_root.rstrip("/")
    listing = json.loads(_ssh(target, f"python3 -c {shlex.quote(_LIST_PY)} {shlex.quote(root)}"))
    by_name = {s.get("name"): s for s in listing}
    names = []
    for name in sessions_to_fetch(listing):
        if safe_name(name):
            names.append(name)
        else:
            print(f"skipping session with unsafe name: {name!r}", file=sys.stderr)
    failed = 0
    for name in names:
        remote = f"{root}/{name}"
        local = Path(args.dest) / safe_component(by_name[name].get("device")) / name
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["scp", "-r", "--", f"{target}:{remote}", str(local.parent)])
            if r.returncode != 0:
                raise RuntimeError("scp failed")
            bad = verify_tree(local, _remote_sums(target, remote))
            if bad:
                raise RuntimeError(f"checksum mismatch: {bad}")
            _ssh(target, f"python3 -c {shlex.quote(_MARK_PY)} {shlex.quote(remote + '/session.json')}")
        except (RuntimeError, OSError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"harvested {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
