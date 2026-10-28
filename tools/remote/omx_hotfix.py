"""Fast fix-and-retry loop for the OMX cell scripts on the site PC; files only, never moves an arm.

  commit --base <rev> --ref <name> --file <repo-path>=<local-path> ... -m <msg>
      Builds a commit on <base> with those files replaced, in a temporary index, so no worktree
      or shared index is touched, and points refs/rosy-wip/<name> at it. Prints the sha.
  test --sha <sha> --log-dir <dir> -- <tests...>
      Runs tools/remote/remote_pytest.py for that sha (never local pytest, D-584) and returns
      its exit code. Records the sha in <dir>/omx-hotfix-sha for deploy.
  deploy --sha <sha> --tested-log <dir>/run-1.txt [--host user@host]
      Refuses unless that log came from `test` for this sha and its last pytest summary passed
      without failures or errors. Unpacks `git archive` of deploy/robot and the OMX adapter plus
      REVISION into ~/rosy-test/omx-tools-<sha10>/ (skipped when its REVISION already matches),
      then switches ~/rosy-test/omx-tools-current to it atomically. Prints folder and old target.
  status [--host user@host]
      Prints the current link target and the five newest omx-tools-* folders.

The host comes from --host or OMX_HOTFIX_HOST; no live address is kept in this public repo (D-226).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HOST_ENV = "OMX_HOTFIX_HOST"
PATHS = ("deploy/robot", "middleware/devices/omx/adapter")
LINK = "omx-tools-current"
SHA_FILE = "omx-hotfix-sha"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15"]
# Last pytest summary line, -q or full form: "3 passed, 1 skipped in 2.10s" / "=== 1 failed ... ===".
SUMMARY = re.compile(r"^=*\s*(\d+ \w+(, )?)+.* in [\d.]+s\b")


def _git(*args: str, env: dict | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    if done.returncode:
        raise SystemExit(f"[omx-hotfix] git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def _ssh(host: str, script: str, data: bytes | None = None) -> str:
    done = subprocess.run([*SSH, host, script], input=data, capture_output=True, check=False)
    if done.returncode:
        raise SystemExit(f"[omx-hotfix] ssh {host} failed (exit {done.returncode}): "
                         f"{done.stderr.decode(errors='replace').strip()}")
    return done.stdout.decode(errors="replace").strip()


def _sha(rev: str) -> str:
    return _git("rev-parse", "--verify", f"{rev}^{{commit}}")


def _repo_path(path: str) -> str:
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts or "\\" in path or ":" in path:
        raise SystemExit(f"[omx-hotfix] not a repo-relative path: {path!r}")
    return pure.as_posix()


def commit(base: str, ref: str, files: list[tuple[str, str]], message: str) -> str:
    base_sha = _sha(base)
    with tempfile.TemporaryDirectory(prefix="omx-hotfix-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git("read-tree", base_sha, env=env)
        for repo_path, local in files:
            listed = _git("ls-tree", base_sha, "--", repo_path).split()
            mode = listed[0] if listed and listed[0] in ("100644", "100755") else "100644"  # keep +x scripts
            blob = _git("hash-object", "-w", f"--path={repo_path}", "--", local)
            _git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{repo_path}", env=env)
        tree = _git("write-tree", env=env)
    sha = _git("commit-tree", tree, "-p", base_sha, "-m", message)
    _git("update-ref", f"refs/rosy-wip/{ref}", sha)
    return sha


def test(sha: str, log_dir: Path, tests: list[str]) -> int:
    full = _sha(sha)
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / SHA_FILE).write_text(full + "\n", encoding="utf-8")
    cmd = [sys.executable, str(ROOT / "tools" / "remote" / "remote_pytest.py"),
           "--sha", full, "--log-dir", str(log_dir), "--", *tests]
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def log_problem(log: Path, sha: str) -> str | None:
    """Why this log does not prove `sha` passed, or None."""
    marker = log.parent / SHA_FILE
    if not log.is_file():
        return f"no log at {log}"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != sha:
        return f"{log.parent} holds no `omx_hotfix.py test` run of {sha[:10]} ({SHA_FILE})"
    summaries = [line.strip() for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                 if SUMMARY.match(line.strip())]
    if not summaries:
        return f"{log} has no pytest summary line"
    last = summaries[-1]
    if "passed" not in last or "failed" in last or "error" in last:
        return f"{log} did not pass: {last}"
    return None


def host_of(value: str | None) -> str:
    host = value or os.environ.get(HOST_ENV, "").strip()
    if not host:
        raise SystemExit(f"[omx-hotfix] no host: pass --host user@host or set {HOST_ENV}"
                         " (the address stays out of tracked files, D-226)")
    return host


def switch_script(name: str) -> str:
    # ln -sfn on the live name is unlink+symlink (a gap); rename over it with mv -T is atomic.
    return (f"cd rosy-test && prev=$(readlink {LINK} || true) && ln -sfn {name} .{LINK}.tmp"
            f" && mv -T .{LINK}.tmp {LINK} && echo \"$prev\"")


def unpack_script(name: str) -> str:
    part = f".{name}.part"
    return (f"set -e; mkdir -p rosy-test; cd rosy-test; rm -rf {part}; mkdir {part};"
            f" tar -xzf - -C {part}; rm -rf {name}; mv {part}/{name} {name}; rmdir {part}")


def deploy(sha: str, host: str, tested_log: Path) -> tuple[str, str]:
    full = _sha(sha)
    problem = log_problem(tested_log, full)
    if problem:
        raise SystemExit(f"[omx-hotfix] refusing to deploy {full[:10]}: {problem}")
    short = full[:10]
    name = f"omx-tools-{short}"
    if _ssh(host, f"cat rosy-test/{name}/REVISION 2>/dev/null || true") == short:
        print(f"[omx-hotfix] {name} already on {host}; not copied again", flush=True)
    else:
        archive = subprocess.run(
            ["git", "archive", "--format=tar.gz", f"--prefix={name}/",
             f"--add-virtual-file={name}/REVISION:{short}\n", full, *PATHS],
            cwd=ROOT, capture_output=True, check=False)
        if archive.returncode:
            raise SystemExit(f"[omx-hotfix] git archive failed: {archive.stderr.decode(errors='replace')}")
        _ssh(host, unpack_script(name), data=archive.stdout)  # stdin, so no scp or local C: paths
    previous = _ssh(host, switch_script(name))
    return f"~/rosy-test/{name}", previous


def status(host: str) -> str:
    return _ssh(host, f"cd rosy-test && echo \"current: $(readlink {LINK} || echo none)\""
                      " && ls -1dt omx-tools-?????????? 2>/dev/null | head -5 || true")


def _file_arg(value: str) -> tuple[str, str]:
    repo_path, sep, local = value.partition("=")
    if not sep or not local:
        raise argparse.ArgumentTypeError("expected <repo-path>=<local-path>")
    if not Path(local).is_file():
        raise argparse.ArgumentTypeError(f"no file {local}")
    return _repo_path(repo_path), local


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("commit")
    c.add_argument("--base", required=True)
    c.add_argument("--ref", required=True)
    c.add_argument("--file", dest="files", type=_file_arg, action="append", required=True)
    c.add_argument("-m", dest="message", required=True)
    t = sub.add_parser("test")
    t.add_argument("--sha", required=True)
    t.add_argument("--log-dir", type=Path, required=True)
    t.add_argument("tests", nargs="+")
    d = sub.add_parser("deploy")
    d.add_argument("--sha", required=True)
    d.add_argument("--tested-log", type=Path, required=True)
    d.add_argument("--host")
    s = sub.add_parser("status")
    s.add_argument("--host")
    args = parser.parse_args(argv)
    if args.command == "commit":
        print(commit(args.base, args.ref, args.files, args.message))
    elif args.command == "test":
        return test(args.sha, args.log_dir, args.tests)
    elif args.command == "deploy":
        folder, previous = deploy(args.sha, host_of(args.host), args.tested_log)
        print(f"deployed: {folder}\nprevious: {previous or 'none'}")
    else:
        print(status(host_of(args.host)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
