# Fleet Cell saved-document list — 2026-10-07

The saved-document list showed raw `cell`/`recipe` types and ISO timestamps as one wrapping line on a 320px screen. It now shows the Korean document type and ID first, then the modification time in the browser's local timezone on a separate line. Invalid time data is labeled unavailable rather than shown as a misleading date.

The focused Chromium test failed before the change and passed at **1440×1000, 390×844, and 320×568** afterward (**3 passed**, `known_failures.py` **0 NEW**). The relevant palette, token, and Fleet grammar checks passed **74 tests**, **0 NEW**. The 320px capture was visually checked; page horizontal overflow was zero. JavaScript syntax and `git diff --check` passed. Raw test logs and three screenshots: `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-saved-list/`.

This is LOCAL browser evidence for one Cell list state. Remaining declared G2 states, current site/device readback, and the operator G3 walkthrough remain **HOLD**.
