"""Remote shell script builder, observation parser, and SSH runner for ``deliver.py``."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[2]
for _p in (_HERE, ROOT / "middleware" / "perception", ROOT / "integrations" / "perception",
           ROOT / "contracts" / "foundation", ROOT / "learning/evaluation/perception", ROOT / "tools/perception"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import operator_ssh  # noqa: E402
from perception_runtime.perception.learned.manifest import MANIFEST_NAME  # noqa: E402

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
#: lane_seg pointer files deliver.py may move. shadow: the D-373 slot the site watcher fills.
#: paint: the D-408 learned paint model (line_observer learned_lane_pointer), moved only by
#: hand, with its own paint.previous and paint.hold so shadow and the watcher are untouched.
POINTER_SLOTS = ("shadow", "paint")
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
                  lock_wait: int = LOCK_WAIT_S, privileged: bool = True,
                  slot: str = "shadow") -> str:
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
    as an ordinary user in tests; main() never passes it.
    slot: the pointer (POINTER_SLOTS) push, rollback, release-hold and status act on;
    a slot other than shadow uses <slot>.previous, <slot>.hold and "<action>-<slot>"
    in hold and history."""
    if slot not in POINTER_SLOTS:
        raise ValueError(f"unknown slot {slot!r}")
    q = shlex.quote
    a = audit or {}
    s = f"{SUDO} " if privileged else ""
    own = f" -o {OWNER} -g {GROUP}" if privileged else ""
    dmode, fmode = (" -m 0750", " -m 0640") if privileged else ("", "")
    ptr, prev, tmp = q(f"{root}/{slot}"), q(f"{root}/{slot}.previous"), q(f"{root}/{slot}.tmp")
    act, act_prev = q(f"{root}/active"), q(f"{root}/previous")  # D-423 slots
    lock, hist = q(f"{root}/{LOCK_NAME}"), q(f"{root}/{HISTORY_NAME}")
    hold_name = HOLD_NAME if slot == "shadow" else f"{slot}.{HOLD_NAME}"
    hold, hold_tmp = q(f"{root}/{hold_name}"), q(f"{root}/{hold_name}.tmp")
    tag = "" if slot == "shadow" else f"-{slot}"
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

    def history_line(act_name: str, revision_expr: str, previous_expr: str) -> list[str]:
        return [
            f"printf {q(_HISTORY_LINE)} {ts} {q(json.dumps(act_name))} "
            f"\"{_safe_word(revision_expr)}\" \"{_safe_word(previous_expr)}\" "
            f"{q(json.dumps(a.get('operator')))} {q(json.dumps(a.get('host_of_operator')))} "
            f"{q(json.dumps(a.get('tool_commit')))} | tee -a {hist} >/dev/null"
            f" || {{ echo 'pointer changed, history not written' >&2; exit {HISTORY_EXIT}; }}",
            f"sync -f {hist} || {{ echo 'pointer changed; history durability unknown' >&2;"
            f" exit {HISTORY_EXIT}; }}",
        ]

    def write_hold(act_name: str, revision_expr: str) -> list[str]:
        """Before the pointer moves: a failure after this still leaves the hold."""
        return [
            f"install{own}{fmode} /dev/null {hold_tmp}",
            f"printf {q(_HOLD_JSON)} {q(json.dumps(a.get('operator')))} "
            f"{q(json.dumps(a.get('host_of_operator')))} {ts} {q(json.dumps(act_name))} "
            f"\"{_safe_word(revision_expr)}\" {q(json.dumps('manual ' + act_name))} > {hold_tmp}",
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
        pointer_src = q(f"{stage_dir}/{slot}")
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
                *([] if unless_held else write_hold("push" + tag, q(rev))),
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
                *history_line("push" + tag, q(rev), '"${cur##*/}"'),
            ], skip_if_held=unless_held),
        ])
    if action == "rollback":
        return "\n".join([
            "set -e",
            *locked([
                f"test -f {prev} || {{ echo 'no {slot}.previous to roll back to' >&2; exit 1; }}",
                f"cur=$(cat {ptr} 2>/dev/null || true)",
                f"new=$(cat {prev})",
                *history_ready(),
                *write_hold("rollback" + tag, '"${new##*/}"'),
                f"mv {prev} {ptr}",
                "sync",
                *history_line("rollback" + tag, '"${new##*/}"', '"${cur##*/}"'),
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
                *history_line("release-hold" + tag, '"${cur##*/}"', '"${cur##*/}"'),
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
        def versioned(label: str, pointer: str) -> list[str]:  # D-558: model_version beside the revision
            sed = r"""sed -n 's/.*"model_version": *"\(v[0-9][0-9.]*\)".*/\1/p'"""
            return [f"cur=$({s}cat {pointer} 2>/dev/null)",
                    f"ver=$({s}{sed} \"$cur/{MANIFEST_NAME}\" 2>/dev/null)",
                    f'echo "{label}: $cur${{ver:+ ($ver)}}"']
        if slot != "shadow":  # the slot's lines first, then the unchanged shadow status
            return "\n".join([
                *versioned(slot, ptr),
                f"echo \"{slot} previous: $({s}cat {prev} 2>/dev/null)\"",
                f"echo \"{hold_name}: $({s}cat {hold} 2>/dev/null || echo none)\"",
                remote_script("status", None, root, history=history, privileged=privileged),
            ])
        return "\n".join([
            *versioned("shadow", ptr),
            f"echo \"previous: $({s}cat {prev} 2>/dev/null)\"",
            *versioned("active", act),
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
