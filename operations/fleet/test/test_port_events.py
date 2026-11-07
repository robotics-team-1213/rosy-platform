"""D-996 1/2/7: closed port events, the append-only cell ledger and the R read across direct child cells."""
import asyncio
from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from core_common.protocol.port_events import PortEvent, event_id
from fleet.server.port_event_routes import contiguous, decode_cursor, install_port_event_routes, read_page
from fleet.server.port_event_store import PortEventConflict, PortEventStore
from fleet.server.site_auth import SitePrincipal

T = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)
CELL = "cell-supply"


def make(kind="container.received_at_intake", ref="obs-1", source=CELL, **fields):
    defaults = {"container.received_at_intake": {"object_ref": "CNTR-1", "intake_point": "intake-A",
                                                 "identity": "observed"},
                "container.stored": {"object_ref": "CNTR-1", "slot_ref": "yard-r1-c2-l1", "identity": "attested"},
                "container.handling_failed": {"reason": "UNREADABLE"},
                "vehicle.release_permitted": {"vehicle_id": "rosy_01"}}[kind]
    return PortEvent(event_id=event_id(source, ref, kind), kind=kind, observation_ref=ref, observed_at=T,
                     **{**defaults, **fields})


@pytest.mark.parametrize("kind,bad", [
    ("container.received_at_intake", {"identity": None}),
    ("container.received_at_intake", {"slot_ref": "yard-r1-c1-l1"}),
    ("container.received_at_intake", {"object_ref": None}),
    ("container.stored", {"slot_ref": None}),
    ("container.stored", {"slot_ref": "A-1"}),
    ("container.handling_failed", {"reason": None}),
    ("container.handling_failed", {"identity": "observed"}),
    ("vehicle.release_permitted", {"object_ref": "CNTR-1"}),
    ("vehicle.release_permitted", {"reason": "LOST"})])
def test_each_kind_has_its_required_and_forbidden_fields(kind, bad):
    with pytest.raises(ValidationError):
        make(kind, **bad)


def test_the_event_is_closed_utc_and_its_id_names_the_source():
    assert make("container.handling_failed", object_ref=None).object_ref is None  # unread and undeclared
    with pytest.raises(ValidationError):
        PortEvent.model_validate({**make().model_dump(mode="json"), "workcell_id": "cell-supply"})
    with pytest.raises(ValidationError):
        PortEvent.model_validate({**make().model_dump(mode="json"), "observed_at": "2026-11-08T12:00:00+09:00"})
    assert make().matches(CELL) and not make().matches("other-cell")


def test_the_ledger_is_append_only_monotonic_and_idempotent_on_event_id(tmp_path):
    store = PortEventStore(tmp_path / "fleet.sqlite3")
    first = store.append(CELL, make())
    assert store.append(CELL, make()) == first  # a resend is the same row
    second = store.append(CELL, make("vehicle.release_permitted", "obs-2"))
    assert second == first + 1
    with pytest.raises(PortEventConflict):
        store.append(CELL, make(object_ref="CNTR-2"))
    with pytest.raises(PermissionError):
        store.append("other-cell", make())
    assert [r["seq"] for r in store.after(0, 10)] == [first, second]
    assert [r["seq"] for r in store.after(first, 10)] == [second]
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as connection:
        for statement in ("UPDATE fleet_port_events SET source='x'", "DELETE FROM fleet_port_events"):
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute(statement)


def test_a_gap_stops_the_read_before_it():
    rows = [{"seq": 4}, {"seq": 5}, {"seq": 7}]
    assert contiguous(rows, 3) == ([{"seq": 4}, {"seq": 5}], True)
    assert contiguous(rows[:2], 3) == ([{"seq": 4}, {"seq": 5}], False)
    with pytest.raises(ValueError):
        decode_cursor("not base64 json")


class FakePeer:
    def __init__(self, ledgers):
        self.ledgers, self.calls = ledgers, []

    async def port_events(self, unit_id, after_seq, limit):
        self.calls.append(unit_id)
        rows = self.ledgers[unit_id]
        if rows is None:
            raise OSError("unreachable")
        return {"rows": [{"seq": s, "event": e.model_dump(mode="json")} for s, e in rows if s > after_seq][:limit]}


def control(ledgers):
    units = {"R": SimpleNamespace(unit_id="R", parent=None, resources=("robot:rosy_01",)),
             "cell-a": SimpleNamespace(unit_id="cell-a", parent="R", resources=("workcell:supply",)),
             "cell-b": SimpleNamespace(unit_id="cell-b", parent="R", resources=("workcell:yard",)),
             "cell-c": SimpleNamespace(unit_id="cell-c", parent="cell-a", resources=("workcell:deep",)),
             "plain": SimpleNamespace(unit_id="plain", parent="R", resources=("robot:rosy_02",))}
    return SimpleNamespace(unit=units["R"], topology=SimpleNamespace(units=units), peer=FakePeer(ledgers))


