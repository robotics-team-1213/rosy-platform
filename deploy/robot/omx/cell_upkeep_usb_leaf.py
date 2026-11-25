"""Where an arm camera sits on USB when it came up unconfigured (no by-id link, no video node): a read-only sysfs lookup.

Split out of cell_upkeep.py on 2026-11-25 so the upkeep entry module stays under the harness lint's 400-line limit.
"""
from __future__ import annotations

import json
from pathlib import Path
import re


def unconfigured_usb_leaf(role, *, sys_usb=None, cameras_path=None, boards_path=None):
    """Resolve an unconfigured/unbound arm camera USB leaf sharing a hub uniquely with its arm's OpenRB."""
    match = re.fullmatch(r"(arm_[a-z])_(?:wrist|top|jieli)", str(role))
    if not match:
        return None
    target_arm = match.group(1)
    cam_file = Path.home() / ".config/rosy/omx-cameras.json" if cameras_path is None else Path(cameras_path)
    board_file = Path("/etc/rosy/omx-arm-boards.json") if boards_path is None else Path(boards_path)
    sys_usb_dir = Path("/sys/bus/usb/devices") if sys_usb is None else Path(sys_usb)
    if not sys_usb_dir.is_dir():
        return None
    try:
        cams = json.loads(cam_file.read_text(encoding="utf-8")).get("cameras", [])
        usb_id = next((c.get("usb_id") for c in cams if isinstance(c, dict) and c.get("role") == role), None)
        id_match = re.fullmatch(r"([0-9a-fA-F]{4}):([0-9a-fA-F]{4})", str(usb_id or ""))
        raw_boards = json.loads(board_file.read_text(encoding="utf-8"))
        if not id_match or not isinstance(raw_boards, dict):
            return None
        vendor, product = id_match.group(1).lower(), id_match.group(2).lower()
        boards = {str(k): str(v) for k, v in raw_boards.items()}
    except (OSError, ValueError, TypeError):
        return None

    candidates = []
    for entry in sorted(sys_usb_dir.iterdir()):
        if not re.fullmatch(r"\d+-[\d.]+", entry.name):
            continue
        try:
            dev = entry.resolve(strict=True)
            dev_class = (dev / "bDeviceClass").read_text().strip() if (dev / "bDeviceClass").exists() else ""
            if dev_class == "09":
                continue
            if (dev / "idVendor").read_text().strip().lower() != vendor:
                continue
            if (dev / "idProduct").read_text().strip().lower() != product:
                continue
            auth = (dev / "authorized").read_text().strip() if (dev / "authorized").exists() else ""
            if auth != "1":
                continue
            bcfg = (dev / "bConfigurationValue").read_text().strip() if (dev / "bConfigurationValue").exists() else ""
            has_v4l = any(dev.glob(f"{dev.name}:*/video4linux"))
            if bcfg not in ("", "0") and has_v4l:
                continue
            if any(
                c.is_dir() and not c.is_symlink() and re.fullmatch(r"\d+-[\d.]+", c.name)
                and (c / "idVendor").is_file() and (c / "idVendor").read_text().strip().lower() == "2f5d"
                for c in dev.iterdir()
            ):
                continue
            hub = dev.parent
            sibling_serials = []
            for sib in hub.iterdir():
                if not re.fullmatch(r"\d+-[\d.]+", sib.name) or sib == dev:
                    continue
                try:
                    if (sib / "idVendor").read_text().strip().lower() != "2f5d":
                        continue
                    ser = (sib / "serial").read_text().strip()
                except OSError:
                    continue
                if ser:
                    sibling_serials.append(ser)
            known_arms = {boards[s] for s in sibling_serials if s in boards}
            if known_arms != {target_arm}:
                continue
            try:
                speed = int((dev / "speed").read_text().strip())
            except (OSError, ValueError):
                speed = 480
            candidates.append((dev, sorted(set(sibling_serials)), speed))
        except OSError:
            continue

    if len(candidates) != 1:
        return None
    dev, sibling_serials, speed = candidates[0]
    return {
        "ports": [],
        "speed": speed,
        "boards": [f"OpenRB:{s}" for s in sibling_serials],
        "leaf": str(dev),
        "leaf_authorized": "1",
        "leaf_boards": [],
    }
