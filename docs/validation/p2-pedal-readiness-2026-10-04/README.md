# P2 페달 정지 계측 — 실행 준비 문서 (사용자 입회 안내)

**Status:** 실행 준비 완료 (2026-10-04). 사용자 입회·실기 Pinky 대기.

**계약:** D-444 §2 R2 (ARM64 payload에서 부팅, Pilot 브라우저로 조종, 합격선은 측정 전 고정 — `docs/plans/2026-10-04-pilot-device-stop-contract-measurement.md`).
**사다리:** `docs/plans/2026-10-04-web-gate-ladder-fleet-readiness-adr-plan.md` §3 P2.

## 준비된 것

| 준비물 | 상태 |
|---|---|
| **합격선** | PC-1 ≤300/500 ms·0.05 m, PC-2 ≤700/900 ms·0.09 m, PC-3 ≤300/500 ms·0.05 m — 계량 문서에 고정 |
| **서명 payload** | `2026.10.04-034.tar.gz` (X:\DevTemp\opencode\payload-034-signed\) — 검증·서명·pack 완료, 로봇 미푸시 |
| **부팅 증거** | arm64 러너에서 `core up` + `api server :8080` + 세 표면 200+CSP (run 37200780702) |
| **측정 도구** | `tools/dashboard_drive.py` 패턴(teleop stop latency) — Pilot 화면 대상으로 확장 필요 |

## 실행 절차 (사용자 입회)

1. 서명 payload를 실기 Pinky에 적용 (`rosy-release-push.ps1`, 사용자 승인 필요).
2. Pilot 브라우저(태블릿)에서 실기 연결 → MANUAL 모드 진입.
3. 각 경로 측정 (전진 0.10 m/s → 해제/e-stop, 5~3회 × 3경로).
4. `docs/validation/pilot-device-<date>/`에 증거 저장 (회차·환경·합격 판정표).
5. 결과가 합격선 안이면 pilot DEVICE GO.

## 사용자가 해야 할 것

1. **시간 조율** — 언제 실기 Pinky 앞에서 측정할지 (30분 내외).
2. **승인** — payload push(`rosy-release-push.ps1`) 실행 승인.
3. **입회** — 페달 해제·e-stop을 직접 누르거나 확인.

준비는 전부 끝났습니다. 사용자가 "시작"이라고 하면 즉시 실행합니다.
