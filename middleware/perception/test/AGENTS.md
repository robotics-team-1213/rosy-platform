
# test/ (pure-logic suite)

**Parent context:** `../AGENTS.md`

## Purpose
ROS-free unittest suite covering every pure-logic decision module. No ROS on the dev machine — numpy/opencv only.

## Key Files
| File | Covers |
|------|--------|
| `test_modes.py` | `control/modes`: label precedence, ESTOP reachable, WARN band edges, `nose_on_wall`, US no-echo/0.80 cap |
| `test_scale.py` | `safety/scale` corridor auto-scale |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fixtures/` | Recorded scans, maps, and localization snapshots used by tests (see `fixtures/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- Mirrors the module tree: a new decision module gets `test_<module>.py`.
- Unittest style (`unittest.TestCase`), plain asserts with boundary comments (see `test_recover.py`).

### Testing Requirements
- `python3 -m pytest test/ -q` (all, ~75 tests) — keep green before committing.
- `python3 -m pytest test/test_recover.py -k backup` to run one test.

### Common Patterns
- Tests encode *hardware rationale*: think-speed crawls can't cover 8 mm in 1.2 s (not stuck); 4095 IR = saturation, never a cliff.
