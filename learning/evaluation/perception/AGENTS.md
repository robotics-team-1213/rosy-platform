# Perception evaluation

**Parent context:** `../AGENTS.md`

Read repository [AGENTS.md](../../../AGENTS.md), D-637 and D-665 before editing source boundaries.

## Working In This Directory

- Curation owns input conversion; registry owns the shared store; training owns trainer jobs. D-637 moved evaluation here preserving bare imports, lineage, class meanings and signatures. Evaluation never activates a learned model or publishes final commands.
- `intake_evaluation.py` owns fixed-set scoring, `intake_eval_gate.py` its pure judgments; registry's `intake.py` re-exports them and keeps admission/publication. Metrics and thresholds are unchanged by the move.
- `road_fitness.py` (D-665/D-667): `evaluate_frame` scores independent road/region truth masks, keeping valid/unknown counts when the region abstains. Reports are diagnostic/HOLD until independent lineage, coverage, thresholds and device evidence exist; never a command or approval gate.
- `summarize_frames` pools pixel counts per domain and condition; never average frame IoUs or merge real/simulation. Abstention and unknown-only truth stay separate; boundary distances are pixels on four-neighbour-known contours.
- `evaluate_model_frame` reuses an opened LaneSegModel; truth and anchors start on the original camera grid. Known truth outside the prediction ROI is excluded, not unknown. The replay caller binds model files, dataset lineage, human authority and calibration; this adapter admits nothing.
- `judgment_acceptance.py` (D-662): named independent labels, frozen hashes/splits, denominators and pre-reviewed limits are required; missing evidence stays HOLD. PASS_OFFLINE_ONLY is never FIELD or provider activation.
- `road_fitness_replay.py` (D-666) runs offline via `rosy_ml fitness`; it refuses mutable versions, missing approvals, source/image overlap and changed artifacts. Reports stay HOLD; no intake/delivery/watcher admission. D-667: observation types live in `core_common.observation`.
- D-670: `LaneSegModel.infer_road_surface` serves truth-free observations; truth is validated before resize. A missing anchor image-reference abstains the region only. No operational transport here.
- `road_observation_replay.py` (D-673, `rosy_ml observe`) writes a new HOLD file and verifies SHA256 and masks on readback; replay clock is not live latency evidence.
- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.

## Testing Requirements

Run `learning/evaluation/perception/test`, `test/learning/perception` and `operations/world/test` through the remote committed-HEAD runner and known-failure comparator.
