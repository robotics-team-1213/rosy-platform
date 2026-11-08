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


def test_signed_control_unit_overlay_mounts_the_unit_read_only_and_names_its_peer():
    """D-960: the signed overlay replaces the unsigned per-site file, so the updater keeps verifying every Compose file."""
    site = ROOT / "deploy/site"
    overlay = yaml.safe_load((site / "compose.control-unit.yaml").read_text(encoding="utf-8"))
    assert set(overlay["services"]) == {"fleet", "control-unit-peer"}
    fleet, peer = overlay["services"]["fleet"], overlay["services"]["control-unit-peer"]
    assert "command" not in fleet and "secrets" not in fleet and "ports" not in peer
    assert fleet["environment"]["ROSY_CONTROL_UNIT_CONFIG"] == "/etc/rosy/control-unit/control-unit.yaml"
    assert "rosy-control-peers" in fleet["networks"] and overlay["networks"]["rosy-control-peers"]["external"]
    mounts = fleet["volumes"] + peer["volumes"]
    assert all(m["type"] == "bind" and m["read_only"] and m["source"].startswith("${ROSY_CONTROL_UNIT_DIR:?")
               and not m["bind"]["create_host_path"] for m in mounts)
    assert peer["image"].startswith("rosy-site-proxy:${ROSY_SITE_IMAGE_TAG")
    assert peer["read_only"] and peer["cap_drop"] == ["ALL"]
    assert peer["networks"]["rosy-control-peers"]["aliases"] == ["${ROSY_CONTROL_UNIT_PEER_ALIAS:?Set this unit's peer alias, e.g. peer-r}"]


def test_remote_peer_overlay_only_publishes_the_peer_origin_and_follows_the_control_unit_overlay():
    """D-994: a neighbour on another PC reaches this unit's peer proxy; nothing else gains a host port."""
    import pytest
    from deploy.site.site_update_io import Refused, allowed_overlays
    overlay = yaml.safe_load((ROOT / "deploy/site/compose.control-unit-remote.yaml").read_text(encoding="utf-8"))
    (port,) = overlay["services"].pop("control-unit-peer")["ports"]
    assert overlay["services"] == {} and port.startswith("${ROSY_CONTROL_UNIT_PEER_BIND:?")
    assert port.count("${ROSY_CONTROL_UNIT_PEER_PORT:?") == 2  # published unchanged, no wildcard default
    site = "-f /opt/rosy/candidate/deploy/site/compose."
    unit, remote = site + "control-unit.yaml", site + "control-unit-remote.yaml"
    for value in (f"{site}pairing.yaml {unit} {remote} {site}monitoring.yaml {site}account.yaml", f"{unit} {remote}"):
        assert allowed_overlays({"ROSY_SITE_PAIRING_COMPOSE": value}) == value.split()
    for value in (remote, f"{remote} {unit}", f"{site}pairing.yaml {remote}"):
        with pytest.raises(Refused):
            allowed_overlays({"ROSY_SITE_PAIRING_COMPOSE": value})
