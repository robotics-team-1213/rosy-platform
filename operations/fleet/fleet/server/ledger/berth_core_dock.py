"""Fleet berth park through CORE's pink-line docking (D-1013, D-200; 2026-11-18 panel).

Fleet does not drive the robot here: it asks CORE to dock at the bay's dock id and reads
CORE's verdict. CORE owns the Nav2 staging, the tray-swept turn guard, the start inside the
bay row (stay still or leave straight) and the DOCKED decision (charge evidence). The dock pose
lives in the robot's own map frame (taught on the robot), so Fleet sends only the id.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Mapping, Optional

TERMINAL = frozenset({"DOCKED", "DOCK_FAILED", "UNDOCKED"})


async def execute_core_line_dock(console: Any, robot_id: str, spec: Mapping[str, Any], *,
                                 timeout_s: float = 420.0, poll_s: float = 0.5, max_bad_reads: int = 10,
                                 clock=time.monotonic, sleep=asyncio.sleep) -> Optional[dict[str, Any]]:
    clients = getattr(console, "_clients", None)
    client = clients.get(robot_id) if isinstance(clients, Mapping) else None
    http, headers = getattr(client, "_http", None), getattr(client, "_headers", None)
    if http is None or not callable(headers):
        return None

    async def call(method: str, path: str, body: Optional[dict] = None) -> tuple[int, dict]:
        resp = await http.request(method, path, json=body, headers=dict(headers()))
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {"text": resp.text[:160]}
        return resp.status_code, data if isinstance(data, dict) else {"body": data}

    try:
        code, started = await call("POST", "/api/v1/docking/dock",
                                   {"dock": spec["dock_id"], "correlation_id": f"berth-{uuid.uuid4().hex[:12]}"})
    except Exception as exc:  # noqa: BLE001 - the robot is unreachable: nothing moved
        return {"executed": False, "succeeded": False, "stop_reason": f"robot_unreachable: {exc}"}
    if code >= 400:
        return {"executed": False, "succeeded": False, "stop_reason": f"core_refused_{code}", "core": started}
    t0, status, phases, bad = clock(), started, [], 0
    while True:
        phase, state = status.get("phase"), status.get("state")
        if phase and (not phases or phases[-1] != phase):
            phases.append(phase)
        if state in TERMINAL:
            break
        if clock() - t0 > timeout_s or bad >= max_bad_reads:
            # Fleet's own deadline (or it lost sight of CORE): cancel CORE's action rather than
            # leave it running unwatched, and say plainly when even the cancel did not land.
            reason = "timeout" if bad < max_bad_reads else "status_unreadable"
            try:
                code, _ = await call("POST", "/api/v1/docking/cancel", {})
            except Exception:  # noqa: BLE001
                code = 0
            return {"executed": True, "succeeded": False,
                    "stop_reason": reason if 200 <= code < 300 else f"{reason}_cancel_failed",
                    "phases_executed": phases, "core": {k: status.get(k) for k in ("state", "dock_id", "error")}}
        await sleep(poll_s)
        try:
            code, read = await call("GET", "/api/v1/docking/status")
        except Exception:  # noqa: BLE001 - counted: CORE keeps its own guards meanwhile
            code, read = 0, None
        if 200 <= code < 300 and read:
            status, bad = read, 0
        else:
            bad += 1
    return {"executed": True, "succeeded": state == "DOCKED", "stop_reason": str(state).lower(),
            "phases_executed": phases, "core": {k: status.get(k) for k in ("state", "dock_id", "error", "retries")}}
