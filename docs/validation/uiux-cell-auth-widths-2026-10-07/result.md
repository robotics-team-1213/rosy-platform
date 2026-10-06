# Fleet Cell rejected-session widths — 2026-10-07

Candidate: `uiux/cell-auth-widths` from local `main` `64bfd5d42`.

The existing `/console/cell` browser scenario was run for HTTP 401 and 403 at 1440×1000, 390×844, and 320×568. After a valid session and two loaded documents, each rejected reconnect removed the saved list and prior summary, reset the revision, disabled proposal and save actions, and showed the denial notice. Both document panels differed in width by at most 1px; the notice and emergency stop started in the first viewport; the document had no horizontal overflow.

Command: `ROSY_BROWSER_TESTS=1 python -m pytest operations/fleet/test/test_cell_app_browser.py -k cell_auth_denial_clears_previous_session -q -rfE -p no:cacheprovider` with `ROSY_SHOT_DIR` set to the raw directory below. Result: **6 passed, 33 deselected; `known_failures.py`: 0 NEW**. One upstream Starlette deprecation warning.

Raw files: `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-auth-widths/` (SHA-256):

| File | SHA-256 |
|---|---|
| `fleet-cell-auth-401-1440x1000.png` | `285fde39471714629e7bbc321a7dab28459e37277a9207fcaa0994c2a3d401a8` |
| `fleet-cell-auth-401-390x844.png` | `809f3d2355cf2a64d51ab14d484462bb1c12ee0008a606bc82c9a9f28c335256` |
| `fleet-cell-auth-401-320x568.png` | `869b0e0b31ffe433ce11e87500afa23e71201cd67b53d7b5738a223f8e0b9c68` |
| `fleet-cell-auth-403-1440x1000.png` | `8303d5267d15d932ac16c1704b33c5d81cf5cd6b429020c3286f499a781422e2` |
| `fleet-cell-auth-403-390x844.png` | `d19f75b9b6e8bf04deb18d49c721c30b6160f99f1fdde19a95462da889e2cc32` |
| `fleet-cell-auth-403-320x568.png` | `71cc880f8bb7e974e70517773a43f89aa623dc786e4824afe011e2ad0dd25398` |
| `run.txt` | `61999aac7e8e1b4d04111f083e39d7b5555e81253d03557f0eccef39ef3317cf` |

This is LOCAL synthetic G2 evidence for one rejected-session state. Remaining Cell states, real site and device readback, and the user's G3 walkthrough keep full-product UI/UX acceptance **HOLD**. No site action, motion, or tablet installation occurred.
