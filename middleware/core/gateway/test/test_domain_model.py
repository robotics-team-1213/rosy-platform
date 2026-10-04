from core_common.domain.model import (
    Asset,
    Component,
    Device,
    DeviceState,
    RuntimeNode,
    inventory_from_config,
    slices_from_config,
)
from core_features.command.arbitration import Mode


def test_slices_come_from_runtime_presets_not_a_hidden_mode_table():
    presets = {
        "core": ["core"],
        "hardware": ["core", "motor", "io", "nav"],
    }
    assert slices_from_config({"runtime": {"mode": "hardware", "presets": presets}}) == (
        "core",
        "motor",
        "io",
        "nav",
    )
    assert slices_from_config({"runtime": {"mode": "core", "presets": presets}}) == ("core",)


def test_inventory_is_a_single_mobile_base_asset():
    data = inventory_from_config(
        {
            "robot": {"id": "rosy_03", "name": "Bay 3", "number": 3},
            "runtime": {"mode": "hardware"},
        },
        profile_model="Pinky Pro",
        sensors=["lidar", "encoder"],
        slices=["core", "motor", "io", "nav"],
        mode=Mode.IDLE,
        health_error=False,
        estop=False,
    )
    assert isinstance(data["node"], RuntimeNode)
    assert data["node"].runtime_mode == "hardware"
    assert data["node"].slices == ("core", "motor", "io", "nav")
    device = data["device"]
    assert isinstance(device, Device)
    assert device.device_id == "rosy_03"
    assert device.device_type == "mobile_base"
    assert {c.name for c in data["components"]} >= {"drive", "lidar", "encoder"}
    asset = data["asset"]
    assert isinstance(asset, Asset)
    assert asset.asset_id == "rosy_03"
    assert asset.type == "mobile_base"
    assert asset.devices == ("rosy_03",)
    assert "omx" not in asset.devices
    assert data["device_state"] is DeviceState.READY


def test_estop_maps_to_safe_stop():
    data = inventory_from_config(
        {"robot": {"id": "rosy_01"}, "runtime": {"mode": "core"}},
        profile_model="Pinky Pro",
        sensors=[],
        slices=["core"],
        mode=Mode.EMERGENCY,
        health_error=False,
        estop=True,
    )
    assert data["device_state"] is DeviceState.SAFE_STOP


def test_booting_when_snapshot_has_not_arrived():
    data = inventory_from_config(
        {"robot": {"id": "rosy_01"}, "runtime": {"mode": "core"}},
        profile_model="Pinky Pro",
        sensors=[],
        slices=["core"],
        mode=Mode.IDLE,
        health_error=False,
        estop=False,
        booting=True,
    )
    assert data["device_state"] is DeviceState.BOOTING


def test_inventory_exposes_descriptors_and_task_kinds():
    data = inventory_from_config(
        {"robot": {"id": "rosy_01"}, "runtime": {"mode": "hardware"}},
        profile_model="Pinky Pro",
        sensors=["lidar"],
        slices=["core", "motor", "io", "nav"],
        mode=Mode.IDLE,
        health_error=False,
        estop=False,
        cap001={
            "teleop": True,
            "navigation": {"goal_navigation": True, "return_home": True},
            "swarm": {"follow": True, "lead": False},
            "docking": {"supported": False},
            "slam": False,
        },
    )
    ids = {d["id"]: d for d in data["descriptors"]}
    assert ids["mobility.move"]["available"] is True
    assert ids["mobility.move"]["state"] == "available"
    assert "manipulate.pick" not in ids
    kinds = {item["kind"]: item["concept_id"] for item in data["task_kinds"]}
    assert kinds["MOVE"] == "mobility.move"
    assert kinds["NAVIGATE"] == "mobility.navigate"
