"""Boot-boundary archival and USB sysfs hardware identity helpers for camera_readiness.py."""
import json
import os
from pathlib import Path
import re
import shutil
import time

_EPHEMERAL = ("baseline.json", "control-run.json", "restoration.json", "changes.json")


def current_boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def host_boot_time_ns(now_ns: int | None = None) -> int | None:
    try:
        uptime_s = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None
    ref = time.time_ns() if now_ns is None else now_ns
    return int(ref - uptime_s * 1_000_000_000)


def is_prior_boot(
    baseline: dict,
    *,
    boot_id: str | None = None,
    boot_time_ns: int | None = None,
    identity_mismatch: bool = False,
) -> bool:
    """True when baseline came from an earlier host boot (including legacy baselines lacking boot_id on reboot drift)."""
    live_boot = current_boot_id() if boot_id is None else boot_id
    saved_boot = baseline.get("boot_id")
    if isinstance(saved_boot, str) and saved_boot:
        return live_boot is not None and saved_boot != live_boot
    if not identity_mismatch:
        return False
    recorded_ns = baseline.get("recorded_ns")
    bt = host_boot_time_ns() if boot_time_ns is None else boot_time_ns
    return type(recorded_ns) is int and bt is not None and recorded_ns < bt


def hardware_identity(device: str, *, sysfs: Path = Path("/sys/class/video4linux")) -> dict | None:
    """Stable USB bus identity (vendor:product, interface, port, serial) behind a /dev/video* node."""
    try:
        node = Path(device).resolve()
    except OSError:
        return None
    if node.parent != Path("/dev") or not node.name.startswith("video"):
        return None
    sys_node = sysfs / node.name
    if not sys_node.exists():
        return None
    try:
        interface = (sys_node / "device").resolve()
        usb = interface.parent
        def _read(name: str) -> str | None:
            p = usb / name
            return p.read_text(encoding="utf-8", errors="replace").strip() if p.exists() else None
        vid, pid = _read("idVendor"), _read("idProduct")
        if not vid or not pid:
            return None
        return {
            "usb_id": f"{vid}:{pid}",
            "usb_port": usb.name,
            "interface": interface.name,
            "serial": _read("serial"),
        }
    except OSError:
        return None


def same_physical_camera(saved_spec: dict, live_hw: dict | None) -> bool:
    """Verify live sysfs USB properties match the baseline's recorded hardware."""
    saved_hw = saved_spec.get("hardware") if isinstance(saved_spec, dict) else None
    if not isinstance(saved_hw, dict) or not isinstance(live_hw, dict):
        return False
    for key in ("usb_id", "usb_port", "interface"):
        if not saved_hw.get(key) or live_hw.get(key) != saved_hw.get(key):
            return False
    if saved_hw.get("serial"):
        return live_hw.get("serial") == saved_hw.get("serial")
    return True


def identity_mismatched(baseline: dict, identity_fn) -> bool:
    for spec in (baseline.get("cameras") or {}).values():
        try:
            if identity_fn(spec["device"]) != spec["identity"]:
                return True
        except (OSError, RuntimeError, KeyError, TypeError):
            return True
    return False


def locked_rdevs(cameras: dict, identity_fn, *, allow_missing: bool = False) -> list[int]:
    rdevs = set()
    for spec in cameras.values():
        try:
            rdevs.add(identity_fn(spec["device"])["rdev"])
        except (OSError, RuntimeError):
            if not allow_missing:
                raise
    return sorted(rdevs)


def stale_baseline(baseline: dict, root: Path, digest: str, identity_fn, get_controls_fn) -> bool:
    """Archive prior-boot or clean profile-updated baseline; raise on dirty digest mismatch; False on active baseline."""
    if is_prior_boot(baseline, identity_mismatch=identity_mismatched(baseline, identity_fn)):
        archive_state(root, f"boot-{baseline.get('boot_id') or 'legacy'}")
        return True
    if baseline.get("profile_sha256") != digest:
        if not baseline_clean(root, baseline, get_controls_fn, identity_fn=identity_fn):
            raise RuntimeError("profile changed; use a new state directory")
        archive_state(root, "profile-update")
        return True
    return False


def prior_restore(baseline: dict, root: Path, identity_fn) -> dict | None:
    if not is_prior_boot(baseline, identity_mismatch=identity_mismatched(baseline, identity_fn)):
        return None
    archive_state(root, f"boot-{baseline.get('boot_id') or 'legacy'}")
    return {role: {"errors": [], "restored": True, "skipped": "prior_boot_baseline"} for role in baseline["cameras"]}


def _sync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive_state(root: Path, tag: str, keep: int = 10) -> Path | None:
    """Move per-boot readiness state under root/archive/ without touching environment.jsonl or recovery-budget.json."""
    targets = [root / name for name in _EPHEMERAL if (root / name).exists()]
    targets.extend(sorted(root.glob("control-intent-*.json")))
    if not targets:
        return None
    archive_root = root / "archive"
    archive_root.mkdir(mode=0o700, exist_ok=True)
    safe_tag = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(tag or "prior")).strip("-")[:32] or "prior"
    dest = archive_root / f"{safe_tag}-{time.time_ns()}"
    dest.mkdir(mode=0o700, exist_ok=True)
    for src in targets:
        os.replace(src, dest / src.name)
    _sync_dir(dest)
    _sync_dir(root)
    existing = sorted((p for p in archive_root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for stale in existing[:-keep] if keep > 0 and len(existing) > keep else ():
        shutil.rmtree(stale, ignore_errors=True)
    return dest


def baseline_clean(root: Path, baseline: dict, get_controls_fn, identity_fn=None) -> bool:
    """True when baseline cameras still hold their original controls (or restoration.json proved clean when unreadable)."""
    cams = baseline.get("cameras") if isinstance(baseline, dict) else None
    if not isinstance(cams, dict) or not cams:
        return True
    try:
        return all((identity_fn is None or identity_fn(spec["device"]) == spec["identity"])
                   and get_controls_fn(spec["device"], spec["original"]) == spec["original"] for spec in cams.values())
    except Exception:
        pass
    rest_path = root / "restoration.json"
    if rest_path.is_file():
        try:
            rest = json.loads(rest_path.read_text(encoding="utf-8"))
            run_path = root / "control-run.json"
            if (isinstance(rest, dict) and set(rest) == set(cams)
                    and all(isinstance(v, dict) and v.get("restored") is True for v in rest.values())):
                if not run_path.exists() or rest_path.stat().st_mtime >= run_path.stat().st_mtime:
                    return True
        except (OSError, ValueError):
            pass
    return False
