# Fleet and games capture asset check — LOCAL

Run date: 2026-10-07. Candidate branch `fix/fleet-games-capture-assets` started at `0407cdbfa`. This is a local browser fixture, not a site or device run.

The earlier `tools/capture_console_games_round.py` run returned six screenshots and exit 0 even though Fleet shared CSS and JavaScript were missing. Its Fleet `TestClient` omitted `web_common`, `/common/*` requests bypassed the route handler, and the report checked only page errors. The resulting Fleet screenshots were unstyled. The repaired script serves the real shared assets and fails on missing Fleet assets.

Replayed `python tools/capture_console_games_round.py --out-dir X:/DevTemp/rosy-fleet-games-current/final`: six styled screenshots, `pageErrors=[]`, `assetErrors=[]`, exit 0. Report: `X:/DevTemp/rosy-fleet-games-current/final/report.json`, SHA-256 `f0e33c3c47c379b8f5e47ad39ed7d186eeff776f65a13beb85a5aed4fe66c360`. The repaired Fleet 320x568 PNG is `35f33819cb74edadb50e6233c1f731d5392cda064984fa91d88300fec30aba6d`; the earlier unstyled PNG was `29dc21e02b7fc2d9e367a2999227a88273c8f8c70ad511e4ac62a48941558ea8`.

Focused Fleet browser width and order checks: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py -k 'console_fits_the_declared_viewport or slow_initial_gather_does_not_spawn_overlapping_polls or single_column_tier_puts_exceptions_before_the_map_and_formation_last' -q -rfE -p no:cacheprovider` → 6 passed, 104 deselected; `python test/known_failures.py X:/DevTemp/rosy-fleet-games-current/layout-tests.txt` → 0 NEW. Log SHA-256: `1a0d192b8b6114f171914f4eaeea4ddf51b00134a0b8d340bfda70f12a41a620`.

At 320 and 390 px, Fleet panels share the single-column content width. At 1920 px, the wider map and narrower operations track follow accepted D-493's deliberate 3:2 desktop layout. These captures cover only the fixture states and six declared cells. D-153 full G2 state coverage, installed runtime, and user G3 walkthrough remain **HOLD**.
