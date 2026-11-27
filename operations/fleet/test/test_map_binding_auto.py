"""D-1022: Fleet re-binds a robot whose map file was redrawn in the same frame (same raster, few cells changed)."""
import asyncio
import copy
from types import SimpleNamespace

import pytest

import test_map_binding_routes as routes
import test_trip_runner
from fleet.localization.map_binding import grid_signature
from fleet.server.map_binding_auto import PRINCIPAL, AutoRebind, camera_sighting
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_runner import TripConfig, TripRunner
from test_map_binding_routes import ARENA, OP, TRUTH, _client, _pairs, _walls_grid, _world_261026_charge_graph
from test_site_map_frame_safety import _SPAN, _TRUTH, _bound_setup

OLD, NEW = "occupancy:0123456789ab", "occupancy:2b01883e1dbb"
SPOT = (-0.414, 0.47)  # where the robot stands, site frame
CORNERS = [(ARENA[0], ARENA[1]), (ARENA[2], ARENA[1]), (ARENA[2], ARENA[3]), (ARENA[0], ARENA[3])]


def _state(grid_id, linear=0.0, mode="IDLE"):
    here = TRUTH.inverse(SPOT)
    return {"robot_id": "rosy_42", "map_id": "world_261026", "map_grid_id": grid_id, "mode": mode,
            "pose": {"x": here[0], "y": here[1], "yaw": 0.0}, "navigation": "IDLE", "safety": {"estop": False},
            "velocity": {"linear": linear, "angular": 0.0}, "evidence": {"velocity": {"evidence": "fresh"}},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def _flip(grid, n):
    """The same raster with n free cells turned occupied."""
    grid = copy.deepcopy(grid)
    free = [i for i, v in enumerate(grid["data"]) if v == 0][:n]
    for i in free:
        grid["data"][i] = 100
    return grid


def _rig(tmp_path, *, sig=True, camera=SPOT, old_grid=None, **state_kw):
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    site, _ = _world_261026_charge_graph()
    draft = store.save_draft(site, expected_revision=None, principal_id="op")
    store.activate(expected_revision=draft["revision"], principal_id="op", route_active=False)
    old_grid = old_grid or _walls_grid()
    store.map_bindings.approve(  # the operator's approval of the old grid: four arena corners and a hold-out
        "rosy_42", _state(OLD), (store.active()[1].map_id, store.active()[0]), _pairs(CORNERS), _pairs([SPOT]), "bob",
        grid_sig=grid_signature(old_grid) if sig else None)
    box = {"grid": _flip(old_grid, 11), "state": _state(NEW, **state_kw), "camera": camera, "now": 100.0}

    async def read_grid(_):
        return box["grid"]

    async def read_state(_):
        return box["state"]

    box["rebind"] = AutoRebind(store, grid=read_grid, state=read_state, camera=lambda _: box["camera"],
                               clock=lambda: box["now"])
    return store, box


def _go(box):
    return asyncio.run(box["rebind"]("rosy_42", box["state"]))


def _refused(store, box, code):
    old = store.map_bindings.active("rosy_42")
    assert _go(box) is False
    assert store.map_bindings.active("rosy_42")["binding_id"] == old["binding_id"]
    assert store.map_bindings.auto_notes["rosy_42"]["code"] == code


def test_a_redrawn_grid_with_eleven_cells_changed_is_rebound_with_the_old_transform(tmp_path):
    store, box = _rig(tmp_path, camera=(SPOT[0] + 0.01, SPOT[1]))  # rule05a -> rule06 changed 11 cells
    old = store.map_bindings.active("rosy_42")
    assert _go(box) is True
    new = store.map_bindings.active("rosy_42")
    assert new["approved_by"] == PRINCIPAL and new["robot_grid_id"] == NEW and new["binding_id"] != old["binding_id"]
    assert new["fit"]["yaw"] == pytest.approx(old["fit"]["yaw"], abs=1e-6)
    assert new["fit"]["tx"] == pytest.approx(old["fit"]["tx"], abs=1e-6)
    assert new["grid_sig"] == grid_signature(box["grid"])
    assert store.map_bindings.matching_fit("rosy_42", box["state"], (new["site_map_id"], new["site_map_version"]))[1] == ""
    assert store.map_bindings.auto_notes["rosy_42"]["code"] == "APPROVED"
    assert any(e["action"] == "map_binding_auto_rebind" for e in store.events())


def test_an_origin_shifted_by_one_cell_is_not_rebound(tmp_path):
    store, box = _rig(tmp_path)
    box["grid"]["origin"]["x"] += 0.05
    _refused(store, box, "GRID_FRAME_CHANGED")


def test_a_raster_turned_half_a_turn_is_not_rebound(tmp_path):
    store, box = _rig(tmp_path)
    box["grid"]["data"] = box["grid"]["data"][::-1]
    _refused(store, box, "GRID_CELLS_CHANGED")


def test_a_grid_of_another_size_is_not_rebound(tmp_path):
    store, box = _rig(tmp_path)
    h = box["grid"]["height"]
    box["grid"]["width"] += 1
    box["grid"]["data"] = box["grid"]["data"] + [0] * h
    _refused(store, box, "GRID_FRAME_CHANGED")


def test_too_many_changed_cells_are_not_rebound(tmp_path):
    store, box = _rig(tmp_path)
    box["grid"] = _flip(_walls_grid(), 13)  # the budget is 12: the field case changed 11
    _refused(store, box, "GRID_CELLS_CHANGED")


@pytest.mark.parametrize("camera, code", [(None, "NO_CAMERA_HOLDOUT"), ((SPOT[0] + 0.2, SPOT[1]), "HOLDOUT"),
                                         ((SPOT[0] + 0.06, SPOT[1]), "HOLDOUT")])  # the store's 0.05 m, no looser auto limit
def test_a_missing_or_disagreeing_camera_holdout_is_not_rebound(tmp_path, camera, code):
    store, box = _rig(tmp_path, camera=camera)
    _refused(store, box, code)


def _symmetric_grid():
    """A centred empty arena: its wall ring is its own half turn and mirror image."""
    w, h = 40, 20
    data = [100 if x in (0, w - 1) or y in (0, h - 1) else 0 for y in range(h) for x in range(w)]
    return {"width": w, "height": h, "resolution": 0.05, "origin": {"x": -1.0, "y": -0.5}, "data": data}


def test_a_symmetric_arena_is_not_rebound_even_when_the_raster_matches(tmp_path):
    from fleet.localization.map_binding import same_raster

    sym = _symmetric_grid()
    store, box = _rig(tmp_path, old_grid=sym)
    turned = copy.deepcopy(sym)
    turned["data"] = turned["data"][::-1]
    assert same_raster(grid_signature(sym), grid_signature(turned)) == 0  # the flip alone passes the raster check
    box["grid"] = turned
    _refused(store, box, "GRID_SYMMETRIC")


def test_a_camera_fix_older_than_two_seconds_is_not_a_holdout():
    def pose(age):
        return SimpleNamespace(camera_x=1.0, camera_y=2.0, camera_residual_m=0.01, last_sighting_age_s=age)

    port = lambda age: SimpleNamespace(arbitrated_pose=lambda _: pose(age))
    assert camera_sighting(port(0.5), "rosy_42") == (1.0, 2.0)
    assert camera_sighting(port(3.0), "rosy_42") is None and camera_sighting(port(None), "rosy_42") is None


@pytest.mark.parametrize("kw", [{"linear": 0.2}, {"mode": "NAVIGATION"}])
def test_a_moving_or_busy_robot_is_not_rebound(tmp_path, kw):
    store, box = _rig(tmp_path, **kw)
    _refused(store, box, "NOT_STANDING")


def test_without_a_stored_signature_there_is_no_rebind_until_a_matching_read_stores_one(tmp_path):
    store, box = _rig(tmp_path, sig=False)
    _refused(store, box, "GRID_SIGNATURE_MISSING")
    swapped_grid, swapped_state = box["grid"], box["state"]
    box["now"] += 20.0
    box["grid"], box["state"] = _walls_grid(), _state(OLD)  # the robot still runs the bound grid
    assert _go(box) is False
    assert store.map_bindings.active("rosy_42")["grid_sig"] == grid_signature(_walls_grid())
    box["now"] += 20.0
    box["grid"], box["state"] = swapped_grid, swapped_state  # a later same-frame swap
    assert _go(box) is True and store.map_bindings.active("rosy_42")["approved_by"] == PRINCIPAL


def test_a_grid_the_binding_covers_is_left_alone(tmp_path):
    store, box = _rig(tmp_path)
    box["state"] = _state(OLD)
    assert _go(box) is False and "rosy_42" not in store.map_bindings.auto_notes


def test_a_manual_approval_keeps_the_signature_of_the_grid(tmp_path):
    client = _client(tmp_path)
    body = {"pairs": _pairs(CORNERS), "holdout": _pairs([SPOT])}
    assert client.post("/api/fleet/robots/rosy_42/map-binding", json=body, headers=OP).status_code == 200
    stored = client.app.state.site_maps.map_bindings.active("rosy_42")["grid_sig"]
    assert stored == grid_signature(_walls_grid())


def _swapped_trip(monkeypatch, config=None):
    """A bound robot whose map file was swapped before the trip sent anything; the hook plays a passed proof."""
    stores, calls = [], []

    async def proof(robot_id, state):
        calls.append(robot_id)
        store = stores[0]
        pairs = [{"site": list(p), "robot": list(_TRUTH.inverse(p))} for p in _SPAN]
        store.map_bindings.approve(robot_id, state, (store.active()[1].map_id, store.active()[0]), pairs,
                                   [{"site": [0.0, 0.0], "robot": list(_TRUTH.inverse((0.0, 0.0)))}], PRINCIPAL)
        return True

    monkeypatch.setattr(TripRunner, "auto_rebind", staticmethod(proof), raising=False)
    if config is not None:
        monkeypatch.setattr(test_trip_runner, "TripConfig", lambda **kw: TripConfig(**kw, **config))
    runner, ports = _bound_setup(grid="occupancy:ffffffffffff", store_out=stores)
    return runner, ports, calls


def test_a_trip_continues_after_the_auto_rebind(monkeypatch):
    runner, ports, calls = _swapped_trip(monkeypatch)
    assert calls == ["rosy_60"] and len(ports.goals) == 1
    assert runner.view("p1")["reason"] != "map_frame"
    assert runner.view("p1")["detail"]["goal_frame"]["map_grid_id"] == "occupancy:ffffffffffff"


def test_with_the_switch_off_the_trip_stops_as_before(monkeypatch):
    runner, ports, calls = _swapped_trip(monkeypatch, {"map_auto_rebind": False})
    row = runner.view("p1")
    assert calls == [] and ports.goals == []
    assert row["reason"] == "map_frame" and row["detail"]["binding"] == "MAP_BINDING_GRID_CHANGED"
