# Device-specific load assessment

Use `python -m omx_adapter.load_motion_cli` with explicit local JSON paths to save characteristics, compare candidate trajectories, or monitor an existing motor-health file. The package must be installed or its adapter directory on `PYTHONPATH`. There is no new service, bus reader, controller or motion endpoint.

Every report has `motion_admitted=false` and `automatic_recovery_enabled=false`. A selected candidate matches a measured load domain; collision, independent stop, runtime identity, task authority and final OMX owner admission remain separate required gates. No setting here changes a servo limit or gain. This implementation does not calculate unmeasured torque or generate new paths.

## Characteristics contract

`rosy.omx-motion-characteristics.v1` is a companion to the unchanged D-496 hardware profile. The authoritative parser is `omx_adapter.motion_characteristics.validate_characteristics`. The document contains:

| Field | Meaning |
|---|---|
| `schema`, `revision`, `status` | Schema identifier, operator-managed revision, `draft` or `measured`. Neither status grants authority. |
| `binding` | Exact `device_id`, `owner_id`, `motor_group`, `hardware_profile_revision`, `calibration_revision`, `robot_model_sha256`, `installation_revision`, `tool_revision`, `assist_mechanism_revision`. Owner and measured motor group are separate identities. Explicit `none` may identify absence of an assist mechanism; unknown is not absence. |
| `measured_at`, `evidence_ref` | ISO measurement date and evidence identifier. References are recorded, never opened as arbitrary file paths. They do not authenticate a measurement. |
| `joints` | Canonically sorted joint map. Each record has `motor_id`, `motor_model`, `raw_zero`, signed nonzero `rad_per_raw`, `position_rad`, `velocity_rad_s`, `acceleration_rad_s2`. Model geometry stays in the referenced model. |
| `monitor` | Positive `max_age_s`, `max_gap_s`, `tracking_duration_s`, `oscillation_window_s`, integer `oscillation_cycles`, and per-joint `error_rad`, `clear_error_rad`, `oscillation_amplitude_rad` under `joints`. Clear error must be below trigger error. |
| `envelopes` | Certified domains as described below; no interpolation between separately measured poses is implied. |

All numerical values use SI units, with temperature in degC and voltage in V. `actual_rad = (present_raw - raw_zero) * rad_per_raw`. The calibration and raw-to-radian conversion must be measured for the selected hardware; do not reuse an unrelated arm's conversion.

One envelope includes `id`, `evidence_ref`, per-joint `position_rad`, `max_velocity_rad_s`, `max_acceleration_rad_s2`, `payload_mass_kg` bounds, 3D `payload_com_min_m` and `payload_com_max_m` in the tool frame, common `temperature_c` and `voltage_v` bounds, `max_motion_s`, `max_hold_s`, integer `max_cycles`, `min_cycle_interval_s`, and `measured_tracking_error_rad`. The common thermal/electrical bounds apply to every configured joint. Envelope motion limits cannot exceed the joint limits. The measured domain must certify the entire stated region and operating conditions, including repetition; isolated successful points are insufficient evidence for a box.

The initial draft may have empty joints/envelopes and missing binding/measurement values:

```json
{
  "schema": "rosy.omx-motion-characteristics.v1",
  "revision": "draft-1",
  "status": "draft",
  "binding": {
    "device_id": null,
    "owner_id": null,
    "motor_group": null,
    "hardware_profile_revision": null,
    "calibration_revision": null,
    "robot_model_sha256": null,
    "installation_revision": null,
    "tool_revision": null,
    "assist_mechanism_revision": null
  },
  "measured_at": null,
  "evidence_ref": null,
  "joints": {},
  "monitor": null,
  "envelopes": []
}
```

Save validates before atomically replacing the destination and returns its canonical content SHA256:

```text
python -m omx_adapter.load_motion_cli save draft.json characteristics.json
```

Drafts cannot be assessed. A measured record must also match the independently accepted digest passed by its caller. Copying a digest from the save output does not establish physical acceptance. Approval and runtime composition stay with the existing owner and commissioning process. This path does not modify their approval state. No measured limits are supplied as product defaults.

## Request and candidate assessment

A `rosy.omx-load-request.v1` JSON request requires these exact fields:

| Field | Required value |
|---|---|
| `context` | Exact characteristics binding for this device/configuration. |
| `task_id`, `scene_revision` | Nonempty task and planning-scene provenance. Scene freshness and collision validity are still owner responsibilities. |
| `source_sequence`, `source_age_s`, `start_at_rest` | Current state sequence, original state age, explicit `true` rest assertion. These are input evidence, not a physical-rest proof. |
| `start_positions_rad`, `goal_positions_rad`, `goal_tolerance_rad` | Complete joint maps and positive joint-space goal tolerance. Cartesian/IK generation and tool orientation remain with the upstream planner. Candidates share this start and joint-space goal. |
| `payload_mass_kg` | Inclusive lower/upper bounds, including uncertainty. Unknown is rejected. |
| `payload_com_min_m`, `payload_com_max_m` | Three-coordinate bounds in the same tool frame used by the measured domain. |
| `temperatures_c`, `voltages_v` | Complete current joint maps. |
| `hold_s`, `cycle_count`, `cycle_interval_s` | Required final hold, intended bounded repetition and cycle interval in the same definition used during measurement. Previous work and thermal state must be accounted for by the caller. |
| `candidates` | Nonempty bounded list described below. |

