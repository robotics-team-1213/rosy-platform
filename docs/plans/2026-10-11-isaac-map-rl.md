# Isaac map RL Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a bounded single-Pinky CPU residual RL experiment on the actual curved map in headless Isaac, and independently judge ordered route completion and physical stop.

**Architecture:** Reuse the STL scene generator, lane graph, URDF importer, CORE CommandManager and final port. A simulation-only owner validates POLICY candidates before the existing navigation slot. Q-learning adjusts pursuit yaw gain; actual physics readback supplies rewards. D-638 leaves D-606 operational acceptance HOLD.

**Tech Stack:** Isaac Sim 5.1 SDK, Python standard library, installed NumPy/PyYAML, existing ROS-free CORE logic. No new dependency, robot endpoint or GPU trainer.

### Task 1: Pure task and admission checks

- Create `tools/sim/isaac/map_task.py` and `learning/envs/isaac/test/test_map_task.py`. Cross-package CORE/Drive diagnostic composition belongs to tools/sim, per D-427.
- Test ordered progress (no shortcut), finite observations, physical terminal-zero dwell, failure vs timeout, Q-learning updates with no evaluation mutation, and POLICY envelope/epoch/expiry refusal.
- Commit tests first, run `python tools/remote/remote_pytest.py --log-dir <X-session>/logs/red -- learning/envs/isaac/test/test_map_task.py`; record expected collection failure, never whitelist it.
- Implement only tested behavior; repeat remote tests and `python test/known_failures.py <log>`; expect exit 0 and NEW=0.

### Task 2: SDK map and physics runner

- Create `tools/sim/isaac/run_map_rl.py`. Reuse `stl_scene.load_scene`, `build_world.training_scene`, `importer_compat`, `drive_runtime`, `graph_contract`, and CORE final port; do not modify generated map files or CORE production source.
- Build the same visual paint and four collision walls in USD. Measure rigid-body pose/velocity and run one physics environment. Stop before resetting; fail closed on invalid data.
- Run native SDK only on the reserved model PC with fresh source archive and hash manifest, bounded memory/time, CPU learning, and separate baseline/train/eval phases. Export JSONL physical trajectory and frozen Q table outside source.

### Task 3: Review and evidence

- Independently review candidate admission, source provenance, physical reset/stop and completeness claims before accepting runtime evidence.
- Create `docs/validation/isaac-map-rl-2026-10-11/result.md` with terminal exits, memory/GPU and physical path readback; update Isaac README/progress/logs if evidence changes its gate.
- Run remote `learning/envs/isaac/test`, relevant motion contracts and CORE guards; compare known failures. Lint ADR log. No push or promotion; merge is a separate instruction.
