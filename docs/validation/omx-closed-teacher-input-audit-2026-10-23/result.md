# Closed teacher input audit — 2026-10-23

Validation source commit: `c4d6f20cbb93d505dc3acc58596094c1342074c9`. Producer commit: `db4d8f87ca649a9922d3dba5d9002138d957d717` (teacher input only). This audit runs the committed demonstration validator, object-truth derivation and four-future-target checks on the model PC; it performs no optimizer, export, policy trial or admission.

The immutable collection remains HOLD: **20 AUDIT_PASS_NOT_ADMITTED, one EXCLUDED_INCOMPLETE, zero AUDIT_REJECTED**. Every file in eight hash-verified archives was compared with the cached extracted bytes: **33,797 files**. The complete episodes contain **31,829 actual PNG frames** with hash/decode, clock, joint and action validation. **14,305 selected examples** represent all **7,540 source commands**. The largest source-relative four-target delta is **0.034998090116065805 rad**, within the unchanged 0.035 bound. Truth derivation succeeds for all 20 complete assisted-SIM inputs.

The planned 25-episode cohort is incomplete. No episode was replaced or added, the original split was unchanged, and no training or evaluation was submitted. The failed episode and previous engineering data remain preserved and excluded. These input checks do not establish unassisted task success, learned policy quality or physical acceptance.

The audit process exited successfully, but its initial uncompressed output download timed out. The same finished remote outputs were recovered as a compressed archive without rerunning the audit. All **393 files** are in the external `C:/DevTemp/learning-execution-20261023/closed-teacher-audit-recovered/`; the recovery archive is 98,661,649 bytes. Program, request and report hashes/lengths match the independently observed result, the frozen cohort hash is unchanged, and independent review matched all 280 proof references across 20 proofs. Driver exit alone was not treated as successful artifact recovery.

| Artifact | SHA256 | Bytes |
|---|---|---:|
| exact `audit-program.py` | sha256:5474a05aa5665dffca75c6b7b4663bf8128d2ac34a7a64d0ba06221deb4ae355 | 5681 |
| exact `audit-request.json` | sha256:2d626edf1cb6c6a4899b7e4c9250c91c3da5902895f9e2e32103c841df35a2ab | 2698 |
| `audit-result.json` | sha256:1755ddc0c33879bb347f62c228435124abff7eaa4eb7b28298cc02d521a87f0b | 18419 |
| frozen collection receipt | sha256:2f803dc7615453962a255d2bef9d2a3d29850cb21977316b08cb656601479d78 | — |

The complete program and request are preserved beside the report; `closed-teacher-audit-bound-observation.json` independently binds their byte lengths and hashes. Remote execution used a fresh isolated output, the existing model learning environment and offline Hub flags. It compared archive members before semantic checks and rejected links, traversal and escaping paths. No credentials, device identities or raw data are published here.

CE: 미해결 — 입력 감사와 증거 회수는 완료했지만 수집을 중단시킨 stale-state의 원인은 아직 미해결이다.