Each candidate has exactly `id`, `joint_names` and `points`. Joint order is the lexicographic order of characteristics joint names. A point uses the existing `JointTrajectoryPoint` fields: positive strictly increasing `time_from_start_s`, plus full `positions`, `velocities`, and `accelerations` arrays. Initial derivatives are zero because this release requires a resting start. Final velocity/acceleration must be zero. Do not feed paths whose controller uses different interpolation semantics.

The evaluator converts each quintic Hermite segment into Bernstein control points. Their convex hull bounds position over the whole segment; derivative control points bound velocity and acceleration. Bounds can reject an otherwise feasible trajectory conservatively. A single certified envelope must cover the entire candidate, including the initial state and final pose/hold. This deliberately avoids extrapolation across unverified transitions. Repetition, mass/COM and environmental conditions are checked before ranking.

```text
python -m omx_adapter.load_motion_cli assess characteristics.json request.json --accepted-sha256 <accepted-content-hash> --output assessment.json
```

Every candidate records its exclusion reasons or matching envelope. Matching candidates rank by measured-domain tracking error, then duration, then candidate ID. Ranking is empirical; no torque margin is invented from PWM. `selected_candidate_id=null` means there is no matching candidate. Reports preserve the characteristics/request/trajectory hashes, configuration, task, scene and original state sequence. Collision status remains `not_checked`.

## Passive monitoring

The monitor consumes the existing `core_common.motor_health.read_motor_health_snapshot` output. It never opens a motor bus. The snapshot must contain the exact configured joints and motor IDs in the bound `motor_group`, the bound owner and pinned source session. Other groups in a multi-arm owner's snapshot are not treated as this arm. An idle observer that requires torque OFF must not run concurrently with an admitted writer; this tool starts neither and changes no ownership rule. A torque-OFF or unknown-torque snapshot produces a review recommendation, not an active-motion verdict.

The native owner's existing `MotorHealth` hook now publishes measured hardware-error and torque-enable fields using its already owned bus at the existing effort-hook cadence. It stops further reads after a known hard fault. The additional RAM reads require device timing acceptance before deployment; source tests do not prove the current 5 Hz cadence can resolve a requested vibration frequency. Legacy snapshots that omit the fields remain unconfirmed.

```text
python -m omx_adapter.load_motion_cli watch characteristics.json request.json --accepted-sha256 <accepted-content-hash> --health <absolute-existing-health-file> --candidate-id <candidate> --command-id <admitted-command-id> --session-id <existing-source-session-uuid> --started-at <command-start-epoch-seconds> --samples <bounded-poll-count> --interval-s <validated-poll-period> --output monitor.json
```

Command start and motor capture times must use the same source clock domain. `samples` bounds polling attempts, not the count of newly captured measurements. Re-reading the same still-fresh sample does not renew it or add oscillation evidence. Lost, stalled, regressing, gapped, terminal or mismatched observations latch `hold_for_owner_review`. The actual owner must enforce any stop; this tool only reports. A new monitor instance cannot serve as operator recovery for an owner HOLD.

`command_id`, start time and candidate are supplied by the caller. The current motor DTO does not carry an execution receipt or calibration/tool revisions, so reports explicitly mark `command_binding=caller_supplied_unverified`. Observing means comparison against the supplied reference, not proof that the owner is executing that trajectory or using that configuration. Runtime owner receipt/configuration binding must be added and accepted before using this analysis as an execution interlock.

Each motor is compared against the interpolated command at its own measurement time, using signed calibrated raw conversion. The snapshot's servo `command_raw` and absolute `error_deg` are not command references. Persistent error uses trigger/clear hysteresis. Oscillation requires repeated sign reversals beyond the configured per-side amplitude within the window; `max_gap_s` must resolve at least four samples per requested cycle. This is a sampled-error detector, not proof that faster vibration is absent. Hardware faults, temperature/voltage limits and departure from the selected domain also latch review.

The CLI emits each new JSON report to stdout and atomically replaces the optional latest-report file. Capture stdout through the existing execution recorder when a complete event history is required. Profile/request file changes during polling invalidate the pinned analysis. Output paths may not replace a profile, request or motor-health input.

Exit codes: `0` analysis/observation completed, `2` invalid input or persistence failure, `3` no measured-domain candidate or owner-review recommendation. Interruption and process exit provide no physical-stop guarantee.

## Verification and remaining acceptance

The four adapter `test_*load*`/`test_motion_characteristics.py` suites and `load_motion_fixtures.py` use synthetic domains and files. Their numbers are not device settings. Run them through `tools/remote/remote_pytest.py` on the committed revision; no local pytest or physical bus access.

Source tests cover persistence/refusals, identity/configuration binding, full-segment bounds, final hold, payload/environment/repetition, source-time errors, oscillation, fault/stale handling and CLI output. Physical calibration, certified operating envelopes, true standstill, safe lowering, device runtime wiring and field acceptance remain unverified. Automatic alternative movement is disabled; a new path must be planned from fresh actual state after owner recovery and pass all existing admission gates.
