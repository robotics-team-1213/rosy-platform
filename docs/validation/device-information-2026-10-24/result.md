# Device information verification — 2026-10-24

## Implementation

D-860/API v1.308 adds descriptive device metadata to Fleet's existing task database and an Installation editor. Device IDs remain stable while names and models are editable. Declared arm counts and hardware identifiers do not establish connection, calibration or permission to move. CORE enrollment and OMX command ownership remain separate.

The final source revision is `9a0f3ae2b20e88979b213cc57df59acbbb38f0b5` on `feat/device-identity-profiles`. Route composition is in the existing registry-route installer so the already large application module does not grow. No new dependencies were added.

## Evidence

| Revision | Check | Result |
|---|---|---|
| `0054db7523` | New persistence/API tests before implementation | Expected missing-module RED |
| `7652ea871c` | New editor behavior/mount tests before implementation | Expected missing-asset and mount RED |
| `737992fade` | Store, API, actual app wiring, existing roster, enrollment-adjacent routes and version contracts | 191 passed, no skips |
| `737992fade` | Enabled Chromium tests, Operator/Viewer at 1440px and 390px | 4 passed, no skips |
| `9a0f3ae2b2` | Final route-expression change: API, actual app and editor integration | 15 passed, no skips |
| source-equivalent guard revision `b14be02c3b` | Existing complete Console Node suite, operator copy, console layout and harness contracts | Passed; known-failure comparison NEW 0 |

Official external log folders: `%TEMP%/rosy-device-profiles-final`, `rosy-device-profiles-final-browser`, `rosy-device-profiles-final-wiring`, and `rosy-device-profiles-guards`. All produced `run-1.txt` reports were compared with `test/known_failures.py`. No tests ran on the laptop.

Screenshots from the source-equivalent browser run were retrieved and visually inspected at desktop and mobile width. The browser tests load real Installation HTML and assets, but stub API responses. Backend authentication and persistence have separate integration tests. Independent read-only review of final source `9a0f3ae2b2` found no supported unresolved findings.

## Operational observation and limits

The operator-declared OMX S single-arm metadata was saved in the existing live Fleet database and read back with the tested store. Real hardware identifiers and account values remain on the site host. Connection remains `not_checked` and control remains disabled in this metadata response.

No running code was replaced, service restarted, operational robot enrolled, fault cleared, serial bus opened or motor moved. The new UI/API has not been deployed to the running Fleet. Existing native OMX hardware ownership still admits no goals. The present board has not been bound to a measured motor map, limits, calibration and stop acceptance. Software tests and metadata readback do not establish those facts.

CE: 미해결 — physical identity/commissioning/motion remain unresolved. D-860 and regression tests already carry the metadata-versus-authority reasoning; no duplicate solved-learning document was created.
