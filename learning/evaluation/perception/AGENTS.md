# Perception evaluation

`road_replay.py`, `road_replay_inputs.py`, and `road_replay_metrics.py` evaluate existing recording inputs using the unchanged replay and metric contracts. Curation owns input conversion; registry owns the shared artifact/provenance store; training owns trainer jobs. D-637 moves the existing evaluation implementation while preserving bare imports, input lineage, class meanings and signatures. Evaluation does not activate a learned model or publish final commands.

Use the unified `test/learning/perception` suite through the remote committed-HEAD runner and known-failure comparator. Read repository [AGENTS.md](../../../AGENTS.md) and D-637 before editing source boundaries. See [progress.md](progress.md), [logs.md](logs.md), and [index.md](index.md).
