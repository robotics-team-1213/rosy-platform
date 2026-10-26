"""Strict firmware observations and RAUC callbacks; only the separate commit owner writes bootstrap."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import sys
import time

from os_state_io import _json_atomic
from os_state_layout import COMMON, _guid, _layout, _object, _pairs, _path, _read
from os_update_manifest import _digest

BOOTSTRAP = "run/rosy-provision-boot/autoboot.txt"
RAUC_STATE = COMMON + "/os-update/rauc"
ARM = RAUC_STATE + "/arm.json"
ACK = RAUC_STATE + "/boot-status.json"
PERMIT = "run/rosy-os-update/arm.json"
BINDING = {"schema_version", "transaction_id", "source_boot_id", "target_slot", "manifest_sha256", "layout_sha256"}
ACK_FIELDS = {"schema_version", "transaction_id", "boot_id", "slot", "state", "phase", "manifest_sha256"}
PERMIT_FIELDS = BINDING | {"claim_holder", "expires_monotonic_ns"}


def autoboot(slot: str) -> bytes:
    if slot not in ("a", "b"):
        raise ValueError("invalid default boot slot")
    normal, trial = (2, 3) if slot == "a" else (3, 2)
    return f"[all]\ntryboot_a_b=1\nboot_partition={normal}\n[tryboot]\nboot_partition={trial}\n".encode("ascii")


def parse_autoboot(raw: bytes) -> str:
    for slot in ("a", "b"):
        if type(raw) is bytes and raw == autoboot(slot):
            return slot
    raise ValueError("unknown bootstrap configuration")


def _dt(root: Path, name: str) -> int:
    base = root / "proc/device-tree"
    if base.is_symlink():
        if base.resolve(strict=True) != root / "sys/firmware/devicetree/base":
            raise ValueError("device-tree alias escapes the kernel tree")
        relative = "sys/firmware/devicetree/base/chosen/bootloader/" + name
    else:
        relative = "proc/device-tree/chosen/bootloader/" + name
    path = _path(root, relative)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid or info.st_mode & 0o022:
            raise ValueError("unsafe firmware property")
        raw = handle.read(5)
    if len(raw) != 4:
        raise ValueError("firmware property is not a raw u32")
    return int.from_bytes(raw, "big")


def boot_facts(root: Path = Path("/")) -> dict:
    try:
        root = Path(root).absolute()
        admitted = _layout(root)
        if admitted is None or admitted[0]["schema_version"] != 2:
            raise ValueError("firmware updates require boot protocol 2")
        slot = admitted[0]["slot"]
        partition, trial = _dt(root, "partition"), _dt(root, "tryboot")
        words = _read(root / "proc/cmdline", 16384).decode("ascii").split()
        if (partition != {"a": 2, "b": 3}[slot] or trial not in (0, 1)
                or [w for w in words if w.startswith("rauc.slot=")] != ["rauc.slot=" + slot]):
            raise ValueError("firmware partition or kernel slot differs")
        boot_id = _read(root / "proc/sys/kernel/random/boot_id", 128, root.stat().st_uid).decode("ascii").strip()
        _guid(boot_id)
        return dict(schema_version=1, slot=slot, partition=partition, tryboot=trial, boot_id=boot_id)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_BOOT_HOLD: {exc}") from exc


def _private(root: Path, relative: str, fields: set):
    path = _path(root, relative)
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("callback record must be a private single-link file")
    return _object(_read(path, 8192, root.stat().st_uid), fields)


def _binding(pending):
    return dict(schema_version=1, transaction_id=pending["transaction_id"], source_boot_id=pending["source_boot_id"],
        target_slot=pending["target_slot"], manifest_sha256=pending["verified"]["manifest_sha256"],
        layout_sha256=pending["layout_sha256"])


def _arm(root, pending):
    value = _private(root, ARM, BINDING | {"armed"})
    if value is None:
        return None
    for field in ("transaction_id", "source_boot_id"):
        _guid(value[field])
    for field in ("manifest_sha256", "layout_sha256"):
        _digest(value[field])
    if type(value["armed"]) is not bool or value["target_slot"] not in ("a", "b"):
        raise ValueError("invalid arm record")
    return value if all(value[k] == v for k, v in _binding(pending).items()) else None


def _ack(root, pending, facts):
    from os_update_state import PHASES
    value = _private(root, ACK, ACK_FIELDS)
    if value is None:
        return None
    _guid(value["transaction_id"])
    _guid(value["boot_id"])
    _digest(value["manifest_sha256"])
    if value["slot"] not in ("a", "b") or value["state"] not in ("good", "bad") or value["phase"] not in PHASES:
        raise ValueError("invalid boot acknowledgement")
    expected = dict(transaction_id=pending["transaction_id"], boot_id=facts["boot_id"],
                    slot=pending["target_slot"], manifest_sha256=pending["verified"]["manifest_sha256"])
    return value if all(value[k] == v for k, v in expected.items()) else None


def _write(root, relative, value, fields):
    _private(root, relative, fields)
    _json_atomic(_path(root, relative), value, 0o600)


@contextmanager
def boot_lock(root: Path):
    """Callbacks and commit owner share this lock; never acquire it while holding the short state lock."""
    import fcntl
    directory = _path(root, RAUC_STATE)
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("private RAUC directory is missing or unsafe")
    path = _path(root, RAUC_STATE + "/boot.lock")
    with os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError("unsafe callback lock")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _snapshot(root):
    from os_update_state import layout_digest, read_state
    facts, state = boot_facts(root), read_state(root)
    default = parse_autoboot(_read(_path(root, BOOTSTRAP), 256, root.stat().st_uid))
    pending = state["pending"]
    if pending is None:
        if facts["tryboot"] or facts["slot"] != state["committed"]["slot"] or default != facts["slot"]:
            raise ValueError("untracked boot or persistent default")
        return facts, state, default
    media = json.loads(_read(_path(root, "etc/rosy/os-media.json"), 32768, root.stat().st_uid), object_pairs_hook=_pairs)
    if layout_digest(media) != pending["layout_sha256"]:
        raise ValueError("transaction media differs from this root")
    if default != state["committed"]["slot"] and not (pending["phase"] == "COMMIT_INTENT" and default == pending["target_slot"]):
        raise ValueError("persistent default changed without commit intent")
    if facts["tryboot"]:
        if (facts["slot"] != pending["target_slot"] or facts["boot_id"] == pending["source_boot_id"]
                or pending["phase"] not in ("ARMED", "TRIAL", "HEALTHY", "COMMIT_INTENT")
                or pending["trial_boot_id"] not in (None, facts["boot_id"])):
            raise ValueError("trial boot is not bound to the pending transaction")
    elif facts["slot"] != pending["source_slot"] and not (pending["phase"] == "COMMIT_INTENT" and default == facts["slot"]):
        raise ValueError("normal boot is not the preserved source or an interrupted commit")
    return facts, state, default


def _claim(root, pending):
    import rosy_claim
    _read(_path(root, "run/rosy-claim/claim.json"), 4096, root.stat().st_uid)
    claim = rosy_claim.check(root)
    if claim is None or claim["holder"] != "os-update:" + pending["transaction_id"]:
        raise ValueError("current OS transaction claim is missing")


def _set_primary(root, facts, pending):
    from os_media import capture
    from os_update_state import layout_digest
    if (pending["phase"] not in ("VERIFIED", "ARMED") or facts["tryboot"]
            or facts["slot"] != pending["source_slot"] or facts["boot_id"] != pending["source_boot_id"]):
        raise ValueError("arm requires the same verified source boot")
    _claim(root, pending)
    permit = _private(root, PERMIT, PERMIT_FIELDS)
    if permit is None or any(permit[k] != v for k, v in _binding(pending).items()):
        raise ValueError("arm permit binding differs")
    expires, now = permit["expires_monotonic_ns"], time.monotonic_ns()
    if (permit["claim_holder"] != "os-update:" + pending["transaction_id"] or type(expires) is not int
            or not now < expires <= now + 15_000_000_000):
        raise ValueError("arm permit is expired or invalid")
    if layout_digest(capture(root)["layout"]) != pending["layout_sha256"]:
        raise ValueError("actual media changed before arm")
    _write(root, ARM, dict(_binding(pending), armed=True), BINDING | {"armed"})


def _primary(root, facts, state, default):
    pending = state["pending"]
    if pending is None:
        return default
    arm = _arm(root, pending)
    if facts["tryboot"]:
        if arm is None or not arm["armed"]:
            raise ValueError("trial has no valid arm record")
        return pending["target_slot"]
    if (arm and arm["armed"] and facts["boot_id"] == pending["source_boot_id"]
            and facts["slot"] == pending["source_slot"] and pending["phase"] in ("VERIFIED", "ARMED")):
        return pending["target_slot"]
    return default


def invoke(root: Path, argv) -> str:
    try:
        root, words = Path(root).absolute(), tuple(argv)
        valid = (words in (("get-current",), ("get-primary",))
            or len(words) == 2 and words[0] in ("get-state", "set-primary") and words[1] in ("a", "b")
            or len(words) == 3 and words[0] == "set-state" and words[1] in ("a", "b") and words[2] in ("good", "bad"))
        if not valid:
            raise ValueError("unsupported callback command")
        with boot_lock(root):
            facts, state, default = _snapshot(root)
            pending = state["pending"]
            if words == ("get-current",):
                return facts["slot"]
            if words == ("get-primary",):
                return _primary(root, facts, state, default)
            slot = words[1]
            if words[0] == "get-state":
                if slot == state["committed"]["slot"]:
                    return "good"
                ack = _ack(root, pending, facts) if pending else None
                return ack["state"] if ack else "bad"
            if words == ("set-state", state["committed"]["slot"], "good"):
                return ""
            if pending is None or slot != pending["target_slot"]:
                raise ValueError("callback cannot mutate the committed slot")
            if words[0] == "set-primary":
                _set_primary(root, facts, pending)
                return ""
            if not facts["tryboot"]:
                if (facts["slot"] != pending["source_slot"] or facts["boot_id"] != pending["source_boot_id"]
                        or pending["phase"] not in ("INSTALLING", "INSTALLED", "VERIFIED", "ARMED")):
                    raise ValueError("acknowledgement has no live install or trial")
                _claim(root, pending)
            ack = dict(schema_version=1, transaction_id=pending["transaction_id"], boot_id=facts["boot_id"],
                slot=slot, state=words[2], phase=pending["phase"], manifest_sha256=pending["verified"]["manifest_sha256"])
            _write(root, ACK, ack, ACK_FIELDS)
            if words[2] == "bad":
                _write(root, ARM, dict(_binding(pending), armed=False), BINDING | {"armed"})
            return ""
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ValueError(f"OS_BOOT_HOLD: {exc}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("command")
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    try:
        result = invoke(args.root, [args.command, *args.arguments])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if result:
        print(result)
    return 0
