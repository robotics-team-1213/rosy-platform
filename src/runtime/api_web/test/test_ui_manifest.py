"""D-204 — 매니페스트는 CAP-001과 역할로 패널을 거르고, not_provided는 생략한다."""

from __future__ import annotations

from core_api_web.api.ui_manifest import build_manifest
from core_api_web.api.ui_registry import Panel, Registry, Surface

SURFACES = {
    "console": Surface("console", "운용", "viewer", "spatial", ("banner", "sense", "observe", "act")),
    "setup": Surface("setup", "작업 준비", "operator", "procedure", ("main",)),
    "device": Surface("device", "설치·정비", "administrator", "procedure", ("main",)),
}


def _panel(pid, surface="console", slot="act", order=10, requires=(), inventory=None, min_role="viewer",
           action_group=None):
    return Panel(pid, pid, surface, slot, order, tuple(requires), inventory, min_role,
                 f"panels/{pid.replace('.', '/')}.js", (), action_group)


REGISTRY = Registry(SURFACES, (
    _panel("drive.teleop", order=40, requires=["teleop"], inventory="mobility.move", min_role="operator",
           action_group="drive"),
    _panel("safety.hero", slot="sense", order=10),
    _panel("vision.front", slot="observe", order=10, requires=["vision.enabled"]),
    _panel("docking.run", order=50, requires=["docking.supported"], inventory="mobility.dock", min_role="operator",
           action_group="docking"),
    _panel("nav.slam", surface="setup", slot="main", requires=["slam"], min_role="operator"),
    _panel("system.events", surface="device", slot="main", order=90, min_role="administrator"),
))

CAPS = {"teleop": True, "slam": True, "vision": {"enabled": False}, "docking": {"supported": True}}


def ids(manifest):
    return [panel["id"] for panel in manifest["panels"]]


def test_a_false_or_missing_flag_is_omitted_not_greyed():
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    assert "vision.front" not in ids(manifest)
    assert "vision.front" not in ids(build_manifest(REGISTRY, "console", "operator", {"teleop": True}, []))


def test_panels_come_in_slot_then_order_sequence():
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    assert ids(manifest) == ["safety.hero", "drive.teleop", "docking.run"]


def test_a_lower_role_does_not_see_the_panel():
    assert "drive.teleop" not in ids(build_manifest(REGISTRY, "console", "viewer", CAPS, []))


def test_a_viewer_gets_no_operator_action_group():
    manifest = build_manifest(REGISTRY, "console", "viewer", CAPS, [])
    assert all(panel["action_group"] is None for panel in manifest["panels"])


def test_an_inventory_descriptor_carries_state_and_reason():
    descriptors = [{"id": "mobility.move", "state": "blocked", "reason": "runtime_mode:core"}]
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, descriptors)
    teleop = next(p for p in manifest["panels"] if p["id"] == "drive.teleop")
    assert (teleop["state"], teleop["reason"]) == ("blocked", "runtime_mode:core")
    hero = next(p for p in manifest["panels"] if p["id"] == "safety.hero")
    assert (hero["state"], hero["reason"]) == ("available", None)
    assert teleop["action_group"] == "drive"


def test_an_unsupported_capability_removes_its_action_group_panel():
    manifest = build_manifest(REGISTRY, "console", "operator", {**CAPS, "docking": {"supported": False}}, [])
    assert "docking.run" not in ids(manifest)


def test_only_groups_from_visible_capability_panels_are_returned():
    manifest = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    groups = {panel["action_group"] for panel in manifest["panels"] if panel["action_group"]}
    assert groups == {"drive", "docking"}
    assert all(panel["action_group"] is None for panel in manifest["panels"] if panel["id"] == "safety.hero")


def test_a_not_provided_descriptor_is_omitted():
    descriptors = [{"id": "mobility.dock", "state": "not_provided", "reason": None}]
    assert "docking.run" not in ids(build_manifest(REGISTRY, "console", "operator", CAPS, descriptors))


def test_surfaces_lists_every_base_surface_the_role_can_open_even_without_panels():
    viewer = build_manifest(REGISTRY, "console", "viewer", CAPS, [])
    assert viewer["surfaces"] == [{"id": "console", "title": "운용"}]
    admin = build_manifest(REGISTRY, "console", "administrator", CAPS, [])
    assert [s["id"] for s in admin["surfaces"]] == ["console", "setup", "device"]


def test_the_manifest_names_the_surface_role_grammar_and_asset_paths():
    manifest = build_manifest(REGISTRY, "device", "administrator", CAPS, [])
    assert manifest["surface"] == "device"
    assert manifest["grammar"] == "procedure"
    assert manifest["role"] == "administrator"
    assert manifest["panels"][0]["module"] == "/assets/panels/system/events.js"
    assert manifest["panels"][0]["title"] == "system.events"


def test_the_revision_moves_only_when_the_content_moves():
    one = build_manifest(REGISTRY, "console", "operator", CAPS, [])["revision"]
    assert one == build_manifest(REGISTRY, "console", "operator", dict(CAPS), [])["revision"]
    assert one != build_manifest(REGISTRY, "console", "operator", {**CAPS, "teleop": False}, [])["revision"]


def test_the_revision_ignores_dynamic_descriptor_state_but_the_panel_state_still_refreshes():
    available = build_manifest(REGISTRY, "console", "operator", CAPS, [])
    blocked_descriptors = [{"id": "mobility.move", "state": "blocked", "reason": "runtime_mode:core"}]
    blocked = build_manifest(REGISTRY, "console", "operator", CAPS, blocked_descriptors)
    # e-stop/health flips change a descriptor's state without moving the
    # revision — the shell must not remount every panel on every health tick.
    assert available["revision"] == blocked["revision"]
    teleop_available = next(p for p in available["panels"] if p["id"] == "drive.teleop")
    teleop_blocked = next(p for p in blocked["panels"] if p["id"] == "drive.teleop")
    assert (teleop_available["state"], teleop_available["reason"]) == ("available", None)
    assert (teleop_blocked["state"], teleop_blocked["reason"]) == ("blocked", "runtime_mode:core")



def test_base_surfaces_remain_listed_when_every_panel_is_absent():
    for role, expected in (("viewer", ["console"]), ("operator", ["console", "setup"]),
                           ("administrator", ["console", "setup", "device"])):
        empty_registry = Registry(SURFACES, ())
        manifest = build_manifest(empty_registry, "console", role, {}, [
            {"id": "mobility.move", "state": "not_provided"},
            {"id": "mobility.dock", "state": "not_provided"},
        ])
        assert manifest["panels"] == []
        assert [surface["id"] for surface in manifest["surfaces"]] == expected
