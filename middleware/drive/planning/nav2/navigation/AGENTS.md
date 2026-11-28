
# navigation (Python)

**Parent context:** `../AGENTS.md`

## Purpose

Nav2 policy used by launch files: D-4 frame prefixing, temp params rewrite, and
Device-profile motion-limit validation. Not a ROS node.

## Key Files

| File | Description |
|------|-------------|
| `site_map.py` | Use host `site.yaml`; allow the demo fallback only when explicitly requested |

## For AI Agents

- Import `navigation.frame_prefix` / `params_rewrite` / `site_map` /
  `profile_limits`. Do not add helpers under `launch/`.
- Tests: `test/test_nav2_hardware_slice.py` (host pytest, no ROS overlay).
