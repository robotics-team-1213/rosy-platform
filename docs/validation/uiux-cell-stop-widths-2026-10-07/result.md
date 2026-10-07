# Fleet Cell emergency-stop feedback widths — 2026-10-07

Local candidate base: `main` `4e1eeb045868e88a1ca9d0ebdec3c6d76745fa35`. Expanded the existing `/console/cell` Chromium scenario from 320×568 to the three declared viewports: **1440×1000, 390×844, 320×568**. Each scenario uses a fixture operator session and intercepted `/api/fleet/estop` responses; it does not contact a robot.

For a partial response (`stopped: 1`, `total: 3`), the page says that physical stop is unconfirmed. For a 503 response, it says the stop result cannot be confirmed. At all three widths, each message is visible in the first viewport, occupies the same horizontal track as the main content, and causes no document overflow. The emergency-stop request carries the fixture operator credential. The focused browser run passed **3 tests, 0 NEW known failures**.

Raw log and six viewport PNGs are in `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-stop-widths/`.

| File | SHA-256 |
|---|---|
| `focused.txt` | `7fb8932dde28732fb681c4037a1d73854559fd878ee45356c974ae893bc15607` |
| `fleet-cell-estop-partial-1440x1000.png` | `e627b1395c4440d35142c3c260f6d694ce7b709d906a74eadcd39f1eae8e9470` |
| `fleet-cell-estop-partial-390x844.png` | `b427303dc8bcca961a1a110f5346dd836c994b8ff389e1ccd588d9e574332efc` |
| `fleet-cell-estop-partial-320x568.png` | `a6778cf8baa63c889b6cba60d708a444414887478bcbfc096bf020c577772a2e` |
| `fleet-cell-estop-unknown-1440x1000.png` | `dc246c56d0c76ffb2bbd2da165f45d8e183fa92dc92cf11162635c148f663dcc` |
| `fleet-cell-estop-unknown-390x844.png` | `af5ac722fd8ffc528e6db3c829b26a03f4e4a1a9f70a1f9b64905be4d726ab17` |
| `fleet-cell-estop-unknown-320x568.png` | `4ee4b36c9102d5f6bb62bc94604e4ed8e58290a2f23f30287e840bee22fb6d8c` |

This extends **LOCAL synthetic G2** coverage for the Cell stop feedback. Physical stop readback, the remaining Cell states and widths, and operator G3 review remain **HOLD**.
