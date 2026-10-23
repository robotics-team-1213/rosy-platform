# Teacher watchdog receipt — 2026-10-23

Production commit: `8ca63bb880`. The native SIM teacher previously omitted the owner's immutable decision-time watchdog observation from its final result. It now copies that observation, including nested intake facts and steady-clock brackets, without acquiring new control authority, sampling providers, polling again or changing freshness bounds. Missing observations remain null; invalid/nonfinite observations or diagnostic exceptions produce only an exception class. The original success/error and shutdown sequence remain intact.

Test-only commit `54db017621` produced five expected remote failures because the receipt lacked the new field. The same tests execute the actual teacher finalization slice with an exact frozen observation, null, malformed values, a failing accessor and nonfinite data. On the production commit the new suite plus demonstration, watchdog and intake regressions passed remotely: **65 passed, 0 NEW**. The omission RED demonstrates that this check detects the prior behavior. Independent safety review found no Important issues. Test logs are external under `C:/DevTemp/learning-execution-20261023/teacher-watchdog-{red,green}/`.

The preserved collection has 20 complete episodes followed by one incomplete episode at `joint_state_stale`; the planned 25-episode cohort remains HOLD. Recorder and owner sequence counters come from independent subscriptions and cannot be compared to infer delivery ordering. This change adds evidence without resolving the stale-state cause, replacing failed data, admitting a training split or demonstrating policy quality. Physical acceptance and genuine human review remain separate.

## One bounded engineering attempt

The reviewed integration candidate, commit `8b9efd4d1b626306c8a1904e0a1bdbb80bb5c3a5`, includes main `8f5d18534a` and the production change. While its official landing waited behind a peer, it was deployed once through the approved isolated native SIM transport with explicit simulation/startup-home flags, `pick-place-demonstrations`, and one requested episode. No actor was restarted. The native job exited 0: **PASS, one attempt/one success, 1,584 RGB frames**, overall cleanup verified. The per-episode process receipt reports `verified_absent=true`, `remaining_groups=[]`. The teacher receipt contains `watchdog_observation: null`: no watchdog stop occurred in this run. Null is not evidence that the prior stale-state cause was fixed, or that decision-time timing was observed in a live failure.

The complete closed artifact fetch is external at `C:/DevTemp/learning-execution-20261023/teacher-watchdog-engineering-once/fetches/20261023T085600-82dc26579613/`. Its receipt binds the compressed archive and extraction map. The source manifest binds the candidate revision and executed source hashes. Independent review matched the archive, inventory and teacher/owner/runtime/watchdog source files to the candidate, the issue-free complete recording, null watchdog key and cleanup receipts. This separately named engineering attempt is excluded from the frozen 25-episode collection; no training, policy evaluation or split modification occurred.

| Closed artifact | SHA256 | Bytes |
|---|---|---:|
| `exit.json` | sha256:05383f5dcb85f842939a05ce9fe3b51a47f7529f0e0e903e237236dcbb089257 | 127 |
| native `manifest.json` | sha256:11ccfb0503093da426a722bd66ca1c35f9d915e88169d9a32e0d876ac43a7a49 | 9604866 |
| `pick-place/result.json` | sha256:c4485539d623ad0bea7aa13d16ad2f2419465e57125c6d16e390bc47d7887a5d | 4346 |
| `episode-1/teacher-result.json` | sha256:ec01f385efbdc28453eb2795d460990ee57c60ecae6d48fb6af03439872fa1b1 | 3885 |
| `episode-1/process-cleanup.json` | sha256:abfe6596d5581fd7e043ca19f08c4d75ba07363e3210b26362a8b498a2b2320e | 49 |
| recording `manifest.json` | sha256:7f5d8afb0c82ad6f403dba44111a4fd786302a6c2aaf5dd12c28dba4d6cd823c | 1599 |

CE: 미해결 — stale-state 원인은 아직 분리되지 않았다. 기존 startup/admission 교훈을 확인했으며, 진단 보완을 해결된 장애 교훈으로 기록하지 않는다.
