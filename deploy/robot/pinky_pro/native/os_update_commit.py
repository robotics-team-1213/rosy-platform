"""Only OS commit owner writes the canonical firmware default; interrupted intent has an explicit recovery role."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess

from auto_update_host import Host
from native_release import NativeReleaseManager
from os_bootloader import (BINDING, BOOTSTRAP, RAUC_STATE, _ack, _binding, _private,
                           _snapshot, autoboot, boot_lock)
from os_media import capture
from os_motion_guard import reconcile
from os_state_io import _json_atomic, _write_atomic
from os_state_layout import _digest, _guid, _pairs, _path, _read
import os_update_health as health
from os_update_policy import _Policy
from os_update_state import layout_digest, locked, read_state
import rosy_claim

INTENT = RAUC_STATE + "/commit.json"
INTENT_FIELDS = BINDING | {"trial_boot_id", "release_id", "health_sha256"}


def _run(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _root(root, run):
    root = Path(root).absolute()
    if root != Path("/") and run is _run:
        raise ValueError("a fake root requires an explicit test runner")
    return root


def _media(root, pending, facts):
    current = capture(root)
    if current["slot"] != facts["slot"] or layout_digest(current["layout"]) != pending["layout_sha256"]:
        raise ValueError("commit media differs from the pending transaction")


def _expected(pending):
    return dict(_binding(pending), trial_boot_id=pending["trial_boot_id"],
                release_id=pending["verified"]["metadata"]["release_id"], health_sha256=pending["health_sha256"])


def _intent(root, pending):
    value = _private(root, INTENT, INTENT_FIELDS)
    if value != _expected(pending):
        raise ValueError("durable commit intent differs from the pending transaction")
    return value


def _proof(root, pending):
    """Persisted intent proof may describe an earlier boot; ordinary admission never uses this as fresh health."""
    path = health._report_path(root, pending)
    report = _private(root, path.relative_to(root).as_posix(), health.FIELDS)
    raw = _read(path, 8192, root.stat().st_uid)
    if (report is None or json.loads(raw, object_pairs_hook=_pairs) != report
            or hashlib.sha256(raw).hexdigest() != pending["health_sha256"]
            or any(report[key] != value for key, value in _binding(pending).items())
            or report["boot_id"] != pending["trial_boot_id"]):
        raise ValueError("persisted exact-byte health proof differs")
    ack = _ack(root, pending, dict(boot_id=pending["trial_boot_id"]))
    if ack is None or ack["state"] != "good" or ack["phase"] != "HEALTHY":
        raise ValueError("commit requires GOOD_ACK issued after this trial became healthy")
    return report


def _controls(root, pending, facts, host):
    if host.boot_id() != facts["boot_id"]:
        raise ValueError("commit policy and firmware boot differ")
    reasons = _Policy(root, host)._controls(pending["transaction_id"])
    if reasons:
        raise ValueError("commit policy deferred: " + "; ".join(reasons))


def _cleanup(root, state, run, host):
    facts, current, _ = _snapshot(root)
    if current != state or current["pending"] is not None:
        raise ValueError("committed state changed before cleanup")
    intent = _private(root, INTENT, INTENT_FIELDS)
    if intent is not None:
        for key in ("transaction_id", "source_boot_id", "trial_boot_id"):
            _guid(intent[key])
        for key in ("manifest_sha256", "layout_sha256", "health_sha256"):
            _digest(intent[key])
        if intent["target_slot"] not in {"a", "b"} or not isinstance(intent["release_id"], str):
            raise ValueError("invalid cleanup intent")
    if reconcile(root):
        raise ValueError("pending motion fence reappeared during cleanup")
    result = run(["/usr/bin/systemctl", "stop", "rosy-os-trial-deadline.timer", "rosy-os-trial-deadline.service"], timeout=30)
    if result.returncode != 0:
        raise ValueError("committed boot deadline cleanup failed")
    completed = intent is not None and (
        intent["target_slot"] == facts["slot"] and intent["release_id"] == current["committed"]["release_id"]
        or intent["target_slot"] != facts["slot"] and intent["release_id"] in current["failed_versions"])
    if completed:
        claim = rosy_claim.check(root, now=host.now())
        holder = "os-update:" + intent["transaction_id"]
        if claim is not None and claim["holder"] == holder:
            rosy_claim.release(root, holder)
    return current


def _commit(root, transaction_id, host, run):
    facts, state, default = _snapshot(root)
    pending = state["pending"]
    if (pending is None or pending["transaction_id"] != transaction_id
            or pending["phase"] not in {"HEALTHY", "COMMIT_INTENT"}
            or facts["tryboot"] != 1 or pending["trial_boot_id"] != facts["boot_id"]
            or facts["slot"] != pending["target_slot"] or default != pending["source_slot"]):
        raise ValueError("commit requires the uncommitted healthy trial")
    _controls(root, pending, facts, host)
    report = health.revalidate(root, pending, run=run)
    if _proof(root, pending) != report:
        raise ValueError("current health differs from persisted proof")
    _media(root, pending, facts)
    _controls(root, pending, facts, host)
    health.read_health(root, pending)  # Recheck the deadline after slow observations and GPT capture.
    if _snapshot(root) != (facts, state, default):
        raise ValueError("trial changed before durable intent")
    if pending["phase"] == "HEALTHY":
        _private(root, INTENT, INTENT_FIELDS)
        _json_atomic(_path(root, INTENT), _expected(pending), 0o600)
        _intent(root, pending)
        with locked(root) as store:
            if store.state != state:
                raise ValueError("OS state changed before intent")
            store.transition(transaction_id, "COMMIT_INTENT", facts["boot_id"])
        state = read_state(root)
        pending = state["pending"]
    else:
        _intent(root, pending)
    _media(root, pending, facts)
    _controls(root, pending, facts, host)
    health.read_health(root, pending)
    if _snapshot(root) != (facts, state, default):
        raise ValueError("trial changed during durable intent publication")
    target = _path(root, BOOTSTRAP)
    mode = stat.S_IMODE(target.stat().st_mode)
    if mode & 0o7022:
        raise ValueError("unsafe bootstrap permission bits")
    # FAT read/execute bits come from mount masks, not a per-file chmod to 0644.
    _write_atomic(target, autoboot(pending["target_slot"]), mode)
    if _read(_path(root, BOOTSTRAP), 256, root.stat().st_uid) != autoboot(pending["target_slot"]):
        raise ValueError("persistent firmware default readback differs")
    with NativeReleaseManager(root=root)._locked(), locked(root) as store:
        if store.state != state:
            raise ValueError("OS state changed after default publication")
        store.commit(transaction_id, pending["trial_boot_id"])
    return _cleanup(root, read_state(root), run, host)


def commit(root: Path, transaction_id: str, *, host: Host | None = None, run=_run) -> dict:
    try:
        root = _root(root, run)
        with boot_lock(root):
            return _commit(root, transaction_id, host if host is not None else Host(root), run)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_COMMIT_HOLD: {exc}") from exc


def recover(root: Path, *, host: Host | None = None, run=_run) -> dict:
    """Finish an already published default, abandon an old default on fresh source boot, or retry same-trial intent."""
    try:
        root = _root(root, run)
        host = host if host is not None else Host(root)
        with boot_lock(root):
            facts, state, default = _snapshot(root)
            pending = state["pending"]
            if pending is None:
                return _cleanup(root, state, run, host)
            if pending["phase"] != "COMMIT_INTENT":
                raise ValueError("no commit intent to reconcile")
            _intent(root, pending)
            _proof(root, pending)
            _media(root, pending, facts)
            if default == pending["target_slot"] and facts["slot"] == pending["target_slot"]:
                with NativeReleaseManager(root=root)._locked(), locked(root) as store:
                    if store.state != state:
                        raise ValueError("intent changed during target recovery")
                    store.commit(pending["transaction_id"], pending["trial_boot_id"])
            elif default == pending["source_slot"] and facts["slot"] == pending["source_slot"] and facts["tryboot"] == 0:
                with NativeReleaseManager(root=root)._locked(), locked(root) as store:
                    if store.state != state:
                        raise ValueError("intent changed during source recovery")
                    store.abandon_commit(pending["transaction_id"], facts["boot_id"], facts["slot"])
            elif default == pending["source_slot"] and facts["boot_id"] == pending["trial_boot_id"] and facts["tryboot"] == 1:
                return _commit(root, pending["transaction_id"], host, run)
            else:
                raise ValueError("commit intent requires offline bootstrap repair")
            return _cleanup(root, read_state(root), run, host)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_COMMIT_HOLD: {exc}") from exc
