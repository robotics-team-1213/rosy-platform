import asyncio

import pytest

from core_common.protocol.integrated_control import ControlOverview, ControlUnitDetail, ControlUnitSummary
from fleet.server.control_unit_collection import ControlUnitCollection
from fleet.server.control_unit_config import ControlUnitTopology
from fleet.server.control_unit_runtime import ControlUnitConfig


def config():
    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [
        {"id": "R"}, {"id": "A", "parent": "R"},
        {"id": "A1", "parent": "A"}, {"id": "B", "parent": "R"},
    ]})
    return ControlUnitConfig("R", topology, {})


def summary(unit, parent, **changes):
    data = dict(unit_id=unit, parent=parent, availability="AVAILABLE",
                sampled_at="2026-10-24T00:00:00Z", age_s=1.0,
                robots_total=0, robots_online=0, tasks_active=0, map=None,
                dispatch={"authority_epoch": 1, "generation": 2}, error=None)
    return ControlUnitSummary.model_validate(data | changes)


class Local:
    async def read(self):
        return summary("R", None), ControlUnitDetail.model_validate(dict(
            unit_id="R", config_revision="v1", availability="AVAILABLE",
            sampled_at="2026-10-24T00:00:00Z", age_s=1.0, robots=[], tasks=[],
            tasks_truncated=False, map=None, dispatch={"authority_epoch": 1, "generation": 2}))

    def map(self):
        return None


def test_nested_overview_calls_only_direct_children_and_ages_without_wall_clock():
    requests, clock = [], [0.0]

    async def peer(unit, method, path):
        requests.append((unit, method, path))
        rows = ([summary("A", "R"), summary("A1", "A")]
                if unit == "A" else [summary("B", "R")])
        return ControlOverview(unit_id=unit, config_revision="v1", units=rows).model_dump(mode="json")

    collection = ControlUnitCollection(config(), Local(), peer, clock=lambda: clock[0])
    assert all(r.availability == "UNAVAILABLE" for r in collection.overview().units)
    asyncio.run(collection.refresh())
    assert set(requests) == {("A", "GET", "overview"), ("B", "GET", "overview")}
    assert {r.unit_id for r in collection.overview().units} == {"R", "A", "A1", "B"}
    clock[0] = 8.0
    assert all(r.age_s == 9.0 and r.availability == "STALE" and r.dispatch is None
               for r in collection.overview().units)


def test_child_failure_retains_last_sample_and_does_not_erase_sibling():
    fail, clock = [False], [0.0]

    async def peer(unit, method, path):
        if unit == "A" and fail[0]:
            raise ConnectionError("private transport detail")
        rows = ([summary("A", "R"), summary("A1", "A")]
                if unit == "A" else [summary("B", "R")])
        return ControlOverview(unit_id=unit, config_revision="v1", units=rows).model_dump(mode="json")

    collection = ControlUnitCollection(config(), Local(), peer, clock=lambda: clock[0])
    asyncio.run(collection.refresh())
    fail[0], clock[0] = True, 2.0
    asyncio.run(collection.refresh())
    rows = {r.unit_id: r for r in collection.overview().units}
    assert rows["A1"].sampled_at is not None and rows["A1"].age_s == 3.0
    assert rows["A1"].availability == "STALE" and rows["A1"].dispatch is None
    assert rows["B"].availability == "AVAILABLE"
    assert "private" not in collection.overview().model_dump_json()


@pytest.mark.parametrize("corrupt", ["sibling", "parent", "revision", "missing", "ownership"])
def test_invalid_child_projection_is_rejected_as_a_whole(corrupt):
    async def peer(unit, method, path):
        rows = [summary("B", "R")] if unit == "B" else [summary("A", "R"), summary("A1", "A")]
        value = ControlOverview(unit_id=unit, config_revision="v1", units=rows).model_dump(mode="json")
        if unit == "A":
            if corrupt == "sibling":
                value["units"].append(summary("B", "R").model_dump(mode="json"))
            elif corrupt == "parent":
                value["units"][0]["parent"] = "B"
            elif corrupt == "revision":
                value["config_revision"] = "other"
            elif corrupt == "missing":
                value["units"].pop()
            else:
                value["units"][0]["robots_total"] = 1
        return value

    collection = ControlUnitCollection(config(), Local(), peer)
    asyncio.run(collection.refresh())
    rows = {r.unit_id: r for r in collection.overview().units}
    assert rows["A"].availability == rows["A1"].availability == "UNAVAILABLE"
    assert rows["B"].availability == rows["R"].availability == "AVAILABLE"


def test_detail_and_map_relay_reject_foreign_targets_and_mismatched_identity():
    requests = []

    async def peer(unit, method, path):
        requests.append((unit, method, path))
        _, detail = await Local().read()
        return detail.model_dump(mode="json")

    collection = ControlUnitCollection(config(), Local(), peer)
    with pytest.raises(ValueError, match="OUTSIDE_SCOPE"):
        asyncio.run(collection.detail("foreign"))
    assert requests == []
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        asyncio.run(collection.detail("A1"))
    assert requests == [("A", "GET", "units/A1")]
    assert asyncio.run(collection.map("R")) is None


@pytest.mark.parametrize("transit", [2.0, 6.0])
def test_detail_transit_ages_robot_observation_and_removes_stale_dispatch(transit):
    clock = [0.0]
    topology = ControlUnitTopology.from_mapping({"revision": "v1", "units": [
        {"id": "R"}, {"id": "A", "parent": "R"},
        {"id": "A1", "parent": "A", "resources": ["robot:a1"]},
    ]})

    async def peer(unit, method, path):
        clock[0] = transit
        return dict(unit_id="A1", config_revision="v1", availability="AVAILABLE",
                    sampled_at="2026-10-24T00:00:00Z", age_s=1.0, tasks=[], tasks_truncated=False,
                    map=None, dispatch={"authority_epoch": 1, "generation": 2}, robots=[dict(
                        robot_id="a1", online=True, state_age_s=2.0, mode=None,
                        battery_percent=None, estop=None, pose=None)])

    collection = ControlUnitCollection(ControlUnitConfig("R", topology, {}), Local(), peer,
                                        clock=lambda: clock[0])
    detail = asyncio.run(collection.detail("A1"))
    assert detail.age_s == transit + 1.0 and detail.robots[0].state_age_s == transit + 2.0
    assert detail.availability == ("STALE" if transit == 6.0 else "AVAILABLE")
    assert (detail.dispatch is None) == (transit == 6.0)
