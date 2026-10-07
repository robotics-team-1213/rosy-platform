# Fleet site map: independent map and robot evidence — LOCAL

The `/console/site-map` page previously awaited the Fleet robot roster as part of loading the active map. A roster 503 made an already loaded map disappear and called it a map failure. At 1440×1000, 390×844, and 320×568, Chromium now keeps the active map visible, states that robot status could not be checked, and disables route preview while keeping the operator's emergency stop available. The 320px screen still has no document horizontal overflow.

A separate 401 roster response after session lookup previously left the operator's stop control enabled. The page now clears its displayed role and disables operator controls for 401/403. The full site-map browser suite passed **38/38**, with `known_failures.py` **0 NEW**. The targeted checks were red before the fixes and green after them. Logs and three 503 screenshots are under `X:/DevTemp/projects/rosy-platform/2026-10-07--site-map-current/`.

These fixture responses are LOCAL evidence for the unavailable and denial cells. Other declared G2 cells, the current installed site screen and robot readback, and the user's eight-item G3 walkthrough remain HOLD.
