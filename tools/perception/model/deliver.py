"""Deliver an intake-passed model to a robot's shadow slot (D-356, D-373).

deliver.py push <host> <model_revision> [--models data/perception/models]
deliver.py rollback <host>
deliver.py status <host>
common: [--user rosy] [--identity KEY] [--known-hosts FILE] [--root /var/lib/rosy/models]
        [--timeout S]  (per ssh/scp step; 600 for push, 60 for rollback/status)

SSH is key-only and pinned (BatchMode, IdentitiesOnly, StrictHostKeyChecking=yes;
see operator_ssh.py). /var/lib/rosy/models is root:rosy-camera 0750, so every
write goes through `sudo -n install` with that owner and mode.

push: needs a passing intake_report.json whose files (name, sha256) equal the
manifest's. The folder is scp'd to a mktemp dir under /tmp (the rosy user's),
checked there, then installed file by file (weights, manifest and report, each
pinned by sha256) into <rev>.partial, checked again, and moved to <rev>. The
pointer is written in the temp dir, installed as shadow.tmp and moved over
shadow (atomic); the old value is installed as shadow.previous the same way.
Re-pushing the live revision keeps shadow.previous. An already installed <rev>
is re-verified on its model files: if they match, only intake_report.json is
replaced (atomically); if not, it is quarantined as <rev>.bad.<pid>. host, user and
--root are validated; ssh/scp get "--" before targets. The pointer holds the
model folder path that ModelSlot reads. Model files are a data generation, not
a release payload."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT / "src" / "runtime" / "sensing", ROOT / "tools" / "perception"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
from control.sensing.perception.learned.manifest import (  # noqa: E402
    MANIFEST_NAME, ManifestError, check_revision, load_manifest, verify_files)

REMOTE_ROOT = "/var/lib/rosy/models"
REPORT_NAME = "intake_report.json"
SUDO, OWNER, GROUP = "sudo -n", "root", "rosy-camera"  # D-373 decision 1
PUSH_TIMEOUT_S, STATUS_TIMEOUT_S = 600, 60
_SAFE_ROOT = re.compile(r"/[A-Za-z0-9._/-]+")
_STAGE = re.compile(r"/tmp/rosy-model\.[A-Za-z0-9]{8,}")


def remote_script(action: str, rev: str | None, root: str = REMOTE_ROOT, *,
                  checks=(), report=None, stage: str | None = None,
                  privileged: bool = True) -> str:
    """Shell text for one remote step. Every path is shlex.quote'd.

    checks: [(sha256, file name), ...] of the model: manifest-listed files and
    the manifest. report: (sha256, name) of the intake report, installed too.
    stage: the scp'd copy, <mktemp dir>/<rev>; the mktemp dir is removed on exit.
    privileged=False drops sudo -n and the -o/-g/-m of install so the script runs
    as an ordinary user in tests (Git Bash cannot set directory modes either);
    main() never passes it."""
    q = shlex.quote
    s = f"{SUDO} " if privileged else ""
    own = f" -o {OWNER} -g {GROUP}" if privileged else ""
    dmode, fmode = (" -m 0750", " -m 0640") if privileged else ("", "")
    ptr, prev, tmp = q(f"{root}/shadow"), q(f"{root}/shadow.previous"), q(f"{root}/shadow.tmp")

    def check(folder: str, *, privileged: bool = True, quiet: bool = False,
              files=None) -> str:
        files = everything if files is None else files
        sums = " ".join(q(f"{sha}  {folder}/{name}") for sha, name in files)
        return (f"printf '%s\\n' {sums} | {s if privileged else ''}sha256sum -c -"
                + (" >/dev/null 2>&1" if quiet else ""))

    everything = [*checks, *([report] if report else [])]
    if action == "prepare":
        return "set -e; umask 077; mktemp -d /tmp/rosy-model.XXXXXXXX"
    if action == "push":
        if not checks or not report or not stage:
            raise ValueError("push needs manifest checks, the report check and a stage path")
        stage_dir = stage.rsplit("/", 1)[0]
        partial_path, final_path = f"{root}/{rev}.partial", f"{root}/{rev}"
        partial, final = q(partial_path), q(final_path)
        pointer_src = q(f"{stage_dir}/shadow")
        installs = [f"{s}install{own}{fmode} {q(f'{stage}/{name}')} "
                    f"{q(f'{partial_path}/{name}')}" for _, name in everything]
        report_dst = f"{final_path}/{report[1]}"
        return "\n".join([
            "set -e",
            # first: nothing after mktemp may fail before the temp dir is cleaned up
            f"trap {q(f'rm -rf -- {q(stage_dir)}')} EXIT",
            check(stage, privileged=False),
            f"{s}test -d {q(root)} || {s}install -d{own}{dmode} {q(root)}",
            f"{s}rm -rf {partial}",
            f"{s}install -d{own}{dmode} {partial}",
            *installs,
            check(partial_path),
            # an installed <rev> is judged on its model files only: a re-run intake
            # writes a new report, which replaces the old one and never quarantines
            f"if {s}test -d {final}; then",
            f"  if {check(final_path, quiet=True, files=checks)}; then",
            f"    {s}install{own}{fmode} {q(f'{stage}/{report[1]}')} {q(report_dst + '.tmp')}",
            f"    {s}mv {q(report_dst + '.tmp')} {q(report_dst)}",
            f"    {s}rm -rf {partial}",
            f"  else {s}mv {final} {final}.bad.$$; {s}mv {partial} {final}; fi",
            f"else {s}mv {partial} {final}; fi",
            check(final_path),
            f"cur=$({s}cat {ptr} 2>/dev/null || true)",
            f'if [ "$cur" != {final} ]; then',
            f"  if {s}test -f {ptr}; then",
            f"    {s}install{own}{fmode} {ptr} {prev}.tmp",
            f"    {s}mv {prev}.tmp {prev}",
            "  fi",
            # separate statements: set -e ignores a failure inside an && list
            f"  printf %s {final} > {pointer_src}",
            f"  {s}install{own}{fmode} {pointer_src} {tmp}",
            f"  {s}mv {tmp} {ptr}",
            "  sync",
            "fi",
        ])
    if action == "rollback":
        return "\n".join([
            "set -e",
            f"{s}test -f {prev} || {{ echo 'no shadow.previous to roll back to' >&2; exit 1; }}",
            f"{s}mv {prev} {ptr}",
        ])
    if action == "status":
        return "\n".join([
            f"echo \"shadow: $({s}cat {ptr} 2>/dev/null)\"",
            f"echo \"previous: $({s}cat {prev} 2>/dev/null)\"",
            f"{s}ls -1 {q(root)} 2>/dev/null || true",
        ])
    raise ValueError(f"unknown action {action!r}")


def _run(runner, cmd, timeout: float):
    """The completed process on success, else None (reported on stderr).

    A timeout is a failed step (the watcher retries it on a later run)."""
    try:
        r = runner(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"failed (timeout {timeout:g} s): {cmd[0]}", file=sys.stderr)
        return None
    if r.returncode != 0:
        print(f"failed ({r.returncode}): {cmd[0]} {getattr(r, 'stderr', '')}", file=sys.stderr)
        return None
    return r


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _push(args, ssh, scp, runner) -> int:
    rev = args.revision
    try:
        check_revision(rev)
    except ManifestError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    folder = Path(args.models) / rev
    try:
        report = json.loads((folder / REPORT_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"refused: no readable intake report: {exc}", file=sys.stderr)
        return 2
    if report.get("verdict") != "pass" or report.get("model_revision") != rev:
        print(f"refused: intake verdict {report.get('verdict')!r} for {rev}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(folder)
        verify_files(manifest)
    except ManifestError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if manifest.model_revision != rev:
        print(f"refused: manifest revision {manifest.model_revision} != {rev}", file=sys.stderr)
        return 2
    if report.get("files") != [{"name": f.name, "sha256": f.sha256} for f in manifest.files]:
        print(f"refused: intake report files differ from the manifest of {rev}", file=sys.stderr)
        return 2
    target = f"{args.user}@{args.host}"
    checks = [(f.sha256, f.name) for f in manifest.files]
    checks.append((_sha256(folder / MANIFEST_NAME), MANIFEST_NAME))
    report_check = (_sha256(folder / REPORT_NAME), REPORT_NAME)
    t = args.timeout
    r = _run(runner, [*ssh, target, remote_script("prepare", rev)], t)
    if r is None:
        return 1
    stage_dir = (r.stdout or "").strip()
    if not _STAGE.fullmatch(stage_dir):
        print(f"refused: unexpected remote temp dir {stage_dir!r}", file=sys.stderr)
        return 1
    if _run(runner, [*scp, str(folder), f"{target}:{stage_dir}/{rev}"], t) is None:
        _run(runner, [*ssh, target, f"rm -rf -- {shlex.quote(stage_dir)}"], t)
        return 1
    r = _run(runner, [*ssh, target, remote_script("push", rev, args.root, checks=checks,
                                                  report=report_check,
                                                  stage=f"{stage_dir}/{rev}")], t)
    if r is None:
        return 1
    print(r.stdout or "", end="")
    print(f"shadow -> {args.root}/{rev} on {args.host}")
    return 0


def main(argv=None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("push", "rollback", "status"):
        p = sub.add_parser(name)
        p.add_argument("host")
        if name == "push":
            p.add_argument("revision")
            p.add_argument("--models", default=str(ROOT / "data" / "perception" / "models"))
        p.add_argument("--user", default=operator_ssh.USER)
        p.add_argument("--root", default=REMOTE_ROOT)
        operator_ssh.add_arguments(p)
        p.add_argument("--timeout", type=float,
                       default=PUSH_TIMEOUT_S if name == "push" else STATUS_TIMEOUT_S,
                       help="seconds per ssh/scp step")
    args = ap.parse_args(argv)
    for label, value in (("host", args.host), ("user", args.user)):
        if not operator_ssh.safe_name(value):
            print(f"refused: unsafe {label} {value!r}", file=sys.stderr)
            return 2
    if not _SAFE_ROOT.fullmatch(args.root) or ".." in args.root.split("/"):
        print(f"refused: --root must be an absolute plain path, got {args.root!r}",
              file=sys.stderr)
        return 2
    try:
        opts = operator_ssh.options(*operator_ssh.resolve(args.identity, args.known_hosts))
    except operator_ssh.SshConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    ssh, scp = ["ssh", *opts, "--"], ["scp", "-r", *opts, "--"]
    if args.action == "push":
        return _push(args, ssh, scp, runner)
    r = _run(runner, [*ssh, f"{args.user}@{args.host}",
                      remote_script(args.action, None, args.root)], args.timeout)
    if r is None:
        return 1
    print(r.stdout or "", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
