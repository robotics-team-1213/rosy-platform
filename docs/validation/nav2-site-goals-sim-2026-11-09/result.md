# D-1003 Nav2 free goals in the robot map frame, Gazebo SIM, 2026-11-09

Evidence grade: **SIM only.** No robot was powered or driven.

Run 9 (commit `32222f0d70`, branch `feat/nav2-site-map-goals`) is the first run on the final head. Runs 1-8 are in the workspace record.

- Host: model PC through `remote_sim.py --host model --durable`, GPU render, sim slot lock `sim-32222f0d70-*`.
- Command: `python tools/remote/remote_sim.py --host model --durable --minutes 40 fleet_trips -- --nav --render gpu --stall-s 60`
- Bench frame: site map turned 90 deg and shifted (2, 3) m against the robot maps. Both robots LOCALIZED on `map` (confidence 0.96 and 0.99).

| Robot | Trip states | Moved | Short of the place | Result |
|---|---|---|---|---|
| rosy_01 | started, running, arrived | 0.327 m | 0.093 m | arrived |
| rosy_02 | started, running, arrived | 0.334 m | 0.086 m | arrived |

`[fleet-trips] PASS`, exit 0, no stall. Both stops are inside the 0.15 m free-arrival margin and Nav2's 0.10 m goal tolerance.

Logs: model PC `~/rosy-test/runs/sim-32222f0d70-8b0961-out/trips/` (`result.json`, `fleet.log`, `launch.log`, `api-log.jsonl`); copies in `Rosy/docs/workspace-records/2026-11-09/nav2-site-maps/sim-run9/`.

Not shown: real Pinky, a real SLAM map pairing, a map version with free edges.
