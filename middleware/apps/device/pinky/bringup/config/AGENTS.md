<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# config

## Purpose

Bringup parameters and a localhost CycloneDDS profile for isolated DDS (D-6).

## Key Files

| File | Description |
|------|-------------|
| `rosy_params.yaml` | Node parameters for bringup |
| `pinky_pro_adapter.yaml` | Pinky Pro board profile loaded by the ROS launch path |
| `cyclonedds_localhost.xml` | Restrict DDS to localhost |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Robot-to-robot DDS isolation is a CORE principle. Do not widen this XML to multicast on the bench unless you intend a shared domain.
- Pi runtime uses `/etc/rosy/cyclonedds.xml` from compose, not necessarily this file.

### Testing Requirements

None dedicated.

### Common Patterns

YAML params + XML DDS.

## Dependencies

### Internal

- `scripts/rosy_env.sh` may point at the XML

### External

- CycloneDDS

<!-- MANUAL: -->
