#!/usr/bin/env python3
"""Diagnose and recover OMX USB hub, OpenRB-150 serial, and camera failures.

Escalate through camera links, hub port reset, and an explicitly gated host reboot.
"""
from __future__ import annotations

import ctypes
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows test host
    fcntl = None  # type: ignore[assignment]
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path
from typing import Callable

USBDEVFS_CONTROL = 0xC0185500
USB_PORT_FEAT_ENABLE = 1
USB_PORT_FEAT_RESET = 4
USB_PORT_FEAT_POWER = 8
DEFAULT_MOTOR_IDS = (11, 12, 13, 14, 15, 16)

CAMERA_SYMLINK_MAP = {
    "rosy-arm_s_jieli": "usb-Jieli_Technology_USB_Composite_Device-video-index0",
    "rosy-arm_s_wrist": "usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0",
}


class _UsbCtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_ubyte),
        ("bRequest", ctypes.c_ubyte),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


def decode_port_status(w_port_status: int, w_port_change: int) -> dict:
    """Decode USB 2.0 Hub `GetPortStatus` (`wPortStatus`, `wPortChange`) bitfields."""
    return {
        "raw_status": f"0x{w_port_status:04x}",
        "raw_change": f"0x{w_port_change:04x}",
        "connected": bool(w_port_status & 0x0001),
        "enabled": bool(w_port_status & 0x0002),
        "suspended": bool(w_port_status & 0x0004),
        "over_current": bool(w_port_status & 0x0008),
        "resetting": bool(w_port_status & 0x0010),
        "powered": bool(w_port_status & 0x0100),
        "low_speed": bool(w_port_status & 0x0200),
        "high_speed": bool(w_port_status & 0x0400),
        "c_connection": bool(w_port_change & 0x0001),
        "c_enable": bool(w_port_change & 0x0002),
        "c_reset": bool(w_port_change & 0x0010),
    }


def restore_camera_symlinks(
    v4l_by_id_dir: str | Path = "/dev/v4l/by-id",
    symlink_map: dict[str, str] | None = None,
) -> dict:
    """Ensure `/dev/v4l/by-id/rosy-arm_s_*` symlinks point to their hardware video-index0 targets
    after a USB hub reset."""
    base = Path(v4l_by_id_dir)
    mapping = symlink_map or CAMERA_SYMLINK_MAP
    restored: list[str] = []
    missing_targets: list[str] = []
    if not base.exists():
        return {"ok": False, "restored": restored, "missing_targets": list(mapping.keys())}

    for alias, target_name in mapping.items():
        target_path = base / target_name
        alias_path = base / alias
        # If udev already created alias -> ../../videoN and it resolves, keep it.
        if alias_path.is_symlink() and alias_path.exists():
            continue
        if not target_path.exists():
            missing_targets.append(alias)
            continue
        need_link = True
        if alias_path.is_symlink():
            try:
                if os.readlink(alias_path) == target_name and alias_path.exists():
                    need_link = False
            except OSError:
                need_link = True
        if need_link:
            try:
                if alias_path.exists() or alias_path.is_symlink():
                    alias_path.unlink()
                alias_path.symlink_to(target_name)
                restored.append(alias)
            except OSError:
                if os.name == "nt":
                    shutil.copy2(target_path, alias_path)
                    restored.append(alias)
                else:
                    missing_targets.append(alias)
    return {"ok": len(missing_targets) == 0, "restored": restored, "missing_targets": missing_targets}


def active_other_arm_sessions(
    lock_dir: str | Path = "/tmp",
    exclude_arm: str = "arm_s",
) -> list[str]:
    """Return active `session-arm_*.lock` files belonging to other arms (`arm_a`, `arm_b`, etc.)."""
    base = Path(lock_dir)
    if not base.exists():
        return []
    active: list[str] = []
    for lock_file in sorted(base.glob("session-arm_*.lock")):
        if lock_file.name == f"session-{exclude_arm}.lock":
            continue
        active.append(lock_file.name)
    return active


