# Fleet site-map offline robot choice — 2026-10-07

Candidate: `uiux/site-map-offline` from local `main` `838c74349`.

The route-preview robot picker previously showed an offline robot as an ordinary available choice. A new Chromium case failed at 1440×1000, 390×844, and 320×568 because its option lacked the disconnected label. The final UI keeps the robot visible as `연결 끊김`, disables route preview when none is connected, explains the next step, and still allows selection of a connected robot in a mixed list. The 320px capture was inspected after correcting an intermediate blank-picker design. Emergency stop stays in the first viewport and there is no document-width overflow.

Checks: site-map Chromium **34 passed**, D-153 named G1 **90 passed**, site-map Node **7 passed**, JS syntax passed. After a readability-only expression cleanup, the affected offline, mixed, and empty cases passed **7/7**. Each Python success run had `known_failures.py` **0 NEW**. Raw logs and captures: `X:/DevTemp/projects/rosy-platform/2026-10-07--site-map-offline/`.

| File | SHA-256 |
|---|---|
| `red.txt` | `c9eb910495936bf7c833566aad4457d422c02d1bd480331480ce6bd3b1516895` |
| `full-browser.txt` | `90628069da1b86312a56b60becb1c780f3eca270635e5e98e84d3ef84fae9c29` |
| `final-focus.txt` | `d40fc308e6d95f5a57441d803ed5de39f48c06159b2ba27d8856c37bd87fb9e4` |
| `g1.txt` | `b21af641d7b47bf8a120a3bc873679b3ab4d027d860a7a2e0c7d53eb614a7c85` |
| `node.txt` | `62a6ceced47af3ab45184edf1ca335c0890a15ccd441c0c37dc1455acf4625ff` |
| `site-map-offline-1440x1000.png` | `5423456aba2d64b1cd4818eaca107f520eaf6ecf4aa1b06ef77ccaa3e71681b3` |
| `site-map-offline-390x844.png` | `09a8e57ec2abbf9e361d3100d0c2b4c8d0730b8378566099fcb997865ecdd0c1` |
| `site-map-offline-320x568.png` | `26884139b447082a1945271b71483df9fb6e5c5636565cf1ef840ab3e2f9045c` |

This is LOCAL synthetic G2 evidence for the offline robot state. The existing site image is older than this candidate; actual site UI, device state, and the user's G3 walkthrough remain **HOLD**. No route was executed and no site deployment occurred.
