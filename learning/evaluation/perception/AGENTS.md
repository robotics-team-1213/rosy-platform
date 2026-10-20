# Perception evaluation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

`road_replay.py`, `road_replay_inputs.py`, and `road_replay_metrics.py` evaluate existing recording inputs using the unchanged replay and metric contracts. Curation owns input conversion; registry owns the shared artifact/provenance store; training owns trainer jobs. D-637 moves the existing evaluation implementation while preserving bare imports, input lineage, class meanings and signatures. Evaluation does not activate a learned model or publish final commands.

`intake_evaluation.py` owns fixed-set model scoring and `intake_eval_gate.py` owns its pure quality judgments. Registry's `intake.py` re-exports the established scoring API and retains admission/publication; moving these functions changes neither stored metrics nor verdict thresholds.

`road_fitness.py` (D-665/D-667) consumes full road labels, shared observation input-validity checks and perception anchor-based region geometry. `evaluate_frame` scores separate independent road/region truth masks, preserving valid/unknown truth counts even when the region abstains. Its reports are always diagnostic/HOLD until independent lineage, conditions/coverage, thresholds and device evidence are supplied. It is not a command, an approval gate or an operational consumer.

`summarize_frames` pools pixel counts within each real/simulation domain and named condition; it never averages frame IoUs or merges domains. Prediction abstention and unknown-only truth remain separate. Boundary distances are image pixels on contours whose four neighbours are known; missing contours and excluded boundary counts remain explicit. This diagnostic summary is not a dataset loader or an independent acceptance receipt.

`evaluate_model_frame` reuses an opened LaneSegModel and its preprocessing; independent binary truth and anchor pixels start on the original camera grid. Labels/truth/anchors share the resized full-frame grid and predicted crop rows. Known truth outside the prediction ROI is recorded as excluded rather than unknown truth, and full-grid coverage retains those exclusions. Model files, dataset lineage, human authority and physical calibration must still be bound by the replay caller; this per-frame adapter does not admit a model or verify those artifacts.

Use `learning/evaluation/perception/test`, the legacy shared `test/learning/perception` suite and `operations/world/test` through the remote committed-HEAD runner and known-failure comparator. Read repository [AGENTS.md](../../../AGENTS.md), D-637 and D-665 before editing source boundaries. See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md).

`judgment_acceptance.py` owns the first Pinky line-stop/re-observation offline checker (D-662). Named independent labels, frozen hashes/splits, denominators and pre-reviewed limits are required; missing acceptance evidence stays HOLD. PASS_OFFLINE_ONLY is never FIELD or provider activation. Curation's incident feedback remains candidate evidence.

`road_fitness_replay.py` (D-666) binds paired immutable human-mask eval sets, model preprocessing/files, separately stored observations and declared training sources. `rosy_ml fitness` runs offline before robot configuration. It refuses mutable versions, missing exact approvals, source/image overlap and changed artifacts. Completed reports remain HOLD; no intake/delivery/watcher admission occurs. D-667 keeps observation types/validity in `core_common.observation`, with World compatibility imports.

D-670 shares `LaneSegModel.infer_road_surface` with truth-free internal observations. Original truth is validated before resize; ROI exclusions and real/simulation separation remain unchanged. Missing anchor image-reference abstains the region without invalidating an otherwise valid road image. No operational observation transport is implemented by this library boundary.

`road_observation_replay.py` (D-673) implements `rosy_ml observe` using a content-addressed image/snapshot input folder and pinned model manifest. It writes a new HOLD diagnostic file and verifies its SHA256 and masks on readback. It does not consume truth, select destinations or implement device transport; the replay clock is not live latency evidence.
