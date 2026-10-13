# Legacy Drive ROS adapters

**Parent context:** `../AGENTS.md`

D-649 moves four existing node modules here: straight/rotate control, goal planning, wander entry and safety entry. Their installed names remain `control.control_node`, `control.goal_node`, `control.wander_node`, `control.safety_node`; they ship through the existing Perception `control` distribution. Source mapping and sdist install exactly one copy.

These are legacy/comparison graph adapters, not a second CORE. Product launches keep the legacy final publisher excluded beside CORE. Do not activate or remap a writer as part of a folder change. Perception sensor/localization observer nodes and shared calibration storage/lease responsibilities stay with their existing owners.

Remote Perception source-audit, QoS/executor, entry-point and isolated wheel tests must include these files. ROS graph and physical acceptance remain separate.
