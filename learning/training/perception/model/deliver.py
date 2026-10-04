"""Deliver an intake-passed model to a robot's shadow slot (D-356, D-373).

deliver.py push <host> <model_revision> [--models data/perception/models]
deliver.py rollback <host> [--slot shadow|active]
deliver.py promote <host>        (D-423: active <- shadow, the old active -> previous;
                                  a no-op when shadow is already active; not for lane_seg)
push: [--allow-unsigned] [--check KEYS_DIR]  object_det must be signed (sign_model.py)
deliver.py release-hold <host>   (removes the hold file; the pointer is not changed)
deliver.py status <host>
common: [--task lane_seg|object_det] [--user rosy] [--identity KEY] [--known-hosts FILE]
        [--journal-dir DIR] (private local attempt files, fsynced before each network step)
        [--root /var/lib/rosy/models]  (the task's pointers live under learned/slots.task_root:
        lane_seg keeps the flat D-373 root, object_det uses <root>/object_det)
        [--timeout S]  (per ssh/scp step; 600 for push, 60 for rollback/status)
push/rollback: [--operator NAME] (default: the OS user; recorded in history.jsonl)
status: [--history N] (last N history.jsonl lines, default 5)

Every pointer change (push, rollback, release-hold) runs on the robot as root
under flock on /var/lib/rosy/models/.lock and appends one JSON line {ts, action,
revision, previous, operator, host_of_operator, tool_commit} to history.jsonl
(root:rosy-camera 0640; audit only). A manual push or rollback first writes the
hold file /var/lib/rosy/models/hold {by, host, ts, action, revision, reason},
which stops the site watcher (push --unless-held) for that robot until
release-hold removes it.

Exit codes: 0 ok, 1 failed, 2 refused locally, 3 history.jsonl not appendable,
75 lock busy for 30 s (retry later), 76 held (--unless-held only; nothing changed),
77 the host name did not resolve (DNS / mDNS), 78 connection refused, timed out or no
route, 79 host key unknown or changed (strict checking; never auto-accepted). 77-79
come from ssh's own failure text, with one stderr line "ssh <kind> (exit N): ...".
--host-key-alias NAME: the host key is looked up under NAME (the robot id), not the
address; the pin survives a renumbered network.

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

ROOT = Path(__file__).resolve().parents[4]
for _p in (ROOT / "src" / "runtime" / "sensing",
           ROOT / "src" / "contracts" / "foundation", ROOT / "learning" / "training" / "perception"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
import delivery_journal  # noqa: E402
from control.sensing.perception.learned.manifest import (  # noqa: E402
    MANIFEST_NAME, TASKS, ManifestError, check_revision, load_manifest, verify_files)
from control.sensing.perception.learned.slots import FLAT_TASKS, task_root  # noqa: E402
from control.sensing.perception.learned.signature import (  # noqa: E402
    SIGNATURE_NAME, SignatureError, verify_manifest_signature)

#: Tasks whose robot node refuses unsigned bundles (D-423; lane_seg is warn-only for now).
SIGNED_TASKS = ("object_det",)

REMOTE_ROOT = "/var/lib/rosy/models"
REPORT_NAME = "intake_report.json"
SUDO, OWNER, GROUP = "sudo -n", "root", "rosy-camera"  # D-373 decision 1
PUSH_TIMEOUT_S, STATUS_TIMEOUT_S = 600, 60
_SAFE_ROOT = re.compile(r"/[A-Za-z0-9._/-]+")
_STAGE = re.compile(r"/tmp/rosy-model\.[A-Za-z0-9]{8,}")


LOCK_WAIT_S = 30
LOCK_BUSY_EXIT = 75  # only flock -w running out (flock -E); the body never exits 75
HELD_EXIT = 76  # --unless-held found the hold file; nothing was touched
HISTORY_EXIT = 3  # history.jsonl not appendable (before: nothing changed; after: see stderr)
LOCK_NAME, HISTORY_NAME, HOLD_NAME = ".lock", "history.jsonl", "hold"
OBSERVE_SEPARATOR = "--- hold"
_HISTORY_LINE = ('{"ts":"%s","action":%s,"revision":"%s","previous":"%s",'
                 '"operator":%s,"host_of_operator":%s,"tool_commit":%s}\\n')
_HOLD_JSON = '{"by":%s,"host":%s,"ts":"%s","action":%s,"revision":"%s","reason":%s}\\n'


def parse_observation(text: str) -> dict:
    """{"shadow": revision or None, "hold": the hold file (dict) or None}."""
    head, _, tail = text.partition(OBSERVE_SEPARATOR)
    pointer, hold_text = head.strip(), tail.strip()
    hold = None
    if hold_text:
        try:
            hold = json.loads(hold_text)
        except ValueError:
            hold = {"raw": hold_text}
        if not isinstance(hold, dict):
            hold = {"raw": hold_text}
    return {"shadow": pointer.rsplit("/", 1)[-1] if pointer else None, "hold": hold}


class SshFailure(RuntimeError):
    """A network-level ssh failure (kind: dns | unreachable | hostkey)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def observe(host: str, *, identity: str, known_hosts: str, user: str = "rosy",
            root: str | None = None, timeout: float | None = None,
            runner=subprocess.run, host_key_alias: str | None = None) -> dict:
    """The robot's real shadow pointer and hold file (watch.py, rosy_ml)."""
    opts = operator_ssh.options(identity, known_hosts, host_key_alias)
    r = _run(runner, ["ssh", *opts, "--", f"{user}@{host}",
                      remote_script("observe", None, root or REMOTE_ROOT)],
             timeout or STATUS_TIMEOUT_S)
    if r.returncode != 0:
        if getattr(r, "net_kind", None):
            raise SshFailure(r.net_kind, f"{r.net_kind}: {r.net_detail}")
        raise RuntimeError(f"cannot read the shadow pointer on {host}")
    return parse_observation(r.stdout or "")


