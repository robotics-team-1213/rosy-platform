"""D-263 migration inventory stays attached to role-owned surfaces."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "hmi" / "dashboard"


def test_device_surface_contains_system_and_host_readbacks():
    manifest = yaml.safe_load((WEB / "panels.yaml").read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in manifest["panels"]}
    expected = {
        "host.system": {"/api/v1/system/runtime", "/api/v1/system/info",
                        "/api/v1/system/capabilities", "/api/v1/system/inventory"},
        "host.operations": {"/api/v1/host/network", "/api/v1/host/release",
                            "/api/v1/host/commissioning", "/api/v1/host/network/mode",
                            "/api/v1/host/network/apply", "/api/v1/host/network/connect",
                            "/api/v1/host/release/rollback", "/api/v1/host/release/clear-hold"},
    }
    for panel_id, endpoints in expected.items():
        panel = panels[panel_id]
        assert panel["surface"] == "device"
        assert panel["min_role"] == "administrator"
        source = (WEB / panel["module"]).read_text(encoding="utf-8")
        assert endpoints <= set(__import__("re").findall(r'"(/api/v1/[^"?]+)', source))


def test_setup_surface_contains_capability_gated_localization_controls():
    manifest = yaml.safe_load((WEB / "panels.yaml").read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in manifest["panels"]}
    panel = panels["setup.localization"]
    assert panel["surface"] == "setup"
    assert panel["min_role"] == "operator"
    source = (WEB / panel["module"]).read_text(encoding="utf-8")
    assert {"/api/v1/system/capabilities", "/api/v1/localization/initialpose",
            "/api/v1/slam/start", "/api/v1/slam/stop", "/api/v1/slam/save"} <= set(
                __import__("re").findall(r'"(/api/v1/[^"?]+)', source))


def test_device_surface_moves_credential_and_safety_policy_controls():
    manifest = yaml.safe_load((WEB / "panels.yaml").read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in manifest["panels"]}
    panel = panels["system.security"]
    assert panel["surface"] == "device"
    assert panel["min_role"] == "administrator"
    source = (WEB / panel["module"]).read_text(encoding="utf-8")
    assert {"/api/v1/system/tokens", "/api/v1/safety/limits"} <= set(
        __import__("re").findall(r'"(/api/v1/[^"?]+)', source))


def test_setup_surface_contains_capability_gated_docking_preparation():
    manifest = yaml.safe_load((WEB / "panels.yaml").read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in manifest["panels"]}
    panel = panels["setup.docking"]
    assert panel["surface"] == "setup"
    assert panel["min_role"] == "operator"
    source = (WEB / panel["module"]).read_text(encoding="utf-8")
    assert {"/api/v1/docking/status", "/api/v1/docking/docks", "/api/v1/docking/dock",
            "/api/v1/docking/undock", "/api/v1/docking/cancel"} <= set(
                __import__("re").findall(r'"(/api/v1/[^"?]+)', source))


def test_console_surface_contains_a_keyboard_accessible_map_panel():
    manifest = yaml.safe_load((WEB / "panels.yaml").read_text(encoding="utf-8"))
    panels = {panel["id"]: panel for panel in manifest["panels"]}
    panel = panels["console.map"]
    assert panel["surface"] == "console"
    assert panel.get("min_role", "viewer") == "viewer"
    source = (WEB / panel["module"]).read_text(encoding="utf-8")
    map_source = (WEB / "map.js").read_text(encoding="utf-8")
    assert "createFieldMap" in source
    assert "destroy" in source
    assert 'tabIndex' in map_source
    assert {"/api/v1/map", "/api/v1/navigation/path"} <= set(
        __import__("re").findall(r'"(/api/v1/[^"?]+)', map_source))
