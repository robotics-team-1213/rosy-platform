"""D-1016 idle-removal marking facts for the enrollment listing — pure, shown only.

Deactivation stays the pairing-token expiry and unenrollment stays a named operator's
call (D-456); this module only derives ``removal_pending`` display facts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

#: An enrolled robot with no accepted CORE event and no register write for this long
#: is shown removal-pending.
IDLE_REMOVAL_S = 30 * 86400.0


class IdlePolicy:
    """Last-activity facts per listing row — a CORE event beats a register write."""

    def __init__(self, last_activity: Callable[[], dict[str, str]] | None = None,
                 idle_removal_s: float = IDLE_REMOVAL_S) -> None:
        #: robot_id -> ISO `received_at` of the last accepted CORE event (None = no events DB).
        self._last_activity = last_activity
        self._idle_removal_s = idle_removal_s

    def facts(self, rows: list[dict], now: float) -> dict[str, dict]:
        raw = self._last_activity() if self._last_activity is not None else None
        events = {robot_id: datetime.fromisoformat(at).timestamp()
                  for robot_id, at in (raw or {}).items()}
        facts: dict[str, dict] = {}
        for row in rows:
            # A stamp from the future is not evidence of activity: register stamps come
            # from the store's own clock, so anything past `now` (+1 s skew) is ignored.
            stamps = [v for v in (events.get(row["robot_id"]),
                                  row.get("updated_at") or row.get("created_at"))
                      if v is not None and v <= now + 1.0]
            last = max(stamps) if stamps else None
            facts[row["robot_id"]] = {
                "last_activity_at": last,
                "days_idle": int((now - last) // 86400) if last is not None else None,
                "removal_pending": last is not None and now - last >= self._idle_removal_s,
            }
        return facts
