# Fleet Cell saved-list error and recovery — 2026-10-07

The existing saved-document list failure, retry, recovery, and credential-change browser scenario was replayed at all three Cell viewports: **1440×1000, 390×844, 320×568**. The 503 state explains that the list could not be read and asks the operator to check the connection and retry. Reconnecting reveals two saved documents; changing credentials hides the old list. Horizontal page overflow was zero in the failure and recovered states at every width.

Chromium: **3 passed**, `known_failures.py`: **0 NEW**. Six LOCAL screenshots and the test log are in `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-list-errors/`. The 320px error and recovered screenshots were visually checked. No product code changed in this evidence pass.

This fills six synthetic saved-list G2 cells. Other declared Cell states, current site/device readback, and the operator G3 walkthrough remain **HOLD**.
