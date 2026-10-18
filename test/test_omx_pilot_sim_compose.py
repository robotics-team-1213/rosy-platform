"""Standalone Pilot SIM configuration must not inherit hardware access."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/robot/omx"


def test_pilot_sim_has_no_hardware_or_host_network_grants():
    compose = yaml.safe_load((DEPLOY / "compose.pilot-sim.yaml").read_text())
    assert set(compose["services"]) == {"vendor", "pilot"}
    for service in compose["services"].values():
        assert not service.get("privileged")
        assert not service.get("devices")
        assert not service.get("device_cgroup_rules")
        assert not service.get("cap_add")
        assert service.get("network_mode") != "host"
        assert service.get("pid") != "host"
    pilot = compose["services"]["pilot"]
    assert pilot["networks"] == ["sim"]
    assert compose["networks"]["sim"]["internal"] is True
    assert pilot["cap_drop"] == ["ALL"]
    assert pilot["security_opt"] == ["no-new-privileges:true"]
    assert pilot["ports"] == ["127.0.0.1:${OMX_PILOT_PORT:-8088}:8088"]


def test_pilot_build_context_and_provenance_match_existing_runtime():
    compose = yaml.safe_load((DEPLOY / "compose.pilot-sim.yaml").read_text())
    vendor, pilot = (compose["services"][name] for name in ("vendor", "pilot"))
    dockerfile = (ROOT / pilot["build"]["dockerfile"]).read_text()
    assert "FROM ${OMX_BASE_IMAGE}" in dockerfile
    assert pilot["build"]["args"]["OMX_BASE_IMAGE"] == vendor["image"]
    assert "${COMPOSE_PROJECT_NAME" in vendor["image"]
    assert "${COMPOSE_PROJECT_NAME" in pilot["image"]
    assert vendor["profiles"] == ["build"]
    assert vendor["command"] == ["true"]
    assert (DEPLOY / pilot["build"]["context"]).resolve() == ROOT
    assert (DEPLOY / vendor["build"]["context"] / vendor["build"]["dockerfile"]).is_file()
    environment = pilot["environment"]
    assert ":?" in environment["ROSY_SIM_SOURCE_REVISION"]
    assert environment["ROS_AUTOMATIC_DISCOVERY_RANGE"] == "LOCALHOST"
    assert environment["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"
    assert pilot["command"] == ["bash", "/repo/deploy/robot/omx/run_pilot_sim.sh"]
    mounts = {item["target"]: item for item in pilot["volumes"]}
    assert set(mounts) == {"/repo", "/recordings"}
    assert mounts["/repo"]["read_only"] is True
    assert (DEPLOY / mounts["/repo"]["source"]).resolve() == ROOT
    assert mounts["/repo"]["bind"]["create_host_path"] is False
    assert mounts["/recordings"]["type"] == "volume"
    assert mounts["/recordings"]["source"] in compose["volumes"]
    assert pilot["restart"] == "no"
