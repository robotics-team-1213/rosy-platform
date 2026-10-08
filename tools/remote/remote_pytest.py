"""Run pytest for one commit on the model PC (OMEN) or the AI PC, not on this laptop.

    python tools/remote/remote_pytest.py [--sha REV] [--log-dir DIR] [--affected-json FILE|-]
                                         [--skip PATH ...] [-- <pytest paths/args>]

Only the committed ``--sha`` (default HEAD) is tested: uncommitted changes are not
shipped. The commit travels as a git bundle (so guard tests that run git see a real
``.git``) into ``~/rosy-test/repo``, a clone of the public origin, and is checked out
as a detached worktree under ``~/rosy-test/runs/``, removed afterwards. Venvs
under ``~/rosy-test/venvs/<deps-sha>`` follow the CI install step
(``.github/workflows/ci.yml``); different dependency versions can run together.
Each pytest runs under a 6 GB memory cap.

Hosts: ``ROSY_TEST_HOSTS`` (space separated, first reachable wins), default model PC
then AI PC. A missing host fails the gate; ``--local`` or ``ROSY_TEST_LOCAL=1``
is for explicit diagnostics.
Logs land in ``--log-dir`` (default ``X:/DevTemp/remote-pytest/<sha>``), one
``run-<n>.txt`` per invocation. Exit code: the worst pytest exit (5, nothing
collected, counts as 0). Standard library only.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
from pathlib import Path

DEFAULT_HOSTS = "rosy@100.98.162.71 ai@100.108.76.123"
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
UV=$(command -v uv || ls ~/.local/bin/uv 2>/dev/null || true)
if [ -n "$UV" ]; then "$UV" venv -q --seed -p /usr/bin/python3 "$N"
else /usr/bin/python3 -m venv "$N"; fi
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

PYTEST = r"""set -euo pipefail
R=~/rosy-test; DEPS=$2; V=$R/venvs/$DEPS; cd "$R/runs/$1"; shift 2
[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ] || { echo "[remote] venv hash mismatch" >&2; exit 1; }
export PYTHONPATH="$V/receiver-crypto${PYTHONPATH:+:$PYTHONPATH}" PYTHONUTF8=1
exec systemd-run --user --scope -q -p MemoryMax=6G -- "$V/bin/python" -m pytest "$@" 2>&1
"""

CLEANUP = r"""R=~/rosy-test
git -C "$R/repo" worktree remove --force "$R/runs/$1" 2>/dev/null || rm -rf "$R/runs/$1"
git -C "$R/repo" worktree prune
git -C "$R/repo" update-ref -d "refs/remote-pytest/$1" 2>/dev/null || true
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


def reachable(host: str) -> bool:
    try:
        return subprocess.run([*SSH, host, "true"], stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_host(hosts: list[str] | None = None, probe=None) -> str | None:
    """First reachable host, or None (run locally)."""
    if os.environ.get("ROSY_TEST_LOCAL") == "1":
        return None
    if hosts is None:
        hosts = os.environ.get("ROSY_TEST_HOSTS", DEFAULT_HOSTS).split()
    return next((h for h in hosts if (probe or reachable)(h)), None)


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
        for base in (bundle_base(repo, sha), None):
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
    host = None if local else pick_host()
    if host is None:
        if require_host and not local and os.environ.get("ROSY_TEST_LOCAL") != "1":
            raise SystemExit("[remote-pytest] no test host reachable; a local run would test the working"
                             " tree, not the commit. Use --local only for explicit diagnostics.")
        if not local and os.environ.get("ROSY_TEST_LOCAL") != "1":
            print("[remote-pytest] WARNING: no test host reachable; running pytest on this machine"
                  " (working tree, not only the commit)", file=sys.stderr, flush=True)
        return [capture([sys.executable, "-m", "pytest", *inv, *PYTEST_TAIL], log, cwd=repo)
                for inv, log in zip(invocations, logs)]
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
            codes.append(capture([*SSH, host, "bash -c " + shlex.quote(PYTEST) + " remote "
                                  + " ".join(map(shlex.quote, [name, deps_sha, *inv, *PYTEST_TAIL]))], log))
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
    parser.add_argument("pytest_args", nargs="*", help="one pytest invocation (after --)")
    args = parser.parse_args(argv)
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
