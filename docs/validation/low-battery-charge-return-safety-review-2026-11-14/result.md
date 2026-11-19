# feat/low-battery-charge-return (D-1029): D-430 independent safety review

Date: 2026-11-14. Scope: the CORE 10 % deferral and 0.10 m/s cap under a `charge_return` trip lease, and the Fleet dispatch after station recovery approval. User decisions: 20 % start, 10 % deferral with the 5 % e-stop unchanged, stop at the bay and a person plugs in, 0.10 m/s.

## Reviewers

| Seat | Round 1 | Round 2 |
|---|---|---|
| Claude subagent (read-only) | BLOCK: 1 blocker, 1 major, 7 minor | PASS |
| opencode GLM 5.3 (read-only) | PASS: 1 major, 3 minor | — |

Codex was unavailable (usage limit until 2026-11-19).

## Findings and resolution

1. **BLOCK (fixed).** A person's e-stop during the return cleared the deferral, so releasing it left the robot unlatched between 10 % and 5 %. Fix: the deferral is kept while the pack stays at or below critical. It latches once the return has been inactive for 2 s and no other stop holds the robot. Test: `test_a_person_stop_during_the_return_keeps_the_deferral_until_it_is_released`.
2. **MAJOR (fixed).** A reading between two legs counted as the end of the return. Fix: the 2 s `INACTIVE_LATCH_S` debounce. Test: `test_a_reading_between_two_legs_does_not_end_the_return`. A BLOCKED robot still counts as active; a stuck trip ends through the Fleet stall check (default 20 s), which ends the lease.
3. **MAJOR (both reviewers, fixed).** A charge-return start was refused by trip admission at critical. Fix: `TripRunner.start` skips the battery check for `purpose == "charge_return"`, like a charge_session job. This is reachable only from `ChargeReturns`.
4. **MINOR (fixed).** A configured cap of 0, a negative value or NaN silently removed the cap. Fix: such values fall back to 0.10. Test: `test_a_bad_charge_return_speed_never_removes_the_cap`.
5. **MINOR (fixed).** An older CORE ignores `purpose`. Fix: Fleet requires the echoed purpose; otherwise it releases the lease with `TRIP_LEASE_PURPOSE_UNSUPPORTED`. Test added.
6. **MINOR (fixed).** The start race between the auto tick and a manual approve, an unguarded settle, and a cancelled start. Fix: a placeholder row before the first await, a per-robot guard on settle, and a cancelled start that fails its row. A race test was added.
7. **MINOR (kept).** Any operator token may set `purpose`. Any operator token can already open a trip lease and move the robot, and the deferral stays bounded by the 5 % e-stop. Follow-up.
8. **MINOR (kept).** One return at a time across the site (`another_returning`). This is D-721 S1's accepted rule.
9. **MINOR (kept).** The approval audit event says `started: false`. The separate `station_recovery_return` event records the real state.
10. **Integration (fixed by the lead).** The deferral checked `nav.fleet_goal()`, which is set only with a goal lease (off by default), so it would never fire. It now checks that navigation is in progress.

## Host evidence (remote, committed HEAD)

- CORE: `test_bridge_battery_policy.py` and `test_core_trip_lease.py`, 166 passed. Including `test_core_logic.py` and `test_api.py`, 278 passed earlier.
- Fleet: `test_station_recovery_dispatch.py`, `test_trip_lease.py` and `test_station_recovery.py`, 88 passed. With `test_person_requests.py`, 116 passed. Trip and CLI tests: 679 passed.

There is no device or site acceptance yet.
