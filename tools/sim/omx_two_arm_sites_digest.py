"""Layout identity digest helpers split from `omx_two_arm_sites` to stay under the 500-line cap."""
from hashlib import sha256
import json


def round_coordinates(value):
    """Remove platform-dependent last bits before comparing layout receipts."""
    if isinstance(value, dict):
        return {key: round_coordinates(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [round_coordinates(item) for item in value]
    return round(value, 9) if isinstance(value, float) else value


def layout_digest(layout, ship_assets=None):
    """Stable SHA-256 over resolved cell geometry, choices, and shipped STL/JSON assets."""
    if ship_assets is None:
        from omx_two_arm_sites import SHIP_ASSETS
        ship_assets = SHIP_ASSETS
    frame = layout.fixture
    data = dict(choices=layout.choices, box=layout.box, table_z=layout.table_z,
                cameras=frame["real_cameras"], temp_plates=layout.plates,
                table=[frame["workplate_center_m"], frame["workplate_size_m"]],
                belt=[layout.belt_stop_x, layout.belt_y, layout.belt_top],
                arms={name: [arm.base.tolist(), arm.yaw, arm.wait.tolist()]
                      for name, arm in layout.arms.items()},
                plan=layout.plan_order(), sites=layout.sites)
    identity = sha256(json.dumps(round_coordinates(data), sort_keys=True, separators=(",", ":")).encode())
    for path in sorted(ship_assets.iterdir(), key=lambda item: item.name):
        if path.suffix in {".stl", ".json"}:
            identity.update(path.name.encode() + b"\0" + sha256(path.read_bytes()).digest())
    return identity.hexdigest()
