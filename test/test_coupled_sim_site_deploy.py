"""Deployment isolation and security checks for deploy/sim_site (D-1088 Slice 3)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SIM_SITE = ROOT / "deploy" / "sim_site"


def _extract_host_port(mapping: str) -> tuple[str, str]:
    # Format: "127.0.0.1:${VAR:-18090}:8080"
    host_ip, rest = mapping.split(":", 1)
    host_port_expr, _container_port = rest.rsplit(":", 1)
    if ":-" in host_port_expr:
        host_port = host_port_expr.split(":-", 1)[1].rstrip("}")
    else:
        host_port = host_port_expr
    return host_ip, host_port


def test_sim_site_compose_isolation_ports_and_world_readonly() -> None:
    raw_text = (SIM_SITE / "compose.yaml").read_text(encoding="utf-8")
    assert "real-site" not in raw_text

    compose = yaml.safe_load(raw_text)
    assert compose["name"] == "rosy-sim-site"

    networks = compose["networks"]
    assert "sim_backend" in networks
    assert "site_backend" not in networks

    volumes = compose["volumes"]
    assert "sim_fleet_data" in volumes

    services = compose["services"]
    expected_services = {"sim-fleet", "sim-controller", "sim-world", "sim-light-core"}
    assert set(services) == expected_services

    forbidden_host_ports = {"8080", "8090", "8140", "8190"}
    seen_host_ports: set[str] = set()
    for name, svc in services.items():
        assert "healthcheck" in svc and svc["healthcheck"].get("test"), f"{name} missing healthcheck"
        assert not svc.get("privileged")
        assert svc.get("network_mode") != "host"
        ports = svc.get("ports") or []
        assert ports, f"{name} must bind loopback port"
        for mapping in ports:
            assert mapping.startswith("127.0.0.1:"), f"{name} port must bind 127.0.0.1"
            _, host_port = _extract_host_port(mapping)
            assert host_port not in forbidden_host_ports, f"{name} host port collides with deploy/site"
            assert host_port not in seen_host_ports
            seen_host_ports.add(host_port)

    assert seen_host_ports == {"18090", "18140", "18190", "18095"}

    sim_world = services["sim-world"]
    assert sim_world["read_only"] is True
    assert sim_world["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in sim_world["security_opt"]
    assert any("/var/lib/rosy-sim-world/worlds:" in str(t) and "uid=10001" in str(t) for t in sim_world["tmpfs"])
    assert sim_world["networks"]["sim_backend"]["aliases"] == ["world"]

    sim_controller = services["sim-controller"]
    assert "--world-url" in sim_controller["command"]
    assert "http://world:18140" in sim_controller["command"]

    sim_fleet_env = services["sim-fleet"]["environment"]
    assert sim_fleet_env["ROSY_FLEET_PINKY_TASK_DISPATCH"] == "1"
    assert sim_fleet_env["ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH"] == "1"
    assert sim_fleet_env["ROSY_SITUATION_PROFILE"] == "sim"
    assert "ROSY_SITUATION_AI_URL" in sim_fleet_env
    assert "ROSY_SIM_CONVERSATION_MODEL" in sim_fleet_env
    assert sim_fleet_env["ROSY_WORLD_HEALTH_URL"] == "http://world:18140/healthz"

    sim_light_core = services["sim-light-core"]
    assert sim_light_core["profiles"] == ["light-core"]


def test_sim_site_env_example_and_readme_present_and_clean() -> None:
    env_text = (SIM_SITE / ".env.example").read_text(encoding="utf-8")
    readme_text = (SIM_SITE / "README.md").read_text(encoding="utf-8")
    assert "ROSY_SIM_FLEET_PORT=18090" in env_text
    assert "ROSY_SIM_AI_URL=" in env_text
    assert "ROSY_SIM_REGISTRY_TOKEN=\n" in env_text
    assert "light-core" in readme_text
    assert "AI PC" in readme_text and "Model PC" in readme_text
