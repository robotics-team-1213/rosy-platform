import yaml
from pathlib import Path


def test_pinky_manifest_declares_mobile_base():
    data = yaml.safe_load((Path(__file__).parents[1] / "config" / "adapter.manifest.yaml").read_text(encoding="utf-8"))
    assert data["id"] == "rosy.device.pinky"
    assert data["device_type"] == "mobile_base"
    assert "drive" in data["provides"]
    assert "cmd_vel" not in data.get("provides", [])
