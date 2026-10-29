<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# omx

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Workstation development and simulation preparation for the OMX-AI workcell: a separate ROS 2 Jazzy OCI image built from an immutable ROBOTIS source lock, host-inventory placement preflight, and Gazebo/pilot probe scripts. It is not part of the Pinky Pi image and not an accepted field actuator runtime. The runtime profile stays disabled (no joint map, hardware plugin, serial or camera identity). Field control is one native systemd instance per workcell (D-246).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Current contract, host inventory, multi-workcell preflight, build and probe usage |
| `stack.lock.yaml` | Pins the official ROBOTIS source set to immutable revisions |
| `fetch_sources.py` | Fetches the locked sources into the build context |
| `Dockerfile`, `Dockerfile.pilot` | Workstation image and pilot-simulation image |
| `compose.yaml`, `entrypoint.sh` | Development container shell and entrypoint |
| `host_inventory.py`, `host-inventory.yaml.example` | Static `rosy.omx-host-inventory.v1` loader and a disabled placement template |
| `preflight.py` | Multi-workcell preflight over the host inventory |
| `run_pilot_sim.sh`, `probe_*.py`, `probe_*.sh` | Simulation and pilot probes (vendor owner, Fleet ROS vendor sim, pilot HTTP, pilot recording) |
| `cell_perception.py`, `cell-profile.example.json` | Cell profile (`rosy.omx-cell-profile.v1`: tray region, box colours, success references, home/transit, tolerances); top-view box centre/yaw, wrist-view box, and the start gate (arm home, box at the reference) before a taught cycle |
| `grasp_servo.py` | Probe-based wrist correction: a small jog per axis measures how the box moves in the wrist view, then pan/reach/roll steps from that response, with an oscillation guard |
| `arm_status_bridge.py` | Arm S positions to Fleet's `workcell-observations/arms/{source_id}`: reads `chunk-io/live.json` from `chunk_runner`, converts to radians, posts through `workcell_observation_bridge.ArmSender`. Read only; needs an arm S source and token in the Fleet manifest |
| `judge_seat.py` | Decision model between chunks: measured facts decide first (fault → park, no box → abort, no proceed without the next chunk's precondition); the model picks among the rest. Backend is any callable; `ollama()` for an Ollama `/api/chat` |
| `cell_pipeline.py`, `cell-pipeline.example.json` | One-arm cell pipeline: `run` resets the box to the start (coarse jaw map when there is no map), calibrates the tray and belt, then A/B cycles; each step is locate (fixed cameras fused) → plan → transfer (wrist hover check, soft-contact retreat) → verify, with the judge seat at every check and `cases.jsonl` for every check that did not pass. `--stage recover --person-at-switch` lifts clear after a guard stop |
| `cell_attempts.py` | One `attempts.jsonl` row per pick attempt or survey, passed or not (`rosy.omx-cell-attempt.v1`): box estimate, plan, each chunk's sent and measured joints, outcome with failed stage, and the code/config/map/choices it ran with; `summary` gives success, jaw offset and arm FK error by box position (also from older receipts) |
| `cell_survey.py` | `cell_pipeline --stage survey`: above the located box without descending, the jaws marked in the top view by closing and opening; the jaws' offset from the box (map plus arm) kept in the attempt row |
| `cell_observe.py` | Where the box is for the pipeline: per-surface detection, fixed cameras fused by their maps' errors, the wrist hover check, kept decision frames, flat-zone footprint check |
| `cell_calibration.py` | Per-surface affine pixel → arm map from points the arm placed, leave-one-out error, jaw marking by opening the fingers, parallax between heights |
| `cell_objects.py`, `object-catalog.example.json` | Objects in the arm S top view from a catalogue (`rosy.omx-object-catalog.v1`: green containers 1/2/3 cells of 30 mm, grasp spec, size tolerance): foreground by colour distance from the surface (any colour; lightness step for black/white), blobs measured in arm mm through the map with parallax from the top height, matched by width/length; a blob 2-3 widths wide is split along its long axis. No match = unmatched, never a grasp target. CLI prints JSON |
| `cell_auto_pick.py`, `cell_pivot.py` | `cell_auto_pick --config --catalog --roi --dest <site\|x,y> [--dry-run]`: observe → choose (catalogue-matched, not tangled, in view, plannable at 40 then 20 mm approach) → self-calibrate → grasp → place → verify → one `cell_attempts` row each. The jaws' closing axis is hidden from the top camera, so `gripper.closing_axis_offset_deg` (90 theory, 0 alternative) competes in `cell_choices` by held/empty/contact and a miss retries once with the better one; a square object is orientation-free. `cell_pivot`: jaw marking by the linkage change (two agreeing marks) and `pivot_calibrate`, which fits the circle the mark traces over several yaws; its centre against the FK TCP is the map's bias, saved as `<map>.bias.json` and subtracted from located points. Aborts (park, then stop) on runner fault, 55 C, a joint at 80 % of its own session cap (caps file, per joint) and not moving for 1.5 s, or stale state; dry-run moves nothing. Test `test/test_omx_cell_auto_pick.py` |
| `cell_knowledge.py`, `cell-knowledge.example.json` | What the cell has learned (`rosy.omx-cell-knowledge.v1`: id, topic, statement, verified/partial/unverified, evidence, `applies_when`). `select()` gives the judge seat verified and partial entries for the next step as background in its prompt; the decision row and every attempt row (`context.knowledge_sha`) name the knowledge used. Config `knowledge` points at a file; measurement still vetoes first |
| `cell_params.py`, `cell-params.example.json` | The cell's decided thresholds as one file (`rosy.omx-cell-params.v1`: per value `value`, `unit`, `source` measured/taught/theory/tuned/default, `evidence`); the loader (stdlib) refuses an unknown name, wrong unit/type or out-of-range value and returns every value with the shipped default as fallback, so no file behaves as before. Config `params_path` (cell_auto_pick, cell_pipeline) and `chunk_runner --params` / `record_session --chunks --params` feed `cell_objects`, `cell_pivot`, `cell_auto_pick` and `chunk_runner`; `context.params_sha` of every attempt row and `params_sha` of every judge decision say which values ran. Auto pick sites must state `surface_z` (grasp height = catalogue top - `auto.grasp_depth_m`); a site `z` below surface + depth is refused. Test `test/test_omx_cell_params.py` |
| `cell_decisions.py`, `decisions.example.jsonl` | One `rosy.omx-cell-decision.v1` row per auto-pick decision point in `work_dir/decisions.jsonl` (target chosen/refused per object, bias region reused or pivot, closing-axis candidate with its ledger, safety abort with rule/joint/value/limit, retry or stop, verify verdict), linked to `attempts.jsonl` by `attempt_id` and carrying knowledge ids, params digest and code revision. A person's correction is a row (`note --stage --text [--supersedes]`). `export` joins outcomes into training/context examples labelled validated_by_outcome / corrected_by_person / unvalidated (verified and partial knowledge only); `export --context` prints the digest `judge_seat.Seat(context=decisions.jsonl)` takes as background (config `decision_context`; measurement still vetoes). No file started, old behaviour. Tests in `test/test_omx_cell_auto_pick.py` |
| `cell_choices.py` | Competing values (taught, measured, sim) with their real outcomes; the best record for the purpose is used, the others kept |
| `cell_record.py` | `cell_pipeline --stage record`: one located A/B cycle recorded through `record_session --replay` in its own run folder, each episode labelled held/empty from the recorded jaws, the reset checked by the top camera |
| `cell_cases.py`, `cell_case_suite.py` | Problem cases of the cell as simulator scenarios: the real stops (`REAL`) and every `cases.jsonl` row with a `scene`; the suite replays each as an Isaac `arm-s-cell-case` run on the model PC and says which still match the real outcome (known Isaac gaps reported as such). Exit 1 before the real arm repeats a case that no longer matches. `cell_cases.py --aim-sweep`: candidates with the pick aimed 0-15 mm off the box along and across the jaw yaw, to measure the grasp tolerance |
| `isaac_cell_frames.py` | The cell's top-down chunk plan aimed at the Isaac scene's box and place point, every 30 fps frame kept (`rosy.omx-isaac-cell-frames.v1`), for the Isaac run worker |
| `motion_profile.py` | Smooth joint-space motion under the guard's limits: synchronised trapezoids, blended corners (overlap capped), exact rest points; `retime` eases a planner's IK path in and out |
| `teach_trajectory.py`, `lerobot_plugins/` | From taught leader episodes: a replay trajectory (A/reset/B), a median standard cycle, or a chunk library; `rosy_replay` LeRobot teleoperator for `record_session.py --replay` |
| `chunk_runner.py` | Scripted-teacher executor under `record_session.py --chunks`, every action through `guarded_native` teacher mode; chunk frames no faster than `teach_trajectory.GUARD_UNITS_PER_S`; `load <library>` swaps plans while holding; a soft contact in descend/grasp/release holds with torque on and `retreat` backs up the same path; `grip` never below the taught closed value: taught chunks one at a time with torque held, judge commands over a FIFO (`run [rel]`, multi-joint `jog`, `grip`, `park`), grasp outcome from jaw position and current, stops on following error, load-bearing PWM at the cap, or temperature |
| `cell_check.py` | Read-only one-arm cell verdict before motion: boards, follower torque/error/voltage/caps via `register_probe.py`, camera readiness; each failure names its fix |
| `joint_tune.py` | Follower joint commissioning (IDs 11-16): bounded move of one joint (sag check at torque ON), gripper sweep of its ends; temporary limits/gains, always torque OFF and restored, camera frames per settled position |
| `record_session.py` | One leader→follower LeRobot record/teleoperate session: follower caps raised only for the run, camera services handed over and back, always torque OFF and caps restored |
| `leader_actuator.py` | Drive the Leader as a commanded reference arm under an explicit hands-off attestation: caps raised with torque OFF and read back, Follower-alignment rate, load and hardware-error stops, torque OFF and the found caps restored on every exit (D-846) |
| `two_arm_config.py` | Configuration, Follower caps and gains, Leader gravity bias and the pose/bus helpers shared by the pipeline: schema check, per-arm bus ownership, saved-then-restored servo state (D-846, D-847) |
| `two_arm_pipeline.py` | D-846 two-arm pipeline: `preflight`/`gap`/`park`/`align`/`drive`/`verify` stages, per-stage JSON receipts, a blocked-joint load diagnosis, and the Follower mirroring the Leader's relative motion through the existing follower guard |
| `task-card.example.yaml` | Task card template (`rosy.omx-task-card.v1`): task text, episode timing, dataset name and design; plugged in with `record_session.py --task-card` |
| `omx_autoupdate.py`, `rosy-omx-autoupdate.{service,timer}`, `omx-autoupdate.json.example` | Native release updater for the cell's tools: newest main with green `ci-result`, unpacked to `~/rosy-omx/releases/<sha12>`, `current` switched atomically only while idle (no session lock, devices free, follower torque OFF), smoke check and rollback. `"kind": "service"` runs the same steps for a host service (AI PC rosy-situation, D-805): config paths/smoke, optional lock, unit restart + health check |
| `requirements-cell.lock` | Exact package set of the verified cell venv (LeRobot 0.4.4, CPU torch); omx_autoupdate.py builds one venv per hash of it |
| `requirements-lerobot-export.txt` | Python deps for demonstration export |
| `sim_reach_task.py`, `sim/reach_task.example.json` | `rosy.omx-sim-reach-task.v1` reach-task validator, seeded start sampling, greedy jog plan and readback judge (stdlib; shared with batch export and the evaluator) |
| `sim_reach_teacher.py` | Scripted SIM teacher over Pilot HTTP: unrecorded reset, recorded greedy jogs, automatic `task_outcome` from joint readback, lease renewal, no goal retry; writes `rosy.omx-sim-reach-teacher-results.v1`. Test `test/test_omx_sim_reach_teacher.py` |

## Arm S carry: modules in run order

One file per step; a step that a parameter turns off returns None and the carry runs without it. Change a step in its own module, never in `cell_auto_pick` (it only orders them; under 600 lines).

| Step | Module | Turned off by |
|---|---|---|
| Before a run | `cell_preflight` (camera shift, other sessions), `cell_calibrate check/auto` (remap, pivot, surface touch; moving steps need `--commissioning --person-at-switch`) | — |
| Look and choose | `cell_objects` (catalogue), `cell_auto_pick.choose` (finger gaps, yaw candidates, plan) | — |
| Location correction | `cell_calibrate.self_calibrate` (pivot near the target, or over it), `cell_pivot` (bias regions), `learn_bias` (from a confirmed place) | `calibrate.bias_near_mm`, `pivot.over_target` |
| D-911 gate | `cell_transfer.Gate` (every command `checked`; each re-plan assessed) | never |
| Hooks, assembled | `cell_hooks.pick_hooks` | — |
| Above the box | `cell_reach` (FK feed-forward) → `cell_wrist_ref` (reference servo) → `cell_fingers` (finger servo) → `cell_wrist` (calibrated band) | `reach.enabled`, `wrist.ref_servo`, `wrist.finger_servo`, `wrist.enabled` |
| After the descent | `cell_pinch` (box between the pads at grasp height; mount signature) | `pinch.enabled` |
| Empty grasp | `cell_feel` (shifted along the closing axis) | `feel.enabled` |
| Carry and place | `cell_transfer.transfer_folded` (fold home between lift and place) | `auto.fold_before_transport` (0: `cell_pipeline.SEQUENCE`) |
| After | `cell_auto_pick.verify_placed`, `cell_attempts`, `cell_decisions`, `episode_recorder`; on a failure `cell_diagnose` (cause from the contact height, strategy table) | — |
| Roles and tasks | `cell_role` (rescue/load/retrieve; automatic, so held by D-911 until reviewed), `cell_task_runner` (move/swap queue) | — |
| Camera geometry | `cell_checkerboard` (intrinsics, gripper-down hand-eye, pixel → plane); not in the pick path yet | — |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `patches/` | Source patches applied on top of the locked ROBOTIS sources (action-only, sim gates, headless Gazebo) |
| `sim/` | Simulation cell profile (`cell_profile.yaml`) |

## For AI Agents

### Working In This Directory

- Keep OMX inputs here; do not move them under `pinky_pro/` and do not add ARM64 product-image content.
- Change `stack.lock.yaml` only to another immutable revision; never a branch name.
- Do not enable a runtime profile or invent joint, serial, or camera identities. Those need device acceptance first.
- Example/template files must stay free of real hosts, addresses, and credentials (public repo).

### Testing Requirements

```bash
python3 -m pytest test/test_omx_workstation.py test/test_omx_host_inventory.py \
  test/test_omx_multi_preflight.py test/test_omx_vendor_stack_lock.py -q
python3 -m pytest test/architecture/test_document_placement.py -q
```

### Common Patterns

- Static YAML contracts with a schema id (`rosy.omx-host-inventory.v1`) validated by a loader, checked by the tests above.
- Evidence from probe runs goes to `docs/validation/`, not here.

## Dependencies

### Internal

- `src/products/omx/` (adapter and packages), `docs/plans/2026-09-26-omx-ai-workstation-runtime.md`, `docs/plans/2026-09-26-site-host-placement-design.md`

### External

- ROBOTIS `open_manipulator` ROS 2 packages (pinned), ROS 2 Jazzy, Docker/OCI, Gazebo for sim probes
