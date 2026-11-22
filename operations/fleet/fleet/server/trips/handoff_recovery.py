"""Read-only recovery for a persisted lane-to-Nav2 handoff with unknown stop outcome."""

from core_common.protocol.native.operation import NativeOperation
from fleet.server.channel.execution.outcomes.evidence import exact_operation, safe_proof


async def stopped_handoff(client, scope, accepted_operation) -> bool:
    state = await client.state()
    velocity = state.get("velocity") or {}
    line = state.get("line_follow") or {}
    if (velocity.get("linear") != 0.0 or velocity.get("angular") != 0.0
            or line.get("mode") != "OFF" or state.get("mode") not in ("IDLE", "NAVIGATION", "EMERGENCY")):
        return False

    path = "/api/v1/navigation/state"
    if accepted_operation is not None:
        path += f"?run_id={accepted_operation['run_id']}"
    view = await client._get(path)
    if view.get("navigation") not in ("IDLE", "ARRIVED", "CANCELED", "FAILED"):
        return False
    owner = view.get("owner") or {}
    if "owner_run_id" not in owner or owner["owner_run_id"] is not None:
        return False

    body = view.get("operation")
    if body is not None:
        operation = (exact_operation(body, accepted_operation) if accepted_operation is not None
                     else NativeOperation.model_validate(body).model_dump(mode="json"))
        quiescent = safe_proof(view, operation)
        if operation["correlation_id"] == scope["correlation_id"]:
            return operation["kind"] == "navigate" and quiescent
        if not quiescent:
            return False
    elif accepted_operation is not None or view.get("lookup") != "UNKNOWN":
        return False

    # No matching native receipt: IDLE plus revoked lane authority closes the old admission path.
    return (state.get("mode") == "IDLE"
            and (state.get("trip_lease") or {}).get("lease_id") != scope["lease_id"])
