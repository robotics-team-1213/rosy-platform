# Fleet site-map rejected-credential width check — 2026-10-07

Candidate base: local `main` commit `b2d82124f952067c31edcbe76adfedf5f230284c`. The `/console/site-map` browser scenario first connected with a fixture operator credential, then retried with an invalid credential at **1440×1000, 390×844, and 320×568**. In all three Chromium captures, the old map and actions cleared, the page asked for a valid control credential, the emergency stop and other actions were disabled, and the document had no horizontal overflow. The three draft buttons use equal available widths. The 1440px width assertion failed before the CSS change (152.61, 176.61, 160.61px) and passed after it.

The full site-map browser suite passed **30 tests**; the D-153 G1 suite passed **90 tests**; the site-map Node checks passed **7 tests**. `known_failures.py` reported **0 NEW** for the successful Python runs. A full browser run initially had one timing failure in the existing slow-load test: a fixed 2.2-second request delay could finish before its disabled-button assertion. That test now holds the fixture request until its pending-state assertions finish, then releases it. The final full run passed.

Raw logs and three PNGs: `X:/DevTemp/projects/rosy-platform/2026-10-07--site-map-auth-width/`.

| File | SHA-256 |
|---|---|
| `site-map-auth-rejected-1440x1000.png` | SHA-256 `1624e85dbf55389affc1d38b9200feed463b1584c4d75582fe21fe1a4830291c` |
| `site-map-auth-rejected-390x844.png` | SHA-256 `83437f21649079b9a59e9e7b84ae5f60de50a3318d1be5e3e6f349abf9176ee3` |
| `site-map-auth-rejected-320x568.png` | SHA-256 `5100e77d9185805fbf27bfb85bcc3c2c73d1211fd8194ec1a3ea804c1eefbb25` |
| `browser-full-final.txt` | SHA-256 `9176e029d66f3b3b0993711318dfbc09b44839ad8957ea76ee8ccf1fcdc49edb` |
| `g1.txt` | SHA-256 `06955f3a9b315063a1a19050006aae333017d347d01ca97c4c4b7b03afd8ead6` |

This is **LOCAL synthetic G2 partial evidence**. It does not prove the candidate is installed on the site PC, any real robot or camera state, or the operator G3 walkthrough. The product remains **HOLD**.