def test_r_reads_direct_workcell_children_with_an_opaque_cursor_and_marks_unreached_cells():
    a1, a2 = make(ref="a1", source="supply"), make("vehicle.release_permitted", "a2", source="supply")
    b1 = make("container.stored", "b1", source="yard")
    ledgers = {"cell-a": [(1, a1), (2, a2)], "cell-b": None}
    unit = control(ledgers)
    page = asyncio.run(read_page(None, unit, None, 50))
    assert [e["event_id"] for e in page["events"]] == [a1.event_id, a2.event_id]
    assert page["complete"] is False  # cell-b did not answer
    assert sorted(set(unit.peer.calls)) == ["cell-a", "cell-b"]  # grandchild and robot-only units are not asked
    ledgers["cell-b"] = [(1, b1), (3, make("vehicle.release_permitted", "b3", source="yard"))]
    again = asyncio.run(read_page(None, unit, page["cursor"], 50))
    assert [e["event_id"] for e in again["events"]] == [b1.event_id]  # cell-a already read; cell-b stops at its gap
    assert again["complete"] is False
    last = asyncio.run(read_page(None, unit, again["cursor"], 50))
    assert last["events"] == [] and last["complete"] is False  # the gap holds until it is filled
    short = asyncio.run(read_page(None, control({"cell-a": [(1, a1), (2, a2)], "cell-b": [(1, b1)]}), None, 2))
    assert len(short["events"]) == 2 and short["complete"] is False  # the page filled before cell-b was reached
    ledgers["cell-b"].insert(1, (2, make("vehicle.release_permitted", "b2", source="yard")))
    filled = asyncio.run(read_page(None, unit, again["cursor"], 50))
    assert len(filled["events"]) == 2 and filled["complete"] is True


def app_with(tmp_path, *, parent="R"):
    app = FastAPI()
    tokens = {"supply": "cell-token"}

    class Observations:
        def authorize_workcell(self, workcell_id, token):
            if workcell_id not in tokens:
                raise KeyError(workcell_id)
            if token != tokens[workcell_id]:
                raise PermissionError

    def authorize(x_who: str = Header("")):
        if not x_who:
            raise HTTPException(401)
        role = "service" if x_who.startswith(("control-unit:", "harbor")) else "viewer"
        return SitePrincipal(x_who, role)

    app.state.control_unit = SimpleNamespace(unit=SimpleNamespace(unit_id="cell-a", parent=parent),
                                             topology=SimpleNamespace(units={}), peer=None)
    install_port_event_routes(app, Observations(), SimpleNamespace(store=SimpleNamespace(path=tmp_path / "f.sqlite3")),
                              authorize=authorize, require_viewer=authorize)
    return TestClient(app)


def test_ingest_needs_the_workcells_machine_token_and_the_peer_read_needs_the_direct_parent(tmp_path):
    client = app_with(tmp_path)
    path = "/api/fleet/workcell-observations/supply/port-events"
    body = make(source="supply").model_dump_json()
    assert client.post(path, content=body).status_code == 401
    assert client.post(path, content=body, headers={"X-Workcell-Observation-Token": "wrong"}).status_code == 401
    token = {"X-Workcell-Observation-Token": "cell-token"}
    first = client.post(path, content=body, headers=token)
    assert first.status_code == 200 and client.post(path, content=body, headers=token).json() == first.json()
    assert client.post(path, content=make(source="other").model_dump_json(), headers=token).status_code == 422
    assert client.post(path, content=b'{"kind": "x"}', headers=token).status_code == 422
    assert client.post(path, content=b"x" * 5000, headers=token).status_code == 413
    release = make("vehicle.release_permitted", "r1", source="supply").model_dump_json()
    assert client.post(path, content=release, headers=token).status_code == 422  # only Fleet releases a vehicle
    peer = "/api/fleet/control-unit/port-events"
    assert client.get(peer, headers={"X-Who": "control-unit:other"}).status_code == 403
    assert client.get(peer, headers={"X-Who": "harbor"}).status_code == 403
    rows = client.get(peer, params={"after_seq": 0}, headers={"X-Who": "control-unit:R"}).json()["rows"]
    assert [r["seq"] for r in rows] == [first.json()["seq"]]
    read = client.get("/api/fleet/port-events", headers={"X-Who": "harbor"}).json()
    assert read["complete"] is True and [e["event_id"] for e in read["events"]] == [first.json()["event_id"]]
    assert client.get("/api/fleet/port-events", params={"after": "%%"}, headers={"X-Who": "harbor"}).status_code == 400
