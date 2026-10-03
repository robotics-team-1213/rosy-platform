"""D-442 operator-delegated recovery of owner HOLD, separate from RearmLocal."""

from dataclasses import asdict
import sqlite3

from .local_stop import LocalStopBlocked


class OwnerRecoveryApi:
    def __init__(self, owner, stop, store, *, allowed_peer_uids, current_fence):
        self.owner, self.stop, self.store = owner, stop, store
        self.allowed_peer_uids = frozenset(allowed_peer_uids)
        self.current_fence = current_fence

    def dispatch(self, request, *, peer_uid):
        def error(status, code):
            return {"version": 1, "status": status, "error": {"code": code}}

        if type(peer_uid) is not int or peer_uid not in self.allowed_peer_uids:
            return error(403, "PEER_NOT_ALLOWED")
        config = self.owner.config
        base = {"version", "operation", "workcell_id", "instance_id"}
        operation = request.get("operation")
        expected = base if operation == "GetOwnerState" else base | {
            "authority_epoch", "dispatch_generation", "operator_confirmed", "observed_sequence", "actor_id"}
        if (type(request.get("version")) is not int or request["version"] != 1
                or set(request) != expected or operation not in {"GetOwnerState", "RecoverOwner"}):
            return error(400, "INVALID_REQUEST")
        if (request["workcell_id"], request["instance_id"]) != (config.workcell_id, config.instance_id):
            return error(404, "OWNER_NOT_FOUND")
        identity = {"workcell_id": config.workcell_id, "instance_id": config.instance_id}
        if operation == "GetOwnerState":
            return {"version": 1, "status": 200, **identity, "owner": self.owner.recovery_state()}
        actor = request["actor_id"]
        if (request["operator_confirmed"] is not True or not isinstance(actor, str)
                or not actor.strip() or actor != actor.strip() or len(actor) > 96
                or any(ord(char) < 32 for char in actor)
                or any(type(request[key]) is not int or request[key] < 0
                       for key in ("authority_epoch", "dispatch_generation", "observed_sequence"))):
            return error(400, "INVALID_REQUEST")
        epoch, generation = request["authority_epoch"], request["dispatch_generation"]
        try:
            decision = self.stop.run_if_open(
                authority_epoch=epoch, dispatch_generation=generation,
                fleet_fence_current=lambda: self.current_fence(epoch, generation) is True,
                operation=lambda: self.owner.recover(
                    operator_confirmed=True, observed_sequence=request["observed_sequence"],
                    recovery_fence=lambda clear: self.store.run_if_no_unresolved(
                        workcell_id=config.workcell_id, instance_id=config.instance_id, operation=clear)),
            )
        except (LocalStopBlocked, PermissionError):
            return error(409, "RECOVERY_FENCE_CLOSED")
        except (OSError, sqlite3.Error):
            return error(503, "RECOVERY_STORAGE_UNAVAILABLE")
        return {"version": 1, "status": 200 if decision.accepted else 409, **identity,
                "actor_id": actor, "observed_sequence": request["observed_sequence"],
                "decision": asdict(decision)}
