<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-06 -->

# control.control (import and installation compatibility)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose
This directory holds `__init__.py` and this guide. The initializer preserves the existing `control.control` exports and adds the four exact source roots declared by `control/_source_layout.py` to its package path. The pure algorithm files are physically owned by Drive after D-630; they are installed once under the unchanged `control.control.*` identities.

| Canonical source holder | Flat pure modules | Responsibility |
|---|---:|---|
| `middleware/drive/motion_limits` | 15 | Candidate gates, body/sweep clearance, floor evidence, speed limits and policy handoff |
| `middleware/drive/tracking` | 6 | Path following, pursuit, route and navigation-session evidence |
| `middleware/drive/recovery` | 11 | Escape, recovery budgets, rotation trials and safe-trail retreat |
| `middleware/drive/calibration` | 18 | Calibration profiles/certificates, startup configuration and canonical mode labels |

The separate planning/grid, tracking/wander and safety/adapter packages retain `control.planning`, `control.wander` and `control.safety`. See the [current platform folder guide](../../../../docs/reference/platform-folder-responsibilities.md) and [composition guide](../AGENTS.md).

## Key Files
| File | Description |
|------|-------------|
| `Drive calibration/modes.py` | Imported as `control.control.modes`: canonical `/robot/mode` labels, hazard > action > contact > idle precedence and hardware cutoffs |
| `Drive recovery/recover.py` | Imported as `control.control.recover`: `hazard_action`, backup/escape policy, turn signs and `ExitSteer` |
| `Drive tracking/route.py` | Imported as `control.control.route`: longest free straight line through live sector ranges |
| `Drive safety/policy_handoff.py` | Imported as `control.control.policy_handoff`: serialized sensor-state to CORE `CommandPolicy` handoff with receive/source deadlines and applied revision |

## For AI Agents

### Working In This Directory
- Edit pure logic in its actual Drive source holder. Keep ROS imports out of those algorithms and pass required node state through their existing inputs.
- Keep this initializer's exports and the narrow source package path. `setup.py` collects the 50 flat modules into one installed `control.control` package; duplicate source names are rejected. The sdist snapshots those declared roots for an isolated rebuild.
- `ControlPolicyProducer` is the one in-process boundary that may hold an `Observations` source and a `CommandPolicy`; call it from the sensor producer's serialized callback/timer group. It carries receive/source deadlines plus candidate-specific translation/tracking evidence and never publishes motor commands.
- `hazard_action` is the only cliff/tilt decision home: **do not re-branch on `self.cliff`/`self.tilt` in FSM code** — call the policy.
- Label list lives once in `modes.MODES`; `WANDER_TO_MODE` maps FSM state names → labels.
- New labels must keep the taxonomy: hazard > action > contact > idle, subjects do not overlap.

### Testing Requirements
- Run `middleware/perception/test/` through the repository's committed-HEAD remote pytest runner (D-584). Mode/recovery/route boundary tests stay in that distribution suite.
- Source holder, installed module/provider identity, isolated sdist/wheel and map-byte checks are in `middleware/perception/test/test_responsibility_layout.py`.

### Common Patterns
- Thresholds as module constants with hardware rationale comments (`US_NOSE_MAX_M = 0.80` — beyond ~0.8 m a US-016 echo is noise).
- NaN/None-safe float handling (`_hit`, `ratio_sign` treat no-echo as no-opinion).

## Dependencies

### Internal
- Consumed under the existing import identities by the actual `middleware/drive/tracking/wander` and `middleware/drive/motion_limits/adapter` implementations, the sensor provider and ROS composition adapters.

### External
- Existing ROS-free algorithm dependencies remain declared by the `control` distribution; this compatibility initializer adds no runtime or motion authority.

<!-- MANUAL: -->
