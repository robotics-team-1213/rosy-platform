"""Per-operation peer roles for the workcell coordinator and the barrier UDS operations (D-780 §1, §3).

``ActionApi`` consults :class:`CoordinatorPeerApi` only when the owner has coordinator peers.
It answers the operations the coordinator may not use, the coordinator's reads that the Fleet
principal check would refuse, and ``GetBarrier``/``ReleaseBarrier``; every other request falls
through to the unchanged Fleet paths. Without this object nothing here runs.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from pydantic import ValidationError

from core_common.protocol.cell_transfer import FleetCellTransferGrant
from core_common.protocol.workcell_barrier import BarrierQuery, BarrierReleaseRequest, BarrierState

from omx_adapter.action_store import ActionStore

from .barrier_journal import BarrierJournal, BarrierRefused
from .barrier_supervisor import BarrierSupervisor

BARRIER_OPERATIONS = frozenset({"GetBarrier", "ReleaseBarrier"})
#: Fleet-only writes (D-780 §1): a coordinator UID is refused even with a valid grant.
FLEET_ONLY_OPERATIONS = frozenset({"SubmitAction", "CancelAction", "RecoverOwner", "RearmLocal"})
BARRIER_VERSION = 2
_UNRESOLVED = frozenset({"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"})
#: Only an Action that can still move may be released; HOLD, UNKNOWN and terminal ones are refused.
_RELEASABLE = frozenset({"SUBMITTING", "ACCEPTED", "RUNNING"})


def coordinator_principal(peer_uid: int) -> str:
    """D-780 1 principal name of an authenticated coordinator peer."""
    return f"coordinator-uid-{peer_uid}"


def _error(code: str, message: str, *, status: int, version: int) -> dict[str, Any]:
    return {"version": version, "status": status, "error": {"code": code, "message": message}}


class CoordinatorPeerApi:
    def __init__(self, store: ActionStore, journal: BarrierJournal, supervisor: BarrierSupervisor, *,
                 workcell_id: str, coordinator_peer_uids: set[int], fleet_peer_uids: set[int],
                 read_receipt: Callable[[str], Mapping[str, Any] | None],
                 fence_current: Callable[[int, int], bool]) -> None:
        self.coordinator_peer_uids = frozenset(coordinator_peer_uids)
        self.fleet_peer_uids = frozenset(fleet_peer_uids)
        if not self.coordinator_peer_uids or self.coordinator_peer_uids & self.fleet_peer_uids:
            raise ValueError("coordinator UIDs must be non-empty and distinct from Fleet UIDs")
        self.store, self.journal, self.supervisor = store, journal, supervisor
        self.workcell_id = workcell_id
        self.read_receipt, self.fence_current = read_receipt, fence_current

    def is_coordinator(self, peer_uid: int) -> bool:
        return type(peer_uid) is int and peer_uid in self.coordinator_peer_uids

    def route(self, api, request: Mapping[str, Any], *, peer_uid: int,
              version: int) -> dict[str, Any] | None:
        """A response for coordinator-specific handling, or None for the unchanged path."""
        operation = request.get("operation")
        if not self.is_coordinator(peer_uid):
            if operation not in BARRIER_OPERATIONS:
                return None
            code = "COORDINATOR_PEER_REQUIRED" if peer_uid in self.fleet_peer_uids else "PEER_NOT_ALLOWED"
            return _error(code, "only the workcell coordinator peer can use barriers",
                          status=403, version=version)
        self.supervisor.contact()
        if operation in FLEET_ONLY_OPERATIONS:
            return _error("COORDINATOR_NOT_ALLOWED", f"{operation} is a Fleet-only operation",
                          status=403, version=version)
        try:
            if operation == "GetAction":
                if set(request) != {"version", "operation", "action_id"}:
                    raise ValueError("GetAction contains unsupported fields")
                receipt = self.read_receipt(request["action_id"])
                if receipt is None:
                    return _error("ACTION_NOT_FOUND", "Action is unavailable", status=404, version=version)
                return api._success(version, receipt)
            if operation not in BARRIER_OPERATIONS:
                return None
            if version != BARRIER_VERSION:
                return _error("UNSUPPORTED_VERSION", "barrier operations use protocol version 2",
                              status=400, version=version)
            body = {key: value for key, value in request.items() if key not in {"version", "operation"}}
            if operation == "GetBarrier":
                return self._get(BarrierQuery.model_validate(body), version)
            return self._release(BarrierReleaseRequest.model_validate(body), version, peer_uid)
        except BarrierRefused as exc:
            status = 404 if exc.code == "BARRIER_NOT_IN_PLAN" else 409
            return _error(exc.code, str(exc), status=status, version=version)
        except KeyError:
            return _error("ACTION_NOT_FOUND", "Action is unavailable", status=404, version=version)
        except (TypeError, ValueError, ValidationError) as exc:
            return _error("INVALID_REQUEST", str(exc), status=400, version=version)
        except Exception:
            return _error("LOCAL_ACTION_ERROR", "barrier processing failed", status=500, version=version)

    def _grant(self, action: Mapping[str, Any]) -> FleetCellTransferGrant | None:
        request = action.get("request", {})
        payload = request.get("payload") if isinstance(request, Mapping) else None
        if not isinstance(payload, Mapping) or payload.get("action_kind") != "CELL_TRANSFER":
            return None
        return FleetCellTransferGrant.model_validate(payload)

    def describe(self, action: Mapping[str, Any]) -> dict[str, Any]:
        grant = self._grant(action)
        if grant is None:
            raise BarrierRefused("NOT_A_PAIRED_ACTION", "the Action carries no barrier plan")
        rows = self.journal.rows(grant.action_id, grant.attempt_id)
        barriers = []
        for barrier in grant.cell_transfer.barriers or ():
            row = rows.get(barrier.barrier_id) or {}
            barriers.append({**barrier.model_dump(mode="json"), "gated_phase": barrier.gated_phase,
                             "state": row.get("state", BarrierState.NOT_REACHED.value),
                             "arrived_at": row.get("arrived_at"), "released_at": row.get("released_at")})
        coupling, _ = self.supervisor.coupling_now(grant, rows)
        return {"action_id": grant.action_id, "attempt_id": grant.attempt_id,
                "workcell_id": grant.workcell_id, "instance_id": grant.instance_id,
                "arm_role": grant.arm_role, "pair_id": grant.pair_id,
                "partner_instance_id": grant.partner_instance_id, "coupling": grant.coupling,
                "coupling_now": coupling, "fence_open": self._fence_open(grant),
                "authority_epoch": grant.authority_epoch,
                "dispatch_generation": grant.dispatch_generation, "action_state": action["state"],
                "moved": bool(self.store.action_phases(grant.action_id, attempt_id=grant.attempt_id)),
                "barriers": barriers}

    def _get(self, query: BarrierQuery, version: int) -> dict[str, Any]:
        if query.action_id is not None:
            action = self.store.get_action(query.action_id)
            if action is None:
                raise KeyError(query.action_id)
            return {"version": version, "status": 200, "action": self.describe(action)}
        paired = []
        for action in self.store.unresolved_actions(workcell_id=self.workcell_id):
            grant = self._grant(action) if action["state"] in _UNRESOLVED else None
            if grant is not None and grant.pair_id is not None:
                paired.append(self.describe(action))
        return {"version": version, "status": 200, "actions": paired}

    def _fence_open(self, grant: FleetCellTransferGrant) -> bool:
        """Stop latch open and authority current at the grant's generation (D-780 3 check 4)."""
        try:
            return self.fence_current(grant.authority_epoch, grant.dispatch_generation) is True
        except Exception:
            return False

    def _release(self, release: BarrierReleaseRequest, version: int, peer_uid: int) -> dict[str, Any]:
        action = self.store.get_action(release.action_id)
        if action is None:
            raise KeyError(release.action_id)
        grant = self._grant(action)
        if grant is None or grant.pair_id is None or grant.pair_id != release.pair_id:
            raise BarrierRefused("PAIR_MISMATCH", "pair_id does not match this owner's grant")
        if not any(item.barrier_id == release.barrier_id for item in grant.cell_transfer.barriers or ()):
            raise BarrierRefused("BARRIER_NOT_IN_PLAN", "the barrier is not in this Action's plan")
        if (release.authority_epoch, release.dispatch_generation) != (
                grant.authority_epoch, grant.dispatch_generation):
            raise BarrierRefused("FENCE_STALE", "authority epoch or dispatch generation differs")
        row = self.journal.rows(grant.action_id, grant.attempt_id).get(release.barrier_id)
        if row is not None and row["state"] == BarrierState.RELEASED.value:
            return {"version": version, "status": 200, "barrier": row, "created": False}  # D-780 3 idempotent
        if action["state"] not in _RELEASABLE:
            raise BarrierRefused("ACTION_NOT_ACTIVE", "the Action can no longer be released")
        if not self._fence_open(grant):
            raise BarrierRefused("FENCE_STALE", "the stop or authority fence is not current")
        recorded, created = self.journal.release(
            grant.action_id, grant.attempt_id, release.barrier_id,
            release={"pair_id": release.pair_id, "coordinator": coordinator_principal(peer_uid),
                     "partner_arrival": release.partner_arrival.model_dump(mode="json")})
        return {"version": version, "status": 200, "barrier": recorded, "created": created}


__all__ = ["BARRIER_OPERATIONS", "BARRIER_VERSION", "CoordinatorPeerApi", "FLEET_ONLY_OPERATIONS",
           "coordinator_principal"]
