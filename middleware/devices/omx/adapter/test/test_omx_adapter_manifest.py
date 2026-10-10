import yaml
from pathlib import Path


def test_disabled_omx_manifest_provides_nothing():
    data = yaml.safe_load(Path(__file__).parents[1].joinpath("config/adapter.manifest.yaml").read_text(encoding="utf-8"))
    assert data["id"] == "rosy.device.omx"
    assert data["enabled"] is False
    assert data["provides"] == []
