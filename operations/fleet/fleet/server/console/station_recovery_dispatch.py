"""D-1029: an approved station recovery request starts one low-battery charge return (default off).

No new driver: the return is an ordinary Fleet trip to the bay's place, planned by the trip plan path and run by
``TripRunner`` with the CORE trip lease opened with ``purpose: "charge_return"``. The trip converts its free goals
into the robot's frame and refuses without a measured map pose, exactly as any trip does. Arrival ends the trip (the
runner halts the robot and releases the lease), then a person is asked to plug in. Any other end is recorded as the
reason. A robot with a trip, claim or console motion is refused by the trip start's own guards.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import HTTPException

from core_common.person_request_text import DEFAULT_TTL_S
from fleet.server.trip_ports import OPEN, TripError

logger = logging.getLogger(__name__)
PURPOSE = "charge_return"
RETRY_S = 60.0   # a finished return (arrived or failed) is not started again for this long


class ChargeReturns:
    def __init__(self, app, robots, monotonic=time.monotonic) -> None:
        self._app, self._robots, self._mono = app, robots, monotonic
        self.rows: dict[str, dict] = {}   # robot_id -> {state: returning|arrived|failed, bay, trip_id, reason, ...}

    def returning(self) -> bool:
        return any(row["state"] == "returning" for row in self.rows.values())

    def view(self, robot_id: str) -> Optional[dict]:
        row = self.rows.get(robot_id)
        return None if row is None else {k: v for k, v in row.items() if k != "ended"}

    def _record(self, robot_id: str, by: str, row: dict) -> dict:
        self.rows[robot_id] = row
        maps = getattr(self._app.state, "site_maps", None)
        if maps is not None:
            maps.record_event("station_recovery_return", by, {"robot_id": robot_id, **self.view(robot_id)})
        return self.view(robot_id)

    def _failed(self, robot_id: str, by: str, bay, reason, trip_id=None) -> dict:
        logger.warning("station recovery: %s return to %s did not run: %s", robot_id, bay, reason)
        return self._record(robot_id, by, {"state": "failed", "bay": bay, "trip_id": trip_id, "by": by,
                                           "reason": reason, "ended": self._mono()})

    async def start(self, answer: dict, by: str) -> dict:
        """Plan and start the return for an approved answer; the row says ``returning`` or why not."""
        robot_id, bay = answer["robot_id"], answer["bay"]
        old = self.rows.get(robot_id)
        if old is not None and (old["state"] == "returning" or self._mono() - old["ended"] < RETRY_S):
            return self.view(robot_id)   # one return per robot at a time, and no retry loop
        # Held before the first await: the auto tick and a person's approve cannot both start one.
        self.rows[robot_id] = {"state": "returning", "bay": bay, "trip_id": None, "by": by, "reason": None,
                               "ended": None}
        from fleet.server.trip_routes import TripRequest   # late: the routes module pulls in the whole trip stack
        state = self._app.state
        runner, plan = getattr(state, "trip_runner", None), getattr(state, "trip_plan", None)
        if runner is None or plan is None or not runner.lease.required:
            return self._failed(robot_id, by, bay, "trip_lease_off" if runner is not None else "no_trip_runner")
        try:
            planned = await plan(robot_id, TripRequest(to=bay), by)   # no measured pose: refused here, nothing sent
            trip = await runner.start(planned["plan_id"], by, purpose=PURPOSE)
        except HTTPException as exc:
            return self._failed(robot_id, by, bay, (exc.detail or {}).get("code") or str(exc.status_code))
        except TripError as exc:
            return self._failed(robot_id, by, bay, exc.code)
        except Exception as exc:  # noqa: BLE001 - recorded, never raised into the approval or the bay loop
            logger.exception("station recovery return of %s", robot_id)
            return self._failed(robot_id, by, bay, type(exc).__name__)
        except BaseException:  # cancelled mid-start: never leave the placeholder row holding every robot
            self._failed(robot_id, by, bay, "cancelled")
            raise
        return self._record(robot_id, by, {"state": "returning", "bay": bay, "trip_id": trip["trip_id"], "by": by,
                                           "reason": None, "ended": None})

    async def poll(self) -> None:
        """Settle each open return from its trip: arrived asks a person, any other end is the reason."""
        runner = getattr(self._app.state, "trip_runner", None)
        for robot_id, row in list(self.rows.items()):
            if row["state"] != "returning" or row["trip_id"] is None or runner is None:
                continue   # trip_id None: still starting
            try:
                view = runner.view(row["trip_id"]) or {"state": "missing", "reason": "TRIP_UNKNOWN"}
                if view["state"] in OPEN:
                    continue
                if view["state"] == "arrived":
                    await self._arrived(robot_id, row)
                else:
                    self._failed(robot_id, row["by"], row["bay"], view.get("reason") or view["state"],
                                 row["trip_id"])
            except Exception:  # noqa: BLE001 - one robot's settle must not stop the bay loop or the others
                logger.exception("station recovery: settling %s", robot_id)
                self.rows[robot_id] = {**row, "state": "failed", "reason": "settle_error", "ended": self._mono()}

    async def _arrived(self, robot_id: str, row: dict) -> None:
        reason, store = None, getattr(self._app.state, "person_requests", None)
        if store is None:
            reason = "no_person_request_store"
        else:
            record = store.create(robot_id=robot_id, kind="plug_charger", requested_by=row["by"],
                                  text=f"Charge me: plug in at bay {row['bay']}",
                                  why="Low battery: Fleet drove here", ttl_s=DEFAULT_TTL_S)
            try:
                await self._robots.put(robot_id, record)
                store.set_delivery(record["id"], "delivered")
            except Exception as exc:  # noqa: BLE001 - the person-request reconcile loop retries the open request
                store.set_delivery(record["id"], "not_delivered", type(exc).__name__)
                reason = "request_not_delivered"
        self._record(robot_id, row["by"], {**row, "state": "arrived", "reason": reason, "ended": self._mono()})
