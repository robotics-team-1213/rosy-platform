"""Real pinned RAUC/CMS behavior without global installs, service access or block writes."""
import json

from os_rauc_fakes import rauc_tool, signer, make_bundle, run


def test_isolated_rauc_accepts_codesigning_self_signed_leaf_and_exposes_full_manifest(tmp_path, rauc_tool):
    key, certificate = signer(tmp_path / "authority")
    bundle, config = make_bundle(tmp_path / "bundle", rauc_tool, key, certificate)
    raw = run([rauc_tool, "--conf", config, "info", "--output-format=json-2", bundle])
    value = json.loads(raw)
    assert value["update"]["compatible"] == "rosy-pinky-pro-ab-v2"
    assert value["bundle"]["format"] == "verity"
    assert value["meta"]["rosy"]["boot_abi"] == "2"
    assert {image["slot-class"] for image in value["images"]} == {"rootfs", "boot"}
