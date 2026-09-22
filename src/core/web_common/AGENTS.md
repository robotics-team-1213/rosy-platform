<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# web_common

## Purpose

Framework-free shared web assets: `tokens.css` (single colour source, D-72 L1) and `core_ui_logic.js` (server-judged evidence enum adapter). Installed to `share/web_common`; consumed by `core_api_web` and `fleet`.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: none |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `tokens.css` | Colour/design tokens — the only palette source |
| `core_ui_logic.js` | Evidence-state adapter; contains no clock math |
| `CMakeLists.txt` | Installs both files to share |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Do not copy tokens into consumers; link `/ui/tokens.css` (D-130.3).
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/test_module_structure.py`.

### Testing Requirements

```bash
PYTHONPATH=src/core:src python -m pytest src/core/core/test/test_ui_token_contracts.py src/core/core/test/test_palette_gates.py -q
```

## Dependencies

### Internal

none

<!-- MANUAL: -->
