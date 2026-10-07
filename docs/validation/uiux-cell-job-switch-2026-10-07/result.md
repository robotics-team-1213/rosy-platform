# Fleet Cell job snapshot invalidation — 2026-10-07

Candidate: `uiux/cell-job-switch-state` from local `main` `7f0e8a38c`.

Changing the job ID disabled approval but left the previous job's summary, detailed state, and step list visible. A browser test failed on that stale summary at 1440×1000, 390×844, and 320×568. Cell now clears the job snapshot together in the existing invalidation paths: session loss, 409 conflict, new proposal, new job read, read failure, and job ID edit. The 320px result was visually checked: the prior job no longer appears, the next step asks for a job ID read, and the disabled actions remain readable without horizontal overflow.

Checks: selected ID-change, failed-read, and auth-denial Chromium cases **12 passed, 32 deselected**, `known_failures.py` **0 NEW**; D-153 named G1 **90 passed**, **0 NEW**; JS syntax passed. An optional full Cell browser run was stopped after about 16 minutes under heavy shared-machine load. Its log contained 22 partial progress dots and has **no final pass result**; it is not acceptance evidence. One earlier three-width run had a 390px fixture `networkidle` setup timeout before scenario execution; that case passed on isolated rerun and in the final 12-case run.

Raw files: `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-job-switch/` (SHA-256):

| File | SHA-256 |
|---|---|
| `red.txt` | SHA-256 `4ffb0b6dffe7811dc2cbcd5590b4feb600202d1b59874a116ce9af2f2c758cac` |
| `targeted.txt` | SHA-256 `9e44f72b3eed6198e30a6fbb0be14a24d3b67d2645bb4eeadd36d090fc53e5e4` |
| `g1.txt` | SHA-256 `e225a9990c85b19bb66e6bac3fa8fc98b40e7399af0e708f7a40f595798a69db` |
| `full.txt` (incomplete) | SHA-256 `ce80221492b7d37fb2d50cb6ab4f74f55f618c49ea4e2d4b471489eb071b9dce` |
| `fleet-cell-job-switch-1440x1000.png` | SHA-256 `c87b68b74f0b74eb0a564f9d0d9140677aa76dfe7d13e67fdaa5acaeb5637b2a` |
| `fleet-cell-job-switch-390x844.png` | SHA-256 `708248d80eb96548605e1d9690fb395cacca68ff5ad30017a7c408f42fcda25e` |
| `fleet-cell-job-switch-320x568.png` | SHA-256 `bfef412c9c2e4fa077207170ea47a94867c7daa61545828acd5582ca9b27948a` |

This is LOCAL synthetic G2 evidence for job switching. The current site UI/device readback, remaining G2 cells, and the user's G3 walkthrough remain **HOLD**. No site operation or device command occurred.
