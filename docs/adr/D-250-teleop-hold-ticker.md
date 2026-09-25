## D-250 TeleopHold — 홀드-티커만 뽑는다. 자격 판단은 표면이 가진다

**Status:** Accepted (2026-09-25). `hold-ticker.js` 신설 + 대시보드 채택 + 브라우저 teleop 46종 + 변이 증명 + G2 셀로 착지. 첫 L2 headless 선례다.

잇는 결정: [D-130](D-130-l2-headless.md) 2항 · [D-150](D-150-web-node-control-navigation-map.md)(진단은 PARKED) · [D-233](D-233-design-system-component-token-draft.md)(L2 후보 TeleopHold) · [D-249](D-249-fieldmap-spec-no-extraction.md)(뽑지 않음의 선례).

**Context (실측):**

| 항목 | 운용 `src/hmi/dashboard/app.js` | 진단 `src/runtime/sensing/web/dashboard.html` |
|---|---|---|
| 홀드 집합 | 버튼 1개 (`data-teleop`, pointerdown/up/cancel/leave) | 키+패드 합집합 (`S.held`, `ACT`·`KEYMAP`) |
| 주기 | `teleopIntervalMs` = 100ms (`setInterval`) | `teleop_period_ms` = 100ms (`S.kt`) |
| 해제 | `stopTeleop` — interval 해제 + zero 전송(keepalive) | `ksync` — 집합 비면 interval 해제 + `tw(0,0)` |
| 자격 게이트 | operator + capability + estop + pose/velocity fresh + MANUAL + 벤치 체크 | `calibrationReady` |
| 전송 | `POST /api/v1/teleop` | `POST /teleop {x, z}` |
| 안전망 | pointerup/blur/pagehide 전역 정지, 실패 시 정지 | (IIFE 내부, 노드 시험이 stub으로 실행) |

공유 가능한 것은 **홀드→100ms 전송→해제 zero** 메커니즘뿐이다. 자격·전송·속도 매핑은 표면의 계약이라 뽑지 않는다.

**Decision (초안):**

1. **`hold-ticker.js`를 `src/hmi/web/`에 둔다.** 스타일 0, `{intervalMs, onTick, onZero}`만 받는다. 자격 판단·전송·UI 바인딩은 갖지 않는다 — D-130.2의 "시각 0, 구조·상태·이벤트만" 자격을 맞춘다.
2. **채택은 대시보드만.** 진단은 PARKED(D-150) + 노드 stub 시험 계약이 있어 이번에 손대지 않는다. 2표면이 필요로 한다는 점(자격)은 실측표로 증명하고, 채택은 단계적으로 한다(D-247 선례: Fleet 단일 표면 착지).
3. **파일럿 커밋 범위.** 신규 파일 1개 + 대시보드 `startTeleop`/`stopTeleop`/`transmitTeleop`의 interval·zero를 티커 호출로 교체. 전송 페이로드·자격·문구는 그대로라 PINNED·적합 게이트에 손대지 않는다.
4. **바꾸지 않는 것.** 100ms 주기(서버 watchdog와 짝), zero-keepalive 의미, 진단 IIFE.

**Alternatives:** 진단까지 같이 옮기는 안 — PARKED 표면의 stub 시험을 깨뜨릴 위험을 파일럿이 질 이유가 없다. 각자 유지안 — 홀드-zero 누락이 두 벌로 drift할 자리(안전 직결)를 방치한다. 자격까지 headless로 올리는 안 — 역할·모드·벤치 계약이 표면마다 달라 Law 4 위반.

**Consequences (Accepted되고 파일럿이 끝나면):** 첫 L2 headless 선례가 된다. 진단이 PARKED에서 나오면 채택 심사를 연다.

**Validation / Transition:** (1) `test_web_dialog_contract.py` + `hmi/web` + `hmi/dashboard` 녹색, (2) `ROSY_RUN_BROWSER_TESTS=1 test_dashboard_browser.py` teleop 경로(hold 전송율·해제 zero) 녹색 + 변이 증명(티커 제거 → zero 미전송 적색), (3) G2 셀 1개(운용 teleop 홀드). `ROSY ADR Log.md`에 `D-250 | TeleopHold — 홀드-티커 추출 | Proposed` 1행 추가가 이 초안의 착지다.

**References:** D-92, D-130, D-150, D-218, D-233, D-249.

---
