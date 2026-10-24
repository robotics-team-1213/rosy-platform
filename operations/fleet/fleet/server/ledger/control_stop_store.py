"""Immutable assigned stops, transactional local latch, and non-replaying receipts."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from uuid import uuid4

from core_common.protocol.integrated_control import (
    ControlDispatchFence, ControlStopHistory, ControlStopIngress, ControlStopReconcile,
    ControlStopReference, ControlStopSnapshot, ControlStopUnitResult,
)
from fleet.server.control_stop_schema import ensure_schema


_UNRESOLVED_SQL = "('PENDING','SENDING','UNKNOWN','PARTIAL')"


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _actor(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 96:
        raise ValueError("CONTROL_STOP_NAMED_ACTOR_REQUIRED")
    return value


def _result(unit, state, *, dispatch=None, error=None):
    return ControlStopUnitResult(unit_id=unit, state=state, dispatch=dispatch,
                                 acknowledged_robots=0, unknown_robots=0, omx_state="UNKNOWN",
                                 physical_stop="UNVERIFIED", error=error).model_dump(mode="json")


def _state(results):
    states = {result["state"] for result in results}
    if states & {"PENDING", "SENDING", "UNKNOWN"}:
        return "UNKNOWN"
    if "PARTIAL" in states:
        return "PARTIAL"
    if len(states) == 1:
        return next(iter(states))
    return "RESOLVED"


@dataclass(frozen=True)
class StopAssignment:
    request: ControlStopIngress | None
    units: tuple[str, ...]

    def body(self):
        return dict(request=self.request.model_dump(mode="json") if self.request is not None else None,
                    units=sorted(self.units))


@dataclass(frozen=True)
class StopTicket:
    delivery_unit: str
    ticket: str


@dataclass(frozen=True)
class StopClaim:
    snapshot: ControlStopSnapshot
    tickets: tuple[StopTicket, ...]


def has_local_uncertainty(connection, unit_id=None):
    """Called inside the same Task rearm transaction; query errors must close rearm."""
    owner = " AND delivery_unit=?" if unit_id is not None else ""
    return connection.execute(
        "SELECT 1 FROM fleet_control_stop_deliveries WHERE kind='LOCAL'" + owner
        + f" AND state IN {_UNRESOLVED_SQL} LIMIT 1",
        (unit_id,) if unit_id is not None else ()).fetchone() is not None


class ControlStopStore:
    def __init__(self, task_store, *, unit_id, config_revision):
        self.tasks, self.unit_id, self.config_revision = task_store, unit_id, config_revision
        with closing(self.tasks._connect()) as connection:
            ensure_schema(connection)

    @contextmanager
    def _connection(self, *, write=False):
        with closing(self.tasks._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()

    @staticmethod
    def _row(connection, origin, stop_id):
        row = connection.execute("SELECT * FROM fleet_control_stops WHERE origin_id=? AND stop_id=?",
                                 (origin, stop_id)).fetchone()
        if row is None:
            raise KeyError("CONTROL_STOP_NOT_FOUND")
        return row

    @staticmethod
    def _deliveries(connection, origin, stop_id):
        return connection.execute(
            "SELECT * FROM fleet_control_stop_deliveries WHERE origin_id=? AND stop_id=? ORDER BY delivery_unit",
            (origin, stop_id)).fetchall()

    def _snapshot(self, connection, row):
        results = [result for delivery in self._deliveries(connection, row["origin_id"], row["stop_id"])
                   for result in json.loads(delivery["results_json"])]
        return ControlStopSnapshot(unit_id=row["unit_id"], origin_id=row["origin_id"], stop_id=row["stop_id"],
                                   target_unit=row["target_unit"], config_revision=row["config_revision"],
                                   results=sorted(results, key=lambda value: value["unit_id"]),
                                   revision=row["revision"])

    @staticmethod
    def _bump(connection, origin, stop_id):
        connection.execute(
            "UPDATE fleet_control_stops SET revision=revision+1,updated_at=? WHERE origin_id=? AND stop_id=?",
            (_now(), origin, stop_id))

    def claim(self, ingress, *, scope, assignments, actor_id):
        """Scope/topology/parent authorization is validated by the caller before this transaction."""
        ingress = ControlStopIngress.model_validate(ingress)
        actor_id = _actor(actor_id)
        if ingress.config_revision != self.config_revision:
            raise ValueError("CONTROL_STOP_CONFIGURATION_CHANGED")
        scope = tuple(sorted(scope))
        if not 1 <= len(scope) <= 64 or len(set(scope)) != len(scope):
            raise ValueError("CONTROL_STOP_INVALID_SCOPE")
        covered = {self.unit_id} if self.unit_id in scope else set()
        assigned = {}
        for child, assignment in assignments.items():
            request = assignment.request
            units = set(assignment.units)
            if (child == self.unit_id or not units or len(units) != len(assignment.units)
                    or covered & units or not units <= set(scope)):
                raise ValueError("CONTROL_STOP_INVALID_ASSIGNMENT")
            fences = {unit: fence for unit, fence in ingress.expected_controls.items() if unit in units}
            if request is None and fences:
                raise ValueError("CONTROL_STOP_MISSING_ASSIGNMENT")
            if request is not None and (
                    request.origin_id != ingress.origin_id or request.stop_id != ingress.stop_id
                    or request.config_revision != ingress.config_revision or request.target_unit not in units
                    or request.expected_controls != fences):
                raise ValueError("CONTROL_STOP_INVALID_ASSIGNMENT")
            covered.update(units)
            assigned[child] = assignment.body()
        if covered != set(scope):
            raise ValueError("CONTROL_STOP_INCOMPLETE_ASSIGNMENT")
        body = _json(dict(request=ingress.model_dump(mode="json"), scope=scope, assignments=assigned))
        origin, stop_id = ingress.origin_id, ingress.stop_id
        with self._connection(write=True) as connection:
            existing = connection.execute(
                "SELECT * FROM fleet_control_stops WHERE origin_id=? AND stop_id=?", (origin, stop_id)).fetchone()
            # Identity wins over current fences: a matching duplicate never gets another ticket.
            if existing is not None:
                if existing["body_json"] != body:
                    raise ValueError("CONTROL_STOP_IDENTITY_CONFLICT")
                return StopClaim(self._snapshot(connection, existing), ())
            pending = connection.execute(
                "SELECT COUNT(*) FROM fleet_control_stops s WHERE EXISTS (SELECT 1 FROM "
                "fleet_control_stop_deliveries d WHERE d.origin_id=s.origin_id AND d.stop_id=s.stop_id "
                f"AND d.state IN {_UNRESOLVED_SQL})").fetchone()[0]
            if pending >= 64:
                raise ValueError("CONTROL_STOP_UNRESOLVED_CAPACITY")
            connection.execute(
                "INSERT INTO fleet_control_stops VALUES (?,?,?,?,?,?,?,?,?)",
                (origin, stop_id, self.unit_id, self.config_revision, ingress.target_unit, body, actor_id, 1, _now()))
            tickets = []
            if self.unit_id in scope:
                expected = ingress.expected_controls.get(self.unit_id)
                fence = connection.execute(
                    "SELECT authority_epoch,generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
                current = ControlDispatchFence(**dict(fence)) if fence is not None else None
                state, ticket, dispatch = "NOT_REACHED", None, current
                if expected is not None and current is not None:
                    state = "STALE_FENCE"
                    if expected == current:
                        self.tasks._advance_dispatch_control_in(
                            connection, enabled=False, actor_id=actor_id, reason="CONTROL_UNIT_STOP",
                            release_pre_dispatch=True)
                        fence = connection.execute(
                            "SELECT authority_epoch,generation FROM fleet_dispatch_control "
                            "WHERE control_id=1").fetchone()
                        dispatch = ControlDispatchFence(**dict(fence))
                        if dispatch != ControlDispatchFence(authority_epoch=current.authority_epoch,
                                                            generation=current.generation + 1):
                            raise ValueError("CONTROL_STOP_LATCH_NOT_ADVANCED")
                        state, ticket = "SENDING", uuid4().hex
                local = StopAssignment(ingress, (self.unit_id,)).body()
                self._insert(connection, origin, stop_id, self.unit_id, "LOCAL", local, state, ticket,
                             [_result(self.unit_id, state, dispatch=dispatch)])
                if ticket is not None:
                    tickets.append(StopTicket(self.unit_id, ticket))
            for child, assignment in assigned.items():
                send = assignment["request"] is not None
                ticket = uuid4().hex if send else None
                state = "SENDING" if send else "NOT_REACHED"
                self._insert(connection, origin, stop_id, child, "CHILD", assignment, state, ticket,
                             [_result(unit, "PENDING" if send else "NOT_REACHED")
                              for unit in assignment["units"]])
                if ticket is not None:
                    tickets.append(StopTicket(child, ticket))
            snapshot = self._snapshot(connection, self._row(connection, origin, stop_id))
        return StopClaim(snapshot, tuple(tickets))

    @staticmethod
    def _insert(connection, origin, stop_id, unit, kind, assigned, state, ticket, results):
        connection.execute(
            "INSERT INTO fleet_control_stop_deliveries "
            "(origin_id,stop_id,delivery_unit,kind,assigned_json,state,ticket,results_json) VALUES (?,?,?,?,?,?,?,?)",
            (origin, stop_id, unit, kind, _json(assigned), state, ticket, _json(results)))

    def assigned(self, origin, stop_id):
        """Internal immutable projections; never expose these bodies as public history."""
        with self._connection() as connection:
            row = self._row(connection, origin, stop_id)
            return json.loads(row["body_json"])

    def snapshot(self, origin, stop_id):
        with self._connection() as connection:
            return self._snapshot(connection, self._row(connection, origin, stop_id))

    @staticmethod
    def _child_result(row, snapshot):
        snapshot = ControlStopSnapshot.model_validate(snapshot)
        assigned = json.loads(row["assigned_json"])
        request = assigned["request"]
        if request is None:
            raise ValueError("CONTROL_STOP_CHILD_NOT_REACHED")
        if (snapshot.unit_id != row["delivery_unit"] or snapshot.origin_id != row["origin_id"]
                or snapshot.stop_id != row["stop_id"] or snapshot.config_revision != request["config_revision"]
                or snapshot.target_unit != request["target_unit"]
                or {result.unit_id for result in snapshot.results} != set(assigned["units"])):
            raise ValueError("CONTROL_STOP_CHILD_RESULT_MISMATCH")
        results = [result.model_dump(mode="json")
                   for result in sorted(snapshot.results, key=lambda value: value.unit_id)]
        if (snapshot.revision < row["peer_revision"] or snapshot.revision == row["peer_revision"]
                and _json(results) != row["results_json"]):
            raise ValueError("CONTROL_STOP_CHILD_REVISION_CONFLICT")
        return results, snapshot.revision

    def finish(self, origin, stop_id, delivery_unit, ticket, result):
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_control_stop_deliveries WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (origin, stop_id, delivery_unit)).fetchone()
            if row is None or row["state"] != "SENDING" or row["ticket"] != ticket or ticket is None:
                return False
            if row["kind"] == "CHILD":
                results, peer_revision = self._child_result(row, result)
            else:
                result = ControlStopUnitResult.model_validate(result)
                before = json.loads(row["results_json"])[0]
                if (result.unit_id != self.unit_id or result.state not in {"ACKNOWLEDGED", "PARTIAL", "UNKNOWN"}
                        or result.model_dump(mode="json")["dispatch"] != before["dispatch"]):
                    raise ValueError("CONTROL_STOP_LOCAL_RESULT_MISMATCH")
                results, peer_revision = [result.model_dump(mode="json")], 0
            connection.execute(
                "UPDATE fleet_control_stop_deliveries SET state=?,ticket=NULL,results_json=?,peer_revision=? "
                "WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (_state(results), _json(results), peer_revision, origin, stop_id, delivery_unit))
            self._bump(connection, origin, stop_id)
        return True

    def observe_child(self, origin, stop_id, child, snapshot):
        """Persist validated GET readback only; grants no execution ticket or local reconciliation."""
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_control_stop_deliveries WHERE origin_id=? AND stop_id=? "
                "AND delivery_unit=? AND kind='CHILD'", (origin, stop_id, child)).fetchone()
            if row is None:
                raise ValueError("CONTROL_STOP_UNASSIGNED_CHILD")
            results, revision = self._child_result(row, snapshot)
            if revision == row["peer_revision"]:
                return self._snapshot(connection, self._row(connection, origin, stop_id))
            connection.execute(
                "UPDATE fleet_control_stop_deliveries SET state=?,ticket=NULL,results_json=?,peer_revision=?,"
                "original_json=CASE WHEN state IN ('UNKNOWN','PARTIAL') THEN COALESCE(original_json,results_json) "
                "ELSE original_json END WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (_state(results), _json(results), revision, origin, stop_id, child))
            self._bump(connection, origin, stop_id)
            return self._snapshot(connection, self._row(connection, origin, stop_id))

    def fail(self, origin, stop_id, delivery_unit, ticket):
        """Record sender uncertainty without fabricating a child response or its revision."""
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT * FROM fleet_control_stop_deliveries WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (origin, stop_id, delivery_unit)).fetchone()
            if row is None or row["state"] != "SENDING" or row["ticket"] != ticket or ticket is None:
                return False
            results = json.loads(row["results_json"])
            for result in results:
                if result["state"] in {"PENDING", "SENDING"}:
                    result.update(state="UNKNOWN", error="DELIVERY_OUTCOME_UNKNOWN")
            connection.execute(
                "UPDATE fleet_control_stop_deliveries SET state='UNKNOWN',ticket=NULL,results_json=? "
                "WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (_json(results), origin, stop_id, delivery_unit))
            self._bump(connection, origin, stop_id)
        return True

    def recover(self):
        """Call once before accepting work at startup; unfinished sends are never replayed."""
        with self._connection(write=True) as connection:
            rows = connection.execute(
                "SELECT * FROM fleet_control_stop_deliveries WHERE state IN ('PENDING','SENDING')").fetchall()
            identities = set()
            for row in rows:
                results = json.loads(row["results_json"])
                for result in results:
                    if result["state"] in {"PENDING", "SENDING"}:
                        result.update(state="UNKNOWN", error="DELIVERY_OUTCOME_UNKNOWN")
                connection.execute(
                    "UPDATE fleet_control_stop_deliveries SET state='UNKNOWN',ticket=NULL,results_json=? "
                    "WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                    (_json(results), row["origin_id"], row["stop_id"], row["delivery_unit"]))
                identities.add((row["origin_id"], row["stop_id"]))
            for identity in identities:
                self._bump(connection, *identity)
        return len(rows)

    def pending_count(self):
        with self._connection() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM fleet_control_stops s WHERE EXISTS (SELECT 1 FROM "
                "fleet_control_stop_deliveries d WHERE d.origin_id=s.origin_id AND d.stop_id=s.stop_id "
                f"AND d.state IN {_UNRESOLVED_SQL})").fetchone()[0]

    def history(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT s.*,EXISTS (SELECT 1 FROM fleet_control_stop_deliveries d WHERE d.origin_id=s.origin_id "
                f"AND d.stop_id=s.stop_id AND d.state IN {_UNRESOLVED_SQL}) AS incomplete,"
                "EXISTS (SELECT 1 FROM fleet_control_stop_deliveries d WHERE d.origin_id=s.origin_id "
                f"AND d.stop_id=s.stop_id AND d.kind='LOCAL' AND d.state IN {_UNRESOLVED_SQL}) AS local_guard "
                "FROM fleet_control_stops s ORDER BY incomplete DESC,s.updated_at DESC,s.origin_id,s.stop_id LIMIT 100"
            ).fetchall()
            stops = [ControlStopReference(origin_id=row["origin_id"], stop_id=row["stop_id"],
                                          target_unit=row["target_unit"], config_revision=row["config_revision"],
                                          revision=row["revision"], incomplete=bool(row["incomplete"]),
                                          local_reconciliation_required=bool(row["local_guard"]),
                                          updated_at=row["updated_at"]) for row in rows]
        return ControlStopHistory(unit_id=self.unit_id, config_revision=self.config_revision, stops=stops)

    def reconcile(self, origin, stop_id, confirmation, *, actor_id, live_work):
        """Caller holds its live-work lock and supplies a callback that checks actual send/thread futures."""
        confirmation = ControlStopReconcile.model_validate(confirmation)
        actor_id = _actor(actor_id)
        if confirmation.affected_units != [self.unit_id]:
            raise ValueError("CONTROL_STOP_LOCAL_RECONCILIATION_ONLY")
        with self._connection(write=True) as connection:
            self._row(connection, origin, stop_id)
            row = connection.execute(
                "SELECT * FROM fleet_control_stop_deliveries WHERE origin_id=? AND stop_id=? "
                "AND delivery_unit=? AND kind='LOCAL'", (origin, stop_id, self.unit_id)).fetchone()
            if row is None or row["state"] not in {"UNKNOWN", "PARTIAL"} or live_work(origin, stop_id) is not False:
                raise ValueError("CONTROL_STOP_RECONCILIATION_REFUSED")
            fence = connection.execute(
                "SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            if fence is None or fence["generation"] != confirmation.expected_generation:
                raise ValueError("CONTROL_STOP_RECONCILIATION_FENCE_CHANGED")
            results = json.loads(row["results_json"])
            for result in results:
                result["state"] = "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
            connection.execute(
                "UPDATE fleet_control_stop_deliveries SET state='SUPERSEDED_BY_OPERATOR_RECOMMISSIONING',"
                "ticket=NULL,original_json=COALESCE(original_json,results_json),results_json=?,reconcile_json=?,"
                "reconciled_by=? WHERE origin_id=? AND stop_id=? AND delivery_unit=?",
                (_json(results), _json(confirmation.model_dump(mode="json")), actor_id, origin, stop_id, self.unit_id))
            self._bump(connection, origin, stop_id)
            return self._snapshot(connection, self._row(connection, origin, stop_id))
