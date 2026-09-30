"""Deliver an intake-passed model to a robot's shadow slot (D-356, D-373).

deliver.py push <host> <model_revision> [--models data/perception/models]
deliver.py rollback <host>
deliver.py release-hold <host>   (ends an operator hold, see operator_hold)
deliver.py status <host>
common: [--user rosy] [--identity KEY] [--known-hosts FILE] [--root /var/lib/rosy/models]
        [--timeout S]  (per ssh/scp step; 600 for push, 60 for rollback/status)
push/rollback: [--operator NAME] (default: the OS user; recorded in history.jsonl)
status: [--history N] (last N history.jsonl lines, default 5)

Every pointer change (push, rollback) runs on the robot as root under flock on
/var/lib/rosy/models/.lock (30 s wait, then a clear "busy" failure) and appends
one JSON line {ts, action, revision, previous, operator, host_of_operator,
tool_commit} to /var/lib/rosy/models/history.jsonl (root:rosy-camera 0640).

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
import getpass
import hashlib
import json
import re
import shlex
import socket
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


LOCK_WAIT_S = 30
LOCK_BUSY_EXIT = 75  # flock -E: the lock stayed held for LOCK_WAIT_S
LOCK_NAME, HISTORY_NAME = ".lock", "history.jsonl"
OBSERVE_SEPARATOR, OBSERVE_HISTORY = "--- history", 50
POINTER_ACTIONS = ("push", "rollback", "release-hold")


def operator_hold(history: list[dict]) -> str | None:
    """The revision an operator rolled back from, while that rollback is the
    latest pointer action (a later push or release-hold ends the hold)."""
    last = next((h for h in reversed(history) if h.get("action") in POINTER_ACTIONS), None)
    if last and last["action"] == "rollback":
        return last.get("previous") or None
    return None


def parse_observation(text: str) -> dict:
    head, _, tail = text.partition(OBSERVE_SEPARATOR)
    pointer = head.strip()
    history = []
    for line in tail.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            history.append(entry)
    return {"shadow": pointer.rsplit("/", 1)[-1] if pointer else None, "history": history}


def observe(host: str, *, identity: str, known_hosts: str, user: str = "rosy",
            root: str = None, timeout: float = None, runner=subprocess.run) -> dict:
    """{"shadow": revision or None, "history": [recent history.jsonl entries]}."""
    opts = operator_ssh.options(identity, known_hosts)
    r = _run(runner, ["ssh", *opts, "--", f"{user}@{host}",
                      remote_script("observe", None, root or REMOTE_ROOT)],
             timeout or STATUS_TIMEOUT_S)
    if r is None:
        raise RuntimeError(f"cannot read the shadow pointer on {host}")
    return parse_observation(r.stdout or "")
_HISTORY_LINE = ('{"ts":"%s","action":%s,"revision":"%s","previous":"%s",'
                 '"operator":%s,"host_of_operator":%s,"tool_commit":%s}\\n')


def _safe_word(expr: str) -> str:
    """Shell text: the value of expr reduced to revision characters (JSON-safe)."""
    return f"$(printf %s {expr} | tr -cd 'A-Za-z0-9._-')"


def remote_script(action: str, rev: str | None, root: str = REMOTE_ROOT, *,
                  checks=(), report=None, stage: str | None = None, audit=None,
                  history: int = 5, lock_wait: int = LOCK_WAIT_S,
                  privileged: bool = True) -> str:
    """Shell text for one remote step. Every path is shlex.quote'd.

    checks: [(sha256, file name), ...] of the model: manifest-listed files and
    the manifest. report: (sha256, name) of the intake report, installed too.
    stage: the scp'd copy, <mktemp dir>/<rev>; the mktemp dir is removed on exit.
    audit: {operator, host_of_operator, tool_commit} for the history line (push,
    rollback). Pointer changes run as root under flock on <root>/.lock (wait
    lock_wait s, exit 75 if busy) and append one JSON line to history.jsonl.
    privileged=False drops sudo -n and the -o/-g/-m of install so the script runs
    as an ordinary user in tests (Git Bash cannot set directory modes either);
    main() never passes it."""
    q = shlex.quote
    s = f"{SUDO} " if privileged else ""
    own = f" -o {OWNER} -g {GROUP}" if privileged else ""
    dmode, fmode = (" -m 0750", " -m 0640") if privileged else ("", "")
    ptr, prev, tmp = q(f"{root}/shadow"), q(f"{root}/shadow.previous"), q(f"{root}/shadow.tmp")
    lock, hist = q(f"{root}/{LOCK_NAME}"), q(f"{root}/{HISTORY_NAME}")

    def check(folder: str, *, quiet: bool = False, files=None) -> str:
        files = everything if files is None else files
        sums = " ".join(q(f"{sha}  {folder}/{name}") for sha, name in files)
        return (f"printf '%s\\n' {sums} | sha256sum -c -"
                + (" >/dev/null 2>&1" if quiet else ""))

    def history_line(act: str, revision_expr: str, previous_expr: str) -> list[str]:
        a = audit or {}
        return [
            f"test -f {hist} || install{own}{fmode} /dev/null {hist}",
            f"printf {q(_HISTORY_LINE)} \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" "
            f"{q(json.dumps(act))} \"{_safe_word(revision_expr)}\" "
            f"\"{_safe_word(previous_expr)}\" {q(json.dumps(a.get('operator')))} "
            f"{q(json.dumps(a.get('host_of_operator')))} {q(json.dumps(a.get('tool_commit')))}"
            f" | tee -a {hist} >/dev/null",
        ]

    def locked(inner: list[str]) -> list[str]:
        """Run inner (as root via sudo -n) while holding the models lock."""
        body = "\n".join(["set -e", *inner])
        return [
            f"{s}test -d {q(root)} || {s}install -d{own}{dmode} {q(root)}",
            f"{s}test -f {lock} || {s}install{own}{fmode} /dev/null {lock}",
            f"{s}flock -E {LOCK_BUSY_EXIT} -w {lock_wait} {lock} sh -c {q(body)} || {{ rc=$?;",
            f"  [ $rc -ne {LOCK_BUSY_EXIT} ] || echo {q(f'models lock {root}/{LOCK_NAME} busy for {lock_wait} s: another push or rollback is running; retry later')} >&2;",
            "  exit $rc; }",
        ]

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
        installs = [f"install{own}{fmode} {q(f'{stage}/{name}')} "
                    f"{q(f'{partial_path}/{name}')}" for _, name in everything]
        report_dst = f"{final_path}/{report[1]}"
        return "\n".join([
            "set -e",
            # first: nothing after mktemp may fail before the temp dir is cleaned up
            f"trap {q(f'rm -rf -- {q(stage_dir)}')} EXIT",
            check(stage),
            *locked([
                f"rm -rf {partial}",
                f"install -d{own}{dmode} {partial}",
                *installs,
                check(partial_path),
                # an installed <rev> is judged on its model files only: a re-run
                # intake writes a new report, which replaces the old one
                f"if test -d {final}; then",
                f"  if {check(final_path, quiet=True, files=checks)}; then",
                f"    install{own}{fmode} {q(f'{stage}/{report[1]}')} {q(report_dst + '.tmp')}",
                f"    mv {q(report_dst + '.tmp')} {q(report_dst)}",
                f"    rm -rf {partial}",
                f"  else mv {final} {final}.bad.$$; mv {partial} {final}; fi",
                f"else mv {partial} {final}; fi",
                check(final_path),
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                f'if [ "$cur" != {final} ]; then',
                f"  if test -f {ptr}; then",
                f"    install{own}{fmode} {ptr} {prev}.tmp",
                f"    mv {prev}.tmp {prev}",
                "  fi",
                # separate statements: set -e ignores a failure inside an && list
                f"  printf %s {final} > {pointer_src}",
                f"  install{own}{fmode} {pointer_src} {tmp}",
                f"  mv {tmp} {ptr}",
                "  sync",
                "fi",
                *history_line("push", q(rev), '"${cur##*/}"'),
            ]),
        ])
    if action == "rollback":
        return "\n".join([
            "set -e",
            *locked([
                f"test -f {prev} || {{ echo 'no shadow.previous to roll back to' >&2; exit 1; }}",
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                f"new=$(cat {prev})",
                f"mv {prev} {ptr}",
                "sync",
                *history_line("rollback", '"${new##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "release-hold":  # history only: ends an operator hold (operator_hold)
        return "\n".join([
            "set -e",
            *locked([
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                *history_line("release-hold", '"${cur##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "observe":  # machine-read by watch.py
        return "\n".join([
            f"{s}cat {ptr} 2>/dev/null || true",
            "echo",
            f"echo {q(OBSERVE_SEPARATOR)}",
            f"{s}tail -n {OBSERVE_HISTORY} {hist} 2>/dev/null || true",
        ])
    if action == "status":
        return "\n".join([
            f"echo \"shadow: $({s}cat {ptr} 2>/dev/null)\"",
            f"echo \"previous: $({s}cat {prev} 2>/dev/null)\"",
            f"{s}ls -1 {q(root)} 2>/dev/null || true",
            f"echo 'history (last {int(history)}):'",
            f"{s}tail -n {int(history)} {hist} 2>/dev/null || true",
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
                                                  report=report_check, audit=_audit(args),
                                                  stage=f"{stage_dir}/{rev}")], t)
    if r is None:
        return 1
    print(r.stdout or "", end="")
    print(f"shadow -> {args.root}/{rev} on {args.host}")
    return 0


def _tool_commit() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                           capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def _audit(args) -> dict:
    return {"operator": args.operator, "host_of_operator": socket.gethostname(),
            "tool_commit": _tool_commit()}


def main(argv=None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("push", "rollback", "release-hold", "status"):
        p = sub.add_parser(name)
        p.add_argument("host")
        if name == "push":
            p.add_argument("revision")
            p.add_argument("--models", default=str(ROOT / "data" / "perception" / "models"))
        p.add_argument("--user", default=operator_ssh.USER)
        p.add_argument("--root", default=REMOTE_ROOT)
        operator_ssh.add_arguments(p)
        if name in ("push", "rollback", "release-hold"):
            p.add_argument("--operator", default=getpass.getuser(),
                           help="who is recorded in the robot's history.jsonl")
        else:
            p.add_argument("--history", type=int, default=5, help="history lines to show")
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
    extra = ({"history": max(args.history, 0)} if args.action == "status"
             else {"audit": _audit(args)})
    r = _run(runner, [*ssh, f"{args.user}@{args.host}",
                      remote_script(args.action, None, args.root, **extra)], args.timeout)
    if r is None:
        return 1
    print(r.stdout or "", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
