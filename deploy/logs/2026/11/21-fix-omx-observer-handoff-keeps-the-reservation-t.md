## 2026-11-21 · uncommitted · fix(omx): observer handoff keeps the reservation, the group watch and the unit topic check

- 변경: observer_handoff no longer re-pids or re-times a live PID-less lease of the same owner (cell_arm_lease.claim keep_live); the _lead leader now stays until no live process but itself is in the group (zombies do not count, container PID 1 never reaps); run refuses a unit env whose ROSY_OBSERVER_TOPIC is not the bridge manifest's joint topic before stopping the observer
- 증거: plain-python checks of claim keep_live and group_members; new tests in test_omx_observer_handoff.py run only on the lab/CI Linux hosts (no pytest on this PC); lint 0 errors
- gate 변화: none; no safety_review path
- 결정: none
- 교훈: none
