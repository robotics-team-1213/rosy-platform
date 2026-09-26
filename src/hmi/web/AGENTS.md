<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-24 -->

# web_common

## Purpose

Framework-free shared web assets: `tokens.css` (single colour and type scale), `components.css` and `ui.js` (shared browser controls, D-194), and `core_ui_logic.js` (server-judged evidence enum adapter). Installed to `share/web_common`; consumed by `core_api_web`, `fleet`, the game host, and the control diagnostic page.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: none |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `test/` | Token, palette, headless, and shared-control contract tests |
| `tokens.css` | Colour and type scale — the only palette and size source |
| `components.css` | Shared text, head, grid, button, field, form, readout, readback, status, tag, chip, triage, evidence |
| `ui.js` | Custom elements for those controls; no build step |
| `core_ui_logic.js` | Evidence-state adapter; contains no clock math |
| `CMakeLists.txt` | Installs the shared files to share |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Do not copy tokens into consumers; link `/ui/tokens.css` or `/common/tokens.css` (D-130.3).
- A new browser page starts from `template.html` (`/common/template.html`). It is a `ui-shell` with a `grammar` of `spatial`, `exception`, `focal`, or `procedure`, and a `ui-topbar`. `test_shared_controls.py` rejects a product `index.html` or `dashboard.html` that omits that shell.
- A new `ui-button` names `kind` as `primary`, `quiet`, `irreversible`, `segment`, or `toggle`. Do not infer kind from a parent class. The same test rejects a button without that attribute, and rejects a surface rule that sets background, color, border, font, or opacity on a `ui-*` control. Placement (flex, width, margin) stays in the surface.
- Copied colour numbers, including the face LCD tuples and the diagnostic page's ink, ground, and status hex, stay equal to `tokens.css`. The same test fails the drift. Pitch colours stay in the one `:root` block of the game sheet. Raster hex (`--unk`, `--free`, `--wall`) stays with the PNG pipeline.
- Padding, margin, gap, and border-radius on a browser surface use `--space-*` and `--radius-*`. A 1px rule is a line. Width, grid, and position stay on the surface.
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest src/hmi/web/test -q
```

## Dependencies

### Internal

none

<!-- MANUAL: -->
