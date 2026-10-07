# Fleet Cell failed job read — 2026-10-07

Candidate: `uiux/cell-job-read-state` from local `main` `76ed3176c`.

After a previously successful job read, a 503 response left the Cell job summary saying `현재 상태 확인 중` indefinitely. The approval action was blocked, but the status claim was wrong. The read path now clears the detailed state and says `작업 상태 확인 불가 · 접속 상태를 확인하고 다시 시도하세요`; the existing error notice still carries the failure and approval remains blocked. The same guard covers failure to read the dispatch generation after the job response.

The prior behavior failed in Chromium at 1440×1000, 390×844, and 320×568. The corrected three-width case passed **3/3**; adjacent approval/cancel and failed-read cases passed **6/6**; D-153 named G1 passed **90/90**; JS syntax passed. Each successful Python run had `known_failures.py` **0 NEW**. The 320px result was visually inspected: the error instruction and disabled approval remain readable with no horizontal overflow.

Raw captures and logs: `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-job-read/` (SHA-256):

| File | SHA-256 |
|---|---|
| `red.txt` | `c8ff155c23372ec7208541217b9fd6be1275a7881acda933f64865af1df7e285` |
| `related.txt` | `9960fe6a9807e1bdccbe939ff8779a7abb7015870a72de7330ffcd2bc2db84b9` |
| `g1.txt` | `9ca551d82fcc0b5cca2cfe2ae74576cda8c8beaa6c3e3ec6366998fde8645829` |
| `fleet-cell-job-read-error-1440x1000.png` | `b0a734be3e8c60f7044733f26c9107d476c2213a2c29e7520393d2512a6502b2` |
| `fleet-cell-job-read-error-390x844.png` | `9ad4a45f8d77e7c81e6314829c57b5f7f4181f7b14563c3872eba63888b6417c` |
| `fleet-cell-job-read-error-320x568.png` | `6318d2ab27f21f50566f399f185aab1cd2568d392e7b5d3864546e57a76a760d` |

This is LOCAL synthetic G2 evidence for one failed read state. Real site/device readback, the remaining declared G2 cells, and the user's G3 walkthrough remain **HOLD**. No site operation or device command occurred.
