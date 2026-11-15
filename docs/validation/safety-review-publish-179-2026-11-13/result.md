# D-430 §5 panel result for the 9 unreviewed safety commits on main 8b65ceaa0f (2026-11-13)

Panel: Claude subagent, Codex (codex exec read-only), opencode glm-5.3. Judge: robot-b3 (re-read the code).
Raw seat reports are kept in robot-b3's session scratchpad (not committed). Recorded here by robot-ec on fix/fleet-real-site-pose.

## Fixes required before the exempt entries (all in fix/fleet-real-site-pose)
1. berth_parking_routes.py POST /road-nav2: done in a56cd55043 (named operator, trip_refusal, no fallback/simulated_dispatch).
2. berth_parking_routes.py berth-park dispatch: same fail-open. Fixed in 394ab97c79 (single path, named operator, trip_refusal, mapped errors).
3. tools/harness/platform_parts.yaml safety modules (done in 4694d03c21): add
   operations/fleet/fleet/server/ledger/berth_parking_routes.py,
   middleware/drive/behaviors/docking/manager_helpers.py,
   operations/fleet/fleet/server/console/console_helpers.py,
   operations/overhead/rosy_vision/ingest_helpers.py
   (guards moved there by 93461496c6 / 973faf9de9; Codex: platform_parts.yaml :1143, :1191, :1224).

## Exempt entries (reason text; "commit" = full SHA)
- 01988565d47d4b97685bb95f9ceb184d1d1477e2: Independent 3-seat panel (Claude/Codex/opencode) 2026-11-13: road-nav2 route bypassed named-operator, trip_refusal and task ledger with fail-open simulated_dispatch; FAIL as landed. Requires fix a56cd55043 (single dispatch path, require_named_operator, trip_refusal, mapped errors) and its remote PASS. No device acceptance.
- 973faf9de9a0521b28d656dd339114689f52cf7c: Same panel: task_dispatch_routes.py change is a move of road-nav2 into berth_parking_routes.py with the same dependencies; berth-park dispatch had the same fail-open. Requires a56cd55043 plus the berth-park fix 394ab97c79 and berth_parking_routes.py in safety_modules. No device acceptance.
- 93461496c670442370f45fa8bd9ec4d3e8366cf5: Same panel: AST comparison shows pure split (docking manager 60/60 functions in manager_helpers.py; console _goal/snapshot to console_helpers.py re-bound at console.py:277-310, trip_refusal/stop paths unchanged; rosy_vision ingest 40/40). Requires the helper files added to platform_parts.yaml safety modules (4694d03c21). No device acceptance.
- ae7a2ed52c69bc1e10b90dc871e44d7180b922b7: Same panel, 3/3 PASS: safety node split into node_helpers.py mixin; motion limits, ultrasonic block, IMU hazards, localization zeroing and missing-transform fail-closed all retained and called from tick (node.py:59,254,324; node_helpers.py:408-441). Fleet change is import indirection only. No device acceptance.
- 65266a619409eaed6762a7b3cb5328c591f30165: Same panel, 3/3 PASS: cached joint/owner sets; per-joint position/velocity/acceleration limits checked in the same order with the same refusals (command_owner.py:227,277,303,314-332); UNKNOWN/HOLD kept in the coordinator active set. No device acceptance.
- 0b6d23e673dd139681476b9fd647f6f37fa78d90: Same panel, 3/3 PASS: commissioning ITEMS frozenset equivalent (commissioning_record.py:29,135); revision computed once with unchanged blockers (:248-254). No device acceptance.
- 2f5be653c2763d0fe96a2032535746caacf9f475: Same panel, 3/3 PASS: action API exact key sets and stop reasons identical as module frozensets (action_api.py:34-41); missing action readback still None (action_store_readback.py:67-75). No device acceptance.
- 3843a78258c3329d3af39aa8839cf38615a512ce: Same panel, 3/3 PASS: Dynamixel gate constants hoisted; joint limit pairs built inside the claim-releasing try and still checked before motion; _send still checks the fence first (dynamixel_port.py:83-103,199-209; dynamixel_motion.py:32-41). No device acceptance.
- 8fee68b17d74a2f055ee024290dcc07f6c9ff86b: Same panel, 3/3 PASS: final trajectory point comparison equivalent given unique names and exact key/length checks (command_types.py:221-226,262,273). No device acceptance.
