#!/usr/bin/env python3
"""Observation Manifest, Readiness Profile & Fleet Decision Synchronization for OMX Cameras (`omx_cameras_sync.py`).

Single Responsibility:
  - Synchronize registered camera device paths into workcell observation YAML manifests (`sync_manifest`, `_sync_manifest_file`).
  - Synchronize readiness camera profiles (`sync_readiness`, `_sync_readiness_file`).
  - Apply Fleet operator camera role decisions (`device_key`, `apply_decisions`, `approve`).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


def sync_manifest(registry: dict, text: str) -> tuple[str, list, list]:
    """(text, changed, unregistered): each camera's device_path set from the registry role with its image_topic."""
    device = {c["topic"]: c["device"] for c in registry["cameras"]}
    lines, topic, changed, unregistered = text.split("\n"), None, [], []
    for i, line in enumerate(lines):
        key, _, value = line.strip().removeprefix("- ").partition(":")
        value = value.split(" #")[0]
        if key == "image_topic":
            topic = value.strip()
        elif key == "device_path" and topic is not None:
            if topic not in device:
                unregistered.append(topic)
            elif value.strip() != device[topic]:
                changed.append({"topic": topic, "from": value.strip(), "to": device[topic]})
                lines[i] = line[: len(line) - len(line.lstrip())] + f"device_path: {device[topic]}"
            topic = None
    return "\n".join(lines), changed, unregistered


def _sync_manifest_file(registry: dict, path: Path) -> list:
    if not path.is_file() or not os.access(path, os.W_OK):
        return []
    text, changed, _ = sync_manifest(registry, path.read_text(encoding="utf-8"))
    if changed:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    return changed


def sync_readiness(registry: dict, profile: dict) -> tuple[dict, list]:
    """Keep each readiness camera's device aligned with its preview unit's role in the registry."""
    by_role = {c["role"]: c["device"] for c in registry["cameras"]}
    changed, cameras = [], {}
    for role, spec in profile.get("cameras", {}).items():
        unit = spec.get("unit", role)
        want = by_role.get(unit)
        if want and spec.get("device") != want:
            changed.append({"role": role, "unit": unit, "from": spec.get("device"), "to": want})
            cameras[role] = {**spec, "device": want}
        else:
            cameras[role] = dict(spec)
    return {**profile, "cameras": cameras}, changed


def _sync_readiness_file(registry: dict, path: Path) -> list:
    if not path.is_file() or not os.access(path, os.W_OK):
        return []
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    updated, changed = sync_readiness(registry, profile)
    if changed:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, path.stat().st_mode)
        os.replace(tmp, path)
    return changed


def approve(registry: dict, role: str, row: dict) -> dict:
    """The registry with ROLE on the proposed camera ROW; a new role gets the topic and frame naming convention."""
    camera = next((c for c in registry["cameras"] if c["role"] == role), None)
    if camera is None:
        camera = {
            "role": role,
            "topic": f"/{role}_camera/image_raw",
            "frame": f"{role}_camera_link",
            "stream": "color",
        }
        registry["cameras"].append(camera)
    camera.update(device=row["device"], usb_id=row["usb_id"])
    return registry


def device_key(device: str) -> str:
    """What the control PC tells Fleet instead of a device name (D-963)."""
    return hashlib.sha256(device.encode()).hexdigest()[:32]


def apply_decisions(registry: dict, proposals: list, path: Path) -> tuple[list, dict]:
    """Approve each proposed camera whose key Fleet decided a role for: (changes, decisions still waiting)."""
    try:
        decided = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(decided, dict):
        return [], {}
    changes = []
    for row in proposals:
        role = decided.pop(device_key(row["device"]), None)
        if isinstance(role, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", role):
            approve(registry, role, row)
            changes.append({"role": role, "to": row["device"]})
    return changes, decided
