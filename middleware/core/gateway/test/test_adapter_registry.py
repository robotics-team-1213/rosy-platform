from core_common.domain.adapters import AdapterRegistry


def test_registry_skips_disabled_omx(tmp_path):
    pinky = tmp_path / "pinky.yaml"
    omx = tmp_path / "omx.yaml"
    pinky.write_text("id: rosy.device.pinky\nversion: 0.1.0\ndevice_type: mobile_base\nenabled: true\nprovides: [drive]\n", encoding="utf-8")
    omx.write_text("id: rosy.device.omx\nversion: 0.1.0\ndevice_type: manipulator\nenabled: false\nprovides: []\n", encoding="utf-8")
    loaded = AdapterRegistry.from_paths([pinky, omx]).enabled()
    assert [item.id for item in loaded] == ["rosy.device.pinky"]


def test_registry_rejects_missing_id(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("device_type: mobile_base\n", encoding="utf-8")
    try:
        AdapterRegistry.from_paths([path])
    except ValueError as exc:
        assert "id" in str(exc)
    else:
        raise AssertionError("manifest without id must fail")
