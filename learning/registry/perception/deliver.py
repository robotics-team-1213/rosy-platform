"""Deliver an intake-passed model to a robot's shadow slot (D-356, D-373).

deliver.py push <host> <model_revision> [--models data/perception/models]
deliver.py rollback <host> [--slot shadow|active]
deliver.py promote <host>        (D-423: active <- shadow, the old active -> previous;
                                  a no-op when shadow is already active; not for lane_seg)
push: [--allow-unsigned] [--check KEYS_DIR]  object_det must be signed (sign_model.py)
deliver.py release-hold <host>   (removes the hold file; the pointer is not changed)
deliver.py status <host>
push/rollback/release-hold/status: [--slot shadow|paint]  (lane_seg; paint is the D-408
        learned paint pointer <root>/paint with paint.previous and paint.hold, moved only by
        hand; shadow, shadow.previous, hold and the site watcher never touch it.
        Nothing reads paint by default: line_observer uses it only when
        /etc/rosy/line_observer_overrides.yaml sets learned_lane_pointer:
        /var/lib/rosy/models/paint, and host_lane_perception.py still reads shadow.
        paint.hold is a record of the manual change only: the watcher never pushes paint,
        so there is nothing for it to stop. status --slot paint prints the paint lines,
        then the usual shadow status. The first paint push leaves no paint.previous, so
        rollback --slot paint refuses until a second push.)
common: [--task lane_seg|object_det] [--user rosy] [--identity KEY] [--known-hosts FILE]
        [--journal-dir DIR] (private local attempt files, fsynced before each network step)
        [--root /var/lib/rosy/models]  (the task's pointers live under learned/slots.task_root:
        lane_seg keeps the flat D-373 root, object_det uses <root>/object_det)
        [--timeout S]  (per ssh/scp step; 600 for push, 60 for rollback/status)
push/rollback: [--operator NAME] (default: the OS user; recorded in history.jsonl)
status: [--history N] (last N history.jsonl lines, default 5)

Every pointer change (push, rollback, release-hold) runs on the robot as root under flock on
/var/lib/rosy/models/.lock and appends one JSON line {ts, action, revision, previous, operator,
host_of_operator, tool_commit} to history.jsonl (root:rosy-camera 0640; audit only). A manual
push or rollback first writes the hold file /var/lib/rosy/models/hold {by, host, ts, action,
revision, reason}, which stops the site watcher (push --unless-held) until release-hold removes it.
push/rollback/promote: [--readback] also read the node's status (promote_readback.py; D-773 A3).

Exit codes: 0 ok, 1 failed, 2 refused locally, 3 history.jsonl not appendable, 75 lock busy for 30 s
(retry later), 76 held (--unless-held only; nothing changed), 77 the host name did not resolve (DNS / mDNS),
78 connection refused, timed out or no route, 79 host key unknown or changed (strict checking; never
auto-accepted). 77-79 come from ssh's own failure text, with one stderr line "ssh <kind> (exit N): ...".
--host-key-alias NAME: the host key is looked up under NAME (the robot id), not the address; the pin
survives a renumbered network. A --readback result never changes these codes.

SSH is key-only and pinned (BatchMode, IdentitiesOnly, StrictHostKeyChecking=yes; see operator_ssh.py).
/var/lib/rosy/models is root:rosy-camera 0750, so every write goes through `sudo -n install` with that owner and mode.

push: needs a passing intake_report.json whose files (name, sha256) equal the manifest's. The folder
is scp'd to a mktemp dir under /tmp (the rosy user's), checked there, then installed file by file
(weights, manifest and report, each pinned by sha256) into <rev>.partial, checked again, and moved to <rev>. The
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
import shlex
import socket
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[2]
for _p in (_HERE, ROOT / "middleware" / "perception", ROOT / "integrations" / "perception",
           ROOT / "contracts" / "foundation", ROOT / 'learning/evaluation/perception', ROOT / 'tools/perception'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import delivery_journal  # noqa: E402
import operator_ssh  # noqa: E402
import promote_readback  # noqa: E402
from deliver_helpers import (  # noqa: E402, F401
    GROUP,
    HELD_EXIT,
    HISTORY_EXIT,
    HISTORY_NAME,
    HOLD_NAME,
    LOCK_BUSY_EXIT,
    LOCK_NAME,
    LOCK_WAIT_S,
    OBSERVE_SEPARATOR,
    OWNER,
    POINTER_SLOTS,
    PUSH_TIMEOUT_S,
    REMOTE_ROOT,
    REPORT_NAME,
    STATUS_TIMEOUT_S,
    SUDO,
    SshFailure,
    _HISTORY_LINE,
    _HOLD_JSON,
    _SAFE_ROOT,
    _STAGE,
    _remote_rc,
    _run,
    _safe_word,
    observe,
    parse_observation,
    remote_script,
)
from intake_eval_gate import road_delivery_error, v13_lineage_error  # noqa: E402
from perception_runtime.perception.learned.manifest import (  # noqa: E402
    MANIFEST_NAME, TASKS, ManifestError, check_revision, load_manifest, verify_files)
from perception_runtime.perception.learned.signature import (  # noqa: E402
    SIGNATURE_NAME, SignatureError, verify_manifest_signature)
from perception_runtime.perception.learned.slots import FLAT_TASKS, task_root  # noqa: E402

#: Tasks whose robot node refuses unsigned bundles (D-423; lane_seg is warn-only for now).
SIGNED_TASKS = ("object_det",)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _push(args, ssh, scp, runner) -> int:
    rev = args.revision
    try:
        check_revision(rev)
    except ManifestError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if rev.startswith("v13-drivable-") and (args.task != "lane_seg" or args.slot != "shadow"):
        print("refused: v13-drivable goes only to the lane_seg shadow slot (D-554)", file=sys.stderr)
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
    if road_delivery_error(manifest.raw):
        print(f"refused: {road_delivery_error(manifest.raw)}", file=sys.stderr)
        return 2
    if rev.startswith("v13-drivable-") and v13_lineage_error(manifest.raw):
        print(f"refused: {v13_lineage_error(manifest.raw)}", file=sys.stderr)
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
                                                  stage=f"{stage_dir}/{rev}", slot=args.slot)], t,
             long_step=True)
    if r.returncode != 0:
        return _remote_rc(r)
    print(r.stdout or "", end="")
    print(f"{args.slot} -> {args.root}/{rev} on {args.host}")
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
    slot = getattr(args, 'slot', 'shadow')
    action = 'rollback-active' if slot == 'active' else args.action
    if action != 'promote' and slot in POINTER_SLOTS:
        extra['slot'] = slot
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
        # rollback alone takes active: it is the only command that moves the D-423 active
        # pointer back; promote has no --slot because it always copies shadow to active.
        if name == "rollback":
            p.add_argument("--slot", choices=(*POINTER_SLOTS, "active"), default="shadow",
                           help="active: back to the model before the last promote (D-423); "
                                "paint: back to paint.previous (lane_seg)")
        elif name != "promote":
            p.add_argument("--slot", choices=POINTER_SLOTS, default="shadow",
                           help="paint: the D-408 learned paint pointer (lane_seg; own previous and hold)")
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
            p.add_argument("--readback", action="store_true", help="check the node's loaded revision")
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
    if getattr(args, "slot", "shadow") == "paint" and args.task not in FLAT_TASKS:
        print(f"refused: the paint slot is a lane_seg pointer, not {args.task}", file=sys.stderr)
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
        promote_readback.after_change(args, ssh, runner, code, lambda: _audit(args) if hasattr(args, "operator")
                                      else {}, sys.stderr)
        return code
    except delivery_journal.JournalError as exc:
        print(str(exc), file=sys.stderr)
        return HISTORY_EXIT


if __name__ == "__main__":
    sys.exit(main())