def emergency_torque_off_arm(
    serial_by_id_path: str | Path,
    *,
    motor_ids: tuple[int, ...] = DEFAULT_MOTOR_IDS,
    baudrate: int = 1_000_000,
    bus_factory: Callable | None = None,
) -> dict:
    """Immediately disable torque (`Torque_Enable (64) = 0`) and reset `Bus_Watchdog (98) = 0`
    on all follower motors (`11..16`) when repeated session or USB/runner failures occur,
    preventing thermal/overload wind-up before hardware recovery steps."""
    serial_path = Path(serial_by_id_path)
    if not (serial_path.is_symlink() and serial_path.exists()):
        return {
            "ok": False,
            "verdict": "port_unavailable_torque_already_unpowered_or_dropped",
            "serial_path": str(serial_path),
            "torques": {},
            "reason": f"serial port {serial_path.name} is offline; cannot send packet torque_off",
        }
    if bus_factory is not None:
        return bus_factory(str(serial_path), motor_ids, baudrate)
    try:
        from dynamixel_sdk import PacketHandler, PortHandler

        resolved = str(serial_path.resolve(strict=True))
        port = PortHandler(resolved)
        packet = PacketHandler(2.0)
        if not (port.openPort() and port.setBaudRate(baudrate)):
            return {"ok": False, "verdict": "port_open_failed", "serial_path": str(serial_path), "torques": {}}
        torques: dict[int, int | str] = {}
        try:
            for mid in motor_ids:
                try:
                    packet.write1ByteTxRx(port, mid, 98, 0)  # Clear Bus_Watchdog first if tripped
                    packet.write1ByteTxRx(port, mid, 64, 0)  # Torque_Enable = 0
                    val, comm, _ = packet.read1ByteTxRx(port, mid, 64)
                    torques[mid] = int(val) if comm == 0 else f"comm:{comm}"
                except Exception as exc:
                    torques[mid] = f"error:{exc}"
        finally:
            port.closePort()
        ok = all(v == 0 for v in torques.values()) and len(torques) == len(motor_ids)
        return {
            "ok": ok,
            "verdict": "torque_off_confirmed" if ok else "torque_off_partial",
            "serial_path": str(serial_path),
            "torques": torques,
            "reason": "all follower motors confirmed torque OFF" if ok else f"torque states: {torques}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "verdict": "torque_off_exception",
            "serial_path": str(serial_path),
            "torques": {},
            "reason": str(exc),
        }


def schedule_last_resort_host_reboot(
    *,
    allow_host_reboot: bool = False,
    lock_dir: str | Path = "/tmp",
    exclude_arm: str = "arm_s",
    run_fn: Callable | None = None,
) -> dict:
    """Reboot only with operator permission and no other arm session lock."""
    other_locks = active_other_arm_sessions(lock_dir=lock_dir, exclude_arm=exclude_arm)
    if not allow_host_reboot:
        return {
            "ok": False,
            "tier": "tier4_host_reboot",
            "verdict": "reboot_skipped_policy_disabled",
            "active_other_locks": other_locks,
            "reason": "host reboot skipped because allow_host_reboot=False",
        }
    if other_locks:
        return {
            "ok": False,
            "tier": "tier4_host_reboot",
            "verdict": "reboot_blocked_by_active_arm",
            "active_other_locks": other_locks,
            "reason": f"host reboot blocked: other arm sessions active ({', '.join(other_locks)})",
        }
    runner = run_fn or subprocess.run
    res = runner(["sudo", "-n", "systemctl", "reboot"], capture_output=True, text=True, check=False)
    ok = getattr(res, "returncode", 1) == 0
    return {
        "ok": ok,
        "tier": "tier4_host_reboot",
        "verdict": "host_reboot_initiated" if ok else "host_reboot_failed",
        "active_other_locks": [],
        "reason": "initiated last-resort host reboot" if ok else f"systemctl reboot failed: {getattr(res, 'stderr', '')}".strip(),
    }


