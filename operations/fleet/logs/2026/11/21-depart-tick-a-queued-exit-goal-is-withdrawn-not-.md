## 2026-11-21 · uncommitted · depart_tick: a queued exit goal is withdrawn, not SENT

- 변경: depart_tick records SENT only for an accepted goal; a Fleet-queued goal (not LOCALIZED, traffic) is removed with FleetConsole.discard_queued_goal (plus console.cancel when a CORE goal may be live) and the record stays SENDING/GOAL_QUEUED_NOT_ACCEPTED, re-checked every tick
- 증거: operations/fleet/test/test_unload_release.py 11 passed (3 new: queued withdrawn not SENT, arm unfold between ticks sends nothing, attempted dispatch cancelled)
- gate 변화: Safety-Review pending robot-08 coordinator (panel7)
- 결정: 없음
- 교훈: 없음
