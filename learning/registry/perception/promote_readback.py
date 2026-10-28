"""Record every pointer change and, on request, read back what the robot's node loaded (D-773 A3).

After a successful push, rollback or promote, deliver.py appends one line to
<journal-dir>/pointer-changes/pointer_changes.jsonl, adding no network step. With --readback it reads the moved
pointer again and the node's latched status topic (perception/learned/status for lane_seg shadow,
perception/learned/object_det/status for object_det active; D-423 §3.6) a few times and
records whether the node's model_revision equals the pointer. Paint reads the next volatile
line/keep_debug frame's consumed paint_model_revision and rechecks its pointer. Slots no
node reads (object_det shadow) are recorded as "no_node".

The record is evidence for people, never device acceptance; the exit code of the pointer change
is unchanged by a readback result, so the site watcher's exit-code contract stays as it was.
A robot whose learned node is off (ROSY_LEARNED_SHADOW / ROSY_OBJECT_DET default false) records
"unavailable", not "no_node": no_node means no node exists for that slot at all.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import shlex
import time
from pathlib import Path

#: (task, moved slot) -> the status topic of the node that runs that slot (CORE models.py).
STATUS_TOPICS = {
    ("lane_seg", "shadow"): "perception/learned/status",
    ("object_det", "active"): "perception/learned/object_det/status",
}
POINTER_ACTIONS = ("push", "rollback", "promote")
RECORD_NAME = "pointer-changes/pointer_changes.jsonl"  # outside the one-file-per-attempt folder
STATUS_SCHEMA = "rosy.perception.learned_status/1"


def moved_slot(args) -> str | None:
    if args.action == "promote":
        return "active"
    return getattr(args, "slot", "shadow") if args.action in POINTER_ACTIONS else None


def pointer_command(root: str, slot: str) -> str:
    return f"sudo -n cat -- {root}/{slot}"


def status_command(topic: str, timeout_s: int = 5, *, durability="transient_local") -> str:
    """One status message; runtime.env is root-only (0600), so it is read under sudo.

    The script is single-quoted so ``$ROSY_NAMESPACE`` expands in the root shell after
    runtime.env is sourced, not in the login shell ssh starts. The echo form follows
    docs/deployment/learned-perception-pinky.md (type, transient_local); --full-length keeps
    the JSON from being cut at 128 characters.
    """
    inner = ("set -a; . /etc/rosy/runtime.env; set +a; . /opt/ros/jazzy/setup.bash; "
             'NS="${ROSY_NAMESPACE:+/$ROSY_NAMESPACE}"; '
             f"timeout {int(timeout_s)} ros2 topic echo --once --full-length --field data "
             f'--qos-durability {durability} "$NS/{topic}" std_msgs/msg/String')
    return "sudo -n bash -c " + shlex.quote(inner)


def revision_of(pointer_text: str) -> str | None:
    text = (pointer_text or "").strip().rstrip("/")
    return text.rsplit("/", 1)[-1] if text else None


def _message(text: str) -> dict | None:
    body = (text or "").split("\n---", 1)[0].strip()
    if body.startswith("'") and body.endswith("'"):
        body = body[1:-1].replace("''", "'")  # YAML single-quoted scalar
    elif body.startswith('"') and body.endswith('"'):
        body = body[1:-1]
    try:
        doc = json.loads(body)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def parse_status(text: str) -> dict | None:
    """The versioned status JSON from `ros2 topic echo --field data`, or None."""
    doc = _message(text)
    return doc if doc is not None and doc.get("schema") == STATUS_SCHEMA else None


def _paint_status(text: str) -> dict | None:
    doc = _message(text)
    if doc is None or doc.get("paint_source_used") not in ("learned", "learned_drivable"):
        return None
    revision, stamp = doc.get("paint_model_revision"), doc.get("stamp")
    if (not isinstance(revision, str) or not revision.strip()
            or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
            or not math.isfinite(stamp) or stamp < 0):
        return None
    return {"model_revision": revision}


def verdict(pointer_revision: str | None, status: dict | None, topic: str | None) -> str:
    if topic is None:
        return "no_node"
    if status is None or pointer_revision is None:
        return "unavailable"
    return "match" if status.get("model_revision") == pointer_revision else "mismatch"


def read_back(ssh, target: str, root: str, task: str, slot: str, runner, *,
              timeout: float, attempts: int = 3, wait_s: float = 2.0, sleep=None) -> dict:
    sleep = sleep or time.sleep
    pointer = runner([*ssh, target, pointer_command(root, slot)], capture_output=True, text=True,
                     timeout=timeout, check=False)
    pointer_revision = revision_of(pointer.stdout) if pointer.returncode == 0 else None
    paint = (task, slot) == ("lane_seg", "paint")
    topic = "line/keep_debug" if paint else STATUS_TOPICS.get((task, slot))
    result = {"pointer_revision": pointer_revision, "node_revision": None, "signed": None}
    status = None
    for attempt in range(max(1, attempts) if topic else 0):
        command = status_command(topic, durability="volatile" if paint else "transient_local")
        r = runner([*ssh, target, command], capture_output=True, text=True,
                   timeout=timeout, check=False)
        status = (_paint_status(r.stdout) if paint else parse_status(r.stdout)) if r.returncode == 0 else None
        if status is not None and status.get("model_revision") == pointer_revision:
            break
        if attempt + 1 < attempts:
            sleep(wait_s)  # the node polls its pointer; give it time to swap
    result.update(readback=verdict(pointer_revision, status, topic),
                  node_revision=(status or {}).get("model_revision"),
                  signed=(status or {}).get("signed") if isinstance((status or {}).get("signed"), bool) else None)
    if paint:
        after = runner([*ssh, target, pointer_command(root, slot)], capture_output=True, text=True,
                       timeout=timeout, check=False)
        if after.returncode != 0 or revision_of(after.stdout) != pointer_revision:
            result["readback"] = "unavailable"
    return result


def record(journal_dir, row: dict) -> Path:
    path = Path(journal_dir) / RECORD_NAME
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps({"schema": "rosy.model-pointer-change/1",
                       "ts": dt.datetime.now(dt.timezone.utc).isoformat(), **row}, allow_nan=False)
    with path.open("ab") as file:
        file.write((line + "\n").encode())
        file.flush()
        os.fsync(file.fileno())
    return path


def after_change(args, ssh, runner, code: int, audit, err) -> None:
    """Called by deliver.main after a pointer command; never changes its exit code.

    ``audit`` is a callable returning the operator fields; it runs only when a row is written.
    """
    slot = moved_slot(args)
    if code != 0 or slot is None:
        return
    seen = {"pointer_revision": getattr(args, "revision", None), "readback": "not_run",
            "node_revision": None, "signed": None}  # no extra network step: what the command names
    if getattr(args, "readback", False):
        try:
            seen = read_back(ssh, f"{args.user}@{args.host}", args.root, args.task, slot, runner,
                             timeout=args.timeout)
        except Exception as exc:  # a failed readback still leaves the pointer change on record
            seen = {**seen, "readback": "unavailable", "readback_error": type(exc).__name__}
    try:
        record(args.journal_dir, {"host": args.host, "task": args.task, "action": args.action,
                                  "slot": slot, **seen, **(audit() if callable(audit) else audit)})
    except Exception as exc:  # evidence only: a failed record must not undo a done pointer change
        print(f"pointer change record failed: {type(exc).__name__}: {exc}", file=err)
        return
    if seen["readback"] in ("mismatch", "unavailable"):
        print(f"readback {seen['readback']}: pointer {seen['pointer_revision']}, "
              f"node {seen['node_revision']} ({args.task} {slot} on {args.host})", file=err)
