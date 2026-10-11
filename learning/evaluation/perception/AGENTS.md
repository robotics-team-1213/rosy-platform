# Perception evaluation

`road_replay.py`, `road_replay_inputs.py`, and `road_replay_metrics.py` evaluate existing recording inputs using the unchanged replay and metric contracts. Curation owns input conversion; registry owns the shared artifact/provenance store; training owns trainer jobs. D-637 moves the existing evaluation implementation while preserving bare imports, input lineage, class meanings and signatures. Evaluation does not activate a learned model or publish final commands.

`road_fitness.py` (D-665) consumes full road labels, World input-validity checks and perception anchor-based region geometry. `evaluate_frame` scores separate independent road/region truth masks, preserving valid/unknown truth counts even when the region abstains. Its reports are always diagnostic/HOLD until independent lineage, conditions/coverage, thresholds and device evidence are supplied. It is not a command, an approval gate or an operational consumer.

Use the unified `test/learning/perception` suite and `operations/world/test` through the remote committed-HEAD runner and known-failure comparator. Read repository [AGENTS.md](../../../AGENTS.md), D-637 and D-665 before editing source boundaries. See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md).
