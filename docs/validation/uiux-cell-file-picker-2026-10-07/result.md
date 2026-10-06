# Fleet Cell file picker — 2026-10-07

The local Chromium capture of `main` `6e64e6dcd` showed English browser file-picker text in both Korean document steps. In `uiux/cell-file-picker`, the recipe and taught-cell pickers use the same full-width Korean action and show the selected filename. The native file input remains focusable, labeled, and responsible for file selection; the existing JSON import path is unchanged.

At 1440×1000, 390×844, and 320×568, both picker tracks match their document-name fields within 1px, with no document horizontal overflow. At 320px, selecting `recipe.json` displays that name and imports the JSON. The browser regression was red **4/4** before implementation and green **4/4** after it. The full Cell browser suite passed **33/33**, D-153's named G1 contracts **90/90**, and Fleet web Node tests **144/144**; `known_failures.py` reported **0 NEW** for browser and G1 runs. Node's directory-only invocation is unsupported on this Windows installation; the passing run supplied the individual `.test.mjs` paths.

Raw captures and logs are under `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-file-picker/`. SHA-256:

| File | SHA-256 |
|---|---|
| `shots/fleet-cell-widths-1440x1000.png` | SHA-256 `c1a6b4b0c3ed99b6abf34b5fbc3398005662d427e2e6d5bf633fbcff42faddb8` |
| `shots/fleet-cell-widths-390x844.png` | SHA-256 `cac5a69559378918dc19785f58a92b77c2424d048c2987d6de1a1fde108d5ea3` |
| `shots/fleet-cell-widths-320x568.png` | SHA-256 `d797adbb1ca0ef586d285867622e4cdc5aae577be67752ea110f1565e2f3543e` |
| `shots/fleet-cell-file-selected-320x568.png` | SHA-256 `52dce718aa43faa79ee10a2fdbc346a4865d605c0bdf0f950c82418b6228d8f7` |
| `logs/browser-full-final.txt` | SHA-256 `c34b32df134211cb37dd8e9991e473aaae36121322e2a8073c3f9d778780d96d` |
| `logs/g1-full.txt` | SHA-256 `737eb5b30dbb7fcf8dbbd1061d9bf9cf01125447fef0bd60bea56a555c195ff2` |

This is **LOCAL G2 and vocabulary evidence for the file-import state only**. Real site installation, actual cell document/operator work, remaining declared states, and G3 remain **HOLD**.
