## 2026-11-21 · uncommitted · depart_tick: a queued exit goal is withdrawn, not SENT

- 변경: depart_tick records SENT only for an accepted goal; a Fleet-queued goal (not LOCALIZED, traffic) is removed with FleetConsole.discard_queued_goal (plus console.cancel when a CORE goal may be live) and the record stays SENDING/GOAL_QUEUED_NOT_ACCEPTED, re-checked every tick; the wait is bounded to DEPART_QUEUE_WAIT_S=120 s from queued_since, then HELD DEPART_WAIT_EXPIRED (operator re-arms)
- 증거: operations/fleet/test/test_unload_release.py 13 passed (5 new: queued withdrawn not SENT, arm unfold between ticks sends nothing, attempted dispatch cancelled, 119 s waits / 121 s HELD once, accept inside the window clears queued_since)
- gate 변화: Safety-Review robot-08 coordinator review approved fa9516e9ed with the 120 s wait bound (panel7)
- 결정: 없음
- 교훈: 없음
