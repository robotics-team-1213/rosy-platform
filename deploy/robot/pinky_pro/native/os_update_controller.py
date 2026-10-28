"""Frozen OS lifecycle owner: source install, one-shot tryboot, trial health/commit and observed fallback."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auto_update_host import Host, UPDATES, UpdateError
from native_release import IO_SETTLE_S, NativeReleaseManager
from os_bootloader import (PERMIT, PERMIT_FIELDS, RAUC_STATE, _binding, _snapshot, _write, invoke)
from os_factory_release import PUBLIC_KEY
from os_media import capture
from os_motion_guard import reconcile
from os_rauc import verify_bundle
from os_rauc_service import RUNTIME, _empty_cgroup, _stop, install as rauc_install, recover as rauc_recover
from os_state_layout import COMMON, _layout, _pairs, _path, _read
import os_update_commit as commit_owner
import os_update_health as health
from os_update_install import read_report
from os_update_policy import _Policy, authorize
from os_update_state import locked, read_state
from os_update_watchdog import admit as watchdog_admit
import rosy_claim

TTL = 10800


def _run(argv, timeout=30):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, LC_ALL="C"))


def _root(root, run):
    root = Path(root).absolute()
    if root != Path("/") and run is _run:
        raise ValueError("a fake root requires an explicit test runner")
    return root


@contextmanager
def _file_lock(root, relative):
    path = _path(root, relative)
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                or info.st_mode & 0o022 or info.st_nlink != 1):
            raise ValueError("unsafe OS/native run lock")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


@contextmanager
def _locks(root):
    read_state(root)  # Never create a substitute for a missing/corrupt factory store.
    with _file_lock(root, COMMON + "/os-update/controller.lock"):
        directory = _path(root, UPDATES)
        directory.mkdir(parents=True, exist_ok=True, mode=0o755)
        with _file_lock(root, UPDATES + "/.run.lock"):
            ra = _path(root, RAUC_STATE)
            ra.mkdir(mode=0o700, exist_ok=True)
            if stat.S_IMODE(ra.stat().st_mode) != 0o700:
                raise ValueError("OS RAUC state directory is not private")
            yield


def _claim(root, transaction_id, host):
    holder = "os-update:" + transaction_id
    current = rosy_claim.check(root, now=host.now())
    if current is None:
        rosy_claim.acquire(root, holder, "whole OS transaction", TTL, now=host.now())
    elif current["holder"] != holder or not rosy_claim.refresh(root, holder, TTL, now=host.now()):
        raise ValueError("OS transaction cannot hold the live claim")


def _call(run, argv):
    result = run(argv, timeout=30)
    if result.returncode != 0:
        raise ValueError("OS lifecycle service request failed: " + " ".join(argv[:3]))


def _quiet(root, run):
    for unit in ("rosy-navigation.service", "rosy-io.service"):
        before = health._properties(run, unit, {"ActiveState", "MainPID", "ControlGroup"})
        _call(run, ["/usr/bin/systemctl", "stop", unit])
        after = health._properties(run, unit, {"ActiveState", "MainPID", "ControlGroup"})
        if after["ActiveState"] not in {"inactive", "failed"} or after["MainPID"] != "0":
            raise ValueError("maintenance unit did not stop")
        for group in {before["ControlGroup"], after["ControlGroup"], "/system.slice/" + unit}:
            _empty_cgroup(root, group, service=unit)


def source_health(root, transaction_id, *, host, run):
    """Read-only source observations; never restart CORE to hide an inconsistent release."""
    facts, _, _ = _snapshot(root)
    if facts["tryboot"] or facts["boot_id"] != host.boot_id():
        raise ValueError("source health requires this normal source boot")
    authorize(root, transaction_id, host=host)
    current = host.current_release()
    manager = NativeReleaseManager(root=root, public_key=_path(root, PUBLIC_KEY))
    manager.verify(current)
    manager.check_python_runtime(current)
    projection = health.verify_ready(root)
    services = {unit: health._service(run, unit) for unit in ("rosy-core.service", "rosy-io.service")}
    if (projection["boot_id"] != facts["boot_id"] or projection["slot"] != facts["slot"]
            or host.process_cwd(int(services["rosy-core.service"]["MainPID"])) != str(root / "opt/rosy/releases" / current)):
        raise ValueError("source projection or running CORE release differs")
    health._io_guard(root, dict(release_id=current))
    watchdog = watchdog_admit(root, run=run)
    health._probe()
    authorize(root, transaction_id, host=host)
    health._probe()
    if (host.current_release() != current or _snapshot(root)[0] != facts or health.verify_ready(root) != projection
            or watchdog_admit(root, run=run) != watchdog
            or any(health._service(run, unit) != value for unit, value in services.items())):
        raise ValueError("source changed while observing health")
    return current


def _transition(root, transaction_id, phase, boot_id, **kwargs):
    with locked(root) as store:
        store.transition(transaction_id, phase, boot_id, **kwargs)


def admit_release(root, metadata, *, host):
    from os_update_feed import Feed
    Feed(root, host=host).admit(metadata)


def _arm(root, transaction_id, host, run):
    source_health(root, transaction_id, host=host, run=run)
    facts, state, _ = _snapshot(root)
    pending = state["pending"]
    if (pending is None or pending["transaction_id"] != transaction_id or facts["tryboot"]
            or facts["boot_id"] != pending["source_boot_id"] or pending["phase"] not in {"VERIFIED", "ARMED"}):
        raise ValueError("cannot arm a stale source boot")
    _claim(root, transaction_id, host)
    admit_release(root, pending["verified"]["metadata"], host=host)
    authorize(root, transaction_id, host=host)
    # The callback recaptures GPT and validates this short-lived source-only permit.
    permit = dict(_binding(pending), claim_holder="os-update:" + transaction_id,
                  expires_monotonic_ns=time.monotonic_ns() + 15_000_000_000)
    _write(root, PERMIT, permit, PERMIT_FIELDS)
    invoke(root, ("set-primary", pending["target_slot"]))
    _transition(root, transaction_id, "ARMED", facts["boot_id"])
    reasons = _Policy(root, host)._gates(transaction_id)
    if reasons:
        raise ValueError("armed source policy changed: " + "; ".join(reasons))
    _call(run, ["/usr/bin/systemctl", "--no-block", "--reboot-argument=0 tryboot", "reboot"])
    return read_state(root)


def start(root: Path, bundle: Path, raw: bytes, signature: str, *, host: Host | None = None, run=_run):
    try:
        root = _root(root, run)
        host = host if host is not None else Host(root)
        with _locks(root):
            facts, initial, _ = _snapshot(root)
            if initial["pending"] is not None or facts["tryboot"]:
                raise ValueError("resume existing OS state before starting a new normal-boot update")
            transaction_id = str(uuid.uuid4())
            _claim(root, transaction_id, host)
            try:
                reasons = _Policy(root, host)._controls(transaction_id)
                if reasons:
                    raise ValueError("OS update deferred: " + "; ".join(reasons))
                watchdog_admit(root, run=run)
                _read(_path(root, "sys/fs/cgroup/cgroup.controllers"), 4096, root.stat().st_uid)
                verified = verify_bundle(root, bundle, raw, signature)
                admit_release(root, verified["metadata"], host=host)
                current = source_health(root, transaction_id, host=host, run=run)
                media = capture(root)
                with NativeReleaseManager(root=root, public_key=_path(root, PUBLIC_KEY))._locked():
                    if read_state(root) != initial or host.current_release() != current or _snapshot(root)[0] != facts:
                        raise ValueError("source changed before posting pending")
                    with locked(root) as store:
                        store.begin(verified, media, facts["boot_id"], transaction_id)
                reconcile(root)
                _quiet(root, run)
                _transition(root, transaction_id, "INSTALLING", facts["boot_id"])
                def install_admission():
                    admit_release(root, verified["metadata"], host=host)
                    authorize(root, transaction_id, host=host)
                result = rauc_install(root, bundle, raw, signature, authorize=install_admission, run=run)
                if (not isinstance(result, dict) or result.get("installed") is not True
                        or result.get("manifest_sha256") != verified["manifest_sha256"] or result.get("report") != read_report(root)):
                    raise ValueError("RAUC client success and installed receipt must both match")
                _transition(root, transaction_id, "INSTALLED", facts["boot_id"])
                _transition(root, transaction_id, "VERIFIED", facts["boot_id"])
                _call(run, ["/usr/bin/systemctl", "restart", "rosy-io.service"])
                host.sleep(IO_SETTLE_S)
                return _arm_or_restore(root, transaction_id, host, run)
            finally:
                if read_state(root)["pending"] is None:
                    rosy_claim.release(root, "os-update:" + transaction_id)
    except (OSError, ValueError, TypeError, KeyError, rosy_claim.ClaimBusy, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_CONTROLLER_HOLD: {exc}") from exc


def _failed_source(root, facts, pending, host, run):
    if (root / RUNTIME).exists():
        rauc_recover(root, run=run)
    else:
        _stop(root, run)
    _quiet(root, run)
    with NativeReleaseManager(root=root, public_key=_path(root, PUBLIC_KEY))._locked(), locked(root) as store:
        if store.state["pending"] != pending:
            raise ValueError("source failure owner changed")
        store.record_failure(pending["transaction_id"], facts["boot_id"], facts["slot"])
    reconcile(root)
    rosy_claim.release(root, "os-update:" + pending["transaction_id"])
    _call(run, ["/usr/bin/systemctl", "restart", "rosy-io.service"])
    return read_state(root)


def _finish(root, facts, result, run):
    intent = commit_owner._private(root, commit_owner.INTENT, commit_owner.INTENT_FIELDS)
    if (facts["tryboot"] and result["pending"] is None and intent is not None
            and intent["trial_boot_id"] == facts["boot_id"] and intent["target_slot"] == facts["slot"]
            and intent["release_id"] == result["committed"]["release_id"]):
        # A normal boot clears retained tryboot and reloads the operator's configured I/O environment.
        _call(run, ["/usr/bin/systemctl", "--no-block", "reboot"])
    return result


def _arm_or_restore(root, transaction_id, host, run):
    from os_update_feed import Withdrawn
    try:
        return _arm(root, transaction_id, host, run)
    except Withdrawn:
        facts, state, _ = _snapshot(root)
        return _failed_source(root, facts, state["pending"], host, run)


def resume(root: Path = Path("/"), *, host: Host | None = None, run=_run):
    try:
        root = _root(root, run)
        host = host if host is not None else Host(root)
        with _locks(root):
            facts, state, _ = _snapshot(root)
            pending = state["pending"]
            if pending is None:
                return _finish(root, facts, commit_owner.recover(root, host=host, run=run), run)
            transaction_id = pending["transaction_id"]
            _claim(root, transaction_id, host)
            if pending["phase"] == "COMMIT_INTENT":
                return _finish(root, facts, commit_owner.recover(root, host=host, run=run), run)
            if facts["tryboot"]:
                try:
                    if pending["phase"] == "ARMED":
                        _transition(root, transaction_id, "TRIAL", facts["boot_id"])
                    if read_state(root)["pending"]["phase"] == "TRIAL":
                        health.check(root, transaction_id, host=host, run=run)
                        pending = read_state(root)["pending"]
                        report = health.read_health(root, pending)
                        raw = _read(health._report_path(root, pending), 8192, root.stat().st_uid)
                        if json.loads(raw, object_pairs_hook=_pairs) != report:
                            raise ValueError("health bytes changed before HEALTHY")
                        _transition(root, transaction_id, "HEALTHY", facts["boot_id"], health_sha256=hashlib.sha256(raw).hexdigest())
                    invoke(root, ("set-state", pending["target_slot"], "good"))
                    return _finish(root, facts, commit_owner.commit(root, transaction_id, host=host, run=run), run)
                except (OSError, ValueError, subprocess.SubprocessError):
                    after = read_state(root)["pending"]
                    # A published intent needs its original GOOD_ACK for recovery, even if cleanup failed.
                    if after is not None and after["phase"] != "COMMIT_INTENT":
                        invoke(root, ("set-state", after["target_slot"], "bad"))
                        _call(run, ["/usr/bin/systemctl", "--no-block", "reboot"])
                    raise
            if facts["boot_id"] != pending["source_boot_id"] or pending["phase"] in {"PREPARED", "INSTALLING"}:
                return _failed_source(root, facts, pending, host, run)
            if pending["phase"] == "INSTALLED":
                read_report(root)
                _transition(root, transaction_id, "VERIFIED", facts["boot_id"])
            if read_state(root)["pending"]["phase"] not in {"VERIFIED", "ARMED"}:
                raise ValueError("unexpected source boot after trial")
            reconcile(root)
            _call(run, ["/usr/bin/systemctl", "restart", "rosy-io.service"])
            host.sleep(IO_SETTLE_S)
            return _arm_or_restore(root, transaction_id, host, run)
    except (OSError, ValueError, TypeError, KeyError, rosy_claim.ClaimBusy, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_CONTROLLER_HOLD: {exc}") from exc


def status(root: Path = Path("/"), *, host=None) -> dict:
    """Observe local state and shared policy; this is not update eligibility or a catalogue check."""
    root = Path(root).absolute()
    state = read_state(root)
    admitted = _layout(root)
    if admitted is None or admitted[0]["schema_version"] != 2:
        raise ValueError("OS_STATUS_LAYOUT_HOLD")
    policy = _Policy(root, Host(root) if host is None else host)
    try:
        config = policy._config()
        hold, _ = policy._hold()
    except UpdateError as exc:
        raise ValueError("OS_STATUS_POLICY_HOLD") from exc
    pending = state["pending"]
    return dict(schema_version=1, running_slot=admitted[0]["slot"], committed=state["committed"],
                pending=None if pending is None else dict(phase=pending["phase"],
                    release_id=pending["verified"]["metadata"]["release_id"],
                    source_slot=pending["source_slot"], target_slot=pending["target_slot"]),
                failed_versions=state["failed_versions"],
                policy=dict(enabled=config["enabled"], repo=config["repo"], hold=hold))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "install", "status"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--signature", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            if any((args.bundle, args.metadata, args.signature)):
                raise ValueError("status does not accept install paths")
            result = status()
        elif args.command in {"run", "resume"}:
            if any((args.bundle, args.metadata, args.signature)):
                raise ValueError("run/resume do not accept install paths")
            if args.command == "run":
                from os_update_feed import run as poll_feed
                result = poll_feed()
            else: result = resume()
        else:
            if not all((args.bundle, args.metadata, args.signature)):
                raise ValueError("install requires bundle/metadata/signature paths")
            result = start(Path("/"), args.bundle, _read(args.metadata, 16384, 0), _read(args.signature, 512, 0).decode("ascii").strip())
        print(json.dumps(dict(ok=True, state=result), sort_keys=True))
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps(dict(ok=False, error=str(exc)), sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
