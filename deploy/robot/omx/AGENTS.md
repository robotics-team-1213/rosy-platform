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
| `omx_incident.py` | D-971: at a session's end measures the incident (latched motors, torque, fold, wind-up, caught jaws), keeps the one allowed device reboot, and reports to Fleet (`arms/{source_id}/incidents`, `.../hold`); unsent reports in `incidents/outbox/`, local hold only as the offline copy. Needs `ROSY_WORKCELL_OBSERVATIONS`, `ROSY_OBSERVATION_WORKCELL`, `ROSY_OBSERVATION_FLEET_URL`, `ROSY_OBSERVATION_CA_FILE` and the arm's `ROSY_ARM_*_TOKEN` in the shell that runs `record_session`. Clearing is Fleet's |
| `judge_seat.py` | Decision model between chunks: measured facts decide first (fault → park, no box → abort, no proceed without the next chunk's precondition); the model picks among the rest. Backend is any callable; `ollama()` for an Ollama `/api/chat` |
| `cell_pipeline.py`, `cell-pipeline.example.json` | One-arm cell pipeline: `run` resets the box to the start (coarse jaw map when there is no map), calibrates the tray and belt, then A/B cycles; each step is locate (fixed cameras fused) → plan → transfer (wrist hover check, soft-contact retreat) → verify, with the judge seat at every check and `cases.jsonl` for every check that did not pass. `--stage recover --person-at-switch` lifts clear after a guard stop |
| `cell_coordinate.py` | D-983: offline, reads files only. Two real carries through `omx_adapter.coordination`: the schedule, the barrier meets, and the time one after the other would take |
| `cell_two_arm.py` | Two arms moving at once on real sessions: the `omx_adapter.coordination` schedule gated on measured progress, one arm's failure stops the other, folds checked from where the arms stand, own-zone targets only. `--carry`: the whole folded carry per arm, the box in the sweep; on a failure each arm climbs out before folding. Commands go out `checked` under each arm's pinned profile, from home only. Needs `--commissioning --person-at-switch`; `--plan-only` moves nothing. |
| `cell_attempts.py` | One `attempts.jsonl` row per pick attempt or survey, passed or not (`rosy.omx-cell-attempt.v1`): box estimate, plan, each chunk's sent and measured joints, outcome with failed stage, and the code/config/map/choices it ran with; `summary` gives success, jaw offset and arm FK error by box position (also from older receipts) |
| `cell_survey.py` | `cell_pipeline --stage survey`: above the located box without descending, the jaws marked in the top view by closing and opening; the jaws' offset from the box (map plus arm) kept in the attempt row |
| `cell_observe.py` | Where the box is for the pipeline: per-surface detection, fixed cameras fused by their maps' errors, the wrist hover check, kept decision frames, flat-zone footprint check |
| `cell_calibration.py` | Per-surface affine pixel → arm map from points the arm placed, leave-one-out error, jaw marking by opening the fingers, parallax between heights |
| `cell_objects.py`, `object-catalog.example.json` | Objects in the arm S top view from a catalogue (`rosy.omx-object-catalog.v1`: green containers 1/2/3 cells of 30 mm, grasp spec, size tolerance): foreground by colour distance from the surface (any colour; lightness step for black/white), blobs measured in arm mm through the map with parallax from the top height, matched by width/length; a blob 2-3 widths wide is split along its long axis. No match = unmatched, never a grasp target. CLI prints JSON |
| `cell_auto_pick.py`, `cell_pivot.py` | `cell_auto_pick --config --catalog --roi --dest <site\|x,y> [--dry-run]`: observe → choose (catalogue-matched, not tangled, in view, plannable at 40 then 20 mm approach) → self-calibrate → grasp → place → verify → one `cell_attempts` row each. The jaws' closing axis is hidden from the top camera, so `gripper.closing_axis_offset_deg` (90 theory, 0 alternative) competes in `cell_choices` by held/empty/contact and a miss retries once with the better one; a square object is orientation-free. `cell_pivot`: jaw marking by the linkage change (two agreeing marks) and `pivot_calibrate`, which fits the circle the mark traces over several yaws; its centre against the FK TCP is the map's bias, saved as `<map>.bias.json` and subtracted from located points. Aborts (park, then stop) on runner fault, 55 C, a joint at 80 % of its own session cap (caps file, per joint) and not moving for 1.5 s, or stale state; dry-run moves nothing. Test `test/test_omx_cell_auto_pick.py` |
| `cell_knowledge.py`, `cell-knowledge.example.json` | What the cell has learned (`rosy.omx-cell-knowledge.v1`: id, topic, statement, verified/partial/unverified, evidence, `applies_when`). `select()` gives the judge seat verified and partial entries for the next step as background in its prompt; the decision row and every attempt row (`context.knowledge_sha`) name the knowledge used. Config `knowledge` points at a file; measurement still vetoes first |
| `cell_params.py`, `cell-params.example.json` | The cell's decided thresholds as one file (`rosy.omx-cell-params.v1`: per value `value`, `unit`, `source` measured/taught/theory/tuned/default, `evidence`); the loader (stdlib) refuses an unknown name, wrong unit/type or out-of-range value and returns every value with the shipped default as fallback, so no file behaves as before. Config `params_path` (cell_auto_pick, cell_pipeline) and `chunk_runner --params` / `record_session --chunks --params` feed `cell_objects`, `cell_pivot`, `cell_auto_pick` and `chunk_runner`; `context.params_sha` of every attempt row and `params_sha` of every judge decision say which values ran. Auto pick sites must state `surface_z` (grasp height = catalogue top - `auto.grasp_depth_m`); a site `z` below surface + depth is refused. Test `test/test_omx_cell_params.py` |
| `cell_params_web.py`, `cell_params_web.html` | Local page on the cell PC (127.0.0.1:8772, reach it over `ssh -L`) listing every `cell_params` value with its range, source and evidence. Vision thresholds and tolerances can be stepped and saved; guards, motion values and any new group or unit stay locked (`lock_reason`, an allow-list). A save needs a note, validates with `cell_params`, replaces the file atomically after appending the previous entries to `<file>.history.jsonl`, and is refused while `session.lock` is held or after the file changed. `--caps` / `--profile` add a read-only table of each follower motor's servo values and the layer that set them (`session_caps.servo_layers`, as `record_session` uses them). Test `test/test_omx_cell_params_web.py` |
| `cell_requests.py` | D-951 addendum 2026-11-09: requests to a person in the cell (`rosy.cell-request.v1`). A `measure` request names candidates with the value each predicts, a unit and a tolerance (refused when two candidates are within twice the tolerance); the answer is a reading and its verdict, the candidate within tolerance or `neither`, never a cell value. A `check` request lists steps and takes pass/fail. Store `ROSY_CELL_REQUESTS` (default `~/.local/state/rosy/cell-requests`): `<id>.json`, its image, `history.jsonl`; one answer per request, with who and when. `tools/sim/omx_real2sim.py request belt` opens the belt reading (G-30). Stdlib. Test `test/test_omx_cell_requests.py` |
| `cell_decisions.py`, `decisions.example.jsonl` | One `rosy.omx-cell-decision.v1` row per auto-pick decision point in `work_dir/decisions.jsonl` (target chosen/refused per object, bias region reused or pivot, closing-axis candidate with its ledger, safety abort with rule/joint/value/limit, retry or stop, verify verdict), linked to `attempts.jsonl` by `attempt_id` and carrying knowledge ids, params digest and code revision. A person's correction is a row (`note --stage --text [--supersedes]`). `export` joins outcomes into training/context examples labelled validated_by_outcome / corrected_by_person / unvalidated (verified and partial knowledge only); `export --context` prints the digest `judge_seat.Seat(context=decisions.jsonl)` takes as background (config `decision_context`; measurement still vetoes). No file started, old behaviour. Tests in `test/test_omx_cell_auto_pick.py` |
| `cell_choices.py` | Competing values (taught, measured, sim) with their real outcomes; the best record for the purpose is used, the others kept |
| `cell_record.py` | `cell_pipeline --stage record`: one located A/B cycle recorded through `record_session --replay` in its own run folder, each episode labelled held/empty from the recorded jaws, the reset checked by the top camera |
| `cell_cases.py`, `cell_case_suite.py` | Problem cases of the cell as simulator scenarios: the real stops (`REAL`) and every `cases.jsonl` row with a `scene`; the suite replays each as an Isaac `arm-s-cell-case` run on the model PC and says which still match the real outcome (known Isaac gaps reported as such). Exit 1 before the real arm repeats a case that no longer matches. `cell_cases.py --aim-sweep`: candidates with the pick aimed 0-15 mm off the box along and across the jaw yaw, to measure the grasp tolerance |
| `isaac_cell_frames.py` | The cell's top-down chunk plan aimed at the Isaac scene's box and place point, every 30 fps frame kept (`rosy.omx-isaac-cell-frames.v1`), for the Isaac run worker |
| `motion_profile.py` | Smooth joint-space motion under the guard's limits: synchronised trapezoids, blended corners (overlap capped), exact rest points; `retime` eases a planner's IK path in and out |
| `session_caps.py`, `omx-ai-follower-tuning.json` | `record_session --caps`: the model's servo tuning (`rosy.omx-servo-tuning.v1`, loaded elbow/wrist I gain with evidence) under the site caps file, the operating profile's `servo` on top (D-951 6); merged values keep the caps ranges and are restored at session end. The two-arm run (`two_arm_config.follower_gains`) takes the same model P/I under its config's `follower_gains`. Test `test/test_omx_session_caps_layers.py` |
| `teach_trajectory.py`, `lerobot_plugins/` | From taught leader episodes: a replay trajectory (A/reset/B), a median standard cycle, or a chunk library; `rosy_replay` LeRobot teleoperator for `record_session.py --replay` |
| `chunk_runner.py` | Scripted-teacher executor under `record_session.py --chunks`, every action through `guarded_native` teacher mode; chunk frames no faster than `teach_trajectory.GUARD_UNITS_PER_S`; `load <library>` swaps plans while holding; a soft contact in descend/grasp/release holds with torque on and `retreat` backs up the same path; `grip` never below the taught closed value: taught chunks one at a time with torque held, judge commands over a FIFO (`run [rel]`, multi-joint `jog`, `grip`, `park`), grasp outcome from jaw position and current, stops on following error, load-bearing PWM at the cap, or temperature |
| `runner_strain.py` | The runner's holds below the guard, split out at chunk_runner's 600-line cap: `strained` (a pushing joint's rising lag, a blocked wrist roll; chunks and jogs) and `shed` (while the guard's `held` freezes an overloaded joint, the XL430 lift and elbow step toward home at half guard speed, each stopping at its own lag; no wrist; park only after the release). Test `test/test_omx_chunk_runner.py` |
| `load_model.py`, `load_predict.py` | Before-motion load check: `load_model.py "<logs>" --out load-model.json` fits per arm (USB serial tail) the standstill PWM of shoulder_lift/elbow/wrist against gravity terms of the pitch angles from follower motor-health logs (fit and held-out error printed); `load_predict` judges a chunk library ok / risky (predicted hold >= `loadcheck.risky_share` of the cap) / unknown (pose outside the logged cells, never extrapolated). `chunk_runner --load-model` refuses a risky library at start and at every `load`; unknown only reported unless `loadcheck.refuse_unknown`. Cannot see a press (arm_b 13:27 was one): that stays with `joint_push`. Test `test/test_omx_load_predict.py` |
| `cell_step.py`, `cell_push.py --friction` | Physics experiments for `tools/sim/omx_sysid.py` (supervised, D-911: `--commissioning --person-at-switch`, else `--dry-run`): `cell_step` ramps each body joint alone `--units` (≤ 4, 1.8 deg each) out from the folded home and back at 0.85 of the guard speed, for the servo fit from the runner trace; `cell_push --friction` turns shoulder_pan alone through a tangential push and repeats it through air on the same path, for `omx_sysid.py friction` (container friction from the pan's PWM difference). Tests `test/test_omx_cell_step.py`, `test/test_omx_cell_push.py` |
| `cell_check.py` | Read-only one-arm cell verdict before motion: boards, follower torque/error/voltage/caps via `register_probe.py`, camera readiness; each failure names its fix |
| `device_inventory.py` | D-943 read-only bench inventory (by-id boards, observer-owned arms, cameras, calibration ids) and a Learning profile draft; opens no device, never guesses a board's arm. Served by the bench viewer as `/inventory.json` |
| `joint_tune.py` | Follower joint commissioning (IDs 11-16): bounded move of one joint (sag check at torque ON), gripper sweep of its ends; temporary limits/gains, always torque OFF and restored, camera frames per settled position |
| `record_session.py` | One leader→follower LeRobot record/teleoperate session: follower caps raised only for the run, camera services handed over and back, always torque OFF and caps restored |
| `bench_record.py` | D-943 bench page (127.0.0.1:8771): after the person confirms the power switch, stops torque-OFF observers and camera units, runs `record_session.py` unchanged, restores those units after `session.lock` is released, seals with `record_seal.py` only after exit 0 and `safe_end` |
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
| Look and choose | `cell_objects` (catalogue; objects by their own colour `object_mask` when config `objects.hsv` names it, else surface difference with shadows dropped; touching boxes split by `cell_split`), `cell_auto_pick.choose` (finger gaps, yaw candidates, plan) | `objects.split_touching`, `objects.drop_shadow` |
| Decision model | `cell_pick_judge` (orders only the candidates the measurement kept; -1 vetoes; no answer keeps the rule order) | absent config `decision_model` |
| Location correction | `cell_calibrate.self_calibrate` (pivot near the target, or over it), `cell_pivot` (bias regions), `learn_bias` (from a confirmed place) | `calibrate.bias_near_mm`, `pivot.over_target` |
| D-911 gate | `cell_transfer.Gate` (every command `checked`; each re-plan assessed) | never |
| Hooks, assembled | `cell_hooks.pick_hooks` | — |
| Above the box | `cell_reach` (FK feed-forward) → `cell_look` (top camera: jaws vs target in one image; also before a push) → `cell_wrist_ref` (reference servo) → `cell_fingers` (finger servo) → `cell_wrist` (calibrated band) | `reach.enabled`, `look.enabled`, `wrist.ref_servo`, `wrist.finger_servo`, `wrist.enabled` |
| After the descent | `cell_pinch` (box between the pads at grasp height; mount signature) | `pinch.enabled` |
| Empty grasp | `cell_feel` (shifted along the closing axis) | `feel.enabled` |
| Carry and place | `cell_transfer.transfer_folded` (fold home between lift and place) | `auto.fold_before_transport` (0: `cell_pipeline.SEQUENCE`) |
| After | `cell_auto_pick.verify_placed`, `cell_attempts`, `cell_decisions`, `episode_recorder`; on a failure `cell_diagnose` (cause from the contact height, strategy table); a stalled first lift lets go and rises (`cell_unwedge.release_and_rise`, supervised); every guard stop first keeps a frame per camera (`cell_hooks.stills`) and, with config `tip_view` (the surveyed camera and base poses), a crop around the FK jaw tip in the top and side frames (`cell_tip_view`); with config `evidence`, every camera about once a second through the carry and, at a stop, one hashed bundle of the seconds around it plus the trace's tail under `incidents/evidence/` (a finished pick descent once per carry as the control; `cell_evidence`, newest 200 per kind) | — |
| Going on after a failed attempt | `cell_recovery` (around `run_auto`: result and top camera name the cause, `cell_diagnose.RECOVERY` the action, each once per cause; push through `cell_align`, then a person; real outcomes reorder the table's actions through `cell_choices`, and what only a person could answer is listed as `unsolved`). `cell_why` reads the cause from the runner's trace (blocked, or too_fast/blocked against the same chunk's runs that met nothing — `work_dir/free_lag.json`, learned from every carry's trace on top of a seed — else undetermined: a joint that keeps moving looks the same in contact and in free motion; a slower retry of one plan, or one from another start at no higher speed, stopping at the same place is blocked, and settles the earlier unknown stops there), asks the decision model (config `why_model`) what the trace cannot tell and what evidence is missing (an arm cause it names, too_fast/blocked/snagged, stays advice: the row says unknown), and hands a cause unknown twice to a person. `cell_failure_scenarios` runs the failure scenarios and a cell's real failures in parallel with no arm | run `cell_auto_pick` alone |
| Roles and tasks | `cell_role` (rescue/load/retrieve; automatic, so held by D-911 until reviewed), `cell_task_runner` (move/swap queue) | — |
| Field trials | `cell_field` (carry, push search and push, jaw-mark probe, recover, snapshot: frames before and after, a side-by-side picture and a JSON report under `work_dir/field/`; moves only through the programs above) | — |
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
- A new real-arm plan (pose set, path or recovery) runs only after four checks, and one "agree" from a session that did not write it:
  1. collision along the whole path in sim at the measured cell;
  2. load along the whole path as tool output, not judgement: per-joint torque (gravity, the path's own acceleration and payload) against the session's actual per-ID caps from the caps file, not the datasheet; `load_predict` where the pose is inside its logged cells; flag at 50 % of a cap;
  3. what happens if it stops midway, and the recovery for that;
  4. the first real run approaches with the runner's strain watch live (jogs are watched from 03f71e3ebd, before that only chunks), and a script reads `state.fault` before each jog and never jogs past a hold.
  An unchanged rerun of a checked plan needs no new check. Why: on 2026-11-09 a hand-eye pose checked for collision only overloaded arm_a's XL330 wrist; the guard cut torque and the extended arm dropped onto its plate.

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