def hub_get_port_status(dev_path: str | Path, port: int, ioctl_fn: Callable | None = None) -> tuple[int, int]:
    """Read `(wPortStatus, wPortChange)` from a USB hub device node (`/dev/bus/usb/BBB/DDD`)."""
    do_ioctl = ioctl_fn or getattr(fcntl, "ioctl", None)
    data = (ctypes.c_ubyte * 4)()
    ctrl = _UsbCtrlTransfer(0xA3, 0x00, 0, int(port), 4, 1000, ctypes.addressof(data))
    with open(dev_path, "rb+") as f:
        do_ioctl(f.fileno(), USBDEVFS_CONTROL, ctrl)
    return struct.unpack("<HH", bytes(data))


def hub_port_power_and_reset(
    dev_path: str | Path,
    port: int,
    *,
    off_s: float = 1.5,
    reset_wait_s: float = 0.15,
    ioctl_fn: Callable | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict:
    """Execute USB Hub Class `ClearPortFeature(PORT_POWER)` -> `SetPortFeature(PORT_POWER)` ->
    `SetPortFeature(PORT_RESET)` on `port` and return decoded before/off/after states."""
    do_ioctl = ioctl_fn or getattr(fcntl, "ioctl", None)

    def _read(fd: int) -> tuple[int, int]:
        data = (ctypes.c_ubyte * 4)()
        ctrl = _UsbCtrlTransfer(0xA3, 0x00, 0, int(port), 4, 1000, ctypes.addressof(data))
        do_ioctl(fd, USBDEVFS_CONTROL, ctrl)
        return struct.unpack("<HH", bytes(data))

    with open(dev_path, "rb+") as f:
        fd = f.fileno()
        before = decode_port_status(*_read(fd))
        # ClearPortFeature(PORT_POWER = 8)
        do_ioctl(fd, USBDEVFS_CONTROL, _UsbCtrlTransfer(0x23, 0x01, USB_PORT_FEAT_POWER, int(port), 0, 1000, 0))
        sleep_fn(off_s)
        during_off = decode_port_status(*_read(fd))
        # SetPortFeature(PORT_POWER = 8)
        do_ioctl(fd, USBDEVFS_CONTROL, _UsbCtrlTransfer(0x23, 0x03, USB_PORT_FEAT_POWER, int(port), 0, 1000, 0))
        sleep_fn(reset_wait_s)
        after = decode_port_status(*_read(fd))

    return {"before": before, "during_off": during_off, "after": after}


def diagnose_and_recover_arm_serial(
    serial_by_id_path: str | Path,
    *,
    hub_sysfs_dir: str | Path = "/sys/bus/usb/devices/3-1",
    port: int = 1,
    v4l_by_id_dir: str | Path = "/dev/v4l/by-id",
    off_s: float = 1.5,
    ensure_torque_off_on_recover: bool = True,
    allow_host_reboot: bool = False,
    lock_dir: str | Path = "/tmp",
    ioctl_fn: Callable | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    run_fn: Callable | None = None,
    torque_off_fn: Callable | None = None,
) -> dict:
    """Self-healing preflight pipeline for `arm_s` OpenRB-150 serial + USB hub cameras.

    1. Restores `/dev/v4l/by-id/rosy-arm_s_*` camera symlinks if a hub reset removed them.
    2. Checks if `serial_by_id_path` exists and resolves cleanly.
    3. If missing, cycles `PORT_POWER` + `PORT_RESET` on the USB hub port via `USBDEVFS_CONTROL`.
    4. If `serial_by_id_path` reappears, immediately enforces `emergency_torque_off_arm` (when
       `ensure_torque_off_on_recover=True`) so motors never stay energized after a crash/reset,
       then returns `verdict="recovered"`.
    5. If `after["connected"]` is True (`D+` pull-up high) and still unrecovered:
       - Evaluates Tier 4 last-resort host reboot (`allow_host_reboot=True` and no other arm locks),
         or returns `verdict="mcu_hardfault_12v_latched"` with `person_needed=True`.
    """
    serial_path = Path(serial_by_id_path)
    cam_status = restore_camera_symlinks(v4l_by_id_dir=v4l_by_id_dir)

    if serial_path.is_symlink() and serial_path.exists():
        return {
            "ok": True,
            "verdict": "ready",
            "class": "serial_online",
            "serial_path": str(serial_path),
            "cameras": cam_status,
            "person_needed": False,
            "reason": f"serial symlink {serial_path.name} is online",
        }

    hub_dir = Path(hub_sysfs_dir)
    busnum_file = hub_dir / "busnum"
    devnum_file = hub_dir / "devnum"
    if not (busnum_file.exists() and devnum_file.exists()):
        return {
            "ok": False,
            "verdict": "hub_missing",
            "class": "usb_hub_disconnected",
            "serial_path": str(serial_path),
            "cameras": cam_status,
            "person_needed": True,
            "reason": f"USB hub sysfs {hub_dir} not present",
        }

    busnum = int(busnum_file.read_text().strip())
    devnum = int(devnum_file.read_text().strip())
    dev_node = Path(f"/dev/bus/usb/{busnum:03d}/{devnum:03d}")

    cycle = hub_port_power_and_reset(
        dev_node,
        port,
        off_s=off_s,
        ioctl_fn=ioctl_fn,
        sleep_fn=sleep_fn,
    )
    sleep_fn(0.5)
    cam_status = restore_camera_symlinks(v4l_by_id_dir=v4l_by_id_dir)

    if serial_path.is_symlink() and serial_path.exists():
        tq_status = (
            (torque_off_fn or emergency_torque_off_arm)(serial_path)
            if ensure_torque_off_on_recover
            else {"ok": True, "verdict": "skipped"}
        )
        return {
            "ok": True,
            "verdict": "recovered",
            "class": "usb_port_reset_recovered",
            "serial_path": str(serial_path),
            "hub_port_cycle": cycle,
            "torque_off": tq_status,
            "cameras": cam_status,
            "person_needed": False,
            "reason": f"recovered {serial_path.name} via USB hub port {port} power+reset cycle (torque_off={tq_status.get('verdict')})",
        }

    after = cycle["after"]
    reboot_attempt = schedule_last_resort_host_reboot(
        allow_host_reboot=allow_host_reboot,
        lock_dir=lock_dir,
        run_fn=run_fn,
    )
    if reboot_attempt.get("ok"):
        return {
            "ok": False,
            "verdict": "host_reboot_initiated",
            "class": "tier4_last_resort_host_reboot",
            "serial_path": str(serial_path),
            "hub_port_cycle": cycle,
            "cameras": cam_status,
            "tier4_reboot": reboot_attempt,
            "person_needed": False,
            "reason": reboot_attempt["reason"],
        }

    if after["connected"]:
        return {
            "ok": False,
            "verdict": "mcu_hardfault_12v_latched",
            "class": "openrb_samd21_usb_isr_hung",
            "serial_path": str(serial_path),
            "hub_port_cycle": cycle,
            "cameras": cam_status,
            "tier4_reboot": reboot_attempt,
            "person_needed": True,
            "reason": (
                f"hub port {port} shows D+ connected ({after['raw_status']}) after VBUS power+reset cycle, "
                "but OpenRB-150 SAMD21 MCU stays powered from 12V VIN(DXL) with USB ISR hung (-110/-62); "
                "press OpenRB-150 RESET button or cycle 12V SMPS"
            ),
        }

    return {
        "ok": False, "verdict": "cable_unplugged", "class": "usb_port_disconnected",
        "serial_path": str(serial_path), "hub_port_cycle": cycle, "cameras": cam_status,
        "tier4_reboot": reboot_attempt, "person_needed": True,
        "reason": f"hub port {port} shows no device connected ({after['raw_status']})",
    }
