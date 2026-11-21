"""D-1065: OMX cell cameras are named by role (top, side, wrist); the device behind a role comes from omx-cameras.json only."""
from __future__ import annotations

ROLES_BY_CELL = {"ab": ("top", "side", "wrist"), "s": ("top", "wrist")}  # D-1065 §1
WRIST_ROLE = {"arm_a": "arm_a_wrist", "arm_b": "arm_b_wrist", "arm_s": "arm_s_wrist"}


def role_devices(cameras_json: dict) -> dict[str, str]:
    """omx-cameras.json -> {role: device}; the one place that maps devices to roles (D-1065 §2)."""
    out = {}
    for cam in cameras_json.get("cameras", []):
        role, device = cam.get("role"), cam.get("device")
        if not role or not device:
            raise ValueError(f"camera entry without role or device: {cam}")
        if role in out:
            raise ValueError(f"camera role {role} listed twice")
        out[role] = device
    return out


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
