"""D-982: rosy.site_rules/1 - defaults equal today's constants, bounds only restrict, store, judge, live wiring."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fleet.charge_bays import GO_PERCENT, LEAVE_PERCENT, Bay, ChargeBays, RobotView, thresholds_of
from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.site_map import SiteMap
from fleet.site_rules import FOLLOW_SPEED_MPS, SiteRules
from fleet.site_rules_judge import Departure, Formation, Return, judge
from fleet.swarm.api.types import MIN_SPACING, FormationSpec
from fleet.traffic import blocks
from fleet.traffic.lane_traffic import TrafficService


def activate(store: SiteMapStore, rules: dict) -> dict:
    draft = store.rules.save_draft(SiteRules.model_validate(rules), expected_revision=None, principal_id="op")
    return store.rules.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)


def test_no_document_means_todays_constants():
    rules = SiteRules()
    assert (rules.departure.merge_max_wait_s, rules.departure.blocks_per_robot) == (20.0, 3)
    assert (rules.return_.go_percent, rules.return_.leave_percent) == (15.0, 80.0) == (GO_PERCENT, LEAVE_PERCENT)
    assert FOLLOW_SPEED_MPS == FormationSpec(formation="COLUMN").max_speed == 0.15
    assert rules.formation.refusal(MIN_SPACING, 9.0) is None  # no extra limit unless the document sets one
    store = SiteMapStore()
    assert store.rules.active_rules() is None and thresholds_of(store) == (GO_PERCENT, LEAVE_PERCENT)
    assert TrafficService(store)._departure() == (blocks.MERGE_MAX_WAIT_S, blocks.HELD_PER_ROBOT)


@pytest.mark.parametrize("bad", [
    {"departure": {"blocks_per_robot": 2}},            # fewer blocks would admit more robots on a loop
    {"departure": {"merge_max_wait_s": 0}},
    {"departure": {"merge_max_wait_s": float("nan")}},
    {"departure": {"order": "random"}},
    {"return": {"go_percent": 14.9}},                  # below CORE critical 10 % + 5 %
    {"return": {"go_percent": 60}},
    {"return": {"go_percent": 40, "leave_percent": 40}},
    {"return": {"leave_percent": 30}},
    {"return": {"when_full": {"wait_at": ""}}},
    {"stops": [{"place": "A", "role": "load", "on_timeout": "depart"}]},   # no rule departs on its own
    {"stops": [{"place": "A", "role": "load", "timeout_s": 0}]},
    {"stops": [{"place": "A", "role": "load"}, {"place": "A", "role": "load"}]},
    {"formation": {"min_gap_m": MIN_SPACING - 0.01}},
    {"formation": {"max_speed_mps": 0.16}},            # above the follow speed used today
    {"schema": "rosy.site_rules/2"},
    {"unknown": 1},
])
def test_values_past_a_safety_bound_are_rejected(bad):
    with pytest.raises(ValidationError):
        SiteRules.model_validate(bad)


def test_a_document_round_trips_with_its_wire_names():
    body = SiteRules.model_validate({"return": {"go_percent": 20, "when_full": {"wait_at": "W"}},
                                     "stops": [{"place": "S", "role": "unload", "release": "timer"}]}).body()
    assert body["return"]["go_percent"] == 20 and body["schema"] == "rosy.site_rules/1"
    assert SiteRules.model_validate(body).body() == body


def test_draft_activation_versions_audit_and_route_guard():
    store = SiteMapStore()
    assert store.rules.draft_view() == {"rules": None, "revision": None}
    first = store.rules.save_draft(SiteRules(), expected_revision=None, principal_id="alice")
    with pytest.raises(SiteMapError) as stale:
        store.rules.save_draft(SiteRules(), expected_revision=None, principal_id="bob")
    assert stale.value.code == "SITE_RULES_DRAFT_CHANGED"
    with pytest.raises(SiteMapError) as busy:
        store.rules.activate(expected_revision=first["revision"], principal_id="bob", route_active=True)
    assert busy.value.code == "SITE_RULES_ROUTE_ACTIVE" and store.rules.active_rules() is None
    with pytest.raises(SiteMapError) as wrong:
        store.rules.activate(expected_revision="nope", principal_id="bob", route_active=False)
    assert wrong.value.code == "SITE_RULES_DRAFT_CHANGED"
    view = store.rules.activate(expected_revision=first["revision"], principal_id="bob", route_active=False)
    assert view["version"] == 1 and view["activated_by"] == "bob" and store.rules.draft_view()["rules"] is None
    with pytest.raises(SiteMapError) as none:
        store.rules.activate(expected_revision=first["revision"], principal_id="bob", route_active=False)
    assert none.value.code == "SITE_RULES_NO_DRAFT"
    assert activate(store, {"return": {"go_percent": 25}})["version"] == 2
    assert store.rules.active_rules().return_.go_percent == 25
    assert [e["action"] for e in store.events(10)][:3] == ["rules_activated", "rules_draft_saved", "rules_activated"]


def test_the_active_document_survives_a_restart(tmp_path):
    store = SiteMapStore(tmp_path / "site.sqlite")
    activate(store, {"departure": {"merge_max_wait_s": 30, "blocks_per_robot": 4}})
    store.close()
    again = SiteMapStore(tmp_path / "site.sqlite")
    assert again.rules.active_rules().departure.blocks_per_robot == 4


def test_a_stored_document_that_no_longer_validates_does_not_stop_fleet(tmp_path):
    store = SiteMapStore(tmp_path / "site.sqlite")
    activate(store, {"return": {"go_percent": 20}})
    with store._db:
        store._db.execute("""UPDATE site_rules_versions SET body = '{"return": {"go_percent": 1}}'""")
    store.close()
    assert SiteMapStore(tmp_path / "site.sqlite").rules.active_rules() is None


def test_places_must_exist_on_the_active_map():
    store = SiteMapStore()
    with pytest.raises(SiteMapError) as no_map:
        store.rules.save_draft(SiteRules.model_validate({"stops": [{"place": "A", "role": "wait"}]}),
                               expected_revision=None, principal_id="op")
    assert no_map.value.code == "SITE_RULES_UNKNOWN_PLACE"
    site = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "rules_test",
        "places": [{"id": "A", "name": "a", "x": 0, "y": 0}, {"id": "B", "name": "b", "x": 1, "y": 0}],
        "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "direction": "two_way",
                   "width_m": 0.18, "speed_cap_mps": 0.1}]})
    draft = store.save_draft(site, expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    with pytest.raises(SiteMapError) as unknown:
        store.rules.save_draft(SiteRules.model_validate({"stops": [{"place": "Z", "role": "wait"}]}),
                               expected_revision=None, principal_id="op")
    assert unknown.value.code == "SITE_RULES_UNKNOWN_PLACE"
    assert activate(store, {"stops": [{"place": "B", "role": "load"}]})["version"] == 1


def test_a_document_changes_what_the_live_code_reads():
    store = SiteMapStore()
    activate(store, {"departure": {"merge_max_wait_s": 30, "blocks_per_robot": 4}, "return": {"go_percent": 25}})
    assert TrafficService(store)._departure() == (30.0, 4)
    assert thresholds_of(store) == (25.0, 80.0)
    fleet = [RobotView("a", True, 20.0, None, None, False)]
    bay = [Bay("C1", 0.0, 0.0)]
    plan = ChargeBays(thresholds=lambda: thresholds_of(store))
    assert plan.plan(fleet, bay)["thresholds"]["go_percent"] == 25.0
    assert plan.plan(fleet, bay)["actions"][0]["action"] == "go"
    assert ChargeBays().plan(fleet, bay)["actions"] == []  # 20 % is above today's 15 %


def waiter(robot_id, seconds, **extra):
    return {"robot_id": robot_id, "waiting_s": seconds, **extra}


def test_departure_order_is_the_order_blocks_step_grants_in():
    rules = SiteRules()
    state = lambda me, capacity=1, **kw: Departure.model_validate(
        {"kind": "departure", "robot_id": me, "capacity": capacity, "robots": [
            waiter("a", 5), waiter("b", 25), waiter("c", 30, in_zone=True), waiter("d", 1, localized=False)], **kw})
    assert judge(rules, state("c"))["verdict"] == "go"       # waited past the bound and inside the zone
    b = judge(rules, state("b"))
    assert (b["verdict"], b["reason"], b["detail"]["ahead"]) == ("wait", "queued_behind", ["c"])
    assert judge(rules, state("b", capacity=2))["verdict"] == "go"
    assert judge(rules, state("a", capacity=2))["reason"] == "queued_behind"
    assert judge(rules, state("d"))["reason"] == "pose_unknown"
    assert judge(rules, state("zz"))["verdict"] == "refuse"
    # a longer bound lets the 25 s waiter no longer jump ahead of the zone robot's earlier wait start
    wide = SiteRules.model_validate({"departure": {"merge_max_wait_s": 60}})
    assert judge(wide, state("b"))["detail"]["past_merge_bound"] is False
    assert blocks.grant_order_key("x", 0.0, 25.0, False) < blocks.grant_order_key("y", 20.0, 25.0, True)


def ask_return(rules, me, percent, bays=("C1",), occupied=None, **extra):
    robots = [{"robot_id": me, "percent": percent, **extra}]
    for robot in (occupied or {}).values():
        robots.append({"robot_id": robot, "percent": 90})
    return judge(rules, Return.model_validate({"kind": "return", "robot_id": me, "robots": robots,
                                                "bays": list(bays), "occupied": occupied or {}}))


def test_return_judgement_is_the_charge_bay_plan():
    rules = SiteRules.model_validate({"return": {"go_percent": 20, "when_full": {"wait_at": "W"}}})
    assert ask_return(rules, "a", 18)["verdict"] == "go" and ask_return(rules, "a", 18)["detail"]["bay"] == "C1"
    assert ask_return(SiteRules(), "a", 18)["reason"] == "not_needed"      # 18 % is above today's 15 %
    full = ask_return(rules, "a", 18, occupied={"C1": "p"})
    assert (full["verdict"], full["reason"], full["detail"]["wait_at"]) == ("wait", "no_free_bay", "W")
    assert ask_return(rules, "a", 18, on_trip=True)["reason"] == "after_trip"
    assert ask_return(rules, "a", None)["reason"] == "battery_unknown"
    assert ask_return(rules, "a", 90)["verdict"] == "refuse"
    assert ask_return(rules, "a", 18, bays=())["reason"] == "no_free_bay"


def test_formation_judgement_uses_the_arming_checks_and_the_site_limits():
    limits = SiteRules.model_validate({"formation": {"min_gap_m": 0.7, "max_speed_mps": 0.1}})
    ask = lambda rules, **kw: judge(rules, Formation.model_validate({"kind": "formation", **kw}))
    assert ask(limits, followers=2, spacing=0.8, max_speed=0.1)["verdict"] == "go"
    assert ask(limits, followers=2, spacing=0.8, max_speed=0.1)["detail"]["enforced"] is False  # stage 3 enforces
    assert ask(limits, followers=2, spacing=0.45)["reason"] == "gap_below_site_min"
    assert ask(limits, followers=2, spacing=0.8)["reason"] == "speed_above_site_max"   # the default speed is 0.15
    assert ask(SiteRules(), followers=2, spacing=0.3)["reason"] == "invalid_formation"   # the floor in slots()
    assert ask(SiteRules(), followers=0)["reason"] == "invalid_formation"
    assert ask(SiteRules(), formation="FOLLOW", followers=2)["verdict"] == "refuse"
    assert ask(SiteRules(), formation="NOPE")["verdict"] == "refuse"
    assert ask(SiteRules(), max_speed=0.15, spacing=0.4)["verdict"] == "go"      # nothing new is refused by default
