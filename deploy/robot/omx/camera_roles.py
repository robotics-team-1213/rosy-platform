"""D-1065: OMX cell cameras are named by role (top, side, wrist); the device behind a role comes from omx-cameras.json only."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROLES_BY_CELL = {"ab": ("top", "side", "wrist"), "s": ("top", "wrist")}  # D-1065 §1
WRIST_ROLE = {"arm_a": "arm_a_wrist", "arm_b": "arm_b_wrist", "arm_s": "arm_s_wrist"}
_BIMANUAL_ROLES = {
    "top": "top", "side": "side",
    "arm_a_wrist": "arm_a_wrist", "arm_b_wrist": "arm_b_wrist",
    "left_wrist": "arm_a_wrist", "right_wrist": "arm_b_wrist",
}


def registry_path() -> Path:
    return Path.home() / ".config/rosy/omx-cameras.json"


def load_registry(path: Path | None = None) -> dict | None:
    """Return parsed omx-cameras.json, None when absent, or raise ValueError on corrupt/invalid JSON."""
    target = path or registry_path()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{target.name}: 읽을 수 없습니다: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("cameras"), list):
        raise ValueError(f"{target.name}: cameras 목록이 없습니다")
    return data


def role_devices(cameras_json: dict) -> dict[str, str]:
    """omx-cameras.json -> {role: device} for enabled cameras (D-1065 §2)."""
    out, seen = {}, set()
    for cam in cameras_json.get("cameras", []):
        role, device = cam.get("role"), cam.get("device")
        if not role or not device:
            raise ValueError(f"camera entry without role or device: {cam}")
        if role in seen:
            raise ValueError(f"camera role {role} listed twice")
        seen.add(role)
        if cam.get("enabled") is False:
            continue
        out[role] = device
    return out


def disabled_roles(cameras_json: dict) -> set[str]:
    """Roles explicitly disabled in omx-cameras.json (e.g. arm_s_top when unplugged)."""
    return {c["role"] for c in cameras_json.get("cameras", []) if isinstance(c, dict) and c.get("enabled") is False and c.get("role")}


def source_role(cam_key: str, arm: str) -> str | None:
    """Map a record-config camera key + selected arm to its omx-cameras.json registry role."""
    if "." in cam_key:
        prefix, raw = cam_key.split(".", 1)
        return source_role(raw, prefix)
    key = str(cam_key).strip().lower()
    if arm == "arm_s":
        return {"top": "arm_s_top", "wrist": "arm_s_wrist", "front": "arm_s_wrist"}.get(key)
    if arm in WRIST_ROLE:
        return {"top": "top", "side": "side", "wrist": WRIST_ROLE[arm], "front": WRIST_ROLE[arm]}.get(key)
    if arm == "arm_ab":
        return _BIMANUAL_ROLES.get(key)
    return None


def _iter_camera_items(robot: dict) -> list[tuple[str, dict]]:
    items = [(k, v) for k, v in (robot.get("cameras") or {}).items() if isinstance(v, dict)]
    if robot.get("type") == "bi_omx_follower":
        for side in ("arm_a", "arm_b"):
            for k, v in ((robot.get(side) or {}).get("cameras") or {}).items():
                if isinstance(v, dict):
                    items.append((f"{side}.{k}", v))
    return items


def resolve_record_cameras(
    cfg: dict, arm: str, cameras_json: dict | None, *, exists=None, realpath=os.path.realpath
) -> tuple[dict, list[str], list[str]]:
    """Resolve config camera paths from omx-cameras.json without losing fail-closed device/duplicate checks."""
    resolved = copy.deepcopy(cfg)
    robot = resolved.get("robot") if isinstance(resolved.get("robot"), dict) else {}
    items = _iter_camera_items(robot)
    exists_fn = exists or (lambda p: Path(p).exists())
    rebinds, issues = [], []
    devices, disabled = None, set()
    if cameras_json is not None:
        try:
            devices = role_devices(cameras_json)
            disabled = disabled_roles(cameras_json)
        except (ValueError, TypeError) as exc:
            return resolved, rebinds, [f"omx-cameras.json 오류: {exc}"]
    for cam_key, spec in items:
        idx = str(spec.get("index_or_path") or "")
        src = source_role(cam_key, arm) if (devices is not None and arm) else None
        if devices is not None and src:
            label = f"{cam_key}({src})" if src != cam_key else cam_key
            if src in disabled:
                issues.append(f"{label}: 비활성 카메라")
                continue
            reg_dev = devices.get(src)
            if reg_dev:
                if not exists_fn(reg_dev):
                    issues.append(f"{label}: 등록 장치 없음({reg_dev})")
                else:
                    if idx != reg_dev:
                        spec["index_or_path"] = reg_dev
                        rebinds.append(f"{cam_key}: {idx or '?'} -> {reg_dev}")
                    idx = reg_dev
                continue
        if idx.startswith("/dev/") and not exists_fn(idx):
            issues.append(f"{cam_key}: 장치 없음({idx})")
    seen_devs = {}
    for cam_key, spec in items:
        idx = str(spec.get("index_or_path") or "")
        if not idx:
            continue
        canon = str(realpath(idx)) if exists_fn(idx) else idx
        if canon in seen_devs:
            issues.append(f"{cam_key}: {seen_devs[canon]}와 동일 장치 중복({idx})")
        else:
            seen_devs[canon] = cam_key
    return resolved, rebinds, issues


def check_record_cameras(record_config: dict, cameras_json: dict, arm: str, cell: str = "ab") -> None:
    """Refuse a recording config whose camera keys are not the cell's role names or whose devices differ (D-1065 §3)."""
    roles = ROLES_BY_CELL[cell]
    cams = (record_config.get("robot") or {}).get("cameras") or {}
    if set(cams) != set(roles):
        raise ValueError(f"recording cameras must be exactly {list(roles)} (D-1065), got {sorted(cams)}")
    devices = role_devices(cameras_json)
    for role in roles:
        source = WRIST_ROLE[arm] if role == "wrist" else role
        want = devices.get(source)
        got = cams[role].get("index_or_path")
        if want is None:
            raise ValueError(f"omx-cameras.json has no {source} camera")
        if got != want:
            raise ValueError(f"camera {role} must be {want} ({source} in omx-cameras.json), got {got}")
