"""The optional unit mount and CLI default stay separate from the shared site configuration."""

from pathlib import Path, PurePosixPath

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_control_unit_overlay_requires_private_fleet_only_readonly_configuration():
    site = ROOT / "deploy/site"
    base = yaml.safe_load((site / "compose.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((site / "compose.control-unit.yaml.example").read_text(encoding="utf-8"))
    assert set(overlay["services"]) == {"fleet"}
    fleet = overlay["services"]["fleet"]
    assert "command" not in fleet and "secrets" not in fleet
    assert "ROSY_CONTROL_UNIT_CONFIG" not in base["services"]["fleet"]["environment"]
    configured = PurePosixPath(fleet["environment"]["ROSY_CONTROL_UNIT_CONFIG"])
    assert configured.is_absolute() and configured.name == "control-unit.yaml"
    assert len(fleet["volumes"]) == 1
    mount = fleet["volumes"][0]
    assert mount["type"] == "bind" and mount["read_only"] is True
    assert mount["source"].startswith("${ROSY_CONTROL_UNIT_DIR:?")
    assert PurePosixPath(mount["target"]) == configured.parent
    example = yaml.safe_load((site / "control-unit.example.yaml").read_text(encoding="utf-8"))
    assert example["share_information_with_parent"] is False and example["accept_parent_stop"] is False
    for relative in [example["tls_ca_file"], *(peer["token_file"] for peer in example["peers"].values())]:
        assert not PurePosixPath(relative).is_absolute() and ".." not in PurePosixPath(relative).parts
