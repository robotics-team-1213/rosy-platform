<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-03 | Updated: 2026-09-03 -->

# navigation (Python)

## Purpose

Nav2 policy used by launch files: D-4 frame prefixing, temp params rewrite, and
Device-profile motion-limit validation. Not a ROS node.

## Key Files

| File | Description |
|------|-------------|
| `frame_prefix.py` | Prefix `odom` / `base_*` TF frames; leave `map` global |
| `params_rewrite.py` | Write a namespaced copy of `nav2_params.yaml` for launch |
| `site_map.py` | Use host `site.yaml`; allow the demo fallback only when explicitly requested |
| `profile_limits.py` | Validate Nav2 and launch velocity ceilings against `/etc/rosy/profile.yaml` |

## For AI Agents

- Import `navigation.frame_prefix` / `params_rewrite` / `site_map` /
  `profile_limits`. Do not add helpers under `launch/`.
- Tests: `test/test_nav2_hardware_slice.py` (host pytest, no ROS overlay).

<!-- MANUAL: -->
