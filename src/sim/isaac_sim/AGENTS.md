<!-- Parent: ../AGENTS.md -->

# isaac_sim

## Purpose

Isaac Sim 6.1-specific simulation integration for one ROSY robot. It is a standalone Isaac Python workflow, not a colcon package or a validated simulation runtime.

## Working Rules

- Reuse `src/sim/description/` for shared robot geometry where practical.
- Keep Isaac Sim-specific scenes and adapters here; keep Gazebo worlds, plugins, and bridges in `src/sim/gz_sim/`.
- Preserve CORE as the final command owner. Simulation results do not establish physical-device acceptance.
- D-98 defers the separate soccer training environment at `src/site/games/games/isaac/`.
- Generate URDF/USD only outside the checkout. On this Windows workspace, use `X:\DevTemp\`.
- A host pytest or generated USD does not establish Isaac ROS-SIM acceptance. Verify ROS graph, motion, stop, and TF on the GPU host.