def _safe_word(expr: str) -> str:
    """Shell text: the value of expr reduced to revision characters (JSON-safe)."""
    return f"$(printf %s {expr} | tr -cd 'A-Za-z0-9._-')"


def remote_script(action: str, rev: str | None, root: str = REMOTE_ROOT, *,
                  checks=(), report=None, stage: str | None = None, audit=None,
                  unless_held: bool = False, history: int = 5,
                  lock_wait: int = LOCK_WAIT_S, privileged: bool = True) -> str:
    """Shell text for one remote step. Every path is shlex.quote'd.

    checks: [(sha256, file name), ...] of the model: manifest-listed files and
    the manifest. report: (sha256, name) of the intake report, installed too.
    stage: the scp'd copy, <mktemp dir>/<rev>; the mktemp dir is removed on exit.
    audit: {operator, host_of_operator, tool_commit} for hold and history.

    Pointer changes run as root under flock on <root>/.lock (wait lock_wait s,
    exit 75 only if the lock stayed busy). A manual push or rollback writes the
    hold file first (fail safe), then moves the pointer, then appends history.
    unless_held (the site watcher): if the hold file exists, exit 76 untouched.
    release-hold removes the hold file; the pointer is not changed.
    privileged=False drops sudo -n and the owner/mode flags so the script runs
    as an ordinary user in tests; main() never passes it."""
    q = shlex.quote
    a = audit or {}
    s = f"{SUDO} " if privileged else ""
    own = f" -o {OWNER} -g {GROUP}" if privileged else ""
    dmode, fmode = (" -m 0750", " -m 0640") if privileged else ("", "")
    ptr, prev, tmp = q(f"{root}/shadow"), q(f"{root}/shadow.previous"), q(f"{root}/shadow.tmp")
    act, act_prev = q(f"{root}/active"), q(f"{root}/previous")  # D-423 slots
    lock, hist = q(f"{root}/{LOCK_NAME}"), q(f"{root}/{HISTORY_NAME}")
    hold, hold_tmp = q(f"{root}/{HOLD_NAME}"), q(f"{root}/{HOLD_NAME}.tmp")
    ts = '"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'

    def check(folder: str, *, quiet: bool = False, files=None) -> str:
        files = everything if files is None else files
        sums = " ".join(q(f"{sha}  {folder}/{name}") for sha, name in files)
        return (f"printf '%s\\n' {sums} | sha256sum -c -"
                + (" >/dev/null 2>&1" if quiet else ""))

    def history_ready() -> list[str]:
        return [
            f"test -e {hist} || install{own}{fmode} /dev/null {hist}",
            # a subshell: a redirect error on the special builtin : would end the shell
            f"(: >> {hist}) 2>/dev/null || {{ echo 'history.jsonl is not appendable; nothing changed' >&2;"
            f" exit {HISTORY_EXIT}; }}",
        ]

    def history_line(act: str, revision_expr: str, previous_expr: str) -> list[str]:
        return [
            f"printf {q(_HISTORY_LINE)} {ts} {q(json.dumps(act))} "
            f"\"{_safe_word(revision_expr)}\" \"{_safe_word(previous_expr)}\" "
            f"{q(json.dumps(a.get('operator')))} {q(json.dumps(a.get('host_of_operator')))} "
            f"{q(json.dumps(a.get('tool_commit')))} | tee -a {hist} >/dev/null"
            f" || {{ echo 'pointer changed, history not written' >&2; exit {HISTORY_EXIT}; }}",
        ]

    def write_hold(act: str, revision_expr: str) -> list[str]:
        """Before the pointer moves: a failure after this still leaves the hold."""
        return [
            f"install{own}{fmode} /dev/null {hold_tmp}",
            f"printf {q(_HOLD_JSON)} {q(json.dumps(a.get('operator')))} "
            f"{q(json.dumps(a.get('host_of_operator')))} {ts} {q(json.dumps(act))} "
            f"\"{_safe_word(revision_expr)}\" {q(json.dumps('manual ' + act))} > {hold_tmp}",
            f"mv {hold_tmp} {hold}",
        ]

    def locked(inner: list[str], *, skip_if_held: bool = False) -> list[str]:
        """inner runs as root while holding the lock, in a subshell whose exit
        code 75/76 is remapped to 1, so 75 can only mean a busy lock and 76 only
        the held check."""
        gate = ([f"if test -e {hold}; then echo \"held: $(cat {hold})\" >&2; exit {HELD_EXIT}; fi"]
                if skip_if_held else [])
        body = "\n".join([
            *gate,
            "set +e",
            "(",
            "set -e",
            *inner,
            ")",
            "rc=$?",
            f"case $rc in {LOCK_BUSY_EXIT}|{HELD_EXIT}) rc=1;; esac",
            "exit $rc",
        ])
        make_lock = f": >> {lock}" + (f"; chown {OWNER}:{GROUP} {lock}; chmod 0640 {lock}"
                                      if privileged else "")
        return [
            f"{s}test -d {q(root)} || {s}install -d{own}{dmode} {q(root)}",
            # create in place, never unlink: a concurrent holder keeps the same inode
            f"{s}sh -c {q(make_lock)}",
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
                *history_ready(),
                *([] if unless_held else write_hold("push", q(rev))),
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
            ], skip_if_held=unless_held),
        ])
    if action == "rollback":
        return "\n".join([
            "set -e",
            *locked([
                f"test -f {prev} || {{ echo 'no shadow.previous to roll back to' >&2; exit 1; }}",
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                f"new=$(cat {prev})",
                *history_ready(),
                *write_hold("rollback", '"${new##*/}"'),
                f"mv {prev} {ptr}",
                "sync",
                *history_line("rollback", '"${new##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "promote":  # D-423: active <- shadow; the old active -> previous
        return "\n".join([
            "set -e",
            *locked([
                f"test -s {ptr} || {{ echo 'no shadow model to promote' >&2; exit 1; }}",
                f"new=$(cat {ptr})",
                f"cur=$(cat {act} 2>/dev/null || true)",
                # nothing to do: no hold, no previous, no history line
                'if [ "$new" = "$cur" ]; then echo "shadow is already active; nothing changed"; exit 0; fi',
                *history_ready(),
                *write_hold("promote", '"${new##*/}"'),
                f"if test -f {act}; then install{own}{fmode} {act} {act_prev}.tmp; mv {act_prev}.tmp {act_prev}; fi",
                f"install{own}{fmode} {ptr} {act}.tmp",
                f"mv {act}.tmp {act}",
                "sync",
                *history_line("promote", '"${new##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "rollback-active":  # D-423: active <- previous
        return "\n".join([
            "set -e",
            *locked([
                f"test -f {act_prev} || {{ echo 'no previous active model to roll back to' >&2; exit 1; }}",
                f"cur=$(cat {act} 2>/dev/null || true)",
                f"new=$(cat {act_prev})",
                *history_ready(),
                *write_hold("rollback-active", '"${new##*/}"'),
                f"mv {act_prev} {act}",
                "sync",
                *history_line("rollback-active", '"${new##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "release-hold":  # removes the hold; the pointer is not changed
        return "\n".join([
            "set -e",
            *locked([
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                *history_ready(),
                f"rm -f {hold}",
                *history_line("release-hold", '"${cur##*/}"', '"${cur##*/}"'),
            ]),
        ])
    if action == "observe":  # machine-read by watch.py and rosy_ml
        return "\n".join([
            f"{s}cat {ptr} 2>/dev/null || true",
            "echo",
            f"echo {q(OBSERVE_SEPARATOR)}",
            f"{s}cat {hold} 2>/dev/null || true",
        ])
    if action == "status":
        return "\n".join([
            f"echo \"shadow: $({s}cat {ptr} 2>/dev/null)\"",
            f"echo \"previous: $({s}cat {prev} 2>/dev/null)\"",
            f"echo \"active: $({s}cat {act} 2>/dev/null)\"",
            f"echo \"active previous: $({s}cat {act_prev} 2>/dev/null)\"",
            f"echo \"hold: $({s}cat {hold} 2>/dev/null || echo none)\"",
            f"{s}ls -1 {q(root)} 2>/dev/null || true",
            f"echo 'history (last {int(history)}):'",
            f"{s}tail -n {int(history)} {hist} 2>/dev/null || true",
        ])
    raise ValueError(f"unknown action {action!r}")


def _run(runner, cmd, timeout: float, *, long_step: bool = False):
    """The completed process (returncode 124 on a timeout); failures go to stderr.

    A timeout is a failed step (the watcher retries it on a later run)."""
    try:
        r = runner(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess(cmd, 124, "", "")
        if long_step:
            print(f"failed (timeout {timeout:g} s): {cmd[0]}", file=sys.stderr)
            return r
    if r.returncode != 0:
        kind = operator_ssh.classify(r.returncode, getattr(r, "stderr", ""),
                                   timeout_is_network=not long_step)
        if kind:  # one clear line; the exit code is KIND_EXIT[kind]
            lines = (getattr(r, "stderr", "") or "").strip().splitlines()
            r.net_kind, r.net_detail = kind, (lines[0] if lines else f"{cmd[0]} timed out")
            print(f"ssh {kind} (exit {operator_ssh.KIND_EXIT[kind]}): {r.net_detail}",
                  file=sys.stderr)
            return r
        word = {HELD_EXIT: "held", LOCK_BUSY_EXIT: "busy"}.get(r.returncode, "failed")
        print(f"{word} ({r.returncode}): {cmd[0]} {getattr(r, 'stderr', '')}", file=sys.stderr)
    return r


def _remote_rc(r) -> int:
    """A network failure maps to its own code (77 dns, 78 unreachable, 79 hostkey); 75 busy,
    76 held and 3 history not written pass through (the docstring's codes); any other
    remote failure is 1."""
    if getattr(r, "net_kind", None):
        return operator_ssh.KIND_EXIT[r.net_kind]
    return r.returncode if r.returncode in (LOCK_BUSY_EXIT, HELD_EXIT, HISTORY_EXIT) else 1


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
    if manifest.task != args.task:
        print(f"refused: {rev} is a {manifest.task} model, not {args.task}", file=sys.stderr)
        return 2
    if manifest.task in SIGNED_TASKS:
        if not (folder / SIGNATURE_NAME).is_file() and not args.allow_unsigned:
            print(f"refused: {rev} is unsigned and the robot refuses unsigned {manifest.task} bundles; "
                  f"sign it (sign_model.py) or pass --allow-unsigned for a dev robot", file=sys.stderr)
            return 2
        if args.check:
            try:
                print(f"signature verified with {verify_manifest_signature(folder, args.check)}")
            except SignatureError as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2
    if report.get("files") != [{"name": f.name, "sha256": f.sha256} for f in manifest.files]:
        print(f"refused: intake report files differ from the manifest of {rev}", file=sys.stderr)
        return 2
    target = f"{args.user}@{args.host}"
    checks = [(f.sha256, f.name) for f in manifest.files]
    checks.append((_sha256(folder / MANIFEST_NAME), MANIFEST_NAME))
    if (folder / SIGNATURE_NAME).is_file():  # D-423: the robot verifies it before opening
        checks.append((_sha256(folder / SIGNATURE_NAME), SIGNATURE_NAME))
    report_check = (_sha256(folder / REPORT_NAME), REPORT_NAME)
    args.delivery_attempt.write('model_verified', revision=rev,
                                manifest_sha256=next(sha for sha, name in checks if name == MANIFEST_NAME),
                                intake_report_sha256=report_check[0])
    t = args.timeout
    r = _run(runner, [*ssh, target, remote_script("prepare", rev)], t)
    if r.returncode != 0:
        return _remote_rc(r)
    stage_dir = (r.stdout or "").strip()
    if not _STAGE.fullmatch(stage_dir):
        print(f"refused: unexpected remote temp dir {stage_dir!r}", file=sys.stderr)
        return 1
    r = _run(runner, [*scp, str(folder), f"{target}:{stage_dir}/{rev}"], t, long_step=True)
    if r.returncode != 0:
        _run(runner, [*ssh, target, f"rm -rf -- {shlex.quote(stage_dir)}"], t)
        return _remote_rc(r)
    r = _run(runner, [*ssh, target, remote_script("push", rev, args.root, checks=checks,
                                                  report=report_check, audit=_audit(args),
                                                  unless_held=args.unless_held,
                                                  stage=f"{stage_dir}/{rev}")], t,
             long_step=True)
    if r.returncode != 0:
        return _remote_rc(r)
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


def _dispatch(args, ssh, scp, runner):
    if args.action == 'push':
        return _push(args, ssh, scp, runner)
    extra = ({'history': max(args.history, 0)} if args.action == 'status' else {'audit': _audit(args)})
    action = 'rollback-active' if getattr(args, 'slot', 'shadow') == 'active' else args.action
    result = _run(runner, [*ssh, f'{args.user}@{args.host}',
                           remote_script(action, None, args.root, **extra)], args.timeout)
    if result.returncode != 0:
        return _remote_rc(result)
    print(result.stdout or '', end='')
    return 0


def main(argv=None, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action", required=True)
    for name in ("push", "rollback", "promote", "release-hold", "status"):
        p = sub.add_parser(name)
        p.add_argument("host")
        p.add_argument("--task", choices=TASKS, default="lane_seg")
        if name == "rollback":
            p.add_argument("--slot", choices=("shadow", "active"), default="shadow",
                           help="active: back to the model before the last promote (D-423)")
        if name == "push":
            p.add_argument("revision")
            p.add_argument("--models", default=str(ROOT / "data" / "perception" / "models"))
            p.add_argument("--allow-unsigned", action="store_true",
                           help="push an unsigned object_det bundle (the robot also needs "
                                "ROSY_ALLOW_UNSIGNED_MODELS=true)")
            p.add_argument("--check", help="verify the signature against this trusted-keys folder first")
            p.add_argument("--unless-held", action="store_true",
                           help="site watcher: exit 76 without changes if the robot is held; "
                                "without it a push is manual and holds the robot")
        p.add_argument("--user", default=operator_ssh.USER)
        p.add_argument("--root", default=REMOTE_ROOT)
        p.add_argument('--journal-dir', type=Path, default=delivery_journal.default_root(),
                       help='private local durable attempt directory (never a robot acceptance claim)')
        operator_ssh.add_arguments(p)
        if name in ("push", "rollback", "promote", "release-hold"):
            p.add_argument("--operator", default=getpass.getuser(),
                           help="who is recorded in the robot's history.jsonl")
        else:
            p.add_argument("--history", type=int, default=5, help="history lines to show")
        p.add_argument("--timeout", type=float,
                       default=PUSH_TIMEOUT_S if name == "push" else STATUS_TIMEOUT_S,
                       help="seconds per ssh/scp step")
    args = ap.parse_args(argv)
    for label, value in (("host", args.host), ("user", args.user),
                         ("host-key-alias", args.host_key_alias or "a")):
        if not operator_ssh.safe_name(value):
            print(f"refused: unsafe {label} {value!r}", file=sys.stderr)
            return 2
    if not _SAFE_ROOT.fullmatch(args.root) or ".." in args.root.split("/"):
        print(f"refused: --root must be an absolute plain path, got {args.root!r}",
              file=sys.stderr)
        return 2
    if args.task in FLAT_TASKS and (args.action == "promote" or getattr(args, "slot", "shadow") == "active"):
        print(f"refused: {args.task} keeps the flat D-373 layout (shadow only); promote and "
              f"rollback --slot active are for per-task slots such as object_det", file=sys.stderr)
        return 2
    args.root = task_root(args.task, args.root)
    try:
        opts = operator_ssh.options(*operator_ssh.resolve(args.identity, args.known_hosts),
                                    args.host_key_alias)
    except operator_ssh.SshConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    ssh, scp = ["ssh", *opts, "--"], ["scp", "-r", *opts, "--"]
    try:
        attempt = delivery_journal.Attempt(args.journal_dir, args)
        args.delivery_attempt = attempt
        try:
            code = _dispatch(args, ssh, scp, attempt.runner(runner))
        except BaseException as exc:
            attempt.interrupted(exc)
            raise
        attempt.finish(code)
        return code
    except delivery_journal.JournalError as exc:
        print(str(exc), file=sys.stderr)
        return HISTORY_EXIT


if __name__ == "__main__":
    sys.exit(main())
