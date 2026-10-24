"""Descriptive profiles persist independently of enrollment and command authority."""

import sqlite3

import pytest

from fleet.server.device_profiles import DeviceProfileStore


def metadata(**overrides):
    return {"display_name": "연구용 양팔 로봇", "manufacturer": "제조사", "model": "M-2",
            "device_kind": "manipulator", "arm_count": 2,
            "hardware_ids": ["serial:abc-123", "asset:실험실"], **overrides}


def test_persistence_replace_and_metadata_only(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE existing_tasks (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO existing_tasks VALUES ('task-1')")
    store = DeviceProfileStore(path)
    assert store.list_profiles() == []
    assert store.get_profile("arm-1") is None
    result = store.put_profile("arm-1", metadata(), updated_by="operator:kim")
    assert result.items() >= metadata().items()
    assert result["device_id"] == "arm-1"
    assert result["updated_by"] == "operator:kim"
    assert result["updated_at"]
    assert result["connection_status"] == "not_checked"
    assert result["control_enabled"] is False
    reopened = DeviceProfileStore(path)
    assert reopened.get_profile("arm-1") == result
    replacement = reopened.put_profile("arm-1", {"display_name": "이동 로봇", "device_kind": "mobile"},
                                       updated_by="operator:lee")
    assert replacement["manufacturer"] == replacement["model"] == ""
    assert replacement["arm_count"] is None
    assert replacement["hardware_ids"] == []
    assert replacement["updated_by"] == "operator:lee"
    assert reopened.list_profiles() == [replacement]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM existing_tasks").fetchall() == [("task-1",)]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"existing_tasks", "fleet_device_profiles"}


@pytest.mark.parametrize("changes", [
    {"display_name": ""}, {"display_name": "  "}, {"display_name": "x" * 81},
    {"display_name": 123}, {"display_name": "robot\nname"}, {"model": None},
    {"manufacturer": "x" * 81}, {"model": "bad\x7f"}, {"device_kind": "arm"},
    {"arm_count": True}, {"arm_count": 2.0}, {"arm_count": "2"},
    {"arm_count": -1}, {"arm_count": 17}, {"arm_count": 0},
    {"hardware_ids": "serial"}, {"hardware_ids": ["same", "same"]},
    {"hardware_ids": [""]}, {"hardware_ids": [" "]}, {"hardware_ids": [False]},
    {"hardware_ids": ["x" * 201]}, {"hardware_ids": ["bad\tserial"]},
    {"hardware_ids": [str(i) for i in range(17)]}, {"control_enabled": True},
    {"connection_status": "connected"}, {"updated_by": "forged"}, {"base_url": "http://device"},
])
def test_invalid_metadata_cannot_replace_existing_profile(tmp_path, changes):
    store = DeviceProfileStore(tmp_path / "tasks.sqlite3")
    original = store.put_profile("robot-1", metadata(), updated_by="operator:kim")
    with pytest.raises(ValueError):
        store.put_profile("robot-1", metadata(**changes), updated_by="operator:kim")
    assert store.get_profile("robot-1") == original


@pytest.mark.parametrize("device_id", ["", "../robot", "robot.id", "한글", "-robot", "x" * 65, "robot\n"])
def test_invalid_device_id(tmp_path, device_id):
    store = DeviceProfileStore(tmp_path / "tasks.sqlite3")
    for operation in (lambda: store.get_profile(device_id),
                      lambda: store.put_profile(device_id, metadata(), updated_by="operator:kim")):
        with pytest.raises(ValueError):
            operation()
    assert store.list_profiles() == []


@pytest.mark.parametrize("kind,count", [("manipulator", None), ("manipulator", 1),
                                       ("mobile", 0), ("other", 16)])
def test_optional_arm_count_and_bounds(tmp_path, kind, count):
    store = DeviceProfileStore(tmp_path / "tasks.sqlite3")
    profile = store.put_profile("R_1", metadata(device_kind=kind, arm_count=count), updated_by="kim")
    assert profile["arm_count"] == count
