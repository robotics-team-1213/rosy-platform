
# config

**Parent context:** `../AGENTS.md`

## Purpose

Bringup parameters and a localhost CycloneDDS profile for isolated DDS (D-6).

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
